import sqlite3
import os
import math
from datetime import datetime

DB_PATH = "data/raudha.db"

def init_db():
    """Buat folder + tabel kalau belum ada."""
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Tabel user + lokasi terakhir
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            last_lat REAL,
            last_lng REAL,
            last_city TEXT,
            last_source TEXT,
            updated_at TEXT
        )
    """)

    # Tabel masjid (Raudha + mitra)
    c.execute("""
        CREATE TABLE IF NOT EXISTS masjid (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL UNIQUE,
            tipe TEXT DEFAULT 'mitra',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            alamat TEXT,
            kota TEXT,
            kontak TEXT,
            catatan TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
            last_lat=excluded.last_lat,
            last_lng=excluded.last_lng,
            last_city=excluded.last_city,
            last_source=excluded.last_source,
            updated_at=excluded.updated_at
    """, (telegram_id, lat, lng, kota, sumber, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def ambil_lokasi_user(telegram_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_lat, last_lng, last_city, last_source FROM users WHERE telegram_id=?",
              (telegram_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"lat": row[0], "lng": row[1], "kota": row[2], "sumber": row[3]}
    return None

# HITUNG JARAK ----------

def hitung_jarak(lat1, lng1, lat2, lng2):
    """Hitung jarak antara 2 titik (Haversine). Output: kilometer."""
    if None in (lat1, lng1, lat2, lng2):
        return float("inf")

    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


if __name__ == "__main__":
    print("Testing modul_database.py...\n")
    init_db()

    print("\nTest simpan lokasi user...")
    simpan_lokasi_user(
        telegram_id=999999,
        lat=-7.353458, lng=109.544621,
        kota="Danakerta", sumber="gps"
    )
    hasil = ambil_lokasi_user(999999)
    print(f"   Lokasi tersimpan: {hasil}")

    print("\nTest hitung jarak...")
    jarak = hitung_jarak(-7.353458, 109.544621, -7.3586, 109.5372)
    print(f"   Masjid Al Falah - pusat Danakerta: {jarak:.3f} km")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM users WHERE telegram_id=999999")
    conn.commit()
    conn.close()
    print("\nData test dibersihkan.")
    print("\n[OK] modul_database.py OK!")