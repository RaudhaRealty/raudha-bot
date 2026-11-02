# hapus_harta.py
import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

# Hapus jurnal
c.execute("DELETE FROM jurnal_syariah WHERE user_id=472469108")
jurnal_deleted = c.rowcount
print(f'Jurnal dihapus: {jurnal_deleted}')

# Hapus pembayaran
c.execute("DELETE FROM rencana_pembayaran WHERE user_id=472469108")
pembayaran_deleted = c.rowcount
print(f'Pembayaran dihapus: {pembayaran_deleted}')

# Set baseline
c.execute("UPDATE users_config SET baseline_awal=100000 WHERE user_id=472469108")
conn.commit()
print('Baseline jadi Rp 100.000')

# Verifikasi
c.execute("SELECT user_id, baseline_awal FROM users_config WHERE user_id=472469108")
print('User:', c.fetchone())
c.execute("SELECT COUNT(*) FROM jurnal_syariah WHERE user_id=472469108")
print('Jurnal:', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM rencana_pembayaran WHERE user_id=472469108")
print('Pembayaran:', c.fetchone()[0])

conn.close()
print('✅ Selesai')