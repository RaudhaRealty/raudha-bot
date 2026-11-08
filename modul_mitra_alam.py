# modul_mitra_alam.py — Modul Wakaf Produktif Tanaman (Mitra Alam Raudha)
"""
Modul ini menangani LOGIKA BISNIS Mitra Alam:
- CRUD pohon_wakaf, pohon_log, pohon_panen
- Statistik & laporan

CATATAN: Tabel database dibuat di app.py (init_web_db()).
Modul ini hanya menyediakan fungsi operasional.
"""

import sqlite3
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

DB_PATH = "data/raudha.db"


# =====================================================================
# VERIFIKASI TABEL (dipanggil setelah init_web_db)
# =====================================================================

def init_db_mitra_alam():
    """
    Verifikasi tabel Mitra Alam sudah ada (dibuat oleh init_web_db).
    Tidak membuat tabel baru — hanya cek & log.
    """
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in c.fetchall()}
    conn.close()

    required = ['komoditas_wakaf', 'pohon_wakaf', 'pohon_log', 'pohon_panen']
    missing = [t for t in required if t not in tables]

    if missing:
        logger.error(f"❌ Tabel Mitra Alam hilang: {missing}")
        raise RuntimeError(f"Tabel Mitra Alam belum dibuat: {missing}")

    logger.info("✅ Modul Mitra Alam siap (tabel terverifikasi)")


# ... (semua fungsi helper lain tetap sama: get_semua_komoditas,
#      get_komoditas_by_id, daftarkan_pohon, get_pohon_by_uid,
#      get_pohon_user, get_pohon_by_lembaga, tambah_log,
#      get_log_pohon, catat_panen, get_panen_pohon, statistik_mitra_alam)


# =====================================================================
# HELPER: KOMODITAS
# =====================================================================

def get_semua_komoditas():
    """Ambil semua komoditas aktif."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, kode, nama_display, harga_pohon, output,
                        siklus_panen, nilai_ekonomi, fungsi_ekologis,
                        deskripsi, foto_url
                 FROM komoditas_wakaf WHERE aktif=1 ORDER BY id""")
    rows = c.fetchall(); conn.close()
    keys = ["id","kode","nama_display","harga_pohon","output",
            "siklus_panen","nilai_ekonomi","fungsi_ekologis",
            "deskripsi","foto_url"]
    return [dict(zip(keys, r)) for r in rows]


def get_komoditas_by_id(komoditas_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, kode, nama_display, harga_pohon, output,
                        siklus_panen, nilai_ekonomi, fungsi_ekologis, deskripsi
                 FROM komoditas_wakaf WHERE id=? AND aktif=1""", (komoditas_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return None
    keys = ["id","kode","nama_display","harga_pohon","output",
            "siklus_panen","nilai_ekonomi","fungsi_ekologis","deskripsi"]
    return dict(zip(keys, row))


# =====================================================================
# HELPER: POHON WAKAF
# =====================================================================

def daftarkan_pohon(nfc_uid, komoditas_id, lembaga_id, muwakif_id=None,
                    varietas=None, lat=None, lng=None, tanggal_tanam=None,
                    rencana_id=None, catatan=None):
    """
    Daftarkan pohon baru. Return (sukses, pesan, pohon_id).
    """
    if not nfc_uid or not komoditas_id or not lembaga_id:
        return False, "NFC UID, komoditas, dan lembaga wajib diisi", None

    # Cek komoditas
    kom = get_komoditas_by_id(komoditas_id)
    if not kom:
        return False, "Komoditas tidak ditemukan", None

    # Cek NFC UID unik
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT 1 FROM pohon_wakaf WHERE nfc_uid=?", (nfc_uid,))
    if c.fetchone():
        conn.close()
        return False, f"NFC UID '{nfc_uid}' sudah terdaftar", None

    # Cek lembaga ada
    c.execute("SELECT 1 FROM lembaga_amil WHERE id=?", (lembaga_id,))
    if not c.fetchone():
        conn.close()
        return False, "Lembaga/masjid tidak ditemukan", None

    try:
        c.execute("""INSERT INTO pohon_wakaf
                     (nfc_uid, komoditas_id, varietas, tanggal_tanam,
                      lat, lng, lembaga_id, muwakif_id, rencana_id,
                      harga_pohon, status, catatan, updated_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?, 'aktif', ?, CURRENT_TIMESTAMP)""",
                  (nfc_uid, komoditas_id, varietas,
                   tanggal_tanam or date.today().strftime("%Y-%m-%d"),
                   lat, lng, lembaga_id, muwakif_id, rencana_id,
                   kom["harga_pohon"], catatan))
        pohon_id = c.lastrowid
        conn.commit()
        logger.info(f"🌱 Pohon baru terdaftar: id={pohon_id}, nfc={nfc_uid}")
        return True, f"Pohon {kom['nama_display']} berhasil didaftarkan", pohon_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Gagal daftar pohon: {e}")
        return False, f"Error: {e}", None
    finally:
        conn.close()


def get_pohon_by_uid(nfc_uid):
    """Ambil detail pohon via NFC UID."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT p.id, p.nfc_uid, p.komoditas_id, k.nama_display,
                        p.varietas, p.tanggal_tanam, p.lat, p.lng,
                        p.lembaga_id, l.nama AS lembaga_nama,
                        p.muwakif_id, u.nama_lengkap AS muwakif_nama,
                        p.harga_pohon, p.status, p.catatan, p.created_at
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 JOIN lembaga_amil l ON l.id = p.lembaga_id
                 LEFT JOIN users_config u ON u.user_id = p.muwakif_id
                 WHERE p.nfc_uid=?""", (nfc_uid,))
    row = c.fetchone(); conn.close()
    if not row:
        return None
    keys = ["id","nfc_uid","komoditas_id","komoditas_nama","varietas",
            "tanggal_tanam","lat","lng","lembaga_id","lembaga_nama",
            "muwakif_id","muwakif_nama","harga_pohon","status","catatan","created_at"]
    return dict(zip(keys, row))


def get_pohon_user(muwakif_id):
    """Ambil semua pohon milik user (muwakif)."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT p.id, p.nfc_uid, k.nama_display,
                        p.tanggal_tanam, p.status, p.lat, p.lng,
                        l.nama AS lembaga_nama,
                        (SELECT foto_url FROM pohon_log
                         WHERE pohon_id=p.id AND tipe='foto'
                         ORDER BY tanggal DESC LIMIT 1) AS foto_terakhir,
                        (SELECT nilai FROM pohon_log
                         WHERE pohon_id=p.id AND tipe='tinggi'
                         ORDER BY tanggal DESC LIMIT 1) AS tinggi_terakhir,
                        (SELECT COUNT(*) FROM pohon_log WHERE pohon_id=p.id) AS jumlah_log
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 JOIN lembaga_amil l ON l.id = p.lembaga_id
                 WHERE p.muwakif_id=?
                 ORDER BY 
                   CASE p.status 
                     WHEN 'aktif' THEN 0 
                     WHEN 'menunggu_tanam' THEN 1 
                     WHEN 'dipanen' THEN 2 
                     WHEN 'mati' THEN 3 
                     ELSE 4 
                   END,
                   p.created_at DESC""", (muwakif_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","nfc_uid","komoditas_nama","tanggal_tanam","status",
            "lat","lng","lembaga_nama","foto_terakhir","tinggi_terakhir","jumlah_log"]
    return [dict(zip(keys, r)) for r in rows]


def get_pohon_by_lembaga(lembaga_id):
    """Ambil pohon di lahan lembaga/masjid tertentu."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT p.id, p.nfc_uid, k.nama_display,
                        p.tanggal_tanam, p.status, p.muwakif_id,
                        u.nama_lengkap AS muwakif_nama
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 LEFT JOIN users_config u ON u.user_id = p.muwakif_id
                 WHERE p.lembaga_id=?
                 ORDER BY p.created_at DESC""", (lembaga_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","nfc_uid","komoditas_nama","tanggal_tanam","status",
            "muwakif_id","muwakif_nama"]
    return [dict(zip(keys, r)) for r in rows]


# =====================================================================
# HELPER: LOG PERAWATAN
# =====================================================================

def tambah_log(pohon_id, tipe, nilai=None, foto_url=None,
               catatan=None, petugas_id=None, tanggal=None):
    """
    Tambah log perawatan/pemantauan pohon.
    tipe: 'foto', 'tinggi', 'kondisi', 'pupuk', 'penyakit', 'lainnya'
    """
    if tipe not in ('foto','tinggi','kondisi','pupuk','penyakit','lainnya','panen'):
        return False, f"Tipe log tidak valid: {tipe}"

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM pohon_wakaf WHERE id=?", (pohon_id,))
        if not c.fetchone():
            return False, "Pohon tidak ditemukan"

        c.execute("""INSERT INTO pohon_log
                     (pohon_id, tanggal, tipe, nilai, foto_url, catatan, petugas_id)
                     VALUES (?,?,?,?,?,?,?)""",
                  (pohon_id,
                   tanggal or date.today().strftime("%Y-%m-%d"),
                   tipe, nilai, foto_url, catatan, petugas_id))
        conn.commit()
        return True, "Log tersimpan"
    except Exception as e:
        conn.rollback()
        return False, f"Error: {e}"
    finally:
        conn.close()


def get_log_pohon(pohon_id, limit=50):
    """Ambil riwayat log pohon."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, tanggal, tipe, nilai, foto_url, catatan, petugas_id
                 FROM pohon_log WHERE pohon_id=?
                 ORDER BY tanggal DESC, id DESC LIMIT ?""", (pohon_id, limit))
    rows = c.fetchall(); conn.close()
    keys = ["id","tanggal","tipe","nilai","foto_url","catatan","petugas_id"]
    return [dict(zip(keys, r)) for r in rows]


# =====================================================================
# HELPER: PANEN (Bagi Hasil Otomatis 70/20/10)
# =====================================================================

def _fmt_rp(nilai):
    """Format angka jadi Rupiah: 175000 → 'Rp 175.000'"""
    try:
        return f"Rp {int(round(float(nilai))):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"


def catat_panen(pohon_id, tanggal_panen, hasil_kg=0, hasil_nominal=0,
                catatan=None, petugas_id=None):
    """
    Catat panen & hitung bagi hasil otomatis (70% masjid, 20% perawatan, 10% Raudha).
    Return (sukses: bool, pesan: str).
    """
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        # Cek pohon ada
        c.execute("SELECT 1 FROM pohon_wakaf WHERE id=?", (pohon_id,))
        if not c.fetchone():
            return False, "Pohon tidak ditemukan"

        # Validasi
        if hasil_nominal < 0:
            return False, "Nominal panen tidak boleh negatif"

        # Hitung bagi hasil
        p_masjid = hasil_nominal * 0.70
        p_perawatan = hasil_nominal * 0.20
        p_raudha = hasil_nominal * 0.10

        # Simpan
        c.execute("""INSERT INTO pohon_panen
                     (pohon_id, tanggal_panen, hasil_kg, hasil_nominal,
                      pembagian_masjid, pembagian_perawatan, pembagian_raudha,
                      catatan, petugas_id)
                     VALUES (?,?,?,?,?,?,?,?,?)""",
                  (pohon_id, tanggal_panen, hasil_kg, hasil_nominal,
                   p_masjid, p_perawatan, p_raudha, catatan, petugas_id))
        conn.commit()

        # Pesan ringkas (format Rupiah konsisten)
        pesan = (
            f"Panen tercatat: {hasil_kg} kg / {_fmt_rp(hasil_nominal)}\n"
            f"Bagi hasil:\n"
            f"  🕌 Masjid:    {_fmt_rp(p_masjid)}\n"
            f"  🌿 Perawatan: {_fmt_rp(p_perawatan)}\n"
            f"  🏛️ Raudha:    {_fmt_rp(p_raudha)}"
        )
        return True, pesan
    except Exception as e:
        conn.rollback()
        return False, f"Error: {e}"
    finally:
        conn.close()


def get_panen_pohon(pohon_id):
    """Ambil riwayat panen pohon."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, tanggal_panen, hasil_kg, hasil_nominal,
                        pembagian_masjid, pembagian_perawatan, pembagian_raudha, catatan
                 FROM pohon_panen WHERE pohon_id=?
                 ORDER BY tanggal_panen DESC, id DESC""", (pohon_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","tanggal_panen","hasil_kg","hasil_nominal",
            "pembagian_masjid","pembagian_perawatan","pembagian_raudha","catatan"]
    return [dict(zip(keys, r)) for r in rows]


def get_total_panen_pohon(pohon_id):
    """Total kumulatif panen untuk 1 pohon."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT 
                    COUNT(*),
                    COALESCE(SUM(hasil_kg), 0),
                    COALESCE(SUM(hasil_nominal), 0),
                    COALESCE(SUM(pembagian_masjid), 0),
                    COALESCE(SUM(pembagian_perawatan), 0),
                    COALESCE(SUM(pembagian_raudha), 0)
                 FROM pohon_panen WHERE pohon_id=?""", (pohon_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"count": 0, "total_kg": 0, "total_nominal": 0,
                "total_masjid": 0, "total_perawatan": 0, "total_raudha": 0}
    return {
        "count": row[0],
        "total_kg": row[1],
        "total_nominal": row[2],
        "total_masjid": row[3],
        "total_perawatan": row[4],
        "total_raudha": row[5],
    }


def get_total_panen_lembaga(lembaga_id):
    """Total kumulatif panen untuk semua pohon di lembaga tertentu."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT 
                    COUNT(*),
                    COALESCE(SUM(pp.hasil_kg), 0),
                    COALESCE(SUM(pp.hasil_nominal), 0),
                    COALESCE(SUM(pp.pembagian_masjid), 0),
                    COALESCE(SUM(pp.pembagian_perawatan), 0),
                    COALESCE(SUM(pp.pembagian_raudha), 0)
                 FROM pohon_panen pp
                 JOIN pohon_wakaf pw ON pw.id = pp.pohon_id
                 WHERE pw.lembaga_id=?""", (lembaga_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return {"count": 0, "total_kg": 0, "total_nominal": 0,
                "total_masjid": 0, "total_perawatan": 0, "total_raudha": 0}
    return {
        "count": row[0],
        "total_kg": row[1],
        "total_nominal": row[2],
        "total_masjid": row[3],
        "total_perawatan": row[4],
        "total_raudha": row[5],
    }

# =====================================================================
# STATISTIK
# =====================================================================

def statistik_mitra_alam():
    """Statistik global program Mitra Alam."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM pohon_wakaf WHERE status='aktif'")
    total_pohon = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT muwakif_id) FROM pohon_wakaf WHERE muwakif_id IS NOT NULL")
    total_muwakif = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT lembaga_id) FROM pohon_wakaf")
    total_lahan = c.fetchone()[0]

    c.execute("""SELECT COALESCE(SUM(hasil_nominal), 0),
                        COALESCE(SUM(pembagian_masjid), 0)
                 FROM pohon_panen""")
    total_panen_nominal, total_bagi_masjid = c.fetchone()

    conn.close()
    return {
        "total_pohon": total_pohon,
        "total_muwakif": total_muwakif,
        "total_lahan": total_lahan,
        "total_panen_nominal": total_panen_nominal,
        "total_bagi_masjid": total_bagi_masjid,
    }