# migrasi_nomor.py
import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

c.execute('PRAGMA table_info(rencana_pembayaran)')
cols = [r[1] for r in c.fetchall()]
print('Kolom rencana_pembayaran:', cols)

if 'nomor_dokumen' not in cols:
    c.execute('ALTER TABLE rencana_pembayaran ADD COLUMN nomor_dokumen TEXT')
    conn.commit()
    print('✅ Kolom nomor_dokumen DITAMBAHKAN')
else:
    print('ℹ️ Kolom nomor_dokumen SUDAH ADA')

conn.close()
print('✅ Migrasi selesai')