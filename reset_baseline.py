import sqlite3

DB_PATH = "data/raudha.db" # Sesuaikan jika nama path-nya berbeda

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. Ubah semua baseline menjadi 0
c.execute("UPDATE users_config SET baseline_awal = 0")
conn.commit()

# 2. Cek hasil
c.execute("SELECT user_id, nama_lengkap, baseline_awal FROM users_config")
for row in c.fetchall():
    print(f"User {row[0]} ({row[1]}): Baseline = {row[2]}")

conn.close()
print("\n✅ Selesai! Semua baseline sudah di-reset ke 0.")