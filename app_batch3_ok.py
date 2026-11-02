# app.py — Spiritual Accountant: Raudha Engine (Final v3)
import os
import sys
import re
import sqlite3
import logging
from flask import Flask, render_template_string, jsonify, request, render_template, send_from_directory
from werkzeug.utils import secure_filename
from flask_cors import CORS
from datetime import datetime, date
from dotenv import load_dotenv

# --- KONFIGURASI AWAL ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HARGA_EMAS_BASE   = 1_050_000
BASELINE_AWAL     = 825_555_559
HARGA_TANI_PER_KG = 15_000
HAUL_HARI         = 354          # 1 tahun hijriah ≈ 354 hari

# --- FOLDER UPLOAD ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
UPLOAD_DOKUMEN = os.path.join(UPLOAD_FOLDER, "dokumen_lembaga")
os.makedirs(UPLOAD_DOKUMEN, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

DB_PATH = os.path.join("data", "raudha.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "raudha.db"

# --- KONSTANTA FIKIH ---
NISAB_EMAS_GRAM    = 85
NISAB_PERAK_GRAM   = 595
NISAB_PERTANIAN_KG = 653
KADAR_ZAKAT        = 0.025
KADAR_TANAH_ALAMI  = 0.10
KADAR_TANAH_BIAYA  = 0.05
KADAR_KHUMUS       = 0.20

# --- APP ---
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

# =====================================================================
# HELPERS
# =====================================================================
def format_idr(nilai):
    try:
        return "Rp {:,.0f}".format(nilai).replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"

app.jinja_env.filters['format_idr'] = format_idr

def tulis_audit(c, user_id, tabel, rec_id, aksi, field="", lama="", baru="", alasan=""):
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tabel TEXT,
            record_id INTEGER, aksi TEXT, field_diubah TEXT, nilai_lama TEXT,
            nilai_baru TEXT, alasan TEXT, waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""INSERT INTO audit_log
                     (user_id, tabel, record_id, aksi, field_diubah, nilai_lama, nilai_baru, alasan)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, tabel, rec_id, aksi, field, str(lama), str(baru), alasan))
    except Exception as e:
        logger.error(f"Error audit: {e}")

# =====================================================================
# RBAC HELPER
# =====================================================================
def get_user_role(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT role, status, lembaga_id FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return {"role": "user", "status": "active", "lembaga_id": None}
    return {"role": row[0] or "user", "status": row[1] or "active", "lembaga_id": row[2]}

def require_role(user_id, allowed_roles):
    info = get_user_role(user_id)
    if info["status"] != "active":
        return False, f"Akun Anda sedang {info['status']}. Hubungi super admin."
    if info["role"] not in allowed_roles:
        return False, f"Akses ditolak. Role Anda: {info['role']}"
    return True, None

def log_sensitive(c, user_id, role, aksi, target_tabel="", target_id=None, detail="", request_obj=None):
    ip = request_obj.remote_addr if request_obj else None
    ua = request_obj.user_agent.string if request_obj else None
    try:
        c.execute("""INSERT INTO log_akses_sensitif
                     (user_id, role, aksi, target_tabel, target_id, detail, ip_address, user_agent)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, role, aksi, target_tabel, target_id, detail, ip, ua))
    except Exception as e:
        logger.error(f"Log sensitive error: {e}")

def buat_kode_verifikasi(nama_lembaga, lembaga_id):
    prefix = re.sub(r'[^A-Z0-9]', '', nama_lembaga.upper()[:10]) or "LEMBAGA"
    return f"{prefix}-{lembaga_id:03d}"

# =====================================================================
# INIT DATABASE
# =====================================================================
def init_web_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. jurnal_syariah
    c.execute("""CREATE TABLE IF NOT EXISTS jurnal_syariah (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, jenis TEXT,
        gaji REAL DEFAULT 0, honor REAL DEFAULT 0, hadiah REAL DEFAULT 0,
        pertanian_kg REAL DEFAULT 0, jenis_pengairan TEXT,
        benda_mewah REAL DEFAULT 0, temuan_laut_karun REAL DEFAULT 0,
        simpanan_bmt_idr REAL DEFAULT 0,
        pengeluaran_rutin REAL DEFAULT 0, pengeluaran_sekolah REAL DEFAULT 0,
        pengeluaran_utang REAL DEFAULT 0, pengeluaran_sedekah REAL DEFAULT 0,
        tgl TEXT)""")
    c.execute("PRAGMA table_info(jurnal_syariah)")
    cols = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('pengeluaran_rutin','REAL DEFAULT 0'),
        ('pengeluaran_sekolah','REAL DEFAULT 0'),
        ('pengeluaran_utang','REAL DEFAULT 0'),
        ('pengeluaran_sedekah','REAL DEFAULT 0'),
        ('updated_at','TEXT'),
        ('edit_count','INTEGER DEFAULT 0'),
        ('is_active','INTEGER DEFAULT 1'),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE jurnal_syariah ADD COLUMN {col} {defn}")

    # 2. users_config
    c.execute("""CREATE TABLE IF NOT EXISTS users_config (
        user_id INTEGER PRIMARY KEY,
        tanggal_mulai_haul TEXT,
        baseline_awal REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("PRAGMA table_info(users_config)")
    cols_uc = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('is_admin','INTEGER DEFAULT 0'),
        ('nama_lengkap','TEXT'),
        ('no_whatsapp','TEXT'),
        ('khumus_aktif','INTEGER DEFAULT 1'),
        ('role',"TEXT DEFAULT 'user'"),
        ('lembaga_id','INTEGER'),
        ('status',"TEXT DEFAULT 'active'"),
        ('verified_by','INTEGER'),
        ('verified_at','TIMESTAMP'),
    ]:
        if col not in cols_uc:
            c.execute(f"ALTER TABLE users_config ADD COLUMN {col} {defn}")

    # 3. lembaga_amil
    c.execute("""CREATE TABLE IF NOT EXISTS lembaga_amil (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT NOT NULL,
        jenis TEXT DEFAULT 'LAZIS',
        deskripsi TEXT,
        logo_url TEXT,
        aktif INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        bisa_dipilih_user INTEGER DEFAULT 1,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("PRAGMA table_info(lembaga_amil)")
    cols_lem = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('status',"TEXT DEFAULT 'pending'"),
        ('kode_verifikasi','TEXT'),
        ('alamat','TEXT'),
        ('npwp','TEXT'),
        ('no_telepon','TEXT'),
        ('email_resmi','TEXT'),
        ('website','TEXT'),
        ('verified_by','INTEGER'),
        ('verified_at','TIMESTAMP'),
        ('verifikasi_metode','TEXT'),
        ('catatan_verifikasi','TEXT'),
        ('dokumen_url','TEXT'),
        ('rekening_atas_nama_lembaga','INTEGER DEFAULT 0'),
        ('is_public','INTEGER DEFAULT 0'),
    ]:
        if col not in cols_lem:
            c.execute(f"ALTER TABLE lembaga_amil ADD COLUMN {col} {defn}")

    # 4. rekening_lembaga
    c.execute("""CREATE TABLE IF NOT EXISTS rekening_lembaga (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER NOT NULL,
        metode TEXT NOT NULL,
        nama_bank TEXT,
        nomor_rekening TEXT,
        atas_nama TEXT,
        qr_image_url TEXT,
        aktif INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # 5. rencana_pembayaran
    c.execute("""CREATE TABLE IF NOT EXISTS rencana_pembayaran (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        jurnal_id INTEGER,
        jenis_kewajiban TEXT NOT NULL,
        keterangan TEXT,
        nominal REAL NOT NULL,
        lembaga_id INTEGER,
        lembaga_nama_manual TEXT,
        rekening_id INTEGER,
        rekening_info_manual TEXT,
        status TEXT DEFAULT 'pending',
        metode_transfer TEXT,
        bukti_transfer_url TEXT,
        bukti_uploaded_at TIMESTAMP,
        verified_by_admin INTEGER,
        verified_at TIMESTAMP,
        catatan_admin TEXT,
        alasan_batal TEXT,
        tanggal_rencana DATE,
        tanggal_bayar DATE,
        catatan_user TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id),
        FOREIGN KEY (rekening_id) REFERENCES rekening_lembaga(id)
    )""")

    # 6. verifikasi_lembaga
    c.execute("""CREATE TABLE IF NOT EXISTS verifikasi_lembaga (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER NOT NULL,
        tahap TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        catatan TEXT,
        dilakukan_oleh INTEGER,
        bukti_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # 7. log_akses_sensitif
    c.execute("""CREATE TABLE IF NOT EXISTS log_akses_sensitif (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        aksi TEXT,
        target_tabel TEXT,
        target_id INTEGER,
        detail TEXT,
        ip_address TEXT,
        user_agent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # 8. Seed Super Admin
    admin_id_env = os.getenv("ADMIN_ID", "").strip()
    if admin_id_env.isdigit():
        super_admin_id = int(admin_id_env)
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (super_admin_id,))
        if c.fetchone():
            c.execute("""UPDATE users_config 
                         SET role='super_admin', status='active'
                         WHERE user_id=?""", (super_admin_id,))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, role, status, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, 'super_admin', 'active', ?, ?)""",
                      (super_admin_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))
        logger.info(f"👑 Super Admin terdaftar: user_id={super_admin_id}")

    # 9. Seed Lembaga Default
    c.execute("SELECT COUNT(*) FROM lembaga_amil")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO lembaga_amil 
                     (nama, jenis, deskripsi, status, kode_verifikasi, 
                      is_default, bisa_dipilih_user, is_public)
                     VALUES 
                     ('LAZIS Raudha', 'LAZIS', 'Lembaga Amil Zakat resmi Raudha', 
                      'verified', 'LAZIS-RAUDHA-001', 1, 1, 1),
                     ('BAZNAS', 'BAZNAS', 'Badan Amil Zakat Nasional', 
                      'verified', 'BAZNAS-001', 0, 1, 1),
                     ('Dompet Dhuafa', 'LAZIS', 'Lembaga filantropi Islam', 
                      'verified', 'DD-001', 0, 1, 1)""")
        logger.info("✅ Seed lembaga_amil default berhasil")

    conn.commit()
    conn.close()

init_web_db()

# =====================================================================
# ENGINE HITUNG
# =====================================================================
def cek_haul_terpenuhi(user_id, tanggal_hari_ini=None):
    """
    Cek haul sejak tanggal_mulai_haul. Return dict.
    """
    if tanggal_hari_ini is None:
        tanggal_hari_ini = date.today()

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT tanggal_mulai_haul FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()

    if not row or not row[0]:
        return {
            "haul_terpenuhi": False, "hari_berlalu": 0,
            "tanggal_mulai_haul": None, "sisa_hari_haul": HAUL_HARI,
            "pesan": "Belum ada data. Input pertama Anda untuk mulai haul."
        }

    try:
        mulai = datetime.strptime(row[0], "%Y-%m-%d").date()
    except ValueError:
        return {
            "haul_terpenuhi": False, "hari_berlalu": 0,
            "tanggal_mulai_haul": None, "sisa_hari_haul": HAUL_HARI,
            "pesan": "Tanggal mulai haul tidak valid."
        }

    selisih = (tanggal_hari_ini - mulai).days
    terpenuhi = selisih >= HAUL_HARI
    sisa = max(0, HAUL_HARI - selisih)

    return {
        "haul_terpenuhi": terpenuhi,
        "hari_berlalu": selisih,
        "tanggal_mulai_haul": mulai.strftime("%Y-%m-%d"),
        "sisa_hari_haul": sisa,
        "pesan": (
            "✅ Haul terpenuhi — zakat maal wajib ditunaikan." if terpenuhi
            else f"⏳ Haul belum terpenuhi — sisa {sisa} hari lagi."
        )
    }


def laporan_tahunan(user_id, harga_emas):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    nisab_maal = NISAB_EMAS_GRAM * harga_emas

    total_pemasukan = total_pengeluaran = 0
    total_zakat_tani = total_khumus = 0
    total_bmt_idr = total_benda_mewah = 0
    total_temuan_kotor = 0

    c.execute("""SELECT gaji, honor, hadiah, pertanian_kg, jenis_pengairan,
                        benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
                        pengeluaran_rutin, pengeluaran_sekolah,
                        pengeluaran_utang, pengeluaran_sedekah
                 FROM jurnal_syariah WHERE user_id=? AND COALESCE(is_active,1)=1""", (user_id,))
    for row in c.fetchall():
        (gj, hnr, hd, tani, pengairan, mewah, temuan, bmt,
         p_rutin, p_sekolah, p_utang, p_sedekah) = row
        total_pemasukan += ((gj or 0)+(hnr or 0)+(hd or 0)+(bmt or 0)+(mewah or 0)
                            + ((tani or 0)*HARGA_TANI_PER_KG) + (temuan or 0))
        total_pengeluaran += ((p_rutin or 0)+(p_sekolah or 0)+(p_utang or 0)+(p_sedekah or 0))
        total_bmt_idr += (bmt or 0)
        total_benda_mewah += (mewah or 0)
        total_temuan_kotor += (temuan or 0)
        if (tani or 0) >= NISAB_PERTANIAN_KG:
            kadar = KADAR_TANAH_ALAMI if pengairan == 'tadah_hujan' else KADAR_TANAH_BIAYA
            total_zakat_tani += (tani * kadar) * HARGA_TANI_PER_KG
        if (temuan or 0) > 0:
            total_khumus += (temuan * KADAR_KHUMUS)

    # Status pembayaran
    c.execute("""SELECT status, COALESCE(SUM(nominal), 0) 
                 FROM rencana_pembayaran WHERE user_id=? GROUP BY status""", (user_id,))
    pay = {"pending": 0, "dibayar": 0, "diverifikasi": 0, "batal": 0}
    for status, nominal in c.fetchall():
        pay[status] = nominal or 0
    total_pembayaran_berkurang = pay["dibayar"] + pay["diverifikasi"]

    # Khumus aktif?
    c.execute("SELECT khumus_aktif FROM users_config WHERE user_id=?", (user_id,))
    row_k = c.fetchone()
    khumus_aktif = bool(row_k[0]) if row_k and row_k[0] is not None else True

    # Zakat maal sudah direncanakan
    c.execute("""SELECT COALESCE(SUM(nominal), 0) FROM rencana_pembayaran
                 WHERE user_id=? AND jenis_kewajiban='zakat_maal'
                   AND status IN ('pending','dibayar','diverifikasi')""", (user_id,))
    zakat_maal_sudah_direncanakan = c.fetchone()[0] or 0
    conn.close()

    harta_kumulatif = max(0, (BASELINE_AWAL + total_pemasukan) 
                              - total_pengeluaran - total_pembayaran_berkurang)
    zakat_maal_potensial = (harta_kumulatif * KADAR_ZAKAT) if harta_kumulatif >= nisab_maal else 0
    haul_info = cek_haul_terpenuhi(user_id)
    zakat_maal_wajib = zakat_maal_potensial if haul_info["haul_terpenuhi"] else 0
    total_khumus_final = total_khumus if khumus_aktif else 0
    zakat_maal_belum_dibayar = max(0, zakat_maal_wajib - zakat_maal_sudah_direncanakan)

    return {
        "total_harta": harta_kumulatif,
        "total_zakat": zakat_maal_wajib + total_zakat_tani,
        "zakat_maal_wajib": zakat_maal_wajib,
        "zakat_maal_potensial": zakat_maal_potensial,
        "zakat_maal_belum_dibayar": zakat_maal_belum_dibayar,
        "zakat_maal_sudah_direncanakan": zakat_maal_sudah_direncanakan,
        "zakat_tani": total_zakat_tani,
        "total_khumus": total_khumus_final,
        "khumus_aktif": khumus_aktif,
        "total_temuan_kotor": total_temuan_kotor,
        "haul_terpenuhi": haul_info["haul_terpenuhi"],
        "hari_berlalu": haul_info["hari_berlalu"],
        "tanggal_mulai_haul": haul_info["tanggal_mulai_haul"],
        "sisa_hari_haul": haul_info["sisa_hari_haul"],
        "haul_pesan": haul_info["pesan"],
        "total_pembayaran_diverifikasi": pay["diverifikasi"],
        "total_pembayaran_dibayar": pay["dibayar"],
        "total_pembayaran_berkurang": total_pembayaran_berkurang,
        "saldo_bmt_idr": total_bmt_idr,
        "saldo_bmt_emas": (total_bmt_idr / harga_emas) if harga_emas else 0,
        "nisab_emas_rupiah": nisab_maal,
    }

# =====================================================================
# API — LAPORAN & KONFIG
# =====================================================================
@app.route('/api/laporan/<int:user_id>')
def api_laporan(user_id):
    res = laporan_tahunan(user_id, HARGA_EMAS_BASE)
    res["zakat_penghasilan_wajib"] = res["total_zakat"] > 0
    return jsonify({"status": "success", "laporan": res})

@app.route('/api/config')
def api_config():
    return jsonify({
        "harga_emas": HARGA_EMAS_BASE,
        "baseline_awal": BASELINE_AWAL,
        "harga_tani_per_kg": HARGA_TANI_PER_KG,
        "nisab_emas_gram": NISAB_EMAS_GRAM,
        "nisab_pertanian_kg": NISAB_PERTANIAN_KG,
        "kadar_zakat": KADAR_ZAKAT,
        "kadar_tanah_alami": KADAR_TANAH_ALAMI,
        "kadar_tanah_biaya": KADAR_TANAH_BIAYA,
        "kadar_khumus": KADAR_KHUMUS,
        "haul_hari": HAUL_HARI,
    })

@app.route('/api/config/khumus/<int:user_id>', methods=['GET'])
def get_khumus_status(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT khumus_aktif FROM users_config WHERE user_id=?", (user_id,))
        row = c.fetchone()
        khumus_aktif = bool(row[0]) if row and row[0] is not None else True
    finally:
        conn.close()
    return jsonify({"status": "success", "khumus_aktif": khumus_aktif})

@app.route('/api/config/khumus', methods=['POST'])
def toggle_khumus():
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    aktif = bool(data.get("aktif", True))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("UPDATE users_config SET khumus_aktif=? WHERE user_id=?",
                      (1 if aktif else 0, user_id))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal, khumus_aktif)
                         VALUES (?, ?, ?, ?)""",
                      (user_id, date.today().strftime("%Y-%m-%d"),
                       BASELINE_AWAL, 1 if aktif else 0))
        tulis_audit(c, user_id, "users_config", user_id, "TOGGLE_KHUMUS",
                    baru=str(aktif), alasan="User toggle khumus")
        conn.commit()
        return jsonify({"status": "success", "khumus_aktif": aktif})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# API — INPUT & EDIT JURNAL
# =====================================================================
@app.route('/api/input/syariah', methods=['POST'])
def input_syariah():
    data = request.json or {}
    user_id = int(data.get("user_id", 99999))
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if not c.fetchone():
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, ?, ?)""",
                      (user_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))
            logger.info(f"[USER BARU] user_id={user_id}")

        c.execute("""INSERT INTO jurnal_syariah
            (user_id, jenis, gaji, honor, hadiah, pertanian_kg, jenis_pengairan,
             benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
             pengeluaran_rutin, pengeluaran_sekolah, pengeluaran_utang, pengeluaran_sedekah, tgl,
             updated_at, edit_count, is_active)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1)""",
            (user_id, data.get("jenis","input_web"),
             data.get("gaji",0), data.get("honor",0), data.get("hadiah",0),
             data.get("pertanian_kg",0), data.get("jenis_pengairan","irigasi"),
             data.get("benda_mewah",0), data.get("temuan_laut_karun",0),
             data.get("simpanan_bmt_idr",0),
             data.get("pengeluaran_rutin",0), data.get("pengeluaran_sekolah",0),
             data.get("pengeluaran_utang",0), data.get("pengeluaran_sedekah",0),
             date.today().strftime("%Y-%m-%d"),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        tulis_audit(c, user_id, "jurnal_syariah", c.lastrowid, "CREATE",
                    alasan="Form Terperinci Mini App")
        conn.commit()
        return jsonify({"status":"success","message":"Berhasil disimpan!", "id": c.lastrowid})
    except Exception as e:
        conn.rollback()
        logger.error(f"Input error: {e}")
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

@app.route('/api/input/syariah/<int:jurnal_id>', methods=['PUT'])
def update_syariah(jurnal_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM jurnal_syariah WHERE id=? AND COALESCE(is_active,1)=1", (jurnal_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Jurnal tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403

        c.execute("""UPDATE jurnal_syariah SET
                        gaji=?, hadiah=?, pertanian_kg=?, jenis_pengairan=?,
                        benda_mewah=?, temuan_laut_karun=?, simpanan_bmt_idr=?,
                        pengeluaran_rutin=?, pengeluaran_sekolah=?,
                        pengeluaran_utang=?, pengeluaran_sedekah=?,
                        updated_at=?, edit_count=COALESCE(edit_count,0)+1
                     WHERE id=?""",
                  (data.get("gaji",0), data.get("hadiah",0),
                   data.get("pertanian_kg",0), data.get("jenis_pengairan","irigasi"),
                   data.get("benda_mewah",0), data.get("temuan_laut_karun",0),
                   data.get("simpanan_bmt_idr",0),
                   data.get("pengeluaran_rutin",0), data.get("pengeluaran_sekolah",0),
                   data.get("pengeluaran_utang",0), data.get("pengeluaran_sedekah",0),
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   jurnal_id))
        tulis_audit(c, user_id, "jurnal_syariah", jurnal_id, "UPDATE",
                    field="multi", baru=str(data), alasan="Edit dari Mini App")
        conn.commit()
        return jsonify({"status": "success", "message": "Data diperbarui"})
    except Exception as e:
        conn.rollback()
        logger.error(f"Edit error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jurnal/<int:user_id>')
def api_jurnal_list(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, tgl, gaji, hadiah, pertanian_kg, jenis_pengairan,
                        benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
                        pengeluaran_rutin, pengeluaran_sekolah,
                        pengeluaran_utang, pengeluaran_sedekah,
                        edit_count, updated_at
                 FROM jurnal_syariah
                 WHERE user_id=? AND COALESCE(is_active,1)=1
                 ORDER BY id DESC LIMIT 50""", (user_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","tgl","gaji","hadiah","pertanian_kg","jenis_pengairan",
            "benda_mewah","temuan_laut_karun","simpanan_bmt_idr",
            "pengeluaran_rutin","pengeluaran_sekolah",
            "pengeluaran_utang","pengeluaran_sedekah",
            "edit_count","updated_at"]
    return jsonify({"status": "success", "jurnal": [dict(zip(keys, r)) for r in rows]})

# =====================================================================
# API — SUPER ADMIN
# =====================================================================
@app.route('/api/admin/lembaga/pending', methods=['GET'])
def admin_list_pending_lembaga():
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, jenis, alamat, npwp, no_telepon, email_resmi,
                        dokumen_url, created_at, status
                 FROM lembaga_amil WHERE status='pending'
                 ORDER BY created_at ASC""")
    rows = c.fetchall(); conn.close()
    keys = ["id","nama","jenis","alamat","npwp","no_telepon","email_resmi",
            "dokumen_url","created_at","status"]
    return jsonify({"status": "success", "lembaga": [dict(zip(keys, r)) for r in rows]})

@app.route('/api/admin/lembaga/<int:lembaga_id>/detail', methods=['GET'])
def admin_detail_lembaga(lembaga_id):
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM lembaga_amil WHERE id=?", (lembaga_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Lembaga tidak ditemukan"}), 404
    cols = [d[0] for d in c.description]
    lembaga = dict(zip(cols, row))

    c.execute("""SELECT tahap, status, catatan, dilakukan_oleh, bukti_url, created_at
                 FROM verifikasi_lembaga WHERE lembaga_id=? ORDER BY created_at ASC""", (lembaga_id,))
    verif_keys = ["tahap","status","catatan","dilakukan_oleh","bukti_url","created_at"]
    verifikasi = [dict(zip(verif_keys, r)) for r in c.fetchall()]

    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, aktif
                 FROM rekening_lembaga WHERE lembaga_id=?""", (lembaga_id,))
    rek_keys = ["id","metode","nama_bank","nomor_rekening","atas_nama","aktif"]
    rekening = [dict(zip(rek_keys, r)) for r in c.fetchall()]

    c.execute("""SELECT user_id, nama_lengkap, no_whatsapp, status, verified_at
                 FROM users_config WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
    adm_keys = ["user_id","nama_lengkap","no_whatsapp","status","verified_at"]
    admins = [dict(zip(adm_keys, r)) for r in c.fetchall()]
    conn.close()
    return jsonify({
        "status": "success", "lembaga": lembaga, "verifikasi": verifikasi,
        "rekening": rekening, "admin_lembaga": admins,
    })

@app.route('/api/admin/lembaga/<int:lembaga_id>/verifikasi-tahap', methods=['POST'])
def admin_verifikasi_tahap(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    tahap = data.get("tahap", "").strip()
    status_tahap = data.get("status", "").strip()
    if tahap not in ("dokumen", "video_call", "kunjungan", "keputusan"):
        return jsonify({"status": "error", "message": "Tahap tidak valid"}), 400
    if status_tahap not in ("lolos", "gagal"):
        return jsonify({"status": "error", "message": "Status tahap tidak valid"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM lembaga_amil WHERE id=?", (lembaga_id,))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "Lembaga tidak ditemukan"}), 404
        c.execute("""INSERT INTO verifikasi_lembaga
                     (lembaga_id, tahap, status, catatan, dilakukan_oleh, bukti_url)
                     VALUES (?,?,?,?,?,?)""",
                  (lembaga_id, tahap, status_tahap,
                   data.get("catatan", ""), user_id, data.get("bukti_url", "")))
        log_sensitive(c, user_id, "super_admin", f"verifikasi_{tahap}",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"status={status_tahap}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": f"Tahap {tahap} dicatat"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/lembaga/<int:lembaga_id>/aktifkan', methods=['POST'])
def admin_aktifkan_lembaga(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT tahap, status FROM verifikasi_lembaga WHERE lembaga_id=?", (lembaga_id,))
        tahap_lolos = {r[0] for r in c.fetchall() if r[1] == "lolos"}
        if "dokumen" not in tahap_lolos:
            return jsonify({"status":"error","message":"Tahap 'dokumen' belum lolos"}), 400
        if not ({"video_call", "kunjungan"} & tahap_lolos):
            return jsonify({"status":"error","message":"Butuh tahap 'video_call' atau 'kunjungan' yang lolos"}), 400

        c.execute("""SELECT COUNT(*) FROM users_config 
                     WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
        if c.fetchone()[0] < 2:
            return jsonify({"status":"error","message":"Butuh minimal 2 admin lembaga"}), 400

        c.execute("""SELECT COUNT(*) FROM rekening_lembaga 
                     WHERE lembaga_id=? AND aktif=1""", (lembaga_id,))
        if c.fetchone()[0] == 0:
            return jsonify({"status":"error","message":"Lembaga belum punya rekening aktif"}), 400

        c.execute("SELECT nama, kode_verifikasi FROM lembaga_amil WHERE id=?", (lembaga_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status":"error","message":"Lembaga tidak ditemukan"}), 404
        nama_lembaga, kode = row
        if not kode:
            kode = buat_kode_verifikasi(nama_lembaga, lembaga_id)
            c.execute("UPDATE lembaga_amil SET kode_verifikasi=? WHERE id=?", (kode, lembaga_id))

        c.execute("""UPDATE lembaga_amil SET status='verified', verified_by=?, 
                        verified_at=CURRENT_TIMESTAMP, is_public=1 WHERE id=?""",
                  (user_id, lembaga_id))
        c.execute("""UPDATE users_config SET status='active', verified_by=?, 
                        verified_at=CURRENT_TIMESTAMP
                     WHERE lembaga_id=? AND role='admin_lembaga'""",
                  (user_id, lembaga_id))
        log_sensitive(c, user_id, "super_admin", "aktifkan_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"kode={kode}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Lembaga diaktifkan",
                        "kode_verifikasi": kode})
    except Exception as e:
        conn.rollback()
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/lembaga/<int:lembaga_id>/suspend', methods=['POST'])
def admin_suspend_lembaga(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    alasan = data.get("alasan", "").strip()
    if not alasan:
        return jsonify({"status": "error", "message": "Alasan wajib diisi"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("UPDATE lembaga_amil SET status='suspended' WHERE id=?", (lembaga_id,))
        c.execute("""UPDATE users_config SET status='suspended'
                     WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
        log_sensitive(c, user_id, "super_admin", "suspend_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"alasan={alasan}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Lembaga disuspend"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# API — DAFTAR LEMBAGA (PUBLIK)
# =====================================================================
@app.route('/api/lembaga/daftar', methods=['POST'])
def daftar_lembaga_baru():
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    required = ["nama", "jenis", "alamat", "npwp", "no_telepon", "email_resmi"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"status": "error", "message": "Field wajib belum lengkap"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT lembaga_id FROM users_config 
                     WHERE user_id=? AND role='admin_lembaga'""", (user_id,))
        if c.fetchone():
            return jsonify({"status": "error",
                            "message": "Anda sudah menjadi admin lembaga lain"}), 400

        c.execute("""INSERT INTO lembaga_amil
                     (nama, jenis, alamat, npwp, no_telepon, email_resmi,
                      dokumen_url, status, created_by)
                     VALUES (?,?,?,?,?,?,?, 'pending', ?)""",
                  (data["nama"].strip(), data["jenis"].strip(),
                   data["alamat"].strip(), data["npwp"].strip(),
                   data["no_telepon"].strip(), data["email_resmi"].strip(),
                   data.get("dokumen_url", ""), user_id))
        lembaga_id = c.lastrowid

        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("""UPDATE users_config SET
                            role='admin_lembaga', lembaga_id=?, status='pending',
                            nama_lengkap=?, no_whatsapp=? WHERE user_id=?""",
                      (lembaga_id, data.get("nama_admin", ""),
                       data.get("no_whatsapp_admin", ""), user_id))
        else:
            c.execute("""INSERT INTO users_config
                         (user_id, role, lembaga_id, status, nama_lengkap,
                          no_whatsapp, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, 'admin_lembaga', ?, 'pending', ?, ?, ?, ?)""",
                      (user_id, lembaga_id, data.get("nama_admin", ""),
                       data.get("no_whatsapp_admin", ""),
                       date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))

        c.execute("""INSERT INTO verifikasi_lembaga
                     (lembaga_id, tahap, status, catatan, dilakukan_oleh)
                     VALUES (?, 'pengajuan', 'pending', 'Menunggu verifikasi', ?)""",
                  (lembaga_id, user_id))
        log_sensitive(c, user_id, "user", "daftar_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"nama={data['nama']}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success",
                        "message": "Pengajuan diterima. Menunggu verifikasi super admin.",
                        "lembaga_id": lembaga_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

 

# =====================================================================
# API — UPLOAD DOKUMEN LEMBAGA
# =====================================================================
def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/api/upload/dokumen', methods=['POST'])
def upload_dokumen_lembaga():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "File tidak ditemukan"}), 400

    file = request.files['file']
    user_id = request.form.get("user_id", "").strip()
    jenis_dokumen = request.form.get("jenis_dokumen", "lainnya").strip()

    if not user_id.isdigit():
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nama file kosong"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", "message": f"Format tidak didukung. Gunakan: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"status": "error", "message": "File terlalu besar (maks 5 MB)"}), 400

    ext = file.filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_jenis = re.sub(r'[^a-z0-9]', '_', jenis_dokumen.lower())[:20] or "dokumen"
    filename = f"lembaga_{user_id}_{safe_jenis}_{timestamp}.{ext}"
    filepath = os.path.join(UPLOAD_DOKUMEN, filename)
    file.save(filepath)

    url = f"/uploads/dokumen_lembaga/{filename}"
    logger.info(f"[UPLOAD] user={user_id} jenis={jenis_dokumen} file={filename}")
    return jsonify({"status": "success", "url": url, "filename": filename, "size": size})


@app.route('/uploads/dokumen_lembaga/<path:filename>')
def serve_dokumen_lembaga(filename):
    return send_from_directory(UPLOAD_DOKUMEN, filename)


# =====================================================================
# API — CEK STATUS PENGAJUAN LEMBAGA
# =====================================================================
@app.route('/api/lembaga/status/<int:user_id>', methods=['GET'])
def cek_status_pengajuan(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT role, status, lembaga_id FROM users_config 
                     WHERE user_id=?""", (user_id,))
        uc = c.fetchone()
        if not uc:
            return jsonify({"status": "success", "kondisi": "belum_terdaftar"})

        role, user_status, lembaga_id = uc
        if role != "admin_lembaga":
            return jsonify({"status": "success", "kondisi": "bukan_admin_lembaga"})

        c.execute("""SELECT id, nama, jenis, status, alamat, no_telepon,
                            email_resmi, kode_verifikasi, created_at, verified_at
                     FROM lembaga_amil WHERE id=?""", (lembaga_id,))
        lem = c.fetchone()
        if not lem:
            return jsonify({"status": "success", "kondisi": "lembaga_hilang"})

        cols = ["id","nama","jenis","status","alamat","no_telepon",
                "email_resmi","kode_verifikasi","created_at","verified_at"]
        lembaga = dict(zip(cols, lem))

        c.execute("""SELECT tahap, status, catatan, created_at
                     FROM verifikasi_lembaga WHERE lembaga_id=?
                     ORDER BY created_at ASC""", (lembaga_id,))
        verif_keys = ["tahap","status","catatan","created_at"]
        verifikasi = [dict(zip(verif_keys, r)) for r in c.fetchall()]

        return jsonify({
            "status": "success",
            "kondisi": lembaga["status"],
            "lembaga": lembaga,
            "verifikasi": verifikasi,
            "user_status": user_status,
        })
    finally:
        conn.close()


@app.route('/api/lembaga', methods=['GET'])
def list_lembaga_publik():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, jenis, deskripsi, logo_url, kode_verifikasi, is_default
                 FROM lembaga_amil
                 WHERE status='verified' AND aktif=1 AND is_public=1
                 ORDER BY is_default DESC, nama ASC""")
    rows = c.fetchall(); conn.close()
    keys = ["id","nama","jenis","deskripsi","logo_url","kode_verifikasi","is_default"]
    return jsonify({"status": "success", "lembaga": [dict(zip(keys, r)) for r in rows]})

@app.route('/api/lembaga/<int:lembaga_id>/rekening', methods=['GET'])
def list_rekening_lembaga(lembaga_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, qr_image_url
                 FROM rekening_lembaga WHERE lembaga_id=? AND aktif=1
                 ORDER BY is_default DESC""", (lembaga_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","metode","nama_bank","nomor_rekening","atas_nama","qr_image_url"]
    return jsonify({"status": "success", "rekening": [dict(zip(keys, r)) for r in rows]})

# =====================================================================
# PUBLIC VERIFICATION PAGE
# =====================================================================
@app.route('/verify/<kode>')
def public_verification_page(kode):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT nama, jenis, alamat, status, verified_at, kode_verifikasi,
                        no_telepon, email_resmi, website
                 FROM lembaga_amil WHERE kode_verifikasi=?""", (kode,))
    row = c.fetchone()
    if not row:
        conn.close()
        return render_template_string("""
            <html><body style="font-family:sans-serif;padding:40px;text-align:center;">
                <h1>❌ Lembaga Tidak Ditemukan</h1>
                <p>Kode verifikasi <strong>{{ kode }}</strong> tidak terdaftar.</p>
            </body></html>""", kode=kode), 404

    cols = ["nama","jenis","alamat","status","verified_at","kode_verifikasi",
            "no_telepon","email_resmi","website"]
    lembaga = dict(zip(cols, row))
    conn.close()
    icon = "✅" if lembaga["status"] == "verified" else "⚠️"
    color = "#10b981" if lembaga["status"] == "verified" else "#f59e0b"

    return render_template_string("""
        <!DOCTYPE html>
        <html><head>
            <meta charset="UTF-8">
            <title>Verifikasi Lembaga — Raudha</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head><body class="bg-slate-50 min-h-screen p-6">
            <div class="max-w-md mx-auto bg-white rounded-3xl shadow-xl overflow-hidden">
                <div class="bg-gradient-to-r from-emerald-600 to-teal-700 text-white p-6 text-center">
                    <div class="text-6xl">{{ icon }}</div>
                    <h1 class="text-xl font-black mt-2">{{ nama }}</h1>
                    <p class="text-sm opacity-90">{{ jenis }}</p>
                </div>
                <div class="p-6 space-y-3 text-sm">
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Kode Verifikasi</span>
                        <strong>{{ kode_verifikasi }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Status</span>
                        <strong style="color:{{ color }}">{{ status }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Terverifikasi</span>
                        <strong>{{ verified_at or '-' }}</strong>
                    </div>
                    <div class="border-b pb-2">
                        <span class="text-slate-500 block mb-1">Alamat</span>
                        <span>{{ alamat }}</span>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Telepon</span>
                        <strong>{{ no_telepon or '-' }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Email</span>
                        <strong>{{ email_resmi or '-' }}</strong>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-500">Website</span>
                        <strong>{{ website or '-' }}</strong>
                    </div>
                </div>
            </div>
        </body></html>""",
        icon=icon, color=color,
        nama=lembaga["nama"], jenis=lembaga["jenis"], alamat=lembaga["alamat"],
        status=lembaga["status"], verified_at=lembaga["verified_at"],
        kode_verifikasi=lembaga["kode_verifikasi"],
        no_telepon=lembaga["no_telepon"], email_resmi=lembaga["email_resmi"],
        website=lembaga["website"])

# =====================================================================
# ROUTE ARSITEKTUR
# =====================================================================
@app.route('/arsitektur')
def render_halaman_galeri_arsitektur_raudha():
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    html_path = os.path.join(templates_dir, "arsitektur.html")
    if not os.path.exists(html_path):
        return "❌ templates/arsitektur.html tidak ditemukan.", 404
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return render_template_string(f.read())
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route('/api/input/arsitektur', methods=['POST'])
def api_input_arsitektur():
    data = request.json or {}
    user_id = data.get("user_id") or 99999
    required = ["pemohon","whatsapp","email","fasilitas","alamat"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"status":"error","message":"Field wajib tidak lengkap"}), 400
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS pengajuan_desain (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            pemohon TEXT, whatsapp TEXT, email TEXT, fasilitas TEXT,
            luas_tanah REAL, kapasitas INTEGER, alamat TEXT,
            budget REAL DEFAULT 0, timeline TEXT DEFAULT 'fleksibel',
            catatan TEXT, status TEXT DEFAULT 'baru',
            tgl TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""INSERT INTO pengajuan_desain
            (user_id, pemohon, whatsapp, email, fasilitas, luas_tanah, kapasitas,
             alamat, budget, timeline, catatan) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, data.get("pemohon","").strip(), data.get("whatsapp","").strip(),
             data.get("email","").strip(), data.get("fasilitas",""),
             float(data.get("luas_tanah",0)), int(data.get("kapasitas",0)),
             data.get("alamat","").strip(), float(data.get("budget",0)),
             data.get("timeline","fleksibel"), data.get("catatan","").strip()))
        tulis_audit(c, user_id, "pengajuan_desain", c.lastrowid, "CREATE",
                    alasan="Web Pengajuan Arsitektur")
        conn.commit()
        return jsonify({"status":"success","message":"Pengajuan tersimpan","id":c.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# ROOT — RENDER MINI APP
# =====================================================================
@app.route('/')
def index():
    cfg = {
        "harga_emas": HARGA_EMAS_BASE,
        "baseline_awal": BASELINE_AWAL,
        "harga_tani_per_kg": HARGA_TANI_PER_KG,
        "nisab_emas_gram": NISAB_EMAS_GRAM,
        "nisab_pertanian_kg": NISAB_PERTANIAN_KG,
        "kadar_zakat": KADAR_ZAKAT,
        "kadar_tanah_alami": KADAR_TANAH_ALAMI,
        "kadar_tanah_biaya": KADAR_TANAH_BIAYA,
        "kadar_khumus": KADAR_KHUMUS,
        "haul_hari": HAUL_HARI,
    }
    return render_template('index.html', cfg=cfg)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)