# migrasi_bahasa.py
import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

# Cek kolom
c.execute('PRAGMA table_info(users_config)')
cols = [r[1] for r in c.fetchall()]
print('Kolom users_config saat ini:', cols)

if 'bahasa' not in cols:
    c.execute('ALTER TABLE users_config ADD COLUMN bahasa TEXT DEFAULT "id"')
    conn.commit()
    print('✅ Kolom bahasa DITAMBAHKAN')
else:
    print('ℹ️ Kolom bahasa SUDAH ADA')

# Verifikasi
c.execute('PRAGMA table_info(users_config)')
print('\nKolom setelah migrasi:')
for r in c.fetchall():
    print(f'  {r[1]:<25} {r[2]}')

conn.close()
print('\n✅ Migrasi selesai')