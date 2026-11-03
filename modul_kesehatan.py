# modul_kesehatan.py
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join("data", "raudha.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "raudha.db"

def init_db_kesehatan():
    """Membuat tabel untuk program kesehatan dan RSVP."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Tabel Program Kesehatan
    c.execute("""CREATE TABLE IF NOT EXISTS program_kesehatan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT NOT NULL,
        jenis TEXT NOT NULL,
        tanggal TEXT NOT NULL,
        waktu TEXT NOT NULL,
        lokasi TEXT NOT NULL,
        kuota INTEGER DEFAULT 30,
        mitra TEXT DEFAULT 'Aeesha Medical Center',
        aktif INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # Tabel RSVP Peserta
    c.execute("""CREATE TABLE IF NOT EXISTS rsvp_kesehatan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        nama TEXT,
        telepon TEXT,
        status TEXT DEFAULT 'terdaftar',
        waktu_daftar TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(program_id, user_id)
    )""")
    
    # Isi data dummy jika tabel kosong (untuk testing)
    c.execute("SELECT COUNT(*) FROM program_kesehatan")
    if c.fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d")
        c.execute("""INSERT INTO program_kesehatan (nama, jenis, tanggal, waktu, lokasi, kuota) 
                     VALUES (?, ?, ?, ?, ?, ?)""", 
                  ("Senam Ahad", "senam", now, "06:00 - 07:30", "Aula Masjid Al Falah", 50))
        c.execute("""INSERT INTO program_kesehatan (nama, jenis, tanggal, waktu, lokasi, kuota) 
                     VALUES (?, ?, ?, ?, ?, ?)""", 
                  ("Cek Tensi Jumat", "tensi", now, "08:00 - 10:00", "Aula Masjid Al Falah", 30))

    conn.commit()
    conn.close()

def get_program_aktif():
    """Mengambil daftar program yang aktif beserta sisa kuota."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT p.id, p.nama, p.jenis, p.tanggal, p.waktu, p.lokasi, p.kuota, p.mitra,
                 (SELECT COUNT(*) FROM rsvp_kesehatan r WHERE r.program_id = p.id AND r.status = 'terdaftar') as terisi
                 FROM program_kesehatan p WHERE p.aktif = 1 ORDER BY p.id DESC""")
    rows = c.fetchall()
    conn.close()
    
    hasil = []
    for r in rows:
        sisa = r[6] - r[8]
        hasil.append({
            "id": r[0], "nama": r[1], "jenis": r[2], "tanggal": r[3],
            "waktu": r[4], "lokasi": r[5], "kuota": r[6], "mitra": r[7],
            "terisi": r[8], "sisa": sisa
        })
    return hasil

def daftar_rsvp(program_id, user_id, nama, telepon=""):
    """Mendaftarkan user ke program. Return (status, pesan)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Cek kuota
    c.execute("SELECT kuota FROM program_kesehatan WHERE id=?", (program_id,))
    kuota = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM rsvp_kesehatan WHERE program_id=? AND status='terdaftar'", (program_id,))
    terisi = c.fetchone()[0]
    
    if terisi >= kuota:
        conn.close()
        return False, "❌ Maaf, kuota program ini sudah penuh."
        
    try:
        # Coba update jika user sudah pernah daftar (status batal)
        c.execute("""UPDATE rsvp_kesehatan SET status='terdaftar', nama=?, telepon=?, waktu_daftar=CURRENT_TIMESTAMP 
                     WHERE program_id=? AND user_id=?""", (nama, telepon, program_id, user_id))
        
        # Jika belum ada baris sama sekali, insert baru
        if c.rowcount == 0:
            c.execute("""INSERT INTO rsvp_kesehatan (program_id, user_id, nama, telepon) 
                         VALUES (?, ?, ?, ?)""", (program_id, user_id, nama, telepon))
                         
        conn.commit()
        return True, f"✅ Pendaftaran berhasil!\nNama: {nama}\nWA: {telepon}\n\nSampai jumpa di lokasi!"
    except sqlite3.IntegrityError:
        return False, "⚠️ Anda sudah terdaftar di program ini."
    finally:
        conn.close()

def batal_rsvp(program_id, user_id):
    """Membatalkan pendaftaran."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE rsvp_kesehatan SET status='batal' WHERE program_id=? AND user_id=?", (program_id, user_id))
    berhasil = c.rowcount > 0
    conn.commit()
    conn.close()
    return berhasil

def get_daftar_peserta(program_id):
    """Mengambil daftar peserta untuk admin."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""SELECT nama, user_id, telepon, waktu_daftar 
                 FROM rsvp_kesehatan WHERE program_id=? AND status='terdaftar'""", (program_id,))
    rows = c.fetchall()
    conn.close()
    return rows



# =====================================================================
# FITUR ARTIKEL KESEHATAN ISLAMI
# =====================================================================
ARTIKEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_kesehatan")

def get_daftar_artikel():
    """Mengambil daftar file artikel yang tersedia."""
    if not os.path.exists(ARTIKEL_DIR):
        return []
    
    files = [f for f in os.listdir(ARTIKEL_DIR) if f.endswith('.txt')]
    hasil = []
    for f in files:
        filepath = os.path.join(ARTIKEL_DIR, f)
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
                if '[JUDUL]' in content:
                    judul = content.split('[JUDUL]')[1].split('[PENULIS]')[0].strip()
                else:
                    judul = f.replace('.txt', '').replace('_', ' ').title()
                
                hasil.append({
                    "filename": f,
                    "judul": judul,
                    "slug": f.replace('.txt', '')
                })
        except Exception as e:
            print(f"Error baca {f}: {e}")
    return hasil

def get_artikel(filename):
    """Membaca isi lengkap artikel dengan toleransi nama file."""
    # 1. Pastikan filename berakhiran .txt
    if not filename.endswith('.txt'):
        filename = f"{filename}.txt"
        
    filepath = os.path.join(ARTIKEL_DIR, filename)
    
    # 2. Jika tidak ketemu, coba cari file yang mirip (case-insensitive)
    if not os.path.exists(filepath):
        if os.path.exists(ARTIKEL_DIR):
            files = os.listdir(ARTIKEL_DIR)
            for f in files:
                if f.lower() == filename.lower():
                    filepath = os.path.join(ARTIKEL_DIR, f)
                    break
                
    if not os.path.exists(filepath):
        print(f"❌ [DEBUG] File tidak ditemukan: {filepath}")
        return None
    
    with open(filepath, 'r', encoding='utf-8') as file:
        content = file.read()
        
    judul = ""
    penulis = ""
    isi = ""
    
    if '[JUDUL]' in content:
        judul = content.split('[JUDUL]')[1].split('[PENULIS]')[0].strip()
    if '[PENULIS]' in content:
        penulis = content.split('[PENULIS]')[1].split('[KONTEN]')[0].strip()
    if '[KONTEN]' in content:
        isi = content.split('[KONTEN]')[1].strip()
        
    return {
        "judul": judul,
        "penulis": penulis,
        "isi": isi
    }