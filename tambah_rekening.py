import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM rekening_lembaga WHERE lembaga_id=7 AND aktif=1")
count = c.fetchone()[0]
print('Rekening aktif:', count)

if count == 0:
    c.execute('''INSERT INTO rekening_lembaga 
                 (lembaga_id, metode, nama_bank, nomor_rekening, atas_nama, aktif) 
                 VALUES (7, "bank_transfer", "BSI", "9876543210", "LAZIZ - BMT RAUDHA", 1)''')
    conn.commit()
    print('✅ Rekening ditambahkan')
else:
    print('ℹ️ Rekening sudah ada')

conn.close()