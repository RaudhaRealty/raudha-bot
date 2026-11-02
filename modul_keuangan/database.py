import sqlite3
DB_PATH = "data/keuangan_privat.db"

def init_db_keuangan():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kas_harian (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tanggal TEXT DEFAULT (date('now')),
            jenis TEXT, jumlah REAL, kategori TEXT, keterangan TEXT
        )
    ''')
    conn.commit()
    conn.close()

def catat_transaksi(user_id, jenis, jumlah, kategori="umum", keterangan=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO kas_harian (user_id, jenis, jumlah, kategori, keterangan) VALUES (?, ?, ?, ?, ?)",
        (user_id, jenis, jumlah, kategori, keterangan)
    )
    conn.commit()
    conn.close()

def ambil_saldo_aktif(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM kas_harian WHERE user_id=? AND jenis='masuk'", (user_id,))
    masuk = float(cursor.fetchone()[0])
    cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM kas_harian WHERE user_id=? AND jenis='keluar'", (user_id,))
    keluar = float(cursor.fetchone()[0])
    conn.close()
    return masuk - keluar