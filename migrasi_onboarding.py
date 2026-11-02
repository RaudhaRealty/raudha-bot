# migrasi_onboarding.py
import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

c.execute('PRAGMA table_info(users_config)')
cols = [r[1] for r in c.fetchall()]
print('Kolom users_config:', cols)

if 'onboarding_selesai' not in cols:
    c.execute('ALTER TABLE users_config ADD COLUMN onboarding_selesai INTEGER DEFAULT 0')
    conn.commit()
    print('✅ Kolom onboarding_selesai DITAMBAHKAN')
else:
    print('ℹ️ Kolom onboarding_selesai SUDAH ADA')

# Verifikasi
c.execute('PRAGMA table_info(users_config)')
print('\nKolom setelah migrasi:')
for r in c.fetchall():
    print(f'  {r[1]:<25} {r[2]}')

conn.close()
print('\n✅ Migrasi selesai')