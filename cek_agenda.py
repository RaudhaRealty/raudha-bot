import sqlite3

DB_PATH = "data/raudha.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("=== DAFTAR AGENDA DI DATABASE ===")
c.execute("SELECT id, lembaga_id, tipe, tanggal, nama, pemateri FROM agenda_masjid")
rows = c.fetchall()

if not rows:
    print("❌ Tabel agenda_masjid KOSONG. Data tidak tersimpan.")
else:
    for r in rows:
        print(f"ID: {r[0]} | Lembaga: {r[1]} | Tipe: {r[2]} | Tgl: {r[3]} | Nama: {r[4]} | Pemateri: {r[5]}")

print("\n=== DAFTAR LEMBAGA & KODE TV ===")
c.execute("""SELECT l.id, l.nama, t.tv_code 
             FROM lembaga_amil l 
             LEFT JOIN tv_masjid_config t ON t.lembaga_id = l.id""")
for r in c.fetchall():
    print(f"Lembaga ID: {r[0]} | Nama: {r[1]} | Kode TV: {r[2]}")

conn.close()