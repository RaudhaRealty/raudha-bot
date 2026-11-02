import sqlite3
import os

# Cari lokasi database
DB_PATH = os.path.join("data", "raudha.db")
if not os.path.exists(DB_PATH) and os.path.exists("raudha.db"):
    DB_PATH = "raudha.db"

print(f"Menggunakan database: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. Ubah semua baseline menjadi 0
c.execute("UPDATE users_config SET baseline_awal = 0")

# 2. Opsional: Hapus riwayat jurnal agar benar-benar bersih dari 0
c.execute("DELETE FROM jurnal_syariah")
c.execute("DELETE FROM rencana_pembayaran")
c.execute("DELETE FROM tagihan")

conn.commit()

# 3. Cek hasil
c.execute("SELECT user_id, nama_lengkap, baseline_awal FROM users_config")
users = c.fetchall()

print("\n--- DAFTAR USER ---")
for row in users:
    print(f"User ID: {row[0]} | Nama: {row[1]} | Baseline: {row[2]}")

conn.close()
print("\n✅ Selesai! Semua baseline sudah di-reset ke 0 dan jurnal dibersihkan.")