# modul_zakat_khumus.py — Spiritual Accountant: Raudha Zakat & Khumus
import os
import sys
import sqlite3
import logging
from datetime import datetime, date

# Pastikan modul validasi bisa diakses
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from modul_validasi import VALIDATOR, ValidationError
except ImportError:
    # Fallback jika modul_validasi belum ada (untuk testing standalone)
    VALIDATOR = {}
    ValidationError = Exception

DB_PATH = os.path.join("data", "raudha_zakat.db")

# ===================== KONSTANTA STANDAR =====================
NISAB_EMAS_GRAM    = 85
NISAB_PERAK_GRAM   = 595
NISAB_PERTANIAN_KG = 653       # 5 wasaq ≈ 653 kg beras
KADAR_ZAKAT        = 0.025     # 2.5%
KADAR_TANAH_ALAMI  = 0.10      # 10% (diairi hujan/sungai)
KADAR_TANAH_BIAYA  = 0.05      # 5% (diairi pompa/irigasi berbayar)
KADAR_KHUMUS       = 0.20      # 20% (1/5)

# ===================== DATABASE =====================

def init_db():
    """Inisialisasi semua tabel jika belum ada."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()

    # Tabel Audit Log (Penting untuk jejak perubahan)
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tabel TEXT,
        record_id INTEGER,
        aksi TEXT CHECK(aksi IN ('CREATE','UPDATE','DELETE')),
        field_diubah TEXT,
        nilai_lama TEXT,
        nilai_baru TEXT,
        alasan TEXT,
        waktu TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    # 1. Pendapatan (Gaji, Honor, Bonus, Hadiah, Usaha)
    c.execute('''CREATE TABLE IF NOT EXISTS pendapatan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kategori TEXT CHECK(kategori IN ('gaji','honor','bonus','hadiah','usaha','lainnya')),
        jumlah REAL,
        keterangan TEXT,
        sumber_halal TEXT DEFAULT 'halal',
        ongkos_produksi REAL DEFAULT 0,
        tgl TEXT DEFAULT CURRENT_DATE
    )''')

    # 2. Pertanian (Sawah, Ladang, Buah, Kurma, dll)
    c.execute('''CREATE TABLE IF NOT EXISTS pertanian (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis_pangan TEXT DEFAULT 'padi',
        hasil_kg REAL,
        harga_per_kg REAL,
        irigasi TEXT CHECK(irigasi IN ('alami','berbiaya')),
        biaya_panen REAL DEFAULT 0,
        tgl_panen TEXT DEFAULT CURRENT_DATE
    )''')

    # 3. Peternakan (Unta, Sapi, Kambing)
    c.execute('''CREATE TABLE IF NOT EXISTS peternakan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('unta','sapi','kambing')),
        jumlah INTEGER,
        sistem_grazing TEXT DEFAULT 'padang',
        dipekerjakan INTEGER DEFAULT 0,
        tgl_mulai_haul TEXT DEFAULT CURRENT_DATE
    )''')

    # 4. Simpanan/Harta (Uang, Emas, Perak, Perhiasan)
    c.execute('''CREATE TABLE IF NOT EXISTS simpanan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('uang','emas_gram','perak_gram','perhiasan_gram')),
        jumlah_uang REAL DEFAULT 0,
        jumlah_gram REAL DEFAULT 0,
        perhiasan_dipakai INTEGER DEFAULT 0,
        tgl_mulai_haul TEXT DEFAULT CURRENT_DATE
    )''')

    # 5. Khumus Khusus (Harta Karun, Tambang, Selam, Rampasan, Fai)
    c.execute('''CREATE TABLE IF NOT EXISTS khumus_khusus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('harta_karun','tambang','selam_laut','rampasan','fai','lainnya')),
        jumlah REAL,
        biaya_perolehan REAL DEFAULT 0,
        tgl TEXT DEFAULT CURRENT_DATE
    )''')

    # 6. Pengeluaran Kebutuhan Hidup (Pengurang Khumus)
    c.execute('''CREATE TABLE IF NOT EXISTS pengeluaran (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kategori TEXT CHECK(kategori IN ('makan','tempat_tinggal','kesehatan','pendidikan','transport','orang_tanggungan','hutang','lainnya')),
        jumlah REAL,
        tgl TEXT DEFAULT CURRENT_DATE
    )''')

    conn.commit(); conn.close()
    logging.info("✅ Database Raudha siap")

init_db()

# ===================== FUNGSI BANTUAN =====================

def tulis_audit(c, user_id, tabel, rec_id, aksi, field="", lama="", baru="", alasan=""):
    """Catat perubahan ke audit_log."""
    if not user_id: return
    try:
        c.execute("""INSERT INTO audit_log
                     (user_id, tabel, record_id, aksi, field_diubah, nilai_lama, nilai_baru, alasan)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, tabel, rec_id, aksi, field, str(lama), str(baru), alasan))
    except Exception as e:
        logging.error(f"Error audit: {e}")

def serialisasi(tabel, d):
    """Map input JSON ke kolom tabel yang sesuai."""
    kolom_map = {
        "pendapatan":    ["user_id","kategori","jumlah","keterangan","sumber_halal","ongkos_produksi","tgl"],
        "pertanian":     ["user_id","jenis_pangan","hasil_kg","harga_per_kg","irigasi","biaya_panen","tgl_panen"],
        "peternakan":    ["user_id","jenis","jumlah","sistem_grazing","dipekerjakan","tgl_mulai_haul"],
        "simpanan":      ["user_id","jenis","jumlah_uang","jumlah_gram","perhiasan_dipakai","tgl_mulai_haul"],
        "khumus_khusus": ["user_id","jenis","jumlah","biaya_perolehan","tgl"],
        "pengeluaran":   ["user_id","kategori","jumlah","tgl"],
    }
    cols = kolom_map.get(tabel, [])
    params = [d.get(c) for c in cols]
    return cols, params

# ===================== PERHITUNGAN ZAKAT & KHUMUS =====================

def zakat_pertanian(hasil_kg, irigasi):
    """Nisab 653 kg. Kadar 10% (alami) atau 5% (berbiaya)."""
    if hasil_kg < NISAB_PERTANIAN_KG:
        return 0, "Belum capai nisab 653 kg"
    kadar = KADAR_TANAH_ALAMI if irigasi == "alami" else KADAR_TANAH_BIAYA
    return hasil_kg * kadar, f"Capai nisab, kadar {int(kadar*100)}%"

def zakat_peternakan(jenis, jumlah):
    """Hitung kewajiban zakat peternakan bertingkat."""
    if jenis == "kambing":
        if jumlah < 40: return 0, "Belum nishab (min 40)"
        if jumlah < 121: return 1, "1 kambing"
        if jumlah < 201: return 2, "2 kambing"
        if jumlah < 301: return 3, "3 kambing"
        return 3 + (jumlah - 300) // 100, "kambing"
    elif jenis == "sapi":
        if jumlah < 30: return 0, "Belum nishab (min 30)"
        return jumlah // 30, "tabi'/musinnah"
    elif jenis == "unta":
        if jumlah < 5: return 0, "Belum nishab (min 5)"
        if jumlah < 25: return jumlah // 5, "kambing"
        return jumlah // 25, "bintu makhad/labun"
    return 0, "Jenis tidak dikenal"

def cek_haul(tgl_mulai):
    """True jika sudah lewat 1 tahun hijriah ± 354 hari."""
    if not tgl_mulai: return False
    try:
        mulai = datetime.strptime(tgl_mulai[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (datetime.now() - mulai).days >= 354

def laporan_tahunan(user_id, harga_emas, tahun):
    """Hitung zakat & khumus untuk user pada tahun tertentu."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    nisab = NISAB_EMAS_GRAM * harga_emas
    hasil = {}

    # --- 1. ZAKAT PENGHASILAN ---
    c.execute("""SELECT kategori, jumlah, sumber_halal, ongkos_produksi
                 FROM pendapatan WHERE user_id=? AND is_deleted=0""", (user_id,))
    total_bersih, total_bercampur = 0, 0
    for kat, jml, halal, ongkos in c.fetchall():
        bersih = max(0, (jml or 0) - (ongkos or 0))
        if halal == "bercampur_haram":
            total_bercampur += bersih
        else:
            total_bersih += bersih
    
    hasil['total_penghasilan'] = total_bersih
    hasil['zakat_penghasilan'] = total_bersih * KADAR_ZAKAT if total_bersih >= nisab else 0
    hasil['khumus_halal_haram'] = total_bercampur * KADAR_KHUMUS

    # --- 2. ZAKAT PERTANIAN ---
    c.execute("SELECT jenis_pangan, hasil_kg, irigasi, biaya_panen FROM pertanian WHERE user_id=? AND is_deleted=0", (user_id,))
    z_tani_kg = 0
    z_tani_info = []
    for pangan, kg, ir, biaya in c.fetchall():
        if pangan != "padi" and pangan != "gandum" and pangan != "kurma" and pangan != "anggur":
            # Bisa disesuaikan dengan jenis makanan pokok lain
            pass 
        if (kg or 0) < NISAB_PERTANIAN_KG:
            z_tani_info.append(f"{pangan}: {kg} kg < nisab")
            continue
        kadar = KADAR_TANAH_ALAMI if ir == "alami" else KADAR_TANAH_BIAYA
        z_tani_kg += kg * kadar
    hasil['zakat_pertanian_kg'] = z_tani_kg
    hasil['zakat_pertanian_info'] = "; ".join(z_tani_info) if z_tani_info else "Telah dihitung"

    # --- 3. ZAKAT PETERNAKAN ---
    c.execute("""SELECT jenis, SUM(jumlah), sistem_grazing, dipekerjakan
                 FROM peternakan WHERE user_id=? AND is_deleted=0 GROUP BY jenis""", (user_id,))
    hasil['peternakan'] = {}
    for j, n, graze, kerja in c.fetchall():
        if graze == "kandang" or kerja:
            hasil['peternakan'][j] = {"jumlah": n, "wajib_ekor": 0, "info": "Tidak wajib (kandang/kerja)"}
            continue
        wajib, info = zakat_peternakan(j, n)
        hasil['peternakan'][j] = {"jumlah": n, "wajib_ekor": wajib, "info": info}

    # --- 4. ZAKAT SIMPANAN ---
    c.execute("""SELECT jenis, SUM(jumlah_uang), SUM(jumlah_gram), perhiasan_dipakai, tgl_mulai_haul
                 FROM simpanan WHERE user_id=? AND is_deleted=0 GROUP BY jenis""", (user_id,))
    z_simpan = 0
    simpan_info = []
    for jenis, uang, gram, dipakai, tgl in c.fetchall():
        if dipakai:
            continue # Perhiasan pakai tidak dizakati
        if not cek_haul(tgl):
            simpan_info.append(f"{jenis}: belum haul")
            continue
            
        if jenis == "uang": nilai = uang
        elif jenis == "perak_gram": nilai = gram * (harga_emas / 10)
        else: nilai = gram * harga_emas # emas/perhiasan

        if nilai >= nisab:
            z_simpan += nilai * KADAR_ZAKAT
            simpan_info.append(f"{jenis}: ≥ nisab")
    hasil['zakat_simpanan'] = z_simpan
    hasil['simpanan_info'] = "; ".join(simpan_info) if simpan_info else "Telah dihitung"

    # --- 5. KHUMUS KHUSUS ---
    c.execute("SELECT jenis, jumlah, biaya_perolehan FROM khumus_khusus WHERE user_id=? AND is_deleted=0", (user_id,))
    k_khusus = 0
    for jenis, jml, biaya in c.fetchall():
        k_khusus += max(0, (jml or 0) - (biaya or 0)) * KADAR_KHUMUS
    hasil['khumus_khusus'] = round(k_khusus, 2)

    # --- 6. KHUMUS PENDAPATAN (Surplus) ---
    c.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran WHERE user_id=? AND is_deleted=0", (user_id,))
    kebutuhan = c.fetchone()[0]
    kelebihan = max(0, total_bersih - kebutuhan)
    hasil['kelebihan_pendapatan'] = kelebihan
    hasil['khumus_pendapatan'] = round(kelebihan * KADAR_KHUMUS, 2)

    # --- TOTAL ---
    hasil['total_zakat'] = hasil['zakat_penghasilan'] + hasil['zakat_simpanan']
    hasil['total_khumus'] = hasil['khumus_khusus'] + hasil['khumus_pendapatan'] + hasil['khumus_halal_haram']
    hasil['nisab_emas_rupiah'] = nisab
    hasil['harga_emas'] = harga_emas

    conn.close()
    return hasil

# ===================== FUNGSI CRUD =====================

def simpan_data(tabel, data):
    """Simpan data dengan validasi dan audit."""
    if tabel not in VALIDATOR:
        return False, "Tabel tidak dikenal"
    
    errors = VALIDATOR[tabel](data)
    fatal = [e for e in errors if not e.startswith("WASPADA")]
    if fatal:
        return False, fatal

    kolom, nilai = serialisasi(tabel, data)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        cur = c.execute(
            f"INSERT INTO {tabel} ({','.join(kolom)}) VALUES ({','.join('?'*len(kolom))})", nilai)
        tulis_audit(c, data.get('user_id'), tabel, cur.lastrowid, "CREATE", alasan="input awal")
        conn.commit()
        return True, cur.lastrowid
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()

def hapus_data(tabel, rec_id, user_id, alasan=""):
    """Soft delete data."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE {tabel} SET is_deleted=1, catatan_koreksi=? WHERE id=? AND is_deleted=0",
              (alasan, rec_id))
    if c.rowcount > 0:
        tulis_audit(c, user_id, tabel, rec_id, "DELETE", alasan=alasan)
        conn.commit()
        return True
    conn.close()
    return False

def get_riwayat(tabel, rec_id):
    """Ambil riwayat perubahan."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT aksi, field_diubah, nilai_lama, nilai_baru, alasan, waktu
                 FROM audit_log WHERE tabel=? AND record_id=? ORDER BY waktu""", (tabel, rec_id))
    rows = c.fetchall()
    conn.close()
    return [{"aksi":r[0],"field":r[1],"lama":r[2],"baru":r[3],"alasan":r[4],"waktu":r[5]} for r in rows]