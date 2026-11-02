import sqlite3
import os
import math
from datetime import datetime

DB_PATH = "data/raudha.db"


# modul_database.py — revisi semua tabel transaksi
def init_db_v2():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    # Kolom standar yang ditambahkan ke SEMUA tabel transaksi
    AUDIT_COLS = """
        is_deleted INTEGER DEFAULT 0,          -- soft delete, bukan DELETE
        versi INTEGER DEFAULT 1,               -- bertambah tiap edit
        dibuat_oleh INTEGER,
        dibuat_pada TEXT DEFAULT CURRENT_TIMESTAMP,
        diubah_pada TEXT,
        diubah_oleh INTEGER,
        catatan_koreksi TEXT
    """

    for tbl in ("pendapatan","pertanian","peternakan","simpanan",
                "khumus_khusus","pengeluaran"):
        for col, typ in [
            ("is_deleted","INTEGER DEFAULT 0"),
            ("versi","INTEGER DEFAULT 1"),
            ("dibuat_pada","TEXT DEFAULT CURRENT_TIMESTAMP"),
            ("diubah_pada","TEXT"),
            ("catatan_koreksi","TEXT"),
        ]:
            try:
                c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass

    # Tabel log perubahan (jejak audit permanen)
    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tabel TEXT,
        record_id INTEGER,
        aksi TEXT CHECK(aksi IN ('CREATE','UPDATE','DELETE','RESTORE')),
        field_diubah TEXT,
        nilai_lama TEXT,
        nilai_baru TEXT,
        alasan TEXT,
        waktu TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit(); conn.close()
    logging.info("✅ Audit & soft-delete siap")

def init_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            last_lat REAL, last_lng REAL,
            last_city TEXT, last_source TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS masjid (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL UNIQUE,
            tipe TEXT DEFAULT 'mitra',
            lat REAL NOT NULL, lng REAL NOT NULL,
            alamat TEXT, kota TEXT, kontak TEXT, catatan TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # modul_database.py — bagian init_db() yang direvisi

    c.execute('''CREATE TABLE IF NOT EXISTS pendapatan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        kategori TEXT,
        jumlah REAL,
        keterangan TEXT,
        -- ▼ variabel syarat baru
        sumber_halal TEXT DEFAULT 'halal',      -- halal | bercampur_haram
        ongkos_produksi REAL DEFAULT 0,
        tgl TEXT DEFAULT CURRENT_DATE
        )
    ''')

    c.execute('''CREATE TABLE IF NOT EXISTS pertanian (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        hasil_kg REAL,
        harga_per_kg REAL,
        irigasi TEXT CHECK(irigasi IN ('alami','berbiaya')),
        -- ▼ variabel syarat baru
        jenis_pangan TEXT DEFAULT 'padi',       -- padi|jagung|kurma|anggur|lain
        biaya_panen REAL DEFAULT 0,
        tgl_panen TEXT DEFAULT CURRENT_DATE
        )
    ''')

    c.execute('''CREATE TABLE IF NOT EXISTS peternakan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('unta','sapi','kambing')),
        jumlah INTEGER,
        -- ▼ variabel syarat baru
        sistem_grazing TEXT DEFAULT 'padang',   -- padang | kandang
        dipekerjakan INTEGER DEFAULT 0,         -- 1 = hewan kerja, tidak dizakati
        jenis_kelamin TEXT DEFAULT 'campuran',  -- jantan|betina|campuran
        tgl_mulai_haul TEXT DEFAULT CURRENT_DATE
        )
    ''')

    c.execute('''CREATE TABLE IF NOT EXISTS simpanan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('uang','emas_gram','perak_gram','perhiasan_gram')),
        jumlah_uang REAL DEFAULT 0,
        jumlah_gram REAL DEFAULT 0,
        -- ▼ variabel syarat baru
        perhiasan_dipakai INTEGER DEFAULT 0,    -- 1 = dipakai rutin
        untuk_kebutuhan_pokok INTEGER DEFAULT 0,
        tgl_mulai_haul TEXT DEFAULT CURRENT_DATE
        )
    ''')

    c.execute('''CREATE TABLE IF NOT EXISTS khumus_khusus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jenis TEXT CHECK(jenis IN ('harta_karun','tambang','selam_laut','rampasan','fai')),
        jumlah REAL,
        -- ▼ variabel syarat baru
        biaya_perolehan REAL DEFAULT 0,
        tgl TEXT DEFAULT CURRENT_DATE
        )
    ''')

    c.execute('''CREATE TABLE IF NOT EXISTS pengeluaran (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        jumlah REAL,
        kategori TEXT CHECK(kategori IN
        ('makan','tempat_tinggal','kesehatan','pendidikan',
        'transport','orang_tanggungan','hutang','lainnya')),
        tgl TEXT DEFAULT CURRENT_DATE
        )
    ''')

    conn.commit()
    conn.close()
    print(f"[OK] Database siap: {DB_PATH}")

def simpan_lokasi_user(telegram_id, lat, lng, kota=None, sumber="gps"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (telegram_id, last_lat, last_lng, last_city, last_source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            last_lat=excluded.last_lat, last_lng=excluded.last_lng,
            last_city=excluded.last_city, last_source=excluded.last_source,
            updated_at=excluded.updated_at
    """, (telegram_id, lat, lng, kota, sumber, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def ambil_lokasi_user(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_lat, last_lng, last_city, last_source FROM users WHERE telegram_id=?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"lat": row[0], "lng": row[1], "kota": row[2], "sumber": row[3]}
    return None

def hitung_jarak(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return float("inf")
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def migrasi():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    for tbl, col, typ in [
        ("pendapatan","sumber_halal","TEXT DEFAULT 'halal'"),
        ("pendapatan","ongkos_produksi","REAL DEFAULT 0"),
        ("pertanian","jenis_pangan","TEXT DEFAULT 'padi'"),
        ("pertanian","biaya_panen","REAL DEFAULT 0"),
        ("peternakan","sistem_grazing","TEXT DEFAULT 'padang'"),
        ("peternakan","dipekerjakan","INTEGER DEFAULT 0"),
        ("simpanan","perhiasan_dipakai","INTEGER DEFAULT 0"),
        ("simpanan","untuk_kebutuhan_pokok","INTEGER DEFAULT 0"),
        ("khumus_khusus","biaya_perolehan","REAL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typ}")
            logging.info(f"✅ Migrasi {tbl}.{col}")
        except sqlite3.OperationalError:
            pass  # sudah ada
    conn.commit(); conn.close()

def cek_haul(tgl_mulai):
    """True jika sudah lewat 1 tahun hijriah ± 354 hari."""
    if not tgl_mulai: return False
    try:
        mulai = datetime.strptime(tgl_mulai[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (datetime.now() - mulai).days >= 354


def laporan_tahunan(user_id, harga_emas, tahun):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    nisab_emas  = NISAB_EMAS_GRAM * harga_emas
    nisab_perak = NISAB_PERAK_GRAM * (harga_emas / 10)
    hasil, catatan_syarat = {}, []

    # ---- 1. PENGHASILAN ----
    c.execute("""SELECT kategori, jumlah, sumber_halal, ongkos_produksi
                 FROM pendapatan WHERE user_id=?""", (user_id,))
    total_bersih, total_bercampur = 0, 0
    for kat, jml, halal, ongkos in c.fetchall():
        bersih = max(0, (jml or 0) - (ongkos or 0))
        if halal == "bercampur_haram":
            total_bercampur += bersih          # → jalur khumus penyucian
        else:
            total_bersih += bersih
    hasil['total_penghasilan'] = total_bersih
    hasil['zakat_penghasilan'] = total_bersih * KADAR_ZAKAT if total_bersih >= nisab_emas else 0
    if total_bersih < nisab_emas:
        catatan_syarat.append(f"Penghasilan Rp{format_idr(total_bersih)} < nisab Rp{format_idr(nisab_emas)} → zakat penghasilan gugur")
    hasil['khumus_halal_haram'] = total_bercampur * KADAR_KHUMUS

    # ---- 2. PERTANIAN ----
    c.execute("SELECT hasil_kg, irigasi, jenis_pangan, biaya_panen FROM pertanian WHERE user_id=?", (user_id,))
    z_tani_nilai, z_tani_kg = 0, 0
    for kg, ir, pangan, biaya in c.fetchall():
        if pangan == "lain":
            catatan_syarat.append(f"Panen '{pangan}' bukan makanan pokok → tidak kena zakat")
            continue
        if (kg or 0) < NISAB_PERTANIAN_KG:
            catatan_syarat.append(f"Panen {kg} kg < nisab 653 kg → belum wajib")
            continue
        kadar = KADAR_TANAH_ALAMI if ir == "alami" else KADAR_TANAH_BIAYA
        z_tani_kg  += kg * kadar
        z_tani_nilai += max(0, kg * kadar * (harga_pangan or 0) - (biaya or 0))
    hasil['zakat_pertanian_kg']    = round(z_tani_kg, 2)
    hasil['zakat_pertanian_nilai'] = round(z_tani_nilai)

    # ---- 3. PETERNAKAN ----
    c.execute("""SELECT jenis, SUM(jumlah), sistem_grazing, dipekerjakan
                 FROM peternakan WHERE user_id=? GROUP BY jenis""", (user_id,))
    hasil['peternakan'] = {}
    for j, n, graze, kerja in c.fetchall():
        if graze == "kandang":
            hasil['peternakan'][j] = {"jumlah": n, "wajib_ekor": 0,
                "info": "Dikandangkan → tidak kena zakat"}
            continue
        if kerja:
            hasil['peternakan'][j] = {"jumlah": n, "wajib_ekor": 0,
                "info": "Hewan pekerjaan → tidak kena zakat"}
            continue
        wajib, info = zakat_peternakan(j, n)
        hasil['peternakan'][j] = {"jumlah": n, "wajib_ekor": wajib, "info": info}


    # ---- 4. SIMPANAN ----
    c.execute("""SELECT jenis, SUM(jumlah_uang), SUM(jumlah_gram),
                        perhiasan_dipakai, untuk_kebutuhan_pokok, tgl_mulai_haul
                 FROM simpanan WHERE user_id=? GROUP BY jenis""", (user_id,))
    z_simpan = 0
    for jenis, uang, gram, dipakai, pokok, tgl in c.fetchall():
        if pokok:
            catatan_syarat.append(f"{jenis}: untuk kebutuhan pokok → gugur")
            continue
        if not cek_haul(tgl):
            catatan_syarat.append(f"{jenis}: belum 1 haul ({tgl}) → ditunda")
            continue
        if jenis == "uang":
            nilai, batas = uang or 0, nisab_emas
        elif jenis == "perak_gram":
            nilai, batas = (gram or 0) * (harga_emas/10), nisab_perak
        else:
            if jenis == "perhiasan_gram" and dipakai:
                catatan_syarat.append("Perhiasan dipakai rutin → pendapat tidak wajib")
                continue
            nilai, batas = (gram or 0) * harga_emas, nisab_emas
        if nilai >= batas:
            z_simpan += nilai * KADAR_ZAKAT
        else:
            catatan_syarat.append(f"{jenis} Rp{format_idr(nilai)} < nisab → belum wajib")
    hasil['zakat_simpanan'] = z_simpan

    # ---- 5. KHUMUS KHUSUS ----
    c.execute("SELECT jenis, jumlah, biaya_perolehan FROM khumus_khusus WHERE user_id=?", (user_id,))
    k_khusus = 0
    for jenis, jml, biaya in c.fetchall():
        k_khusus += max(0, (jml or 0) - (biaya or 0)) * KADAR_KHUMUS
    hasil['khumus_khusus'] = round(k_khusus)

    # ---- 6. KHUMUS PENDAPATAN ----
    c.execute("SELECT kategori, SUM(jumlah) FROM pengeluaran WHERE user_id=? GROUP BY kategori", (user_id,))
    rincian_keluar = {k: v for k, v in c.fetchall()}
    kebutuhan = sum(rincian_keluar.values())
    kelebihan = max(0, total_bersih - kebutuhan)
    hasil['rincian_pengeluaran']  = rincian_keluar
    hasil['kelebihan_pendapatan'] = kelebihan
    hasil['khumus_pendapatan']    = kelebihan * KADAR_KHUMUS

    # ---- TOTAL & AUDIT ----
    hasil['total_zakat'] = hasil['zakat_penghasilan'] + hasil['zakat_simpanan'] + hasil['zakat_pertanian_nilai']
    hasil['total_khumus'] = hasil['khumus_khusus'] + hasil['khumus_pendapatan'] + hasil['khumus_halal_haram']
    hasil['catatan_syarat'] = catatan_syarat
    hasil['nisab_emas_rupiah'], hasil['harga_emas'] = nisab_emas, harga_emas
    conn.close()
    return hasil

if __name__ == "__main__":
    init_db()
    simpan_lokasi_user(999999, -7.353458, 109.544621, kota="Danakerta", sumber="gps")
    print("Lokasi:", ambil_lokasi_user(999999))
    print("Jarak:", hitung_jarak(-7.353458, 109.544621, -7.3586, 109.5372))
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users WHERE telegram_id=999999")
    conn.commit(); conn.close()