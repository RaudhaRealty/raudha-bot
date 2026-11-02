import json
import os
import sqlite3

DB_PATH = "data/raudha.db"
SEED_PATH = "data/masjid_seed.json"

def load_seed_masjid():
    if not os.path.exists(SEED_PATH):
        print(f"[WARN] File seed tidak ditemukan: {SEED_PATH}")
        return (0, 0)
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    semua = data.get("raudha", []) + data.get("mitra", [])
    if not semua:
        print("[INFO] Tidak ada data masjid di seed file.")
        return (0, 0)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
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
    inserted, updated = 0, 0
    for m in semua:
        nama = m.get("nama")
        if not nama:
            print(f"[SKIP] Masjid tanpa nama: {m}")
            continue
        c.execute("SELECT id FROM masjid WHERE nama = ?", (nama,))
        row = c.fetchone()
        if row:
            c.execute("""
                UPDATE masjid SET tipe=?, lat=?, lng=?, alamat=?, kota=?,
                kontak=?, catatan=?, updated_at=CURRENT_TIMESTAMP WHERE nama=?
            """, (
                m.get("tipe", "mitra"), m.get("lat"), m.get("lng"),
                m.get("alamat"), m.get("kota"), m.get("kontak"),
                m.get("catatan"), nama
            ))
            updated += 1
        else:
            c.execute("""
                INSERT INTO masjid (nama, tipe, lat, lng, alamat, kota, kontak, catatan)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                nama, m.get("tipe", "mitra"), m.get("lat"), m.get("lng"),
                m.get("alamat"), m.get("kota"), m.get("kontak"), m.get("catatan")
            ))
            inserted += 1
    conn.commit()
    conn.close()
    print(f"[OK] Seed selesai: {inserted} baru, {updated} diperbarui.")
    return (inserted, updated)

def list_masjid():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nama, tipe, lat, lng, kota FROM masjid ORDER BY tipe, nama")
    rows = c.fetchall()
    conn.close()
    print(f"\nDaftar Masjid ({len(rows)} total):")
    print("-" * 75)
    for r in rows:
        tanda = "R" if r[2] == "raudha" else " "
        print(f" [{tanda}] id={r[0]:<3} {r[1]:<30} {r[3]:>10.4f}, {r[4]:>10.4f}  {r[5] or '-'}")
    print("-" * 75)

if __name__ == "__main__":
    from modul_database import init_db
    init_db()
    load_seed_masjid()
    list_masjid()