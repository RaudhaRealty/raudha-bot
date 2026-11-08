# app.py — Spiritual Accountant: Raudha Engine (Final v3)
import os
import sys
import re
import sqlite3
import logging
from flask import Flask, render_template_string, jsonify, request, render_template, send_from_directory
from werkzeug.utils import secure_filename
from flask_cors import CORS
from datetime import datetime, date
import hmac
import hashlib
from urllib.parse import parse_qsl
from functools import wraps
import time
from dotenv import load_dotenv
from modul_kesehatan import get_artikel
from modul_sholat import (
    ambil_jadwal_untuk_display,
    ke_hijriah,
    WIB,
    OFFSET_SUBUH,
    OFFSET_MAGHRIB,
)


# --- KONFIGURASI AWAL ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ===== TELEGRAM AUTH =====
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
if not TELEGRAM_BOT_TOKEN:
    logger.warning("⚠️ TELEGRAM_BOT_TOKEN tidak ditemukan — verifikasi initData akan gagal")

HARGA_EMAS_BASE   = 1_050_000
BASELINE_AWAL     = 100_000
HARGA_TANI_PER_KG = 0
HAUL_HARI         = 354          # 1 tahun hijriah ≈ 354 hari

# --- FOLDER UPLOAD ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
UPLOAD_DOKUMEN = os.path.join(UPLOAD_FOLDER, "dokumen_lembaga")
os.makedirs(UPLOAD_DOKUMEN, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

DB_PATH = os.path.join("data", "raudha.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "raudha.db"

# --- KONSTANTA FIKIH ---
NISAB_EMAS_GRAM    = 85
NISAB_PERAK_GRAM   = 595
NISAB_PERTANIAN_KG = 653
KADAR_ZAKAT        = 0.025
KADAR_TANAH_ALAMI  = 0.10
KADAR_TANAH_BIAYA  = 0.05
KADAR_KHUMUS       = 0.20

# --- APP ---
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATE_CACHE'] = False  # <-- TAMBAHKAN INI
CORS(app)

# =====================================================================
# API JADWAL SHOLAT DARI KOORDINAT (untuk GPS HP user)
# =====================================================================

@app.route('/api/jadwal-sholat')
def api_jadwal_sholat():
    """
    Terima lat/lng (dari GPS browser) atau kota (fallback manual),
    kembalikan jadwal sholat dalam format JSON.

    Contoh:
      /api/jadwal-sholat?lat=-7.39&lng=109.69
      /api/jadwal-sholat?kota=Banjarnegara
    """
    lat  = request.args.get('lat', type=float)
    lng  = request.args.get('lng', type=float)
    kota = request.args.get('kota', '').strip()

    # Import di dalam fungsi agar tidak bentrok jika modul_sholat belum siap
    from modul_sholat import ambil_jadwal_dari_koordinat

    try:
        if lat is not None and lng is not None:
            data = ambil_jadwal_dari_koordinat(lat, lng, nama_kota="Lokasi GPS")
        elif kota:
            data = ambil_jadwal_untuk_display(kota)
        else:
            return jsonify({
                "status": "error",
                "message": "Butuh parameter lat & lng, atau kota"
            }), 400

        return jsonify({
            "status": "success",
            "kota": data['kota']['nama'],
            "lat": data['kota'].get('lat'),
            "lng": data['kota'].get('lng'),
            "subuh":   data['subuh'],
            "zuhur":   data['zuhur'],
            "ashar":   data['ashar'],
            "maghrib": data['maghrib'],
            "isya":    data['isya'],
            "sumber":  data['sumber'],
        })
    except Exception as e:
        logger.error(f"[API JADWAL] Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/daftar_masjid', methods=['POST'])
def api_daftar_masjid():
    data = request.json or {}
    nama = data.get("nama", "").strip()
    alamat = data.get("alamat", "").strip()
    kategori = data.get("kategori", "masjid")
    user_id = data.get("user_id", 99999)

    if not nama or not alamat:
        return jsonify({"status": "error", "message": "Nama dan alamat wajib diisi."}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO lembaga_amil (nama, alamat, jenis, kategori_lembaga, status, created_by) 
                     VALUES (?, ?, 'masjid', ?, 'pending', ?)""", (nama, alamat, kategori, user_id))
        conn.commit()
        return jsonify({"status": "success", "message": "Pendaftaran terkirim. Menunggu verifikasi."})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# DISPLAY JAM SHOLAT
# =====================================================================

@app.route('/display')
def display_jam_sholat():
    # 1. Ambil parameter
    kota_param = request.args.get('kota', '').strip()
    tv_code    = request.args.get('tv', '').strip()
    mode       = request.args.get('mode', '').strip()

    now = datetime.now(WIB)

    # ============================================================
    # DETEKSI MODE: TV MASJID vs HP USER (DENGAN COOKIE MEMORY)
    # ============================================================

    # Cek apakah browser ini pernah membuka mode TV (tersimpan di cookie)
    cookie_tv = request.cookies.get('raudha_is_tv')
    
    # Jika ada ?tv=, ATAU cookie bilang ini TV, ATAU mode=tv -> Jadikan TV!
    is_tv_mode = bool(tv_code) or (cookie_tv == '1') or (mode == 'tv')

    if is_tv_mode:
        # ---------- MODE TV: lokasi tetap dari database ----------
        if tv_code:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("""SELECT kota, latitude, longitude
                         FROM tv_masjid_config
                         WHERE tv_code=?""", (tv_code,))
            row = c.fetchone()
            conn.close()
            if row and row[0]:
                kota_param = row[0]
        
        if not kota_param:
            kota_param = 'Banjarnegara'  # fallback TV
            
        data = ambil_jadwal_untuk_display(kota_param)
        lokasi_awal = kota_param
        
    else:
        # ---------- MODE HP: jadwal awal pakai kota default ----------
        kota_awal = kota_param or 'Banjarnegara'
        data = ambil_jadwal_untuk_display(kota_awal)
        lokasi_awal = kota_awal

    jadwal = {
        'subuh':   data['subuh'],
        'zuhur':   data['zuhur'],
        'ashar':   data['ashar'],
        'maghrib': data['maghrib'],
        'isya':    data['isya'],
    }

    # 2. Hitung sholat berikutnya
    jam_sekarang = now.hour + now.minute / 60 + now.second / 3600

    def to_desimal(jam_str):
        try:
            h, m = jam_str.split(':')
            return int(h) + int(m) / 60
        except Exception:
            return 0

    urutan = [
        ("Subuh",   jadwal['subuh']),
        ("Zuhur",   jadwal['zuhur']),
        ("Ashar",   jadwal['ashar']),
        ("Maghrib", jadwal['maghrib']),
        ("Isya",    jadwal['isya']),
    ]

    ikon = {"Subuh": "🌌", "Zuhur": "☀️", "Ashar": "🌇", "Maghrib": "🌅", "Isya": "🌃"}

    next_nama, next_jam = urutan[0]
    for nama, jam_str in urutan:
        if jam_sekarang < to_desimal(jam_str):
            next_nama, next_jam = nama, jam_str
            break

    sholat_list = [
        {"nama": n, "jam": j, "icon": ikon[n], "aktif": n == next_nama}
        for n, j in urutan
    ]

    # ============================================================
    # 3. AMBIL TOTAL ZAKAT KHUSUS MASJID (JIKA TV CODE VALID)
    # ============================================================

    total_zakat_masjid = 0
    nama_masjid_tv = ""

    if tv_code:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("""
            SELECT l.nama, COALESCE(SUM(rp.nominal), 0)
            FROM tv_masjid_config t
            JOIN lembaga_amil l ON l.id = t.lembaga_id
            LEFT JOIN rencana_pembayaran rp
                ON rp.lembaga_id = l.id AND rp.status = 'diverifikasi'
            WHERE t.tv_code = ?
            GROUP BY l.id
        """, (tv_code,))
        row = c.fetchone()
        conn.close()

        if row:
            nama_masjid_tv = row[0]
            total_zakat_masjid = row[1]

    # 4. Render ke template
    from flask import make_response
    resp = make_response(render_template(
        'display.html',
        kota_nama=data['kota']['nama'],
        tanggal_masehi=now.strftime('%A, %d %B %Y'),
        tanggal_hijriah=ke_hijriah(now.date()),
        next_sholat_nama=next_nama,
        next_sholat_jam=next_jam,
        sholat_list=sholat_list,
        server_offset_sec=int(now.utcoffset().total_seconds()),
        offset_info=f"Subuh +{OFFSET_SUBUH} mnt, Maghrib +{OFFSET_MAGHRIB} mnt",
        sumber_jadwal=data['sumber'],
        total_zakat_masjid=total_zakat_masjid,
        nama_masjid_tv=nama_masjid_tv,
        is_tv_mode=is_tv_mode,
        tv_code=tv_code,
        lokasi_awal=lokasi_awal,
    ))
    
    # 5. SIMPAN COOKIE (Jika ini TV)
    if is_tv_mode:
        resp.set_cookie('raudha_is_tv', '1', max_age=2592000)
        if tv_code:
            resp.set_cookie('raudha_tv_code', tv_code, max_age=2592000)
        
    return resp

# =====================================================================
# MENU TV
# =====================================================================

@app.route('/streaming')
def streaming_tv():
    """Halaman Live Streaming dengan pilihan channel"""
    channel = request.args.get('ch', 'haram').lower()
    tv_code = request.args.get('tv', '').strip() # <-- TAMBAHKAN INI
    
    channels = {
        "haram": {"nama": "Masjidil Haram, Makkah", "embed_id": "TOuCl7-tuY0"},
        "nabawi": {"nama": "Masjid Nabawi, Madinah", "embed_id": "a9bIRKcCPZo"},
        "aqsa": {"nama": "Masjid Al-Aqsa, Yerusalem", "embed_id": "ffoHEWPQOpA"},
        "raudha": {"nama": "Live Channel Raudha (Kajian)", "embed_id": "c0fzbu2vaWU"},
        "lokal": {"nama": "Live Masjid Lokal (Admin)", "embed_id": "GANTI_ID_VIDEO_LOKAL"}
    }
    
    data = channels.get(channel, channels['haram'])
    # Kirim tv_code ke template streaming
    return render_template('streaming.html', channel=data, active_ch=channel, tv_code=tv_code)

# =====================================================================
# MENU UTAMA TV & HALAMAN ZAKAT TV
# =====================================================================

@app.route('/menu')
def menu_tv():
    # 1. Ambil tv_code dari URL
    tv_code = request.args.get('tv', '').strip()
    
    # 2. JIKA URL TIDAK ADA ?tv=, AMBIL DARI COOKIE!
    if not tv_code:
        tv_code = request.cookies.get('raudha_tv_code', '').strip()
        
    lembaga_id = None
    nama_masjid = "Masjid Raudha"
    hari_besar = []
    kegiatan = []
    
    # ... (SISA KODE DI BAWAHNYA BIARKAN SAMA SEPERTI SEBELUMNYA) ...
    
    if tv_code:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("""SELECT t.lembaga_id, l.nama 
                     FROM tv_masjid_config t 
                     JOIN lembaga_amil l ON l.id = t.lembaga_id 
                     WHERE t.tv_code=?""", (tv_code,))
        row = c.fetchone()
        
        if row:
            lembaga_id = row[0]
            nama_masjid = row[1]
            
            # Ambil agenda dari database
            from datetime import datetime
            c.execute("SELECT tanggal, nama, pemateri FROM agenda_masjid WHERE lembaga_id=? AND tipe='kegiatan' ORDER BY tanggal ASC LIMIT 5", (lembaga_id,))
            kegiatan = []
            for r in c.fetchall():
                try:
                    # Ubah 2026-11-01 jadi 01 Nov 2026
                    tgl_format = datetime.strptime(r[0], "%Y-%m-%d").strftime("%d %b %Y")
                except:
                    tgl_format = r[0]
                kegiatan.append({"tgl": tgl_format, "nama": r[1], "pemateri": r[2]})
        conn.close()
    
    return render_template(
        'menu_tv.html', 
        lembaga_id=lembaga_id, 
        tv_code=tv_code,
        nama_masjid=nama_masjid,
        hari_besar=hari_besar,
        kegiatan=kegiatan
    )

@app.route('/admin/tv')
def admin_tv_page():
    """Halaman dashboard untuk mengatur TV Masjid."""
    return render_template('admin_tv.html')

@app.route('/admin')
def admin_dashboard():
    """Halaman Dashboard Admin (Mini App) dengan Role Dinamis."""
    
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Dashboard Admin - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
        </style>
    </head>
    <body class="antialiased text-slate-800 pb-10">
        
        <!-- HEADER -->
        <div class="bg-gradient-to-r from-emerald-700 to-emerald-900 text-white p-4 shadow-md sticky top-0 z-50 rounded-b-3xl">
            <div class="max-w-md mx-auto flex items-center gap-3">
                <span class="text-2xl" id="header-icon">🖥️</span>
                <div>
                    <h1 class="text-lg font-black tracking-tight">Dashboard Admin</h1>
                    <p class="text-[10px] text-emerald-200 uppercase tracking-wider" id="header-role">Memuat...</p>
                </div>
            </div>
        </div>

        <!-- MAIN MENU -->
        <div class="max-w-md mx-auto p-4 space-y-4 mt-2">
            
            <!-- MENU SUPER ADMIN -->
            <div id="menu-super" class="hidden bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <h2 class="text-sm font-bold text-slate-800 mb-3 border-b pb-2">👑 Super Admin</h2>
                <div class="grid grid-cols-2 gap-3">
                    <a href="/admin/artikel" class="bg-emerald-50 text-emerald-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-emerald-100 transition">Tulis Artikel</a>
                    <a href="/admin/jadwal" class="bg-blue-50 text-blue-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-blue-100 transition">Buat Jadwal</a>
                    <a href="/admin/peserta" class="bg-slate-50 text-slate-600 p-4 rounded-xl text-center font-bold text-sm col-span-2 hover:bg-slate-100 transition">Lihat Peserta Kesehatan</a>
                    <a href="#" onclick="alert('Fitur segera hadir!')" class="bg-slate-50 text-slate-500 p-4 rounded-xl text-center font-bold text-sm">Verifikasi Masjid</a>
                    <a href="#" onclick="alert('Fitur segera hadir!')" class="bg-slate-50 text-slate-500 p-4 rounded-xl text-center font-bold text-sm">Tugaskan Admin</a>
                </div>
            </div>

            <!-- MENU KESEHATAN -->
            <div id="menu-kesehatan" class="hidden bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <h2 class="text-sm font-bold text-slate-800 mb-3 border-b pb-2">🩺 Kesehatan</h2>
                <div class="grid grid-cols-2 gap-3">
                    <a href="/admin/artikel" class="bg-blue-50 text-blue-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-blue-100 transition">Tulis Artikel</a>
                    <a href="/admin/jadwal" class="bg-blue-50 text-blue-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-blue-100 transition">Buat Jadwal</a>
                    <a href="/admin/peserta" class="bg-slate-50 text-slate-600 p-4 rounded-xl text-center font-bold text-sm col-span-2 hover:bg-slate-100 transition">Lihat Peserta RSVP</a>
                </div>
            </div>

            <!-- MENU LAZIS -->
            <div id="menu-lazis" class="hidden bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <h2 class="text-sm font-bold text-slate-800 mb-3 border-b pb-2">💰 LAZIS</h2>
                <div class="grid grid-cols-2 gap-3">
                    <a href="#" onclick="alert('Fitur segera hadir!')" class="bg-amber-50 text-amber-700 p-4 rounded-xl text-center font-bold text-sm">Laporan Zakat</a>
                    <a href="/mitra-alam/admin/verifikasi" class="bg-emerald-50 text-emerald-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-emerald-100 transition">🌱 Verifikasi Wakaf</a>
                </div>
            </div>

            <!-- MENU MASJID -->
            <div id="menu-masjid" class="hidden bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <h2 class="text-sm font-bold text-slate-800 mb-3 border-b pb-2">🕌 Takmir Masjid</h2>
                <div class="grid grid-cols-2 gap-3">
                    <a href="/admin/profil_masjid" class="bg-emerald-50 text-emerald-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-emerald-100 transition">Profil Masjid</a>
                    <a href="/admin/pengumuman" class="bg-amber-50 text-amber-700 p-4 rounded-xl text-center font-bold text-sm hover:bg-amber-100 transition">Buat Pengumuman</a>
                    <a href="#" onclick="alert('Fitur Kas Masjid segera hadir!')" class="bg-slate-50 text-slate-500 p-4 rounded-xl text-center font-bold text-sm col-span-2">Laporan Kas & Infaq</a>
                </div>
            </div>

            <div class="text-center mt-8">
                <p class="text-xs text-slate-400">Raudha Admin Panel v1.1</p>
            </div>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) { tg.ready(); tg.expand(); }
            
            const userId = tg?.initDataUnsafe?.user?.id;
            
            async function loadRole() {
                try {
                    const res = await fetch(`/api/role/${userId}`);
                    const data = await res.json();
                    
                    if (data.status === 'success') {
                        const role = data.role;
                        const roleTextMap = {
                            'super_admin': 'Raudha Super Admin',
                            'kesehatan': 'Raudha Kesehatan',
                            'lazis': 'Raudha Lazis',
                            'masjid': 'Raudha Masjid'
                        };
                        document.getElementById('header-role').innerText = roleTextMap[role] || 'Raudha Admin';
                        
                        if (role === 'super_admin') {
                            document.getElementById('menu-super').classList.remove('hidden');
                            document.getElementById('menu-kesehatan').classList.remove('hidden');
                            document.getElementById('menu-lazis').classList.remove('hidden');
                            document.getElementById('menu-masjid').classList.remove('hidden');
                        } else if (role === 'kesehatan') {
                            document.getElementById('menu-kesehatan').classList.remove('hidden');
                        } else if (role === 'lazis') {
                            document.getElementById('menu-lazis').classList.remove('hidden');
                        } else if (role === 'masjid') {
                            document.getElementById('menu-masjid').classList.remove('hidden');
                        } else if (role === 'admin_lembaga') {
                            // Admin lembaga: tampilkan menu LAZIS & Masjid
                            document.getElementById('menu-lazis').classList.remove('hidden');
                            document.getElementById('menu-masjid').classList.remove('hidden');
                        } else {
                            document.getElementById('header-role').innerText = "Akses Ditolak";
                        }
                    }
                } catch (e) {
                    console.error(e);
                }
            }
            loadRole();
        </script>
    </body>
    </html>
    """
    return html

@app.route('/artikel/<slug>')
def view_artikel(slug):
    """Halaman untuk membaca artikel lengkap di Mini App."""
    from modul_kesehatan import get_artikel
    artikel = get_artikel(slug)
    
    if not artikel:
        return "❌ Artikel tidak ditemukan.", 404

    # HTML untuk tampilan artikel
    html = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>{artikel['judul']} - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
            body {{ font-family: 'Plus Jakarta Sans', sans-serif; background-color: #f8fafc; }}
        </style>
    </head>
    <body class="antialiased text-slate-800 pb-10">
        
        <!-- Header -->
        <div class="bg-emerald-800 text-white p-4 shadow-md sticky top-0 z-50">
            <div class="max-w-md mx-auto flex items-center gap-3">
                <a href="javascript:history.back()" class="text-white opacity-80 hover:opacity-100 text-xl">⬅️</a>
                <h1 class="text-sm font-bold truncate">Artikel Kesehatan</h1>
            </div>
        </div>

        <!-- Konten Artikel -->
        <div class="max-w-md mx-auto p-4 mt-2">
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-100">
                <h1 class="text-2xl font-black text-slate-900 leading-tight mb-2">{artikel['judul']}</h1>
                <div class="flex items-center gap-2 mb-6 border-b pb-4">
                    <div class="w-8 h-8 bg-emerald-100 text-emerald-700 rounded-full flex items-center justify-center text-xs font-bold">A</div>
                    <div>
                        <p class="text-xs font-bold text-slate-700">{artikel['penulis']}</p>
                        <p class="text-[10px] text-slate-400">Kontributor Raudha</p>
                    </div>
                </div>
                
                <!-- Isi teks (menggunakan whitespace-pre-wrap agar enter/paragraf terjaga) -->
                <div class="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">{artikel['isi']}</div>
            </div>
            
            <div class="mt-8 text-center">
                <button onclick="window.Telegram.WebApp.close()" class="bg-slate-200 text-slate-700 font-bold py-3 px-8 rounded-xl text-sm hover:bg-slate-300 transition">
                    Tutup
                </button>
            </div>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) {{ tg.ready(); tg.expand(); }}
        </script>
    </body>
    </html>
    """
    return html

@app.route('/admin/artikel', methods=['GET', 'POST'])
def admin_artikel():
    """Halaman untuk menulis artikel baru."""
    
    if request.method == 'POST':
        # Ambil data dari form
        judul = request.form.get('judul', '').strip()
        penulis = request.form.get('penulis', 'Tim Medis Aeesha').strip()
        konten = request.form.get('konten', '').strip()
        
        if not judul or not konten:
            return "Error: Judul dan konten wajib diisi.", 400
            
        # Buat slug (nama file) dari judul
        import re
        slug = re.sub(r'[^a-z0-9]+', '_', judul.lower()).strip('_')
        filename = f"{slug}.txt"
        
        # Format konten sesuai standar bot
        file_content = f"[JUDUL]\n{judul}\n\n[PENULIS]\n{penulis}\n\n[KONTEN]\n{konten}\n"
        
        # Simpan ke folder data_kesehatan
        folder_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_kesehatan")
        os.makedirs(folder_path, exist_ok=True) # Buat folder jika belum ada
        file_path = os.path.join(folder_path, filename)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(file_content)
            
        # Tampilkan halaman sukses
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <script src="https://cdn.tailwindcss.com"></script>
            <script src="https://telegram.org/js/telegram-web-app.js"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center h-screen p-4 text-center">
            <div class="bg-white p-8 rounded-3xl shadow-xl max-w-sm w-full">
                <div class="text-6xl mb-4">✅</div>
                <h1 class="text-xl font-black text-slate-800 mb-2">Artikel Tersimpan!</h1>
                <p class="text-sm text-slate-500 mb-6">Artikel berhasil ditambahkan ke sistem. Bot akan otomatis menampilkannya.</p>
                <button onclick="window.Telegram.WebApp.close()" class="bg-emerald-600 text-white font-bold py-3 px-6 rounded-xl w-full">Kembali ke Telegram</button>
            </div>
        </body>
        </html>
        """

    # Jika GET, tampilkan form
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Tulis Artikel - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>
            body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }
        </style>
    </head>
    <body class="antialiased text-slate-800 p-4 pb-10">
        
        <div class="max-w-md mx-auto">
            <div class="flex items-center gap-3 mb-6">
                <a href="/admin" class="text-slate-400 hover:text-slate-800">⬅️</a>
                <h1 class="text-lg font-black">Tulis Artikel Baru</h1>
            </div>

            <form method="POST" class="space-y-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Judul Artikel</label>
                    <input type="text" name="judul" required placeholder="Misal: Manfaat Puasa untuk Kesehatan" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>
                
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Penulis</label>
                    <input type="text" name="penulis" value="Tim Medis Aeesha" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Isi Artikel</label>
                    <textarea name="konten" required rows="8" placeholder="Tulis isi artikel di sini..." class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm"></textarea>
                </div>

                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition text-sm">
                    💾 Simpan & Publish
                </button>
            </form>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) { tg.ready(); tg.expand(); }
        </script>
    </body>
    </html>
    """
    return html

@app.route('/admin/jadwal', methods=['GET', 'POST'])
def admin_jadwal():
    """Halaman untuk membuat jadwal kesehatan baru."""
    
    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        jenis = request.form.get('jenis', 'senam')
        tanggal = request.form.get('tanggal', '')
        waktu = request.form.get('waktu', '')
        lokasi = request.form.get('lokasi', '').strip()
        kuota = int(request.form.get('kuota', 30))
        
        if not nama or not tanggal or not waktu or not lokasi:
            return "Error: Field wajib tidak boleh kosong.", 400
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO program_kesehatan (nama, jenis, tanggal, waktu, lokasi, kuota) 
                         VALUES (?, ?, ?, ?, ?, ?)""", (nama, jenis, tanggal, waktu, lokasi, kuota))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return f"Error database: {e}", 500
        finally:
            conn.close()
            
        # Tampilkan halaman sukses
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <script src="https://cdn.tailwindcss.com"></script>
            <script src="https://telegram.org/js/telegram-web-app.js"></script>
        </head>
        <body class="bg-slate-50 flex items-center justify-center h-screen p-4 text-center">
            <div class="bg-white p-8 rounded-3xl shadow-xl max-w-sm w-full">
                <div class="text-6xl mb-4">✅</div>
                <h1 class="text-xl font-black text-slate-800 mb-2">Jadwal Dibuat!</h1>
                <p class="text-sm text-slate-500 mb-6">Jadwal kesehatan baru berhasil ditambahkan ke sistem. Bot akan otomatis menampilkannya.</p>
                <button onclick="window.Telegram.WebApp.close()" class="bg-emerald-600 text-white font-bold py-3 px-6 rounded-xl w-full">Kembali ke Telegram</button>
            </div>
        </body>
        </html>
        """

    # Jika GET, tampilkan form
    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Buat Jadwal - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }</style>
    </head>
    <body class="antialiased text-slate-800 p-4 pb-10">
        
        <div class="max-w-md mx-auto">
            <div class="flex items-center gap-3 mb-6">
                <a href="/admin" class="text-slate-400 hover:text-slate-800">⬅️</a>
                <h1 class="text-lg font-black">Buat Jadwal Kesehatan</h1>
            </div>

            <form method="POST" class="space-y-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Nama Program</label>
                    <input type="text" name="nama" required placeholder="Misal: Senam Ahad" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>
                
                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Jenis</label>
                        <select name="jenis" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                            <option value="senam">🏃‍♀️ Senam</option>
                            <option value="tensi">🩺 Cek Tensi</option>
                            <option value="konsultasi">👨‍⚕️ Konsultasi</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Kuota</label>
                        <input type="number" name="kuota" value="30" required min="1" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Tanggal</label>
                        <input type="date" name="tanggal" required class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Waktu</label>
                        <input type="text" name="waktu" required placeholder="Misal: 08:00 - 10:00" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Lokasi</label>
                    <input type="text" name="lokasi" required placeholder="Misal: Aula Masjid Al Falah" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>

                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition text-sm">
                    💾 Simpan Jadwal
                </button>
            </form>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) { tg.ready(); tg.expand(); }
        </script>
    </body>
    </html>
    """
    return html

@app.route('/admin/peserta')
def admin_peserta():
    """Halaman untuk melihat daftar peserta RSVP."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Ambil semua program kesehatan
    c.execute("SELECT id, nama, tanggal, jenis FROM program_kesehatan ORDER BY id DESC")
    programs = c.fetchall()
    
    # Ambil semua peserta
    c.execute("""SELECT r.nama, r.telepon, r.waktu_daftar, p.nama as program_nama 
                 FROM rsvp_kesehatan r
                 JOIN program_kesehatan p ON r.program_id = p.id
                 WHERE r.status = 'terdaftar'
                 ORDER BY r.id DESC""")
    peserta_list = c.fetchall()
    conn.close()
    
    # Susun HTML tabel peserta
    rows_html = ""
    if not peserta_list:
        rows_html = "<tr><td colspan='4' class='text-center py-4 text-slate-400'>Belum ada peserta yang mendaftar.</td></tr>"
    else:
        for nama, telp, waktu, program in peserta_list:
            rows_html += f"""
            <tr class="border-b border-slate-100">
                <td class="py-3 px-2 font-bold text-slate-800">{nama}</td>
                <td class="py-3 px-2 text-slate-600">{telp or '-'}</td>
                <td class="py-3 px-2 text-xs text-slate-500">{program}</td>
            </tr>
            """
            
    html = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Daftar Peserta - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>body {{ font-family: 'Inter', sans-serif; background-color: #f8fafc; }}</style>
    </head>
    <body class="antialiased text-slate-800 p-4 pb-10">
        
        <div class="max-w-md mx-auto">
            <div class="flex items-center gap-3 mb-6">
                <a href="/admin" class="text-slate-400 hover:text-slate-800">⬅️</a>
                <h1 class="text-lg font-black">Daftar Peserta</h1>
            </div>

            <div class="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
                <table class="w-full text-left border-collapse text-sm">
                    <thead>
                        <tr class="bg-slate-50 text-slate-500 text-xs uppercase tracking-wider">
                            <th class="py-3 px-2 font-bold">Nama</th>
                            <th class="py-3 px-2 font-bold">WA</th>
                            <th class="py-3 px-2 font-bold">Program</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
            
            <p class="text-center text-xs text-slate-400 mt-6">Total Peserta Terdaftar: <strong>{len(peserta_list)}</strong></p>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) {{ tg.ready(); tg.expand(); }}
        </script>
    </body>
    </html>
    """
    return html

@app.route('/admin/profil_masjid', methods=['GET', 'POST'])
def admin_profil_masjid():
    """Halaman untuk mengedit profil masjid."""
    # Catatan: Untuk sementara kita hardcode masjid ID 1 (Al Falah) 
    # Nanti bisa diambil dari admin_penugasan user yang login
    masjid_id = 1 
    
    if request.method == 'POST':
        nama = request.form.get('nama', '').strip()
        alamat = request.form.get('alamat', '').strip()
        kota = request.form.get('kota', '').strip()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("UPDATE masjid SET nama=?, alamat=?, kota=? WHERE id=?", (nama, alamat, kota, masjid_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return f"Error: {e}", 500
        finally:
            conn.close()
            
        return """
        <script>
            alert('✅ Profil masjid berhasil diperbarui!');
            window.location.href = '/admin';
        </script>
        """
        
    # Ambil data masjid saat ini
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT nama, alamat, kota FROM masjid WHERE id=?", (masjid_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return "Masjid tidak ditemukan.", 404
        
    nama_masjid, alamat_masjid, kota_masjid = row
    
    html = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Profil Masjid - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>body {{ font-family: 'Inter', sans-serif; background-color: #f8fafc; }}</style>
    </head>
    <body class="antialiased text-slate-800 p-4 pb-10">
        
        <div class="max-w-md mx-auto">
            <div class="flex items-center gap-3 mb-6">
                <a href="/admin" class="text-slate-400 hover:text-slate-800">⬅️</a>
                <h1 class="text-lg font-black">Profil Masjid</h1>
            </div>

            <form method="POST" class="space-y-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Nama Masjid</label>
                    <input type="text" name="nama" value="{nama_masjid or ''}" required class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>
                
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Kota / Kabupaten</label>
                    <input type="text" name="kota" value="{kota_masjid or ''}" required class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>

                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Alamat Lengkap</label>
                    <textarea name="alamat" required rows="3" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">{alamat_masjid or ''}</textarea>
                </div>

                <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-3 rounded-xl transition text-sm">
                    💾 Simpan Perubahan
                </button>
            </form>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) {{ tg.ready(); tg.expand(); }}
        </script>
    </body>
    </html>
    """
    return html

# =====================================================================
# ADMIN PENGUMUMAN DI TV ZAKAT
# =====================================================================

@app.route('/admin/pengumuman', methods=['GET', 'POST'])
def admin_pengumuman():
    """Halaman untuk membuat pengumuman masjid."""
    
    if request.method == 'POST':
        judul = request.form.get('judul', '').strip()
        isi = request.form.get('isi', '').strip()
        
        if not judul or not isi:
            return "Error: Judul dan isi wajib diisi.", 400
            
        # Simpan ke database (kita asumsikan tabel ini sudah ada atau buat baru)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS pengumuman_masjid (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                masjid_id INTEGER DEFAULT 1,
                judul TEXT,
                isi TEXT,
                tanggal TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            c.execute("INSERT INTO pengumuman_masjid (masjid_id, judul, isi) VALUES (1, ?, ?)", (judul, isi))
            conn.commit()
        except Exception as e:
            conn.rollback()
            return f"Error: {e}", 500
        finally:
            conn.close()
            
        return """
        <script>
            alert('✅ Pengumuman berhasil dibuat!');
            window.location.href = '/admin';
        </script>
        """

    html = """
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Buat Pengumuman - Raudha</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://telegram.org/js/telegram-web-app.js"></script>
        <style>body { font-family: 'Inter', sans-serif; background-color: #f8fafc; }</style>
    </head>
    <body class="antialiased text-slate-800 p-4 pb-10">
        
        <div class="max-w-md mx-auto">
            <div class="flex items-center gap-3 mb-6">
                <a href="/admin" class="text-slate-400 hover:text-slate-800">⬅️</a>
                <h1 class="text-lg font-black">Buat Pengumuman</h1>
            </div>

            <form method="POST" class="space-y-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Judul Pengumuman</label>
                    <input type="text" name="judul" required placeholder="Misal: Kerja Bakti Ahad Pagi" class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm">
                </div>
                
                <div>
                    <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Isi Pengumuman</label>
                    <textarea name="isi" required rows="5" placeholder="Tulis detail pengumuman..." class="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-emerald-500 font-medium text-sm"></textarea>
                </div>

                <button type="submit" class="w-full bg-amber-500 hover:bg-amber-600 text-white font-bold py-3 rounded-xl transition text-sm">
                    📢 Publikasikan
                </button>
            </form>
        </div>

        <script>
            const tg = window.Telegram?.WebApp;
            if (tg) { tg.ready(); tg.expand(); }
        </script>
    </body>
    </html>
    """
    return html

# =====================================================================
# TV ZAKAT
# =====================================================================

@app.route('/tv/zakat')
def tv_zakat():
    """Halaman Kas & Zakat untuk TV Masjid"""
    masjid_id = request.args.get('masjid')
    tv_code = request.args.get('tv', '').strip() # <-- TAMBAHKAN INI
    
    # ... (kode pengecekan database Anda tetap sama) ...

    # Cari baris <a href="/menu" di dalam return HTML zakat Anda, 
    # dan ubah menjadi seperti ini:
    # <a href="/menu?tv={tv_code}" ...>    
    if not masjid_id:
        return "<h1 style='color:white; text-align:center; background:black; height:100vh; padding-top:20%'>Parameter ?masjid= ID belum dimasukkan.</h1>"

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    # Cek apakah masjid/lembaga ini terdaftar di database
    c.execute("SELECT nama, status FROM lembaga_amil WHERE id=?", (masjid_id,))
    lembaga = c.fetchone()
    
    if not lembaga:
        conn.close()
        # TAMPILAN JIKA MASJID BELUM TERDAFTAR (Pemacu Admin)
        return """
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>Belum Terdaftar</title><script src="https://cdn.tailwindcss.com"></script></head>
        <body class="bg-slate-900 flex flex-col items-center justify-center h-screen text-center text-white">
            <h1 class="text-6xl mb-4">🕌</h1>
            <h1 class="text-3xl font-bold text-amber-500 mb-2">Masjid Belum Terdaftar</h1>
            <p class="text-slate-400 mb-6 max-w-md">Masjid ini belum memiliki laporan Kas & Zakat digital.<br>Mari lengkapi laporan melalui Bot Telegram.</p>
           <a href="/menu?tv={tv_code}" class="bg-slate-700 hover:bg-slate-600 px-8 py-4 rounded-xl font-bold text-lg">🔙 Kembali ke Menu</a>
        </body>
        </html>
        """
        
    # Jika terdaftar, ambil total dana (zakat yang sudah diverifikasi)
    c.execute("""SELECT COALESCE(SUM(nominal), 0) FROM rencana_pembayaran 
                 WHERE lembaga_id=? AND status='diverifikasi'""", (masjid_id,))
    total_dana = c.fetchone()[0]
    conn.close()

    # Tampilkan Layar Zakat TV
    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Kas & Zakat - {lembaga[0]}</title><script src="https://cdn.tailwindcss.com"></script></head>
    <body class="bg-slate-900 flex flex-col items-center justify-center h-screen text-white">
        <div class="bg-slate-800 p-12 rounded-3xl shadow-2xl border border-slate-700 text-center w-full max-w-2xl">
            <h1 class="text-xl text-slate-400 uppercase tracking-widest mb-2">Total Kas & Zakat Terkumpul</h1>
            <h1 class="text-3xl font-bold text-amber-400 mb-8">{lembaga[0]}</h1>
            <p class="text-7xl font-black text-emerald-400 mb-10">Rp {int(total_dana):,}</p>
            <a href="/menu?tv={tv_code}" class="bg-slate-700 hover:bg-slate-600 px-8 py-4 rounded-xl font-bold text-lg">🔙 Kembali ke Menu</a>
        </div>
    </body>
    </html>
    """.replace(",", ".")

# =====================================================================
# HELPERS
# =====================================================================

def format_idr(nilai):
    try:
        return "Rp {:,.0f}".format(nilai).replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"

app.jinja_env.filters['format_idr'] = format_idr

def tulis_audit(c, user_id, tabel, rec_id, aksi, field="", lama="", baru="", alasan=""):
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tabel TEXT,
            record_id INTEGER, aksi TEXT, field_diubah TEXT, nilai_lama TEXT,
            nilai_baru TEXT, alasan TEXT, waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""INSERT INTO audit_log
                     (user_id, tabel, record_id, aksi, field_diubah, nilai_lama, nilai_baru, alasan)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, tabel, rec_id, aksi, field, str(lama), str(baru), alasan))
    except Exception as e:
        logger.error(f"Error audit: {e}")

# =====================================================================
# TELEGRAM AUTH — VERIFIKASI INITDATA (HMAC-SHA256)
# =====================================================================

from init_data_py import validate_by_hash

def verify_telegram_init_data(init_data: str) -> dict:
    """Verifikasi initData pakai library init-data-py."""
    if not init_data or not TELEGRAM_BOT_TOKEN:
        return None
    try:
        validated = validate_by_hash(init_data, TELEGRAM_BOT_TOKEN)
        if validated.user:
            return {"id": validated.user.id}
        return {}
    except Exception as e:
        logger.error(f"InitData verification error: {e}")
        return None

def require_telegram_auth(f):
    """Dekorator: Verifikasi initData sebelum request diproses."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        init_data = request.headers.get('X-Telegram-Init-Data', '')
        user = verify_telegram_init_data(init_data)
        
        if not user:
            # Fallback 1: dari query string
            fallback_user_id = request.args.get('user_id')
            
            # Fallback 2: dari body JSON
            if not fallback_user_id:
                try:
                    body = request.get_json(silent=True) or {}
                    fallback_user_id = body.get('user_id')
                except Exception:
                    pass
            
            # ✨ Fallback 3: dari path parameter (misal /api/laporan/<user_id>)
            if not fallback_user_id and 'user_id' in kwargs:
                fallback_user_id = kwargs.get('user_id')
            
            if fallback_user_id:
                try:
                    uid = int(fallback_user_id)
                    request.telegram_user_id = uid
                    logger.warning(f"⚠️ [DEV] Akses tanpa initData, fallback user_id={uid}")
                    return f(*args, **kwargs)
                except (ValueError, TypeError):
                    pass
            
            return jsonify({"status": "error", "message": "Unauthorized: Invalid Telegram data"}), 401
        
        request.telegram_user_id = user.get('id')
        return f(*args, **kwargs)
    return decorated_function    

# =====================================================================
# RBAC HELPER
# =====================================================================

def get_user_role(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT role, status, lembaga_id FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return {"role": "user", "status": "active", "lembaga_id": None}
    return {"role": row[0] or "user", "status": row[1] or "active", "lembaga_id": row[2]}

def require_role(user_id, allowed_roles):
    info = get_user_role(user_id)
    if info["status"] != "active":
        return False, f"Akun Anda sedang {info['status']}. Hubungi super admin."
    if info["role"] not in allowed_roles:
        return False, f"Akses ditolak. Role Anda: {info['role']}"
    return True, None

def log_sensitive(c, user_id, role, aksi, target_tabel="", target_id=None, detail="", request_obj=None):
    ip = request_obj.remote_addr if request_obj else None
    ua = request_obj.user_agent.string if request_obj else None
    try:
        c.execute("""INSERT INTO log_akses_sensitif
                     (user_id, role, aksi, target_tabel, target_id, detail, ip_address, user_agent)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (user_id, role, aksi, target_tabel, target_id, detail, ip, ua))
    except Exception as e:
        logger.error(f"Log sensitive error: {e}")

def buat_kode_verifikasi(nama_lembaga, lembaga_id):
    prefix = re.sub(r'[^A-Z0-9]', '', nama_lembaga.upper()[:10]) or "LEMBAGA"
    return f"{prefix}-{lembaga_id:03d}"

# =====================================================================
# INIT DATABASE (GABUNGAN — Semua Tabel dalam Satu Fungsi)
# =====================================================================

def init_web_db():
    """
    Inisialisasi SEMUA tabel database Raudha dalam satu fungsi:
    - Tabel inti: jurnal_syariah, users_config, lembaga_amil, rekening_lembaga,
      rencana_pembayaran, verifikasi_lembaga, tagihan, log_akses_sensitif
    - Tabel TV: tv_masjid_config, agenda_masjid
    - Tabel Mitra Alam: komoditas_wakaf, pohon_wakaf, pohon_log, pohon_panen
    - Seed data: Super Admin, Lembaga default, Komoditas wakaf
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # =================================================================
    # A. TABEL INTI
    # =================================================================

    # A.1. jurnal_syariah
    c.execute("""CREATE TABLE IF NOT EXISTS jurnal_syariah (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, jenis TEXT,
        gaji REAL DEFAULT 0, honor REAL DEFAULT 0, hadiah REAL DEFAULT 0,
        pertanian_kg REAL DEFAULT 0, jenis_pengairan TEXT,
        benda_mewah REAL DEFAULT 0, temuan_laut_karun REAL DEFAULT 0,
        simpanan_bmt_idr REAL DEFAULT 0,
        pengeluaran_rutin REAL DEFAULT 0, pengeluaran_sekolah REAL DEFAULT 0,
        pengeluaran_utang REAL DEFAULT 0, pengeluaran_sedekah REAL DEFAULT 0,
        tgl TEXT)""")
    c.execute("PRAGMA table_info(jurnal_syariah)")
    cols = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('pengeluaran_rutin','REAL DEFAULT 0'),
        ('pengeluaran_sekolah','REAL DEFAULT 0'),
        ('pengeluaran_utang','REAL DEFAULT 0'),
        ('pengeluaran_sedekah','REAL DEFAULT 0'),
        ('updated_at','TEXT'),
        ('edit_count','INTEGER DEFAULT 0'),
        ('is_active','INTEGER DEFAULT 1'),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE jurnal_syariah ADD COLUMN {col} {defn}")

    # A.2. users_config
    c.execute("""CREATE TABLE IF NOT EXISTS users_config (
        user_id INTEGER PRIMARY KEY,
        tanggal_mulai_haul TEXT,
        baseline_awal REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("PRAGMA table_info(users_config)")
    cols_uc = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('is_admin','INTEGER DEFAULT 0'),
        ('nama_lengkap','TEXT'),
        ('no_whatsapp','TEXT'),
        ('khumus_aktif','INTEGER DEFAULT 1'),
        ('role',"TEXT DEFAULT 'user'"),
        ('lembaga_id','INTEGER'),
        ('status',"TEXT DEFAULT 'active'"),
        ('verified_by','INTEGER'),
        ('verified_at','TIMESTAMP'),
        ('onboarding_selesai', 'INTEGER DEFAULT 0'),
    ]:
        if col not in cols_uc:
            c.execute(f"ALTER TABLE users_config ADD COLUMN {col} {defn}")

    # A.3. lembaga_amil
    c.execute("""CREATE TABLE IF NOT EXISTS lembaga_amil (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT NOT NULL,
        jenis TEXT DEFAULT 'LAZIS',
        deskripsi TEXT,
        logo_url TEXT,
        aktif INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        bisa_dipilih_user INTEGER DEFAULT 1,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("PRAGMA table_info(lembaga_amil)")
    cols_lem = {r[1] for r in c.fetchall()}
    for col, defn in [
        ('status',"TEXT DEFAULT 'pending'"),
        ('kode_verifikasi','TEXT'),
        ('alamat','TEXT'),
        ('npwp','TEXT'),
        ('no_telepon','TEXT'),
        ('email_resmi','TEXT'),
        ('website','TEXT'),
        ('verified_by','INTEGER'),
        ('verified_at','TIMESTAMP'),
        ('verifikasi_metode','TEXT'),
        ('catatan_verifikasi','TEXT'),
        ('dokumen_url','TEXT'),
        ('rekening_atas_nama_lembaga','INTEGER DEFAULT 0'),
        ('is_public','INTEGER DEFAULT 0'),
    ]:
        if col not in cols_lem:
            c.execute(f"ALTER TABLE lembaga_amil ADD COLUMN {col} {defn}")

    # A.4. rekening_lembaga
    c.execute("""CREATE TABLE IF NOT EXISTS rekening_lembaga (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER NOT NULL,
        metode TEXT NOT NULL,
        nama_bank TEXT,
        nomor_rekening TEXT,
        atas_nama TEXT,
        qr_image_url TEXT,
        aktif INTEGER DEFAULT 1,
        is_default INTEGER DEFAULT 0,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # A.5. rencana_pembayaran
    c.execute("""CREATE TABLE IF NOT EXISTS rencana_pembayaran (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        jurnal_id INTEGER,
        jenis_kewajiban TEXT NOT NULL,
        keterangan TEXT,
        nominal REAL NOT NULL,
        lembaga_id INTEGER,
        lembaga_nama_manual TEXT,
        rekening_id INTEGER,
        rekening_info_manual TEXT,
        status TEXT DEFAULT 'pending',
        metode_transfer TEXT,
        bukti_transfer_url TEXT,
        bukti_uploaded_at TIMESTAMP,
        verified_by_admin INTEGER,
        verified_at TIMESTAMP,
        catatan_admin TEXT,
        alasan_batal TEXT,
        tanggal_rencana DATE,
        tanggal_bayar DATE,
        catatan_user TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id),
        FOREIGN KEY (rekening_id) REFERENCES rekening_lembaga(id)
    )""")

    # A.6. verifikasi_lembaga
    c.execute("""CREATE TABLE IF NOT EXISTS verifikasi_lembaga (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER NOT NULL,
        tahap TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        catatan TEXT,
        dilakukan_oleh INTEGER,
        bukti_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # A.7. tagihan
    c.execute("""CREATE TABLE IF NOT EXISTS tagihan (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        jenis TEXT NOT NULL,
        nama TEXT NOT NULL,
        nominal REAL NOT NULL,
        jatuh_tempo DATE,
        frekuensi TEXT DEFAULT 'sekali',
        status TEXT DEFAULT 'belum_lunas',
        metode_bayar TEXT,
        bukti_bayar_url TEXT,
        tanggal_bayar DATE,
        catatan TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tagihan_user ON tagihan(user_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tagihan_tempo ON tagihan(jatuh_tempo, status)")

    # A.8. log_akses_sensitif
    c.execute("""CREATE TABLE IF NOT EXISTS log_akses_sensitif (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        aksi TEXT,
        target_tabel TEXT,
        target_id INTEGER,
        detail TEXT,
        ip_address TEXT,
        user_agent TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # =================================================================
    # B. TABEL TV & AGENDA MASJID
    # =================================================================

    # B.1. tv_masjid_config
    c.execute("""CREATE TABLE IF NOT EXISTS tv_masjid_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER UNIQUE,
        tv_code TEXT UNIQUE,
        latitude REAL,
        longitude REAL,
        kota TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # B.2. agenda_masjid
    c.execute("""CREATE TABLE IF NOT EXISTS agenda_masjid (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lembaga_id INTEGER NOT NULL,
        tipe TEXT CHECK(tipe IN ('kegiatan', 'hari_besar')),
        tanggal TEXT NOT NULL,
        nama TEXT NOT NULL,
        pemateri TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")

    # =================================================================
    # C. TABEL MITRA ALAM (WAKAF PRODUKTIF TANAMAN)
    # =================================================================

    # C.1. komoditas_wakaf
    c.execute("""CREATE TABLE IF NOT EXISTS komoditas_wakaf (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kode TEXT UNIQUE NOT NULL,
        nama_display TEXT NOT NULL,
        harga_pohon REAL NOT NULL,
        output TEXT,
        siklus_panen TEXT,
        nilai_ekonomi TEXT,
        fungsi_ekologis TEXT,
        deskripsi TEXT,
        foto_url TEXT,
        aktif INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")

    # C.2. pohon_wakaf
    c.execute("""CREATE TABLE IF NOT EXISTS pohon_wakaf (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nfc_uid TEXT UNIQUE NOT NULL,
        komoditas_id INTEGER NOT NULL,
        varietas TEXT,
        tanggal_tanam DATE,
        lat REAL,
        lng REAL,
        lembaga_id INTEGER NOT NULL,
        muwakif_id INTEGER,
        rencana_id INTEGER,
        harga_pohon REAL,
        status TEXT DEFAULT 'aktif',
        catatan TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        FOREIGN KEY (komoditas_id) REFERENCES komoditas_wakaf(id),
        FOREIGN KEY (lembaga_id) REFERENCES lembaga_amil(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pohon_muwakif ON pohon_wakaf(muwakif_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pohon_lembaga ON pohon_wakaf(lembaga_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pohon_status ON pohon_wakaf(status)")

    # C.3. pohon_log
    c.execute("""CREATE TABLE IF NOT EXISTS pohon_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pohon_id INTEGER NOT NULL,
        tanggal DATE NOT NULL,
        tipe TEXT NOT NULL,
        nilai TEXT,
        foto_url TEXT,
        catatan TEXT,
        petugas_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (pohon_id) REFERENCES pohon_wakaf(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_log_pohon ON pohon_log(pohon_id, tanggal)")

    # C.4. pohon_panen
    c.execute("""CREATE TABLE IF NOT EXISTS pohon_panen (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pohon_id INTEGER NOT NULL,
        tanggal_panen DATE NOT NULL,
        hasil_kg REAL DEFAULT 0,
        hasil_nominal REAL DEFAULT 0,
        pembagian_masjid REAL DEFAULT 0,
        pembagian_perawatan REAL DEFAULT 0,
        pembagian_raudha REAL DEFAULT 0,
        catatan TEXT,
        petugas_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (pohon_id) REFERENCES pohon_wakaf(id)
    )""")

    # =================================================================
    # D. SEED DATA
    # =================================================================

    # D.1. Seed Super Admin
    admin_id_env = os.getenv("ADMIN_ID", "").strip()
    if admin_id_env.isdigit():
        super_admin_id = int(admin_id_env)
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (super_admin_id,))
        if c.fetchone():
            c.execute("""UPDATE users_config 
                         SET role='super_admin', status='active'
                         WHERE user_id=?""", (super_admin_id,))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, role, status, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, 'super_admin', 'active', ?, ?)""",
                      (super_admin_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))
        logger.info(f"👑 Super Admin terdaftar: user_id={super_admin_id}")

    # D.2. Seed Lembaga Default
    c.execute("SELECT COUNT(*) FROM lembaga_amil")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO lembaga_amil 
                     (nama, jenis, deskripsi, status, kode_verifikasi, 
                      is_default, bisa_dipilih_user, is_public)
                     VALUES 
                     ('LAZIS Raudha', 'LAZIS', 'Lembaga Amil Zakat resmi Raudha', 
                      'verified', 'LAZIS-RAUDHA-001', 1, 1, 1),
                     ('BAZNAS', 'BAZNAS', 'Badan Amil Zakat Nasional', 
                      'verified', 'BAZNAS-001', 0, 1, 1),
                     ('Dompet Dhuafa', 'LAZIS', 'Lembaga filantropi Islam', 
                      'verified', 'DD-001', 0, 1, 1)""")
        logger.info("✅ Seed lembaga_amil default berhasil")

    # D.3. Seed Komoditas Wakaf Mitra Alam
    c.execute("SELECT COUNT(*) FROM komoditas_wakaf")
    if c.fetchone()[0] == 0:
        seed_komoditas = [
            ('kurma_hibrida', 'Kurma Hibrida', 250000,
             'Buah + pohon', '3-5 tahun',
             'Rp 300-500 rb/pohon/tahun', 'Peneduh, pangan',
             'Kurma hibrida unggul yang mampu berbuah di iklim tropis. '
             'Buah bernilai ekonomi tinggi, pohon dapat dijual sebagai bibit.'),
            ('kopi_wulung', 'Kopi Wulung (Langka)', 150000,
             'Biji kopi premium', '2-3 tahun',
             'Rp 200-400 rb/pohon/tahun', 'Konservasi, agroforestri',
             'Varietas kopi langka dengan cita rasa khas. Cocok untuk '
             'agroforestri dan konservasi tanah.'),
            ('kayu_jati', 'Kayu Jati', 500000,
             'Kayu (siklus 15 tahun)', '15 tahun',
             'Rp 5-15 jt/pohon', 'Penahan erosi, penyerap CO₂',
             'Kayu jati berkualitas tinggi untuk mebel dan konstruksi. '
             'Investasi jangka panjang yang bernilai tinggi.'),
            ('kayu_balsa', 'Kayu Balsa', 200000,
             'Kayu (siklus 5 tahun)', '5 tahun',
             'Rp 1-2 jt/pohon', 'Cepat panen, bahan industri',
             'Kayu balsa tumbuh cepat, ringan, dan kuat. Banyak dipakai '
             'untuk industri model, panel, dan isolasi.'),
            ('aren', 'Aren (Pohon Serbaguna)', 300000,
             'Buah + nira/gula', '5-7 tahun',
             'Rp 500 rb-1 jt/pohon/tahun', 'Penahan longsor, konservasi air',
             'Pohon aren berfungsi ganda: akar kuat menahan longsor, '
             'nira menghasilkan gula aren, buah dapat diolah.'),
        ]
        c.executemany("""INSERT INTO komoditas_wakaf
                         (kode, nama_display, harga_pohon, output,
                          siklus_panen, nilai_ekonomi, fungsi_ekologis, deskripsi)
                         VALUES (?,?,?,?,?,?,?,?)""", seed_komoditas)
        logger.info("✅ Seed 5 komoditas wakaf berhasil")

    # =================================================================
    # D.4. PROGRAM CONFIG (mode verifikasi wakaf, dll)
    # =================================================================
   
    c.execute("""CREATE TABLE IF NOT EXISTS program_config (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""INSERT OR IGNORE INTO program_config (key, value) 
                 VALUES ('wakaf_verification_mode', 'super_only')""")
    c.execute("SELECT value FROM program_config WHERE key='wakaf_verification_mode'")
    row_mode = c.fetchone()
    current_mode = row_mode[0] if row_mode else 'super_only'
    logger.info(f"⚙️ Program config: wakaf_verification_mode={current_mode}")

    # =================================================================
    # COMMIT & CLOSE
    # =================================================================

    conn.commit()
    conn.close()
    logger.info("✅ Semua tabel database Raudha siap (termasuk Mitra Alam)")


init_web_db()

# =====================================================================
# ENGINE HITUNG
# =====================================================================

def cek_haul_terpenuhi(user_id, tanggal_hari_ini=None):
    """
    Cek haul sejak tanggal_mulai_haul. Return dict.
    """
    if tanggal_hari_ini is None:
        tanggal_hari_ini = date.today()

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT tanggal_mulai_haul FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone(); conn.close()

    if not row or not row[0]:
        return {
            "haul_terpenuhi": False, "hari_berlalu": 0,
            "tanggal_mulai_haul": None, "sisa_hari_haul": HAUL_HARI,
            "pesan": "Belum ada data. Input pertama Anda untuk mulai haul."
        }

    try:
        mulai = datetime.strptime(row[0], "%Y-%m-%d").date()
    except ValueError:
        return {
            "haul_terpenuhi": False, "hari_berlalu": 0,
            "tanggal_mulai_haul": None, "sisa_hari_haul": HAUL_HARI,
            "pesan": "Tanggal mulai haul tidak valid."
        }

    selisih = (tanggal_hari_ini - mulai).days
    terpenuhi = selisih >= HAUL_HARI
    sisa = max(0, HAUL_HARI - selisih)

    return {
        "haul_terpenuhi": terpenuhi,
        "hari_berlalu": selisih,
        "tanggal_mulai_haul": mulai.strftime("%Y-%m-%d"),
        "sisa_hari_haul": sisa,
        "pesan": (
            "✅ Haul terpenuhi — zakat maal wajib ditunaikan." if terpenuhi
            else f"⏳ Haul belum terpenuhi — sisa {sisa} hari lagi."
        )
    }

def laporan_tahunan(user_id, harga_emas):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    nisab_maal = NISAB_EMAS_GRAM * harga_emas

    total_pemasukan = total_pengeluaran = 0
    total_zakat_tani = total_khumus_kotor = 0
    total_bmt_idr = total_benda_mewah = 0
    total_temuan_kotor = 0

    # 1. HITUNG PEMASUKAN & PENGELUARAN DARI JURNAL
    c.execute("""SELECT gaji, honor, hadiah, pertanian_kg, jenis_pengairan,
                        benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
                        pengeluaran_rutin, pengeluaran_sekolah,
                        pengeluaran_utang, pengeluaran_sedekah
                 FROM jurnal_syariah WHERE user_id=? AND COALESCE(is_active,1)=1""", (user_id,))
    for row in c.fetchall():
        (gj, hnr, hd, tani, pengairan, mewah, temuan, bmt,
         p_rutin, p_sekolah, p_utang, p_sedekah) = row
        total_pemasukan += ((gj or 0)+(hnr or 0)+(hd or 0)+(bmt or 0)+(mewah or 0)
                            + ((tani or 0)*HARGA_TANI_PER_KG) + (temuan or 0))
        total_pengeluaran += ((p_rutin or 0)+(p_sekolah or 0)+(p_utang or 0)+(p_sedekah or 0))
        total_bmt_idr += (bmt or 0)
        total_benda_mewah += (mewah or 0)
        total_temuan_kotor += (temuan or 0)
        
        # Zakat Tani (jika mencapai nisab)
        if (tani or 0) >= NISAB_PERTANIAN_KG:
            kadar = KADAR_TANAH_ALAMI if pengairan == 'tadah_hujan' else KADAR_TANAH_BIAYA
            total_zakat_tani += (tani * kadar) * HARGA_TANI_PER_KG
            
        # Khumus Temuan (Harta Karun)
        if (temuan or 0) > 0:
            total_khumus_kotor += (temuan * KADAR_KHUMUS)

    # 2. TAGIHAN LUNAS
    c.execute("""SELECT COALESCE(SUM(nominal), 0) 
                 FROM tagihan WHERE user_id=? AND status='lunas'""", (user_id,))
    total_tagihan_lunas = c.fetchone()[0] or 0

    # 3. STATUS PEMBAYARAN (Zakat, Khumus, Infaq)
    c.execute("""SELECT jenis_kewajiban, status, COALESCE(SUM(nominal), 0) 
                 FROM rencana_pembayaran WHERE user_id=? GROUP BY jenis_kewajiban, status""", (user_id,))
    
    total_pembayaran_dibayar = 0
    total_pembayaran_diverifikasi = 0
    zakat_maal_dibayar = 0
    khumus_dibayar = 0
    infaq_dibayar = 0

    for jenis, status, nominal in c.fetchall():
        if status in ('dibayar', 'diverifikasi'):
            if jenis == 'zakat_maal':
                zakat_maal_dibayar += nominal
            elif jenis == 'khumus':
                khumus_dibayar += nominal
            elif jenis == 'infaq':
                infaq_dibayar += nominal

        if status == 'dibayar':
            total_pembayaran_dibayar += nominal
        elif status == 'diverifikasi':
            total_pembayaran_diverifikasi += nominal

    total_pembayaran_berkurang = total_pembayaran_dibayar + total_pembayaran_diverifikasi

    # 4. CEK KHUMUS AKTIF
    c.execute("SELECT khumus_aktif FROM users_config WHERE user_id=?", (user_id,))
    row_k = c.fetchone()
    khumus_aktif = bool(row_k[0]) if row_k and row_k[0] is not None else True
    conn.close()

    # 5. HITUNG HARTA KUMULATIF (Bersih)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT baseline_awal FROM users_config WHERE user_id=?", (user_id,))
    row_baseline = c.fetchone()
    baseline_user = row_baseline[0] if row_baseline and row_baseline[0] else BASELINE_AWAL
    conn.close()

    # Harta Bersih = (Baseline + Pemasukan) - (Pengeluaran Jurnal + Tagihan Lunas + Semua Pembayaran)
    # Pemasukan bersih (Pemasukan - Pengeluaran Jurnal)
    pemasukan_bersih = (baseline_user + total_pemasukan) - total_pengeluaran
    
    # Harta kumulatif tidak boleh minus, dan pembayaran (Zakat/Khumus/Infaq) hanya memotong jika pemasukan bersih masih ada
    harta_kumulatif = max(0, pemasukan_bersih - total_pembayaran_berkurang - total_tagihan_lunas) 

    # 6. HITUNG KEWAJIBAN ZAKAT MAAL
    haul_info = cek_haul_terpenuhi(user_id)
    zakat_maal_potensial = (harta_kumulatif * KADAR_ZAKAT) if harta_kumulatif >= nisab_maal else 0
    zakat_maal_wajib = zakat_maal_potensial if haul_info["haul_terpenuhi"] else 0
    
    # Sisa yang harus dibayar = Wajib - Yang sudah dibayar (Zakat saja)
    zakat_maal_belum_dibayar = max(0, zakat_maal_wajib - zakat_maal_dibayar)

    # 7. HITUNG KEWAJIBAN KHUMUS
    # Sesuai Fikih: Khumus dihitung dari Harta Kotor (Temuan/Surplus).
    # Infaq/Sedekah TIDAK mengurangi kewajiban Khumus, melainkan hanya mengurangi Harta Kumulatif.
    if khumus_aktif:
        # Khumus Wajib = Total Khumus Kotor - Pembayaran Khumus (jika ada)
        total_khumus_final = max(0, total_khumus_kotor - khumus_dibayar)
    else:
        total_khumus_final = 0

    return {
        "total_harta": harta_kumulatif,
        "total_penghasilan": harta_kumulatif,  # <--- TAMBAHKAN INI (atau gunakan variabel yang sesuai)
        "total_zakat": zakat_maal_wajib + total_zakat_tani,
        "zakat_maal_wajib": zakat_maal_wajib,
        "zakat_maal_potensial": zakat_maal_potensial,
        "zakat_maal_belum_dibayar": zakat_maal_belum_dibayar, # Ini yang harus ditagihkan
        "zakat_maal_sudah_direncanakan": zakat_maal_dibayar,
        "zakat_tani": total_zakat_tani,
        "total_khumus": total_khumus_final, # Ini sisa Khumus
        "khumus_aktif": khumus_aktif,
        "total_temuan_kotor": total_temuan_kotor,
        "haul_terpenuhi": haul_info["haul_terpenuhi"],
        "hari_berlalu": haul_info["hari_berlalu"],
        "tanggal_mulai_haul": haul_info["tanggal_mulai_haul"],
        "sisa_hari_haul": haul_info["sisa_hari_haul"],
        "haul_pesan": haul_info["pesan"],
        "total_pembayaran_dibayar": total_pembayaran_dibayar,
        "total_pembayaran_diverifikasi": total_pembayaran_diverifikasi,
        "total_pembayaran_berkurang": total_pembayaran_berkurang,
        "total_tagihan_lunas": total_tagihan_lunas,
        "saldo_bmt_idr": total_bmt_idr,
        "saldo_bmt_emas": (total_bmt_idr / harga_emas) if harga_emas else 0,
        "nisab_emas_rupiah": nisab_maal,
    }

# =====================================================================
# API — LAPORAN & KONFIG
# =====================================================================

@app.route('/api/role/<int:user_id>')
def get_role(user_id):
    """
    Endpoint untuk mengecek role admin dari Mini App.
    Prioritas: super_admin (env) > users_config > admin_penugasan
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    # 1. Super Admin dari env
    admin_id = os.getenv("ADMIN_ID")
    if admin_id and admin_id.isdigit() and int(admin_id) == user_id:
        return jsonify({"status": "success", "role": "super_admin"})
    
    # 2. Cek users_config (PRIORITAS)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, status, lembaga_id FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    
    if row:
        role_db, status, lembaga_id = row
        if status == 'active' and role_db in ('super_admin', 'admin_lembaga'):
            conn.close()
            return jsonify({
                "status": "success",
                "role": role_db,
                "lembaga_id": lembaga_id,
            })
    
    # 3. Fallback: admin_penugasan
    c.execute("SELECT jenis_layanan FROM admin_penugasan WHERE user_id = ? AND status = 'aktif' LIMIT 1", (user_id,))
    row2 = c.fetchone()
    conn.close()
    
    if row2:
        return jsonify({"status": "success", "role": row2[0]})
    
    return jsonify({"status": "error", "message": "Not an admin"}), 403

@app.route('/api/laporan/<int:user_id>')
@require_telegram_auth
def api_laporan(user_id):
    # Ambil user_id peminta (dari Telegram auth atau query string fallback)
    req_uid = request.telegram_user_id
    if not req_uid:
        try:
            req_uid = int(request.args.get('user_id', 0)) or None
        except (ValueError, TypeError):
            pass
    
    if req_uid and req_uid != user_id:
        info = get_user_role(req_uid)
        
        if info.get("role") == "super_admin":
            pass  # OK
        
        elif info.get("role") == "admin_lembaga":
            lembaga_id = info.get("lembaga_id")
            if not lembaga_id:
                return jsonify({"status": "error", 
                                "message": "Admin lembaga tanpa lembaga_id"}), 403
            
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("""SELECT 1 FROM rencana_pembayaran 
                         WHERE user_id=? AND lembaga_id=? AND status='diverifikasi'
                         LIMIT 1""", (user_id, lembaga_id))
            has_transaction = c.fetchone()
            conn.close()
            
            if not has_transaction:
                return jsonify({"status": "error", 
                                "message": "Akses ditolak. User tidak punya transaksi di lembaga Anda."}), 403
        else:
            return jsonify({"status": "error", "message": "Akses ditolak"}), 403
    
    res = laporan_tahunan(user_id, HARGA_EMAS_BASE)
    res["zakat_penghasilan_wajib"] = res["total_zakat"] > 0
    return jsonify({"status": "success", "laporan": res})

@app.route('/api/config')
def api_config():
    return jsonify({
        "harga_emas": HARGA_EMAS_BASE,
        "baseline_awal": BASELINE_AWAL,
        "harga_tani_per_kg": HARGA_TANI_PER_KG,
        "nisab_emas_gram": NISAB_EMAS_GRAM,
        "nisab_pertanian_kg": NISAB_PERTANIAN_KG,
        "kadar_zakat": KADAR_ZAKAT,
        "kadar_tanah_alami": KADAR_TANAH_ALAMI,
        "kadar_tanah_biaya": KADAR_TANAH_BIAYA,
        "kadar_khumus": KADAR_KHUMUS,
        "haul_hari": HAUL_HARI,
    })

@app.route('/api/bot/laporan/<int:user_id>')
def api_bot_laporan(user_id):
    """Endpoint khusus bot — tanpa auth (bot sudah terautentikasi via Telegram)."""
    res = laporan_tahunan(user_id, HARGA_EMAS_BASE)
    res["zakat_penghasilan_wajib"] = res["total_zakat"] > 0
    return jsonify({"status": "success", "laporan": res})


@app.route('/api/bot/tagihan/<int:user_id>')
def api_bot_tagihan(user_id):
    """Endpoint khusus bot — tagihan."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, jenis, nama, nominal, jatuh_tempo, status
                 FROM tagihan WHERE user_id=?
                 ORDER BY id DESC LIMIT 20""", (user_id,))
    rows = c.fetchall()
    conn.close()
    keys = ["id", "jenis", "nama", "nominal", "jatuh_tempo", "status"]
    return jsonify({"status": "success", "tagihan": [dict(zip(keys, r)) for r in rows]})

# =====================================================================
# API — ONBOARDING (Batch 13)
# =====================================================================

@app.route('/api/onboarding/<int:user_id>', methods=['GET'])
def get_onboarding_state(user_id):
    """Cek apakah user sudah selesai onboarding."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT onboarding_selesai FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    sudah = bool(row[0]) if row and row[0] is not None else False
    return jsonify({"status": "success", "onboarding_selesai": sudah})


@app.route('/api/onboarding/selesai', methods=['POST'])
def set_onboarding_selesai():
    """Tandai onboarding selesai."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("UPDATE users_config SET onboarding_selesai=1 WHERE user_id=?", (user_id,))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal, onboarding_selesai)
                         VALUES (?, ?, ?, 1)""",
                      (user_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))
        conn.commit()
        return jsonify({"status": "success", "message": "Onboarding selesai"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


# =====================================================================
# API — BAHASA USER
# =====================================================================

@app.route('/api/config/bahasa/<int:user_id>', methods=['GET'])
def get_bahasa(user_id):
    """Ambil preferensi bahasa user."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT bahasa FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    bahasa = (row[0] if row and row[0] else "id")
    return jsonify({"status": "success", "bahasa": bahasa})


@app.route('/api/config/bahasa', methods=['POST'])
def set_bahasa():
    """Set preferensi bahasa user."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    bahasa = data.get("bahasa", "id").strip()
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    if bahasa not in ("id", "en"):
        return jsonify({"status": "error", "message": "Bahasa tidak valid"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("UPDATE users_config SET bahasa=? WHERE user_id=?", (bahasa, user_id))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal, bahasa)
                         VALUES (?, ?, ?, ?)""",
                      (user_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL, bahasa))
        conn.commit()
        return jsonify({"status": "success", "bahasa": bahasa})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/config/khumus/<int:user_id>', methods=['GET'])
def get_khumus_status(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT khumus_aktif FROM users_config WHERE user_id=?", (user_id,))
        row = c.fetchone()
        khumus_aktif = bool(row[0]) if row and row[0] is not None else True
    finally:
        conn.close()
    return jsonify({"status": "success", "khumus_aktif": khumus_aktif})

@app.route('/api/config/khumus', methods=['POST'])
def toggle_khumus():
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    aktif = bool(data.get("aktif", True))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("UPDATE users_config SET khumus_aktif=? WHERE user_id=?",
                      (1 if aktif else 0, user_id))
        else:
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal, khumus_aktif)
                         VALUES (?, ?, ?, ?)""",
                      (user_id, date.today().strftime("%Y-%m-%d"),
                       BASELINE_AWAL, 1 if aktif else 0))
        tulis_audit(c, user_id, "users_config", user_id, "TOGGLE_KHUMUS",
                    baru=str(aktif), alasan="User toggle khumus")
        conn.commit()
        return jsonify({"status": "success", "khumus_aktif": aktif})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()



# =====================================================================
# API — INPUT & EDIT JURNAL
# =====================================================================

@app.route('/api/input/syariah', methods=['POST'])
@require_telegram_auth
def input_syariah():
    data = request.json or {}
    user_id = int(data.get("user_id", 99999))
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if not c.fetchone():
            c.execute("""INSERT INTO users_config 
                         (user_id, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, ?, ?)""",
                      (user_id, date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))
            logger.info(f"[USER BARU] user_id={user_id}")

        c.execute("""INSERT INTO jurnal_syariah
            (user_id, jenis, gaji, honor, hadiah, pertanian_kg, jenis_pengairan,
             benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
             pengeluaran_rutin, pengeluaran_sekolah, pengeluaran_utang, pengeluaran_sedekah, tgl,
             updated_at, edit_count, is_active)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1)""",
            (user_id, data.get("jenis","input_web"),
             data.get("gaji",0), data.get("honor",0), data.get("hadiah",0),
             data.get("pertanian_kg",0), data.get("jenis_pengairan","irigasi"),
             data.get("benda_mewah",0), data.get("temuan_laut_karun",0),
             data.get("simpanan_bmt_idr",0),
             data.get("pengeluaran_rutin",0), data.get("pengeluaran_sekolah",0),
             data.get("pengeluaran_utang",0), data.get("pengeluaran_sedekah",0),
             date.today().strftime("%Y-%m-%d"),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        tulis_audit(c, user_id, "jurnal_syariah", c.lastrowid, "CREATE",
                    alasan="Form Terperinci Mini App")
        conn.commit()
        return jsonify({"status":"success","message":"Berhasil disimpan!", "id": c.lastrowid})
    except Exception as e:
        conn.rollback()
        logger.error(f"Input error: {e}")
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

@app.route('/api/input/syariah/<int:jurnal_id>', methods=['PUT'])
def update_syariah(jurnal_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM jurnal_syariah WHERE id=? AND COALESCE(is_active,1)=1", (jurnal_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Jurnal tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403

        c.execute("""UPDATE jurnal_syariah SET
                        gaji=?, hadiah=?, pertanian_kg=?, jenis_pengairan=?,
                        benda_mewah=?, temuan_laut_karun=?, simpanan_bmt_idr=?,
                        pengeluaran_rutin=?, pengeluaran_sekolah=?,
                        pengeluaran_utang=?, pengeluaran_sedekah=?,
                        updated_at=?, edit_count=COALESCE(edit_count,0)+1
                     WHERE id=?""",
                  (data.get("gaji",0), data.get("hadiah",0),
                   data.get("pertanian_kg",0), data.get("jenis_pengairan","irigasi"),
                   data.get("benda_mewah",0), data.get("temuan_laut_karun",0),
                   data.get("simpanan_bmt_idr",0),
                   data.get("pengeluaran_rutin",0), data.get("pengeluaran_sekolah",0),
                   data.get("pengeluaran_utang",0), data.get("pengeluaran_sedekah",0),
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   jurnal_id))
        tulis_audit(c, user_id, "jurnal_syariah", jurnal_id, "UPDATE",
                    field="multi", baru=str(data), alasan="Edit dari Mini App")
        conn.commit()
        return jsonify({"status": "success", "message": "Data diperbarui"})
    except Exception as e:
        conn.rollback()
        logger.error(f"Edit error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/jurnal/<int:user_id>')
def api_jurnal_list(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, tgl, gaji, hadiah, pertanian_kg, jenis_pengairan,
                        benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
                        pengeluaran_rutin, pengeluaran_sekolah,
                        pengeluaran_utang, pengeluaran_sedekah,
                        edit_count, updated_at
                 FROM jurnal_syariah
                 WHERE user_id=? AND COALESCE(is_active,1)=1
                 ORDER BY id DESC LIMIT 50""", (user_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","tgl","gaji","hadiah","pertanian_kg","jenis_pengairan",
            "benda_mewah","temuan_laut_karun","simpanan_bmt_idr",
            "pengeluaran_rutin","pengeluaran_sekolah",
            "pengeluaran_utang","pengeluaran_sedekah",
            "edit_count","updated_at"]
    return jsonify({"status": "success", "jurnal": [dict(zip(keys, r)) for r in rows]})


@app.route('/api/input/syariah/<int:jurnal_id>', methods=['DELETE'])
def hapus_jurnal(jurnal_id):
    """Soft-delete jurnal (is_active=0) — data tetap tersimpan untuk audit."""
    user_id = int(request.args.get('user_id', 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM jurnal_syariah WHERE id=? AND COALESCE(is_active,1)=1", (jurnal_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Jurnal tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403

        c.execute("UPDATE jurnal_syariah SET is_active=0, updated_at=? WHERE id=?",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), jurnal_id))
        tulis_audit(c, user_id, "jurnal_syariah", jurnal_id, "DELETE",
                    alasan="Hapus dari Mini App (soft delete)")
        conn.commit()
        return jsonify({"status": "success", "message": "Data dihapus"})
    except Exception as e:
        conn.rollback()
        logger.error(f"Hapus jurnal error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/jurnal/<int:user_id>/<int:jurnal_id>', methods=['GET'])
def api_jurnal_single(user_id, jurnal_id):
    """Ambil satu jurnal untuk edit."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, tgl, gaji, honor, hadiah, pertanian_kg, jenis_pengairan,
                        benda_mewah, temuan_laut_karun, simpanan_bmt_idr,
                        pengeluaran_rutin, pengeluaran_sekolah,
                        pengeluaran_utang, pengeluaran_sedekah
                 FROM jurnal_syariah
                 WHERE id=? AND user_id=? AND COALESCE(is_active,1)=1""",
              (jurnal_id, user_id))
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"status": "error", "message": "Jurnal tidak ditemukan"}), 404
    keys = ["id","tgl","gaji","honor","hadiah","pertanian_kg","jenis_pengairan",
            "benda_mewah","temuan_laut_karun","simpanan_bmt_idr",
            "pengeluaran_rutin","pengeluaran_sekolah",
            "pengeluaran_utang","pengeluaran_sedekah"]
    return jsonify({"status": "success", "jurnal": dict(zip(keys, row))})       


# =====================================================================
# API — SUPER ADMIN
# =====================================================================

@app.route('/api/admin/lembaga/pending', methods=['GET'])
@require_telegram_auth
def admin_list_pending_lembaga():
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, jenis, alamat, npwp, no_telepon, email_resmi,
                        dokumen_url, created_at, status
                 FROM lembaga_amil WHERE status='pending'
                 ORDER BY created_at ASC""")
    rows = c.fetchall(); conn.close()
    keys = ["id","nama","jenis","alamat","npwp","no_telepon","email_resmi",
            "dokumen_url","created_at","status"]
    return jsonify({"status": "success", "lembaga": [dict(zip(keys, r)) for r in rows]})

@app.route('/api/admin/lembaga/<int:lembaga_id>/detail', methods=['GET'])
def admin_detail_lembaga(lembaga_id):
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT * FROM lembaga_amil WHERE id=?", (lembaga_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Lembaga tidak ditemukan"}), 404
    cols = [d[0] for d in c.description]
    lembaga = dict(zip(cols, row))

    c.execute("""SELECT tahap, status, catatan, dilakukan_oleh, bukti_url, created_at
                 FROM verifikasi_lembaga WHERE lembaga_id=? ORDER BY created_at ASC""", (lembaga_id,))
    verif_keys = ["tahap","status","catatan","dilakukan_oleh","bukti_url","created_at"]
    verifikasi = [dict(zip(verif_keys, r)) for r in c.fetchall()]

    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, aktif
                 FROM rekening_lembaga WHERE lembaga_id=?""", (lembaga_id,))
    rek_keys = ["id","metode","nama_bank","nomor_rekening","atas_nama","aktif"]
    rekening = [dict(zip(rek_keys, r)) for r in c.fetchall()]

    c.execute("""SELECT user_id, nama_lengkap, no_whatsapp, status, verified_at
                 FROM users_config WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
    adm_keys = ["user_id","nama_lengkap","no_whatsapp","status","verified_at"]
    admins = [dict(zip(adm_keys, r)) for r in c.fetchall()]
    conn.close()
    return jsonify({
        "status": "success", "lembaga": lembaga, "verifikasi": verifikasi,
        "rekening": rekening, "admin_lembaga": admins,
    })

@app.route('/api/admin/lembaga/<int:lembaga_id>/verifikasi-tahap', methods=['POST'])
def admin_verifikasi_tahap(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    tahap = data.get("tahap", "").strip()
    status_tahap = data.get("status", "").strip()
    if tahap not in ("dokumen", "video_call", "kunjungan", "keputusan"):
        return jsonify({"status": "error", "message": "Tahap tidak valid"}), 400
    if status_tahap not in ("lolos", "gagal"):
        return jsonify({"status": "error", "message": "Status tahap tidak valid"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM lembaga_amil WHERE id=?", (lembaga_id,))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "Lembaga tidak ditemukan"}), 404
        c.execute("""INSERT INTO verifikasi_lembaga
                     (lembaga_id, tahap, status, catatan, dilakukan_oleh, bukti_url)
                     VALUES (?,?,?,?,?,?)""",
                  (lembaga_id, tahap, status_tahap,
                   data.get("catatan", ""), user_id, data.get("bukti_url", "")))
        log_sensitive(c, user_id, "super_admin", f"verifikasi_{tahap}",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"status={status_tahap}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": f"Tahap {tahap} dicatat"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/lembaga/<int:lembaga_id>/aktifkan', methods=['POST'])
def admin_aktifkan_lembaga(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT tahap, status FROM verifikasi_lembaga WHERE lembaga_id=?", (lembaga_id,))
        tahap_lolos = {r[0] for r in c.fetchall() if r[1] == "lolos"}
        if "dokumen" not in tahap_lolos:
            return jsonify({"status":"error","message":"Tahap 'dokumen' belum lolos"}), 400
        if not ({"video_call", "kunjungan"} & tahap_lolos):
            return jsonify({"status":"error","message":"Butuh tahap 'video_call' atau 'kunjungan' yang lolos"}), 400

        c.execute("""SELECT COUNT(*) FROM users_config 
                     WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
        if c.fetchone()[0] < 2:
            return jsonify({"status":"error","message":"Butuh minimal 2 admin lembaga"}), 400

        c.execute("""SELECT COUNT(*) FROM rekening_lembaga 
                     WHERE lembaga_id=? AND aktif=1""", (lembaga_id,))
        if c.fetchone()[0] == 0:
            return jsonify({"status":"error","message":"Lembaga belum punya rekening aktif"}), 400

        c.execute("SELECT nama, kode_verifikasi FROM lembaga_amil WHERE id=?", (lembaga_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status":"error","message":"Lembaga tidak ditemukan"}), 404
        nama_lembaga, kode = row
        if not kode:
            kode = buat_kode_verifikasi(nama_lembaga, lembaga_id)
            c.execute("UPDATE lembaga_amil SET kode_verifikasi=? WHERE id=?", (kode, lembaga_id))

        c.execute("""UPDATE lembaga_amil SET status='verified', verified_by=?, 
                        verified_at=CURRENT_TIMESTAMP, is_public=1 WHERE id=?""",
                  (user_id, lembaga_id))
        c.execute("""UPDATE users_config SET status='active', verified_by=?, 
                        verified_at=CURRENT_TIMESTAMP
                     WHERE lembaga_id=? AND role='admin_lembaga'""",
                  (user_id, lembaga_id))
        log_sensitive(c, user_id, "super_admin", "aktifkan_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"kode={kode}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Lembaga diaktifkan",
                        "kode_verifikasi": kode})
    except Exception as e:
        conn.rollback()
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/lembaga/<int:lembaga_id>/suspend', methods=['POST'])
def admin_suspend_lembaga(lembaga_id):
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    alasan = data.get("alasan", "").strip()
    if not alasan:
        return jsonify({"status": "error", "message": "Alasan wajib diisi"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("UPDATE lembaga_amil SET status='suspended' WHERE id=?", (lembaga_id,))
        c.execute("""UPDATE users_config SET status='suspended'
                     WHERE lembaga_id=? AND role='admin_lembaga'""", (lembaga_id,))
        log_sensitive(c, user_id, "super_admin", "suspend_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"alasan={alasan}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Lembaga disuspend"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/semua-lembaga', methods=['GET'])
def admin_semua_lembaga():
    """Ambil SEMUA lembaga (untuk super admin)."""
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT id, nama, jenis, status FROM lembaga_amil ORDER BY id")
    rows = c.fetchall()
    conn.close()
    keys = ["id", "nama", "jenis", "status"]
    return jsonify({"status": "success", "lembaga": [dict(zip(keys, r)) for r in rows]})        


# =====================================================================
# API — DAFTAR LEMBAGA (PUBLIK)
# =====================================================================

@app.route('/api/lembaga/daftar', methods=['POST'])
def daftar_lembaga_baru():
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    required = ["nama", "jenis", "alamat", "npwp", "no_telepon", "email_resmi"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"status": "error", "message": "Field wajib belum lengkap"}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT lembaga_id FROM users_config 
                     WHERE user_id=? AND role='admin_lembaga'""", (user_id,))
        if c.fetchone():
            return jsonify({"status": "error",
                            "message": "Anda sudah menjadi admin lembaga lain"}), 400

        c.execute("""INSERT INTO lembaga_amil
                     (nama, jenis, alamat, npwp, no_telepon, email_resmi,
                      dokumen_url, status, created_by)
                     VALUES (?,?,?,?,?,?,?, 'pending', ?)""",
                  (data["nama"].strip(), data["jenis"].strip(),
                   data["alamat"].strip(), data["npwp"].strip(),
                   data["no_telepon"].strip(), data["email_resmi"].strip(),
                   data.get("dokumen_url", ""), user_id))
        lembaga_id = c.lastrowid

        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (user_id,))
        if c.fetchone():
            c.execute("""UPDATE users_config SET
                            role='admin_lembaga', lembaga_id=?, status='pending',
                            nama_lengkap=?, no_whatsapp=? WHERE user_id=?""",
                      (lembaga_id, data.get("nama_admin", ""),
                       data.get("no_whatsapp_admin", ""), user_id))
        else:
            c.execute("""INSERT INTO users_config
                         (user_id, role, lembaga_id, status, nama_lengkap,
                          no_whatsapp, tanggal_mulai_haul, baseline_awal)
                         VALUES (?, 'admin_lembaga', ?, 'pending', ?, ?, ?, ?)""",
                      (user_id, lembaga_id, data.get("nama_admin", ""),
                       data.get("no_whatsapp_admin", ""),
                       date.today().strftime("%Y-%m-%d"), BASELINE_AWAL))

        c.execute("""INSERT INTO verifikasi_lembaga
                     (lembaga_id, tahap, status, catatan, dilakukan_oleh)
                     VALUES (?, 'pengajuan', 'pending', 'Menunggu verifikasi', ?)""",
                  (lembaga_id, user_id))
        log_sensitive(c, user_id, "user", "daftar_lembaga",
                      target_tabel="lembaga_amil", target_id=lembaga_id,
                      detail=f"nama={data['nama']}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success",
                        "message": "Pengajuan diterima. Menunggu verifikasi super admin.",
                        "lembaga_id": lembaga_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

 

# =====================================================================
# API — UPLOAD DOKUMEN LEMBAGA
# =====================================================================

def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/api/upload/dokumen', methods=['POST'])
def upload_dokumen_lembaga():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "File tidak ditemukan"}), 400

    file = request.files['file']
    user_id = request.form.get("user_id", "").strip()
    jenis_dokumen = request.form.get("jenis_dokumen", "lainnya").strip()

    if not user_id.isdigit():
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    if file.filename == '':
        return jsonify({"status": "error", "message": "Nama file kosong"}), 400
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", "message": f"Format tidak didukung. Gunakan: {', '.join(ALLOWED_EXTENSIONS)}"}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"status": "error", "message": "File terlalu besar (maks 5 MB)"}), 400

    ext = file.filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_jenis = re.sub(r'[^a-z0-9]', '_', jenis_dokumen.lower())[:20] or "dokumen"
    filename = f"lembaga_{user_id}_{safe_jenis}_{timestamp}.{ext}"
    filepath = os.path.join(UPLOAD_DOKUMEN, filename)
    file.save(filepath)

    url = f"/uploads/dokumen_lembaga/{filename}"
    logger.info(f"[UPLOAD] user={user_id} jenis={jenis_dokumen} file={filename}")
    return jsonify({"status": "success", "url": url, "filename": filename, "size": size})


@app.route('/uploads/dokumen_lembaga/<path:filename>')
def serve_dokumen_lembaga(filename):
    return send_from_directory(UPLOAD_DOKUMEN, filename)


# =====================================================================
# API — CEK STATUS PENGAJUAN LEMBAGA
# =====================================================================

@app.route('/api/lembaga/status/<int:user_id>', methods=['GET'])
def cek_status_pengajuan(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT role, status, lembaga_id FROM users_config 
                     WHERE user_id=?""", (user_id,))
        uc = c.fetchone()
        if not uc:
            return jsonify({"status": "success", "kondisi": "belum_terdaftar"})

        role, user_status, lembaga_id = uc
        if role != "admin_lembaga":
            return jsonify({"status": "success", "kondisi": "bukan_admin_lembaga"})

        c.execute("""SELECT id, nama, jenis, status, alamat, no_telepon,
                            email_resmi, kode_verifikasi, created_at, verified_at
                     FROM lembaga_amil WHERE id=?""", (lembaga_id,))
        lem = c.fetchone()
        if not lem:
            return jsonify({"status": "success", "kondisi": "lembaga_hilang"})

        cols = ["id","nama","jenis","status","alamat","no_telepon",
                "email_resmi","kode_verifikasi","created_at","verified_at"]
        lembaga = dict(zip(cols, lem))

        c.execute("""SELECT tahap, status, catatan, created_at
                     FROM verifikasi_lembaga WHERE lembaga_id=?
                     ORDER BY created_at ASC""", (lembaga_id,))
        verif_keys = ["tahap","status","catatan","created_at"]
        verifikasi = [dict(zip(verif_keys, r)) for r in c.fetchall()]

        return jsonify({
            "status": "success",
            "kondisi": lembaga["status"],
            "lembaga": lembaga,
            "verifikasi": verifikasi,
            "user_status": user_status,
        })
    finally:
        conn.close()


@app.route('/api/lembaga', methods=['GET'])
def list_lembaga_publik():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, jenis, deskripsi, logo_url, kode_verifikasi, is_default
                 FROM lembaga_amil
                 WHERE status='verified' AND aktif=1 AND is_public=1
                 ORDER BY is_default DESC, nama ASC""")
    rows = c.fetchall(); conn.close()
    keys = ["id","nama","jenis","deskripsi","logo_url","kode_verifikasi","is_default"]
    return jsonify({"status": "success", "lembaga": [dict(zip(keys, r)) for r in rows]})

@app.route('/api/lembaga/<int:lembaga_id>/rekening', methods=['GET'])
def list_rekening_lembaga(lembaga_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, qr_image_url
                 FROM rekening_lembaga WHERE lembaga_id=? AND aktif=1
                 ORDER BY is_default DESC""", (lembaga_id,))
    rows = c.fetchall(); conn.close()
    keys = ["id","metode","nama_bank","nomor_rekening","atas_nama","qr_image_url"]
    return jsonify({"status": "success", "rekening": [dict(zip(keys, r)) for r in rows]})

# =====================================================================
# API — KELOLA REKENING LEMBAGA (Admin Lembaga & Super Admin)
# =====================================================================

def _cek_akses_lembaga(user_id, lembaga_id):
    """
    Cek apakah user berhak kelola rekening lembaga ini.
    Return: (bool, error_message, user_info)
    """
    info = get_user_role(user_id)
    
    # Super admin boleh kelola semua lembaga
    if info["role"] == "super_admin":
        return True, None, info
    
    # Admin lembaga hanya boleh kelola lembaganya sendiri
    if info["role"] == "admin_lembaga":
        if info["lembaga_id"] != lembaga_id:
            return False, "Anda bukan admin lembaga ini", info
        if info["status"] != "active":
            return False, f"Akun Anda {info['status']}, belum bisa kelola rekening", info
        return True, None, info
    
    return False, "Akses ditolak — bukan admin lembaga", info


@app.route('/api/lembaga/<int:lembaga_id>/rekening', methods=['POST'])
def tambah_rekening_lembaga(lembaga_id):
    """Tambah rekening baru untuk lembaga."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    metode = data.get("metode", "bank_transfer").strip()
    nama_bank = data.get("nama_bank", "").strip()
    nomor_rekening = data.get("nomor_rekening", "").strip()
    atas_nama = data.get("atas_nama", "").strip()
    
    if not nama_bank or not nomor_rekening or not atas_nama:
        return jsonify({"status": "error", "message": "Field wajib belum lengkap"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM lembaga_amil WHERE id=?", (lembaga_id,))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "Lembaga tidak ditemukan"}), 404
        
        # Cek apakah sudah ada rekening default
        c.execute("SELECT COUNT(*) FROM rekening_lembaga WHERE lembaga_id=? AND aktif=1", (lembaga_id,))
        jumlah_ada = c.fetchone()[0]
        is_default = 1 if jumlah_ada == 0 else 0
        
        c.execute("""INSERT INTO rekening_lembaga
                     (lembaga_id, metode, nama_bank, nomor_rekening, atas_nama, aktif, is_default)
                     VALUES (?,?,?,?,?,1,?)""",
                  (lembaga_id, metode, nama_bank, nomor_rekening, atas_nama, is_default))
        rek_id = c.lastrowid
        log_sensitive(c, user_id, info["role"], "tambah_rekening",
                      target_tabel="rekening_lembaga", target_id=rek_id,
                      detail=f"lembaga={lembaga_id}, bank={nama_bank}, norek={nomor_rekening}",
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Rekening ditambahkan", "id": rek_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/lembaga/<int:lembaga_id>/rekening/<int:rek_id>', methods=['PUT'])
def edit_rekening_lembaga(lembaga_id, rek_id):
    """Edit rekening lembaga."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM rekening_lembaga WHERE id=? AND lembaga_id=?", (rek_id, lembaga_id))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "Rekening tidak ditemukan"}), 404
        
        c.execute("""UPDATE rekening_lembaga SET
                        metode=?, nama_bank=?, nomor_rekening=?, atas_nama=?, aktif=?
                     WHERE id=? AND lembaga_id=?""",
                  (data.get("metode", "bank_transfer"),
                   data.get("nama_bank", "").strip(),
                   data.get("nomor_rekening", "").strip(),
                   data.get("atas_nama", "").strip(),
                   1 if data.get("aktif", True) else 0,
                   rek_id, lembaga_id))
        log_sensitive(c, user_id, info["role"], "edit_rekening",
                      target_tabel="rekening_lembaga", target_id=rek_id,
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Rekening diperbarui"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/lembaga/<int:lembaga_id>/rekening/<int:rek_id>', methods=['DELETE'])
def hapus_rekening_lembaga(lembaga_id, rek_id):
    """Hapus (nonaktifkan) rekening lembaga."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM rekening_lembaga WHERE id=? AND lembaga_id=?", (rek_id, lembaga_id))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "Rekening tidak ditemukan"}), 404
        
        # Soft delete: set aktif=0 (jangan hapus permanen, agar riwayat tetap)
        c.execute("UPDATE rekening_lembaga SET aktif=0, is_default=0 WHERE id=? AND lembaga_id=?",
                  (rek_id, lembaga_id))
        log_sensitive(c, user_id, info["role"], "hapus_rekening",
                      target_tabel="rekening_lembaga", target_id=rek_id,
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Rekening dihapus"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/lembaga/<int:lembaga_id>/rekening/semua', methods=['GET'])
def semua_rekening_lembaga(lembaga_id):
    """Lihat semua rekening lembaga (termasuk yang nonaktif) — untuk admin."""
    user_id = int(request.args.get("user_id", 0))
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, aktif, is_default
                 FROM rekening_lembaga WHERE lembaga_id=?
                 ORDER BY is_default DESC, aktif DESC, id DESC""", (lembaga_id,))
    rows = c.fetchall()
    conn.close()
    keys = ["id","metode","nama_bank","nomor_rekening","atas_nama","aktif","is_default"]
    return jsonify({"status": "success", "rekening": [dict(zip(keys, r)) for r in rows]})

# =====================================================================
# API — PENGATURAN TV MASJID
# =====================================================================

@app.route('/api/lembaga/<int:lembaga_id>/tv-config', methods=['GET', 'POST'])
def tv_config_lembaga(lembaga_id):
    user_id = int(request.args.get("user_id", 0))
    if request.method == 'POST':
        user_id = int((request.json or {}).get("user_id", 0))
    
    # Cek hak akses (hanya admin lembaga / super admin)
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT tv_code, kota FROM tv_masjid_config WHERE lembaga_id=?", (lembaga_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return jsonify({"status": "success", "tv_code": row[0], "kota": row[1]})
        return jsonify({"status": "success", "tv_code": None, "kota": None})
        
    elif request.method == 'POST':
        data = request.json or {}
        kota = data.get("kota", "Banjarnegara").strip()
        
        # Generate TV Code jika belum ada (Misal: RAUDHA-01)
        c.execute("SELECT tv_code FROM tv_masjid_config WHERE lembaga_id=?", (lembaga_id,))
        existing = c.fetchone()
        
        if existing:
            tv_code = existing[0]
            c.execute("""UPDATE tv_masjid_config 
                         SET kota=?, updated_at=CURRENT_TIMESTAMP 
                         WHERE lembaga_id=?""", (kota, lembaga_id))
        else:
            # Buat kode unik berdasarkan nama lembaga
            c.execute("SELECT nama FROM lembaga_amil WHERE id=?", (lembaga_id,))
            nama_lembaga = c.fetchone()[0]
            tv_code = re.sub(r'[^A-Z0-9]', '', nama_lembaga.upper()[:10])[:10] + f"-{lembaga_id:02d}"
            
            c.execute("""INSERT INTO tv_masjid_config 
                         (lembaga_id, tv_code, kota) 
                         VALUES (?, ?, ?)""", (lembaga_id, tv_code, kota))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "tv_code": tv_code, "message": "Pengaturan TV disimpan"})

# API Agenda Masjid
@app.route('/api/lembaga/<int:lembaga_id>/agenda', methods=['GET', 'POST', 'DELETE'])
def api_agenda_lembaga(lembaga_id):
    user_id = int(request.args.get("user_id", 0))
    if request.method == 'POST':
        user_id = int((request.json or {}).get("user_id", 0))
    
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT id, tipe, tanggal, nama, pemateri FROM agenda_masjid WHERE lembaga_id=? ORDER BY tanggal ASC", (lembaga_id,))
        rows = c.fetchall()
        conn.close()
        keys = ["id", "tipe", "tanggal", "nama", "pemateri"]
        return jsonify({"status": "success", "agenda": [dict(zip(keys, r)) for r in rows]})
        
    elif request.method == 'POST':
        data = request.json or {}
        c.execute("""INSERT INTO agenda_masjid (lembaga_id, tipe, tanggal, nama, pemateri) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (lembaga_id, data.get("tipe"), data.get("tanggal"), data.get("nama"), data.get("pemateri", "")))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Agenda ditambahkan"})

# =====================================================================
# PUBLIC VERIFICATION PAGE
# =====================================================================

@app.route('/verify/<kode>')
def public_verification_page(kode):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT nama, jenis, alamat, status, verified_at, kode_verifikasi,
                        no_telepon, email_resmi, website
                 FROM lembaga_amil WHERE kode_verifikasi=?""", (kode,))
    row = c.fetchone()
    if not row:
        conn.close()
        return render_template_string("""
            <html><body style="font-family:sans-serif;padding:40px;text-align:center;">
                <h1>❌ Lembaga Tidak Ditemukan</h1>
                <p>Kode verifikasi <strong>{{ kode }}</strong> tidak terdaftar.</p>
            </body></html>""", kode=kode), 404

    cols = ["nama","jenis","alamat","status","verified_at","kode_verifikasi",
            "no_telepon","email_resmi","website"]
    lembaga = dict(zip(cols, row))
    conn.close()
    icon = "✅" if lembaga["status"] == "verified" else "⚠️"
    color = "#10b981" if lembaga["status"] == "verified" else "#f59e0b"

    return render_template_string("""
        <!DOCTYPE html>
        <html><head>
            <meta charset="UTF-8">
            <title>Verifikasi Lembaga — Raudha</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head><body class="bg-slate-50 min-h-screen p-6">
            <div class="max-w-md mx-auto bg-white rounded-3xl shadow-xl overflow-hidden">
                <div class="bg-gradient-to-r from-emerald-600 to-teal-700 text-white p-6 text-center">
                    <div class="text-6xl">{{ icon }}</div>
                    <h1 class="text-xl font-black mt-2">{{ nama }}</h1>
                    <p class="text-sm opacity-90">{{ jenis }}</p>
                </div>
                <div class="p-6 space-y-3 text-sm">
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Kode Verifikasi</span>
                        <strong>{{ kode_verifikasi }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Status</span>
                        <strong style="color:{{ color }}">{{ status }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Terverifikasi</span>
                        <strong>{{ verified_at or '-' }}</strong>
                    </div>
                    <div class="border-b pb-2">
                        <span class="text-slate-500 block mb-1">Alamat</span>
                        <span>{{ alamat }}</span>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Telepon</span>
                        <strong>{{ no_telepon or '-' }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Email</span>
                        <strong>{{ email_resmi or '-' }}</strong>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-slate-500">Website</span>
                        <strong>{{ website or '-' }}</strong>
                    </div>
                </div>
            </div>
        </body></html>""",
        icon=icon, color=color,
        nama=lembaga["nama"], jenis=lembaga["jenis"], alamat=lembaga["alamat"],
        status=lembaga["status"], verified_at=lembaga["verified_at"],
        kode_verifikasi=lembaga["kode_verifikasi"],
        no_telepon=lembaga["no_telepon"], email_resmi=lembaga["email_resmi"],
        website=lembaga["website"])

# =====================================================================
# ROUTE ARSITEKTUR
# =====================================================================

@app.route('/arsitektur')
def render_halaman_galeri_arsitektur_raudha():
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    html_path = os.path.join(templates_dir, "arsitektur.html")
    if not os.path.exists(html_path):
        return "❌ templates/arsitektur.html tidak ditemukan.", 404
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return render_template_string(f.read())
    except Exception as e:
        return f"❌ Error: {e}", 500

@app.route('/api/input/arsitektur', methods=['POST'])
def api_input_arsitektur():
    data = request.json or {}
    user_id = data.get("user_id") or 99999
    required = ["pemohon","whatsapp","email","fasilitas","alamat"]
    if not all(data.get(k, "").strip() for k in required):
        return jsonify({"status":"error","message":"Field wajib tidak lengkap"}), 400
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS pengajuan_desain (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            pemohon TEXT, whatsapp TEXT, email TEXT, fasilitas TEXT,
            luas_tanah REAL, kapasitas INTEGER, alamat TEXT,
            budget REAL DEFAULT 0, timeline TEXT DEFAULT 'fleksibel',
            catatan TEXT, status TEXT DEFAULT 'baru',
            tgl TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""INSERT INTO pengajuan_desain
            (user_id, pemohon, whatsapp, email, fasilitas, luas_tanah, kapasitas,
             alamat, budget, timeline, catatan) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, data.get("pemohon","").strip(), data.get("whatsapp","").strip(),
             data.get("email","").strip(), data.get("fasilitas",""),
             float(data.get("luas_tanah",0)), int(data.get("kapasitas",0)),
             data.get("alamat","").strip(), float(data.get("budget",0)),
             data.get("timeline","fleksibel"), data.get("catatan","").strip()))
        tulis_audit(c, user_id, "pengajuan_desain", c.lastrowid, "CREATE",
                    alasan="Web Pengajuan Arsitektur")
        conn.commit()
        return jsonify({"status":"success","message":"Pengajuan tersimpan","id":c.lastrowid})
    except Exception as e:
        conn.rollback()
        return jsonify({"status":"error","message":str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# ROUTE MITRA ALAM — WAKAF PRODUKTIF TANAMAN
# =====================================================================

@app.route('/mitra-alam/katalog')
def mitra_alam_katalog():
    """
    Halaman katalog komoditas wakaf pohon.
    Menampilkan 5 komoditas dari database dengan harga dinamis.
    """
    from modul_mitra_alam import get_semua_komoditas
    komoditas = get_semua_komoditas()
    
    # Ambil statistik global untuk hero section
    from modul_mitra_alam import statistik_mitra_alam
    try:
        stats = statistik_mitra_alam()
    except Exception as e:
        logger.warning(f"Gagal load stats: {e}")
        stats = {"total_pohon": 0, "total_muwakif": 0, 
                 "total_lahan": 0, "total_panen_nominal": 0, 
                 "total_bagi_masjid": 0}
    
    # Ambil daftar masjid/pesantren yang punya lahan (untuk filter nanti)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, alamat FROM lembaga_amil 
                 WHERE status='verified' AND aktif=1
                 ORDER BY nama ASC""")
    lembaga_rows = c.fetchall()
    conn.close()
    
    return render_template(
        'mitra_alam/katalog.html',
        komoditas=komoditas,
        stats=stats,
        lembaga_list=lembaga_rows,
    )


@app.route('/mitra-alam')
def mitra_alam_home():
    """Redirect ke katalog (untuk akses langsung /mitra-alam)."""
    from flask import redirect
    return redirect('/mitra-alam/katalog')      

@app.route('/mitra-alam/wakaf')
def mitra_alam_wakaf_form():
    """Form wakaf pohon — pilih jumlah, lokasi, doa."""
    komoditas_id = request.args.get('komoditas', type=int)
    if not komoditas_id:
        from flask import redirect
        return redirect('/mitra-alam/katalog')
    
    from modul_mitra_alam import get_komoditas_by_id
    kom = get_komoditas_by_id(komoditas_id)
    if not kom:
        return "❌ Komoditas tidak ditemukan.", 404
    
    # Ambil daftar lembaga/lahan
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, nama, alamat FROM lembaga_amil 
                 WHERE status='verified' AND aktif=1
                 ORDER BY nama ASC""")
    lembaga_list = c.fetchall()
    conn.close()
    
    return render_template(
        'mitra_alam/wakaf.html',
        kom=kom,
        lembaga_list=lembaga_list,
    ) 

@app.route('/api/mitra-alam/wakaf/submit', methods=['POST'])
def mitra_alam_wakaf_submit():
    """Simpan pengajuan wakaf pohon → buat rencana_pembayaran."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    komoditas_id = int(data.get("komoditas_id", 0))
    jumlah = int(data.get("jumlah", 1))
    lembaga_id = int(data.get("lembaga_id", 0))
    doa = (data.get("doa") or "").strip()
    nama_muwakif = (data.get("nama_muwakif") or "").strip()
    
    if not user_id or not komoditas_id or not lembaga_id:
        return jsonify({"status": "error", "message": "Data tidak lengkap"}), 400
    if jumlah < 1 or jumlah > 100:
        return jsonify({"status": "error", "message": "Jumlah harus 1-100 pohon"}), 400
    
    from modul_mitra_alam import get_komoditas_by_id
    kom = get_komoditas_by_id(komoditas_id)
    if not kom:
        return jsonify({"status": "error", "message": "Komoditas tidak ditemukan"}), 404
    
    total = kom["harga_pohon"] * jumlah
    
    # Cek lembaga valid
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT nama FROM lembaga_amil WHERE id=? AND status='verified'", (lembaga_id,))
    lem_row = c.fetchone()
    if not lem_row:
        conn.close()
        return jsonify({"status": "error", "message": "Lembaga tidak valid"}), 400
    nama_lembaga = lem_row[0]
    
    # Pastikan user ada di users_config, dan isi nama kalau kosong
    c.execute("SELECT nama_lengkap FROM users_config WHERE user_id=?", (user_id,))
    user_row = c.fetchone()
    
    if not user_row:
        # User baru — insert dengan nama
        c.execute("""INSERT INTO users_config 
                     (user_id, tanggal_mulai_haul, baseline_awal, nama_lengkap)
                     VALUES (?, ?, 100000, ?)""",
                  (user_id, date.today().strftime("%Y-%m-%d"), 
                   nama_muwakif or f"User #{user_id}"))
    else:
        # User ada — update nama kalau ada input baru & nama lama kosong/generic
        if nama_muwakif and (not user_row[0] or user_row[0].startswith("User #")):
            c.execute("UPDATE users_config SET nama_lengkap=? WHERE user_id=?",
                      (nama_muwakif, user_id))
    
    try:
        keterangan = f"Wakaf {jumlah} {kom['nama_display']} di {nama_lembaga}"
        if doa:
            keterangan += f" — Doa: {doa}"
        
        c.execute("""INSERT INTO rencana_pembayaran
                     (user_id, jenis_kewajiban, keterangan, nominal,
                      lembaga_id, status, tanggal_rencana, catatan_user, created_at)
                     VALUES (?, 'wakaf_pohon', ?, ?, ?, 'pending', ?, ?, CURRENT_TIMESTAMP)""",
                  (user_id, keterangan, total, lembaga_id,
                   date.today().strftime("%Y-%m-%d"), doa))
        rencana_id = c.lastrowid
        
        # Simpan detail wakaf pohon di tabel pohon_wakaf (status 'pending')
        # nfc_uid di-generate sementara; akan diupdate saat penanaman
        for i in range(jumlah):
            nfc_uid_temp = f"PENDING-{rencana_id}-{i+1}-{int(time.time())}"
            c.execute("""INSERT INTO pohon_wakaf
                         (nfc_uid, komoditas_id, tanggal_tanam,
                          lembaga_id, muwakif_id, rencana_id,
                          harga_pohon, status, catatan, updated_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, 'menunggu_tanam', ?, CURRENT_TIMESTAMP)""",
                      (nfc_uid_temp, komoditas_id,
                       date.today().strftime("%Y-%m-%d"),
                       lembaga_id, user_id, rencana_id,
                       kom["harga_pohon"], doa))
        
        conn.commit()
        logger.info(f"🌱 Wakaf baru: user={user_id}, {jumlah} {kom['nama_display']}, "
                    f"rencana_id={rencana_id}, total=Rp {int(total):,}")
        
        return jsonify({
            "status": "success",
            "message": "Wakaf berhasil diajukan",
            "rencana_id": rencana_id,
            "total": total,
        })
    except Exception as e:
        conn.rollback()
        logger.error(f"Gagal simpan wakaf: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/mitra-alam/pembayaran/<int:rencana_id>')
def mitra_alam_pembayaran(rencana_id):
    """Halaman pembayaran wakaf — instruksi transfer + upload bukti."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT rp.id, rp.user_id, rp.jenis_kewajiban, rp.keterangan,
                        rp.nominal, rp.status, rp.lembaga_id, rp.bukti_transfer_url,
                        rp.created_at, l.nama AS lembaga_nama
                 FROM rencana_pembayaran rp
                 LEFT JOIN lembaga_amil l ON l.id = rp.lembaga_id
                 WHERE rp.id=?""", (rencana_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return "❌ Transaksi tidak ditemukan.", 404
    
    keys = ["id","user_id","jenis_kewajiban","keterangan","nominal",
            "status","lembaga_id","bukti_transfer_url","created_at","lembaga_nama"]
    rencana = dict(zip(keys, row))

    # Tambahkan bypass param ngrok untuk URL bukti
    if rencana.get("bukti_transfer_url"):
        sep = "&" if "?" in rencana["bukti_transfer_url"] else "?"
        rencana["bukti_transfer_url_ngrok"] = (
            rencana["bukti_transfer_url"] 
            + sep + "ngrok-skip-browser-warning=true"
        )
    else:
        rencana["bukti_transfer_url_ngrok"] = None
    
    # Ambil detail pohon yang terkait
    c.execute("""SELECT p.id, p.nfc_uid, k.nama_display, p.status
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 WHERE p.rencana_id=?
                 ORDER BY p.id ASC""", (rencana_id,))
    pohon_rows = c.fetchall()
    pohon_list = [{"id": r[0], "nfc_uid": r[1], "komoditas": r[2], "status": r[3]} 
                  for r in pohon_rows]
    
    # Ambil rekening default lembaga
    c.execute("""SELECT id, metode, nama_bank, nomor_rekening, atas_nama, qr_image_url
                 FROM rekening_lembaga
                 WHERE lembaga_id=? AND aktif=1
                 ORDER BY is_default DESC, id ASC
                 LIMIT 1""", (rencana["lembaga_id"],))
    rek_row = c.fetchone()
    if rek_row:
        rekening = {
            "id": rek_row[0], "metode": rek_row[1], "nama_bank": rek_row[2],
            "nomor_rekening": rek_row[3], "atas_nama": rek_row[4], 
            "qr_image_url": rek_row[5],
        }
    else:
        rekening = None
    
    conn.close()
    
    return render_template(
        'mitra_alam/pembayaran.html',
        rencana=rencana,
        pohon_list=pohon_list,
        rekening=rekening,
    )


@app.route('/api/mitra-alam/pembayaran/<int:rencana_id>/upload', methods=['POST'])
def mitra_alam_upload_bukti(rencana_id):
    """Upload bukti transfer wakaf pohon."""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "File tidak ditemukan"}), 400
    
    file = request.files['file']
    user_id = request.form.get("user_id", "").strip()
    
    if not user_id.isdigit():
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    user_id = int(user_id)
    
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", 
                        "message": "Format tidak didukung (jpg/png/pdf)"}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell(); file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"status": "error", 
                        "message": "File terlalu besar (maks 5 MB)"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id, status FROM rencana_pembayaran WHERE id=?", 
                  (rencana_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", 
                            "message": "Transaksi tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403
        if row[1] != 'pending':
            return jsonify({"status": "error", 
                            "message": f"Status sudah {row[1]}"}), 400
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bukti_wakaf_{rencana_id}_{user_id}_{timestamp}.{ext}"
        filepath = os.path.join(UPLOAD_DOKUMEN, filename)
        file.save(filepath)
        
        url = f"/uploads/dokumen_lembaga/{filename}"
        
        c.execute("""UPDATE rencana_pembayaran SET
                        status='dibayar',
                        bukti_transfer_url=?,
                        bukti_uploaded_at=CURRENT_TIMESTAMP,
                        tanggal_bayar=?,
                        updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""",
                  (url, date.today().strftime("%Y-%m-%d"), rencana_id))
        
        logger.info(f"🌱 Bukti wakaf uploaded: rencana_id={rencana_id}")
        conn.commit()
        return jsonify({"status": "success", "message": "Bukti terupload", "url": url})
    except Exception as e:
        conn.rollback()
        logger.error(f"Upload error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# API — VERIFIKASI PEMBAYARAN WAKAF (ADMIN)
# =====================================================================

@app.route('/api/mitra-alam/pembayaran/list/<int:lembaga_id>')
@app.route('/api/mitra-alam/pembayaran/list/all')
def mitra_alam_pembayaran_list(lembaga_id=None):
    """
    Daftar pembayaran wakaf:
    - lembaga_id = angka → filter per lembaga (admin lembaga)
    - lembaga_id = 'all' → semua lembaga (super admin)
    """
    user_id = int(request.args.get("user_id", 0))
    info = get_user_role(user_id)
    is_super = info.get("role") == "super_admin"
    
    # Route /all hanya untuk super admin
    if lembaga_id is None:  # 'all'
        if not is_super:
            return jsonify({"status": "error", "message": "Akses ditolak"}), 403
        lembaga_id = None  # all
    else:
        # Filter lembaga_id → cek akses
        ok, err, info2 = _cek_akses_lembaga(user_id, lembaga_id)
        if not ok:
            return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    # Bangun query dinamis
    if lembaga_id is None:
        # Super admin: semua lembaga
        c.execute("""SELECT rp.id, rp.user_id, rp.keterangan, rp.nominal,
                            rp.status, rp.bukti_transfer_url, rp.created_at,
                            rp.verified_at, rp.catatan_admin,
                            uc.nama_lengkap, uc.no_whatsapp,
                            l.nama AS lembaga_nama
                     FROM rencana_pembayaran rp
                     LEFT JOIN users_config uc ON uc.user_id = rp.user_id
                     LEFT JOIN lembaga_amil l ON l.id = rp.lembaga_id
                     WHERE rp.jenis_kewajiban = 'wakaf_pohon'
                       AND rp.status IN ('dibayar', 'diverifikasi')
                     ORDER BY 
                       CASE rp.status WHEN 'dibayar' THEN 0 ELSE 1 END,
                       rp.created_at DESC
                     LIMIT 200""")
    else:
        # Admin lembaga: filter per lembaga
        c.execute("""SELECT rp.id, rp.user_id, rp.keterangan, rp.nominal,
                            rp.status, rp.bukti_transfer_url, rp.created_at,
                            rp.verified_at, rp.catatan_admin,
                            uc.nama_lengkap, uc.no_whatsapp,
                            l.nama AS lembaga_nama
                     FROM rencana_pembayaran rp
                     LEFT JOIN users_config uc ON uc.user_id = rp.user_id
                     LEFT JOIN lembaga_amil l ON l.id = rp.lembaga_id
                     WHERE rp.lembaga_id = ?
                       AND rp.jenis_kewajiban = 'wakaf_pohon'
                       AND rp.status IN ('dibayar', 'diverifikasi')
                     ORDER BY 
                       CASE rp.status WHEN 'dibayar' THEN 0 ELSE 1 END,
                       rp.created_at DESC
                     LIMIT 100""", (lembaga_id,))
    
    rows = c.fetchall()
    conn.close()
    
    keys = ["id","user_id","keterangan","nominal","status",
            "bukti_transfer_url","created_at","verified_at","catatan_admin",
            "nama_lengkap","no_whatsapp","lembaga_nama"]
    pembayaran = [dict(zip(keys, r)) for r in rows]
    
    # Tambah URL bypass ngrok
    for p in pembayaran:
        if p.get("bukti_transfer_url"):
            sep = "&" if "?" in p["bukti_transfer_url"] else "?"
            p["bukti_url_ngrok"] = p["bukti_transfer_url"] + sep + "ngrok-skip-browser-warning=true"
        else:
            p["bukti_url_ngrok"] = None
    
    # Cek mode verifikasi global
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT value FROM program_config WHERE key='wakaf_verification_mode'")
    row_mode = c.fetchone()
    verification_mode = row_mode[0] if row_mode else 'super_only'
    conn.close()
    
    return jsonify({
        "status": "success",
        "pembayaran": pembayaran,
        "is_super_admin": is_super,
        "lembaga_id": lembaga_id,
        "verification_mode": verification_mode,
    })

@app.route('/api/mitra-alam/pembayaran/<int:rencana_id>/verifikasi', methods=['POST'])
def mitra_alam_verifikasi_pembayaran(rencana_id):
    """Verifikasi pembayaran wakaf — update status & aktifkan pohon."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    catatan = (data.get("catatan_admin") or "").strip()
    
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        # Cek transaksi ada & statusnya 'dibayar'
        c.execute("""SELECT user_id, lembaga_id, status, nominal 
                     FROM rencana_pembayaran 
                     WHERE id=? AND jenis_kewajiban='wakaf_pohon'""", (rencana_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Transaksi tidak ditemukan"}), 404
        
        pembuat_id, lembaga_id, status, nominal = row
        
                # === CEK AKSES (mode-aware) ===
        info = get_user_role(user_id)
        is_super = info.get("role") == "super_admin"
        
        # Cek mode verifikasi global
        c.execute("SELECT value FROM program_config WHERE key='wakaf_verification_mode'")
        row_mode = c.fetchone()
        verification_mode = row_mode[0] if row_mode else 'super_only'
        
        # MODE super_only: hanya Super Admin yang bisa verifikasi
        if verification_mode == 'super_only' and not is_super:
            return jsonify({
                "status": "error",
                "message": "Verifikasi saat ini hanya oleh Super Admin.\n\n"
                           "Admin lembaga akan diaktifkan setelah onboarding selesai."
            }), 403
        
        # MODE multi_admin: admin lembaga juga bisa verifikasi (lembaga sendiri)
        if not is_super:
            ok, err, info2 = _cek_akses_lembaga(user_id, lembaga_id)
            if not ok:
                return jsonify({"status": "error", "message": err}), 403
        
        # Guard self-verify: berlaku untuk non-super-admin saja
        if not is_super and pembuat_id == user_id:
            return jsonify({"status": "error", 
                            "message": "Tidak bisa verifikasi pembayaran sendiri. Minta admin lain."}), 403
        
        # Log extra kalau super admin verifikasi sendiri
        if is_super and pembuat_id == user_id:
            logger.warning(f"⚠️ Super Admin {user_id} verifikasi transaksi sendiri #{rencana_id}")  
        if status != 'dibayar':
            return jsonify({"status": "error", 
                            "message": f"Status saat ini: {status}. Hanya 'dibayar' yang bisa diverifikasi"}), 400
        
        # Update transaksi
        c.execute("""UPDATE rencana_pembayaran SET
                        status='diverifikasi',
                        verified_by_admin=?,
                        verified_at=CURRENT_TIMESTAMP,
                        catatan_admin=?,
                        updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""", (user_id, catatan, rencana_id))
        
        # Aktifkan pohon terkait (status: menunggu_tanam → aktif)
        c.execute("""UPDATE pohon_wakaf SET
                        status='aktif',
                        tanggal_tanam=?,
                        updated_at=CURRENT_TIMESTAMP
                     WHERE rencana_id=? AND status='menunggu_tanam'""",
                  (date.today().strftime("%Y-%m-%d"), rencana_id))
        jumlah_pohon_aktif = c.rowcount
        
        log_sensitive(c, user_id, info.get("role", "admin_lembaga"),
                      "verifikasi_wakaf", target_tabel="rencana_pembayaran",
                      target_id=rencana_id,
                      detail=f"lembaga={lembaga_id}, nominal={nominal}, pohon={jumlah_pohon_aktif}",
                      request_obj=request)
        
        conn.commit()
        logger.info(f"✅ Wakaf #{rencana_id} diverifikasi oleh admin {user_id}, "
                    f"{jumlah_pohon_aktif} pohon diaktifkan")
        
        return jsonify({
            "status": "success",
            "message": f"Pembayaran diverifikasi. {jumlah_pohon_aktif} pohon diaktifkan.",
            "jumlah_pohon_aktif": jumlah_pohon_aktif,
        })
    except Exception as e:
        conn.rollback()
        logger.error(f"Verifikasi error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/mitra-alam/admin/verifikasi')
def mitra_alam_admin_verifikasi():
    """Halaman admin verifikasi pembayaran wakaf."""
    return render_template('mitra_alam/admin_verifikasi.html')       

@app.route('/api/mitra-alam/admin/lembaga-saya/<int:user_id>')
def mitra_alam_lembaga_admin(user_id):
    """Ambil lembaga_id yang dikelola user (untuk admin verifikasi wakaf)."""
    info = get_user_role(user_id)
    
    # Super admin: lihat SEMUA transaksi (semua lembaga)
    if info.get("role") == "super_admin":
        return jsonify({
            "status": "success",
            "lembaga_id": None,           # None = semua lembaga
            "is_super_admin": True,
            "mode": "super_admin_all",    # mode baru
        })
    
    # Admin lembaga: pakai lembaga_id dari users_config
    lembaga_id = info.get("lembaga_id")
    if not lembaga_id:
        return jsonify({"status": "error", 
                        "message": "Anda bukan admin lembaga"}), 403
    
    return jsonify({
        "status": "success",
        "lembaga_id": lembaga_id,
        "is_super_admin": False,
    })

# =====================================================================
# HALAMAN PUBLIK POHON (Tap NFC)
# =====================================================================

@app.route('/pohon/<nfc_uid>')
def halaman_pohon_publik(nfc_uid):
    """
    Halaman publik pohon — dibuka saat NFC di-tap.
    Menampilkan detail pohon, riwayat perawatan, muwakif, dan estimasi panen.
    """
    from modul_mitra_alam import get_pohon_by_uid, get_log_pohon, get_panen_pohon
    
    pohon = get_pohon_by_uid(nfc_uid)
    if not pohon:
        return render_template_string("""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"><title>Pohon Tidak Ditemukan</title>
            <script src="https://cdn.tailwindcss.com"></script></head>
            <body class="bg-slate-50 min-h-screen flex items-center justify-center p-6">
                <div class="max-w-md mx-auto bg-white rounded-3xl shadow-xl overflow-hidden">
                    <div class="bg-gradient-to-r from-rose-600 to-rose-700 text-white p-8 text-center">
                        <div class="text-6xl mb-3">🌱</div>
                        <h1 class="text-xl font-black">Pohon Tidak Ditemukan</h1>
                        <p class="text-sm opacity-90 mt-1">UID: {{ uid }}</p>
                    </div>
                    <div class="p-6 text-center text-sm text-slate-600">
                        <p>Pohon dengan UID ini belum terdaftar di sistem Raudha.</p>
                        <p class="mt-2 text-xs text-slate-400">Pastikan tag NFC tertempel dengan benar atau hubungi petugas.</p>
                    </div>
                </div>
            </body></html>
        """, uid=nfc_uid), 404
    
    # Ambil log & panen
    logs = get_log_pohon(pohon["id"], limit=20)
    panen = get_panen_pohon(pohon["id"])
    
    # Ambil komoditas detail
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT kode, nama_display, output, siklus_panen, 
                        nilai_ekonomi, fungsi_ekologis, deskripsi
                 FROM komoditas_wakaf WHERE id=?""", (pohon["komoditas_id"],))
    kom_row = c.fetchone()
    kom = None
    if kom_row:
        kom = {
            "kode": kom_row[0], "nama_display": kom_row[1],
            "output": kom_row[2], "siklus_panen": kom_row[3],
            "nilai_ekonomi": kom_row[4], "fungsi_ekologis": kom_row[5],
            "deskripsi": kom_row[6],
        }
    
    # Ambil info lembaga (lokasi tanam)
    c.execute("SELECT nama, alamat FROM lembaga_amil WHERE id=?", (pohon["lembaga_id"],))
    lem_row = c.fetchone()
    lembaga = {"nama": lem_row[0], "alamat": lem_row[1]} if lem_row else None
    
    # Hitung umur pohon (hari)
    umur_hari = None
    if pohon.get("tanggal_tanam"):
        try:
            tgl_tanam = datetime.strptime(pohon["tanggal_tanam"], "%Y-%m-%d").date()
            umur_hari = (date.today() - tgl_tanam).days
        except (ValueError, TypeError):
            pass
    
    conn.close()
    
    # Tambah bypass ngrok untuk foto
    for log in logs:
        if log.get("foto_url"):
            sep = "&" if "?" in log["foto_url"] else "?"
            log["foto_url_ngrok"] = log["foto_url"] + sep + "ngrok-skip-browser-warning=true"
        else:
            log["foto_url_ngrok"] = None
    
    return render_template(
        'mitra_alam/pohon_publik.html',
        pohon=pohon,
        kom=kom,
        lembaga=lembaga,
        logs=logs,
        panen=panen,
        umur_hari=umur_hari,
    )

# =====================================================================
# DASHBOARD POHON SAYA
# =====================================================================

@app.route('/mitra-alam/pohon-saya')
def mitra_alam_pohon_saya():
    """Dashboard 'Pohon Saya' — semua pohon yang diwakafkan user."""
    return render_template('mitra_alam/pohon_saya.html')


@app.route('/api/mitra-alam/pohon-saya/<int:user_id>')
def api_mitra_alam_pohon_saya(user_id):
    """List semua pohon milik user + statistik."""
    from modul_mitra_alam import get_pohon_user
    
    pohon_list = get_pohon_user(user_id)
    
    # Pastikan list (bukan None)
    if pohon_list is None:
        pohon_list = []
    
    # Hitung statistik
    total_pohon = len(pohon_list)
    total_aktif = sum(1 for p in pohon_list if p.get("status") == "aktif")
    total_nilai = 0
    
    # Ambil detail komoditas untuk hitung total nilai
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for p in pohon_list:
        c.execute(
            """SELECT k.harga_pohon, k.output, k.siklus_panen 
               FROM komoditas_wakaf k
               JOIN pohon_wakaf w ON w.komoditas_id = k.id
               WHERE w.id=?""",
            (p["id"],)
        )
        row = c.fetchone()
        if row:
            total_nilai += row[0] or 0
            p["harga_pohon"] = row[0]
            p["output"] = row[1]
            p["siklus_panen"] = row[2]
    
    # Total panen
    c.execute(
        """SELECT COALESCE(SUM(pp.pembagian_masjid), 0),
                  COALESCE(SUM(pp.hasil_nominal), 0),
                  COUNT(*)
           FROM pohon_panen pp
           JOIN pohon_wakaf pw ON pw.id = pp.pohon_id
           WHERE pw.muwakif_id=?""",
        (user_id,)
    )
    row_panen = c.fetchone()
    conn.close()
    
    return jsonify({
        "status": "success",
        "pohon": pohon_list,
        "stats": {
            "total_pohon": total_pohon,
            "total_aktif": total_aktif,
            "total_nilai": total_nilai,
            "total_panen_nominal": row_panen[1] if row_panen else 0,
            "total_panen_count": row_panen[2] if row_panen else 0,
        },
    })


# =====================================================================
# API — RENCANA PEMBAYARAN (Batch 5a)
# =====================================================================

def bisa_verifikasi(user_id, rencana_id):
    """Cek apakah user bisa verifikasi pembayaran ini."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT rp.user_id AS pembuat_id, rp.lembaga_id,
                            uc.role AS verif_role, uc.lembaga_id AS verif_lembaga,
                            uc.status AS verif_status
                     FROM rencana_pembayaran rp
                     JOIN users_config uc ON uc.user_id = ?
                     WHERE rp.id = ?""", (user_id, rencana_id))
        row = c.fetchone()
        if not row:
            return False, "Pembayaran tidak ditemukan"
        
        pembuat_id, lembaga_id, verif_role, verif_lembaga, verif_status = row
        
        # Super admin: boleh verifikasi semua (termasuk sendiri — fase awal)
        if verif_role == 'super_admin' and verif_status == 'active':
            # ✅ Boleh self-verify (konsisten dengan wakaf, fase awal)
            # Log untuk audit kalau self-verify
            if pembuat_id == user_id:
                logger.warning(f"⚠️ Super Admin {user_id} verifikasi zakat sendiri #{rencana_id}")
            return True, None
        
        if verif_role == 'admin_lembaga' and verif_status == 'active':
            if verif_lembaga != lembaga_id:
                return False, "Anda bukan admin lembaga tujuan pembayaran"
            if pembuat_id == user_id:
                return False, "Admin tidak bisa verifikasi pembayaran miliknya sendiri. Minta admin lain."
            return True, None
        
        return False, "Hanya admin lembaga atau super admin yang bisa verifikasi"
    finally:
        conn.close()


@app.route('/api/rencana-pembayaran', methods=['POST'])
def buat_rencana_pembayaran():
    """User membuat rencana pembayaran baru."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    jenis = data.get("jenis_kewajiban", "").strip()
    nominal = float(data.get("nominal", 0))
    lembaga_id = int(data.get("lembaga_id", 0))
    rekening_id = int(data.get("rekening_id", 0))
    keterangan = data.get("keterangan", "").strip()
    catatan_user = data.get("catatan_user", "").strip()
    
    if not jenis or nominal <= 0 or not lembaga_id:
        return jsonify({"status": "error", "message": "Field wajib belum lengkap"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT nama, status FROM lembaga_amil WHERE id=?", (lembaga_id,))
        lem_row = c.fetchone()
        if not lem_row or lem_row[1] != 'verified':
            return jsonify({"status": "error", "message": "Lembaga tidak terverifikasi"}), 400
        
        c.execute("SELECT nama_bank, nomor_rekening, atas_nama FROM rekening_lembaga WHERE id=? AND lembaga_id=? AND aktif=1",
                  (rekening_id, lembaga_id))
        rek_row = c.fetchone()
        if not rek_row:
            return jsonify({"status": "error", "message": "Rekening tidak valid atau nonaktif"}), 400
        
        rek_info = f"{rek_row[0]} - {rek_row[1]} a.n. {rek_row[2]}"
        info = get_user_role(user_id)
        pembuat_role = info.get("role", "user")
        
        c.execute("""INSERT INTO rencana_pembayaran
                     (user_id, jenis_kewajiban, keterangan, nominal,
                      lembaga_id, rekening_id, rekening_info_manual,
                      status, tanggal_rencana, catatan_user, created_at)
                     VALUES (?,?,?,?,?,?,?, 'pending', ?, ?, CURRENT_TIMESTAMP)""",
                  (user_id, jenis, keterangan, nominal,
                   lembaga_id, rekening_id, rek_info,
                   date.today().strftime("%Y-%m-%d"), catatan_user))
        rencana_id = c.lastrowid
        
        log_sensitive(c, user_id, pembuat_role, "buat_rencana_pembayaran",
                      target_tabel="rencana_pembayaran", target_id=rencana_id,
                      detail=f"jenis={jenis}, nominal={nominal}, lembaga={lembaga_id}",
                      request_obj=request)
        conn.commit()
        return jsonify({
            "status": "success",
            "message": "Rencana pembayaran dibuat",
            "rencana_id": rencana_id,
            "rekening_info": rek_info,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/rencana-pembayaran/<int:rencana_id>/upload-bukti', methods=['POST'])
def upload_bukti_pembayaran(rencana_id):
    """User upload bukti transfer untuk rencana pembayaran."""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "File tidak ditemukan"}), 400
    
    file = request.files['file']
    user_id = request.form.get("user_id", "").strip()
    
    if not user_id.isdigit():
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    user_id = int(user_id)
    
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", "message": "Format tidak didukung"}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"status": "error", "message": "File terlalu besar (maks 5 MB)"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id, status FROM rencana_pembayaran WHERE id=?", (rencana_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Rencana tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403
        if row[1] not in ('pending',):
            return jsonify({"status": "error", "message": f"Status sudah {row[1]}, tidak bisa upload ulang"}), 400
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bukti_rencana_{rencana_id}_{user_id}_{timestamp}.{ext}"
        filepath = os.path.join(UPLOAD_DOKUMEN, filename)
        file.save(filepath)
        
        url = f"/uploads/dokumen_lembaga/{filename}"
        
        c.execute("""UPDATE rencana_pembayaran SET
                        status='dibayar',
                        bukti_transfer_url=?,
                        bukti_uploaded_at=CURRENT_TIMESTAMP,
                        tanggal_bayar=?
                     WHERE id=?""",
                  (url, date.today().strftime("%Y-%m-%d"), rencana_id))
        log_sensitive(c, user_id, get_user_role(user_id).get("role", "user"),
                      "upload_bukti", target_tabel="rencana_pembayaran",
                      target_id=rencana_id, detail=f"file={filename}", request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Bukti terupload", "url": url})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/rencana-pembayaran/<int:rencana_id>/verifikasi', methods=['POST'])
def verifikasi_pembayaran(rencana_id):
    """Admin lembaga atau super admin verifikasi pembayaran."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    ok, alasan = bisa_verifikasi(user_id, rencana_id)
    if not ok:
        return jsonify({"status": "error", "message": alasan}), 403
    
    catatan_admin = data.get("catatan_admin", "").strip()
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT status FROM rencana_pembayaran WHERE id=?", (rencana_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Rencana tidak ditemukan"}), 404
        if row[0] not in ('dibayar',):
            return jsonify({"status": "error", "message": f"Status saat ini: {row[0]}, hanya 'dibayar' yang bisa diverifikasi"}), 400
        
        c.execute("""UPDATE rencana_pembayaran SET
                        status='diverifikasi',
                        verified_by_admin=?,
                        verified_at=CURRENT_TIMESTAMP,
                        catatan_admin=?
                     WHERE id=?""",
                  (user_id, catatan_admin, rencana_id))
        log_sensitive(c, user_id, get_user_role(user_id).get("role", "user"),
                      "verifikasi_pembayaran", target_tabel="rencana_pembayaran",
                      target_id=rencana_id, detail=f"catatan={catatan_admin}",
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Pembayaran diverifikasi"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/rencana-pembayaran/<int:user_id>', methods=['GET'])
def list_rencana_user(user_id):
    """List semua rencana pembayaran milik user."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT rp.id, rp.jenis_kewajiban, rp.keterangan, rp.nominal,
                        rp.status, rp.bukti_transfer_url, rp.created_at, rp.tanggal_bayar,
                        l.nama AS lembaga_nama, rp.rekening_info_manual,
                        rp.verified_at, rp.catatan_admin
                 FROM rencana_pembayaran rp
                 LEFT JOIN lembaga_amil l ON l.id = rp.lembaga_id
                 WHERE rp.user_id=?
                 ORDER BY rp.created_at DESC LIMIT 100""", (user_id,))
    rows = c.fetchall()
    conn.close()
    keys = ["id","jenis_kewajiban","keterangan","nominal","status",
            "bukti_transfer_url","created_at","tanggal_bayar",
            "lembaga_nama","rekening_info_manual","verified_at","catatan_admin"]
    return jsonify({"status": "success", "rencana": [dict(zip(keys, r)) for r in rows]})


@app.route('/api/lembaga/<int:lembaga_id>/pembayaran-masuk', methods=['GET'])
def list_pembayaran_lembaga(lembaga_id):
    """Admin lembaga lihat pembayaran masuk (status dibayar/diverifikasi)."""
    user_id = int(request.args.get("user_id", 0))
    ok, err, info = _cek_akses_lembaga(user_id, lembaga_id)
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT rp.id, rp.user_id, rp.jenis_kewajiban, rp.nominal,
                        rp.status, rp.bukti_transfer_url, rp.tanggal_bayar,
                        uc.nama_lengkap, uc.no_whatsapp
                 FROM rencana_pembayaran rp
                 LEFT JOIN users_config uc ON uc.user_id = rp.user_id
                 WHERE rp.lembaga_id=? AND rp.status IN ('dibayar','diverifikasi')
                 ORDER BY rp.created_at DESC LIMIT 100""", (lembaga_id,))
    rows = c.fetchall()
    conn.close()
    keys = ["id","user_id","jenis_kewajiban","nominal","status",
            "bukti_transfer_url","tanggal_bayar","nama_lengkap","no_whatsapp"]
    return jsonify({"status": "success", "pembayaran": [dict(zip(keys, r)) for r in rows]})


@app.route('/api/check-role/<int:user_id>', methods=['GET'])
def check_role(user_id):
    """Cek role user — publik, hanya mengembalikan role & status."""
    info = get_user_role(user_id)
    return jsonify({
        "status": "success",
        "role": info.get("role", "user"),
        "is_super_admin": info.get("role") == "super_admin",
        "is_admin_lembaga": info.get("role") == "admin_lembaga",
        "lembaga_id": info.get("lembaga_id"),
    })

# =====================================================================
# API — KELOLA USER (Khusus Super Admin)
# =====================================================================

@app.route('/api/admin/users', methods=['GET'])
@require_telegram_auth
def admin_list_users():
    """List semua user (khusus super admin)."""
    user_id = int(request.args.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT uc.user_id, uc.nama_lengkap, uc.no_whatsapp,
                        uc.role, uc.status, uc.lembaga_id,
                        l.nama AS lembaga_nama,
                        uc.created_at, uc.verified_at
                 FROM users_config uc
                 LEFT JOIN lembaga_amil l ON l.id = uc.lembaga_id
                 ORDER BY uc.created_at DESC""")
    rows = c.fetchall()
    conn.close()
    keys = ["user_id","nama_lengkap","no_whatsapp","role","status",
            "lembaga_id","lembaga_nama","created_at","verified_at"]
    return jsonify({"status": "success", "users": [dict(zip(keys, r)) for r in rows]})


@app.route('/api/admin/users/<int:target_user_id>/role', methods=['POST'])
def admin_ubah_role_user(target_user_id):
    """Ubah role user (khusus super admin)."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    role_baru = data.get("role", "").strip()
    if role_baru not in ("user", "admin_lembaga", "super_admin"):
        return jsonify({"status": "error", "message": "Role tidak valid"}), 400
    
    lembaga_id = data.get("lembaga_id")
    if role_baru == "admin_lembaga" and not lembaga_id:
        return jsonify({"status": "error", "message": "Admin lembaga butuh lembaga_id"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT 1 FROM users_config WHERE user_id=?", (target_user_id,))
        if not c.fetchone():
            return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404
        
        c.execute("""UPDATE users_config SET
                        role=?, lembaga_id=?, status='active'
                     WHERE user_id=?""",
                  (role_baru, lembaga_id if role_baru == "admin_lembaga" else None, target_user_id))
        log_sensitive(c, user_id, "super_admin", "ubah_role_user",
                      target_tabel="users_config", target_id=target_user_id,
                      detail=f"role_baru={role_baru}, lembaga_id={lembaga_id}",
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "Role diubah"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/admin/users/<int:target_user_id>/nonaktifkan', methods=['POST'])
def admin_nonaktifkan_user(target_user_id):
    """Nonaktifkan user (khusus super admin)."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    ok, err = require_role(user_id, ["super_admin"])
    if not ok:
        return jsonify({"status": "error", "message": err}), 403
    
    if target_user_id == user_id:
        return jsonify({"status": "error", "message": "Tidak bisa menonaktifkan diri sendiri"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("UPDATE users_config SET status='suspended' WHERE user_id=?", (target_user_id,))
        log_sensitive(c, user_id, "super_admin", "nonaktifkan_user",
                      target_tabel="users_config", target_id=target_user_id,
                      request_obj=request)
        conn.commit()
        return jsonify({"status": "success", "message": "User dinonaktifkan"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

# =====================================================================
# API — PUBLIC STATS (Tanpa Login)
# =====================================================================

@app.route('/api/public/stats', methods=['GET'])
def public_stats():
    """Statistik publik — transparansi Raudha."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    # Total pembayaran diverifikasi
    c.execute("""SELECT COUNT(*), COALESCE(SUM(nominal), 0) 
                 FROM rencana_pembayaran WHERE status='diverifikasi'""")
    total_transaksi, total_zakat = c.fetchone()
    
    # Total pembayaran yang masih pending
    c.execute("""SELECT COUNT(*), COALESCE(SUM(nominal), 0) 
                 FROM rencana_pembayaran WHERE status='dibayar'""")
    pending_transaksi, pending_nominal = c.fetchone()
    
    # Jumlah muzakki unik (user yang pernah bayar)
    c.execute("""SELECT COUNT(DISTINCT user_id) 
                 FROM rencana_pembayaran WHERE status='diverifikasi'""")
    total_muzakki = c.fetchone()[0]
    
    # Jumlah lembaga terverifikasi
    c.execute("SELECT COUNT(*) FROM lembaga_amil WHERE status='verified'")
    total_lembaga = c.fetchone()[0]
    
    # Grafik per bulan (12 bulan terakhir)
    c.execute("""SELECT strftime('%Y-%m', verified_at) AS bulan,
                        COUNT(*), SUM(nominal)
                 FROM rencana_pembayaran
                 WHERE status='diverifikasi' AND verified_at IS NOT NULL
                   AND verified_at >= date('now', '-12 months')
                 GROUP BY bulan ORDER BY bulan ASC""")
    grafik_rows = c.fetchall()
    grafik = [{"bulan": r[0], "transaksi": r[1], "nominal": r[2] or 0} for r in grafik_rows]
    
    # Daftar lembaga terverifikasi
    c.execute("""SELECT id, nama, jenis, alamat, kode_verifikasi, verified_at
                 FROM lembaga_amil WHERE status='verified' AND is_public=1
                 ORDER BY nama ASC""")
    lembaga_rows = c.fetchall()
    lembaga_list = [{"id": r[0], "nama": r[1], "jenis": r[2], "alamat": r[3], 
                     "kode_verifikasi": r[4], "verified_at": r[5]} for r in lembaga_rows]
    
    conn.close()
    return jsonify({
        "status": "success",
        "data": {
            "total_transaksi": total_transaksi,
            "total_zakat": total_zakat,
            "pending_transaksi": pending_transaksi,
            "pending_nominal": pending_nominal,
            "total_muzakki": total_muzakki,
            "total_lembaga": total_lembaga,
            "grafik": grafik,
            "lembaga": lembaga_list,
        }
    })


@app.route('/stats')
def public_stats_page():
    """Halaman publik statistik Raudha."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    c.execute("""SELECT COUNT(*), COALESCE(SUM(nominal), 0) 
                 FROM rencana_pembayaran WHERE status='diverifikasi'""")
    total_transaksi, total_zakat = c.fetchone()
    
    c.execute("""SELECT COUNT(DISTINCT user_id) 
                 FROM rencana_pembayaran WHERE status='diverifikasi'""")
    total_muzakki = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM lembaga_amil WHERE status='verified'")
    total_lembaga = c.fetchone()[0]
    
    c.execute("""SELECT strftime('%Y-%m', verified_at), COUNT(*), SUM(nominal)
                 FROM rencana_pembayaran
                 WHERE status='diverifikasi' AND verified_at IS NOT NULL
                   AND verified_at >= date('now', '-12 months')
                 GROUP BY strftime('%Y-%m', verified_at)
                 ORDER BY strftime('%Y-%m', verified_at)""")
    grafik_rows = c.fetchall()
    
    c.execute("""SELECT id, nama, jenis, alamat, kode_verifikasi, verified_at
                 FROM lembaga_amil WHERE status='verified' AND is_public=1
                 ORDER BY nama ASC""")
    lembaga_rows = c.fetchall()
    
    conn.close()
    
    # Format data untuk template
    grafik_labels = [r[0] for r in grafik_rows]
    grafik_data = [int(r[2] or 0) for r in grafik_rows]
    
    html = """
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Transparansi Zakat — Raudha</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 min-h-screen">

<!-- HEADER -->
<div class="bg-gradient-to-r from-emerald-800 to-teal-900 text-white p-6 shadow-lg">
  <div class="max-w-4xl mx-auto text-center">
    <div class="text-4xl mb-2">🕌</div>
    <h1 class="text-2xl font-black">Transparansi Zakat Raudha</h1>
    <p class="text-sm text-emerald-200 mt-1">Laporan publik penyaluran zakat, infaq, sedekah</p>
  </div>
</div>

<!-- STATS -->
<div class="max-w-4xl mx-auto p-4 -mt-6">
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div class="bg-white rounded-2xl p-4 shadow-lg border border-slate-100 text-center">
      <p class="text-[10px] text-slate-400 font-bold uppercase">Total Zakat</p>
      <p class="text-xl font-black text-emerald-700 mt-1">Rp """ + f"{int(total_zakat):,}".replace(",", ".") + """</p>
    </div>
    <div class="bg-white rounded-2xl p-4 shadow-lg border border-slate-100 text-center">
      <p class="text-[10px] text-slate-400 font-bold uppercase">Transaksi</p>
      <p class="text-xl font-black text-emerald-700 mt-1">""" + str(total_transaksi) + """</p>
    </div>
    <div class="bg-white rounded-2xl p-4 shadow-lg border border-slate-100 text-center">
      <p class="text-[10px] text-slate-400 font-bold uppercase">Muzakki</p>
      <p class="text-xl font-black text-emerald-700 mt-1">""" + str(total_muzakki) + """</p>
    </div>
    <div class="bg-white rounded-2xl p-4 shadow-lg border border-slate-100 text-center">
      <p class="text-[10px] text-slate-400 font-bold uppercase">Lembaga</p>
      <p class="text-xl font-black text-emerald-700 mt-1">""" + str(total_lembaga) + """</p>
    </div>
  </div>
</div>

<!-- GRAFIK -->
<div class="max-w-4xl mx-auto p-4">
  <div class="bg-white rounded-2xl p-5 shadow-lg border border-slate-100">
    <h2 class="text-lg font-black text-slate-800 mb-4">📊 Grafik Penyaluran 12 Bulan Terakhir</h2>
    <canvas id="grafikZakat" height="80"></canvas>
  </div>
</div>

<!-- LEMBAGA -->
<div class="max-w-4xl mx-auto p-4">
  <div class="bg-white rounded-2xl p-5 shadow-lg border border-slate-100">
    <h2 class="text-lg font-black text-slate-800 mb-4">🏛️ Lembaga Amil Terverifikasi</h2>
    <div class="space-y-2">
      """ + "".join([
        f'''<div class="bg-emerald-50 border border-emerald-200 rounded-xl p-3">
          <div class="flex justify-between items-start">
            <div>
              <p class="font-black text-slate-800">{r[1]}</p>
              <p class="text-[10px] text-slate-500">{r[2]} • {r[3] or "-"}</p>
            </div>
            <span class="bg-emerald-600 text-white text-[9px] font-bold px-2 py-1 rounded-full">✓ TERVERIFIKASI</span>
          </div>
          <p class="text-[10px] text-emerald-700 mt-1 font-mono">Kode: {r[4]}</p>
        </div>''' for r in lembaga_rows
      ]) + """
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="max-w-4xl mx-auto p-4 pb-8 text-center">
  <p class="text-xs text-slate-400">
    Data terakhir diperbarui: """ + time.strftime("%Y-%m-%d %H:%M:%S WIB") + """<br>
    © 2026 Raudha Spiritual Accountant — Laporan Publik
  </p>
</div>

<script>
const ctx = document.getElementById('grafikZakat').getContext('2d');
new Chart(ctx, {
  type: 'bar',
  data: {
    labels: """ + str(grafik_labels) + """,
    datasets: [{
      label: 'Zakat Tersalurkan (Rp)',
      data: """ + str(grafik_data) + """,
      backgroundColor: 'rgba(16, 185, 129, 0.7)',
      borderColor: 'rgba(16, 185, 129, 1)',
      borderWidth: 2,
      borderRadius: 8,
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => 'Rp ' + ctx.parsed.y.toLocaleString('id-ID')
        }
      }
    },
    scales: {
      y: {
        ticks: {
          callback: (v) => 'Rp ' + (v/1000000).toFixed(0) + ' jt'
        }
      }
    }
  }
});
</script>
</body>
</html>
"""
    return html       

# =====================================================================
# API — EXPORT PDF LAPORAN ZAKAT (Batch 9)
# =====================================================================

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, KeepTogether
)
from reportlab.pdfgen import canvas
import qrcode
import io
import hashlib
from datetime import datetime as dt


def generate_nomor_dokumen(user_id):
    """Baca nomor dokumen dari database (yang terakhir diverifikasi)."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT nomor_dokumen FROM rencana_pembayaran 
                 WHERE user_id=? AND status='diverifikasi' AND nomor_dokumen IS NOT NULL
                 ORDER BY id DESC LIMIT 1""", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    # Fallback
    now = dt.now()
    return f"RDH/ZKT/{now.year}/{now.month:02d}/0001"

def generate_qr_verifikasi(nomor_dokumen):
    """Generate QR code untuk verifikasi dokumen."""
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    # URL ke halaman verifikasi (harus ada /verify-doc/)
    qr.add_data(f"https://brush-agreed-spookily.ngrok-free.dev/verify-doc/{nomor_dokumen}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def generate_hash_dokumen(nomor_dokumen, user_id, total_zakat):
    """Generate hash SHA-256 untuk keaslian dokumen (deterministik)."""
    raw = f"{nomor_dokumen}|{user_id}|{int(total_zakat)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


@app.route('/api/export/pdf/<int:user_id>', methods=['GET'])
def export_pdf_laporan(user_id):
    """Generate PDF laporan zakat tahunan."""

    # === AUTH CHECK ===
    req_user_id_raw = request.args.get('user_id') or request.headers.get('X-User-Id', '')
    
    try:
        req_user_id = int(req_user_id_raw) if req_user_id_raw else None
    except (ValueError, TypeError):
        req_user_id = None
    
    if req_user_id:
        if req_user_id != user_id:
            info = get_user_role(req_user_id)
            
            if info.get("role") == "super_admin":
                pass  # OK
            
            elif info.get("role") == "admin_lembaga":
                lembaga_id = info.get("lembaga_id")
                if not lembaga_id:
                    return jsonify({"status": "error", 
                                    "message": "Admin lembaga tanpa lembaga_id"}), 403
                
                conn_auth = sqlite3.connect(DB_PATH); c_auth = conn_auth.cursor()
                c_auth.execute("""SELECT 1 FROM rencana_pembayaran 
                                  WHERE user_id=? AND lembaga_id=? 
                                    AND status='diverifikasi'
                                  LIMIT 1""", (user_id, lembaga_id))
                has_transaction = c_auth.fetchone()
                conn_auth.close()
                
                if not has_transaction:
                    return jsonify({"status": "error", 
                                    "message": "Akses ditolak. User tidak punya transaksi di lembaga Anda."}), 403
            else:
                return jsonify({"status": "error", "message": "Akses ditolak"}), 403
    
    # === END AUTH CHECK === 

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    # Ambil data user
    c.execute("""SELECT user_id, nama_lengkap, no_whatsapp 
                 FROM users_config WHERE user_id=?""", (user_id,))
    user_row = c.fetchone()
    if not user_row:
        conn.close()
        return jsonify({"status": "error", "message": "User tidak ditemukan"}), 404
    
    nama_user = user_row[1] or f"User #{user_row[0]}"
    wa_user = user_row[2] or "-"
    
    # Ambil data laporan
    laporan = laporan_tahunan(user_id, HARGA_EMAS_BASE)
    
    # Ambil pembayaran diverifikasi
    c.execute("""SELECT rp.id, rp.jenis_kewajiban, rp.nominal, rp.verified_at,
                 l.nama AS lembaga_nama, rp.rekening_info_manual
                 FROM rencana_pembayaran rp
                 LEFT JOIN lembaga_amil l ON l.id = rp.lembaga_id
                 WHERE rp.user_id=? AND rp.status='diverifikasi'
                 ORDER BY rp.verified_at DESC""", (user_id,))
    pembayaran = c.fetchall()
        # Cek apakah ada pembayaran diverifikasi
    if not pembayaran:
        conn.close()
        return jsonify({
            "status": "error",
            "message": "Belum ada pembayaran zakat yang terverifikasi. PDF tidak bisa di-generate."
        }), 400
    
    total_zakat = sum(p[2] for p in pembayaran)
    
    # Generate nomor dokumen & hash
    nomor_dokumen = generate_nomor_dokumen(user_id)
    hash_doc = generate_hash_dokumen(nomor_dokumen, user_id, total_zakat)
    qr_buf = generate_qr_verifikasi(nomor_dokumen)
    
    # Buffer untuk PDF
    pdf_buf = io.BytesIO()
    doc = SimpleDocTemplate(
       pdf_buf, pagesize=A4,
       leftMargin=15*mm, rightMargin=15*mm,
       topMargin=12*mm,      # ← dari 20mm jadi 10mm (kop naik)
       bottomMargin=14*mm,   # ← dari 20mm jadi 12mm (footer muat)
       title=f"Surat Keterangan Zakat - {nama_user}",
       author="Raudha Spiritual Accountant",
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    style_title = ParagraphStyle(
        'Title', parent=styles['Heading1'],
        fontSize=18, textColor=colors.HexColor('#065f46'),
        alignment=1, spaceAfter=6, fontName='Helvetica-Bold',
    )
    style_subtitle = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#64748b'),
        alignment=1, spaceAfter=4,
    )
    style_section = ParagraphStyle(
        'Section', parent=styles['Heading2'],
        fontSize=12, textColor=colors.HexColor('#065f46'),
        spaceBefore=12, spaceAfter=6, fontName='Helvetica-Bold',
    )
    style_normal = ParagraphStyle(
        'Normal', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#1e293b'),
        leading=14,
    )
    style_legal = ParagraphStyle(
        'Legal', parent=styles['Normal'],
        fontSize=8, textColor=colors.HexColor('#475569'),
        leading=11, alignment=4,
    )
    style_footer = ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=7, textColor=colors.HexColor('#94a3b8'),
        alignment=1,
    )
    
    # Konten PDF
    story = []
    
    # === KOP SURAT ===
    story.append(Paragraph("RAUDHA SPIRITUAL ACCOUNTANT", style_title))
    story.append(Paragraph(
        "Sistem Akuntansi Zakat Digital | LAZIS & BAZNAS Terintegrasi<br/>"
        "Website: raudha.id | Email: admin@raudha.id | WhatsApp: +62 821-6069-0554",
        style_subtitle
    ))
    story.append(Spacer(1, 2*mm))   # ← dari 3mm jadi 2mm
    
    # Garis horizontal
    line_table = Table([['']], colWidths=[180*mm], rowHeights=[1])
    line_table.setStyle(TableStyle([
        ('LINEABOVE', (0,0), (-1,0), 2, colors.HexColor('#065f46')),
    ]))
    story.append(line_table)
    story.append(Spacer(1, 3*mm))   # ← dari 5mm jadi 3mm
    
    # === JUDUL DOKUMEN ===
    story.append(Paragraph("SURAT KETERANGAN ZAKAT", style_title))
    story.append(Paragraph(f"Nomor: {nomor_dokumen}", style_subtitle))
    # Watermark kalau belum ada pembayaran
    if not pembayaran:
        style_watermark = ParagraphStyle(
            'Watermark', parent=styles['Heading1'],
            fontSize=20, textColor=colors.HexColor('#dc2626'),
            alignment=1, spaceBefore=6, spaceAfter=6,
            fontName='Helvetica-Bold'
        )
        story.append(Paragraph("⚠️ DRAFT — BELUM SAH", style_watermark))
        story.append(Paragraph(
            "<i>Dokumen ini belum sah karena belum ada pembayaran zakat terverifikasi.</i>",
            style_subtitle
        ))
    story.append(Spacer(1, 6*mm))   # ← dari 6mm jadi 4mm
    
    # === IDENTITAS MUZAKKI ===
    story.append(Paragraph("A. IDENTITAS MUZAKKI", style_section))
    identitas_data = [
        ['Nama Muzakki', ':', nama_user],
        ['User ID', ':', str(user_id)],
        ['No. WhatsApp', ':', wa_user],
        ['Periode Zakat', ':', '1 Syawal 1446 H - 30 Ramadhan 1447 H'],
        ['Status Haul', ':', 'Terpenuhi' if laporan.get('haul_terpenuhi') else 'Belum Terpenuhi'],
    ]
    identitas_table = Table(identitas_data, colWidths=[45*mm, 5*mm, 130*mm])
    identitas_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#475569')),
        ('TEXTCOLOR', (2,0), (2,-1), colors.HexColor('#1e293b')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(identitas_table)
    story.append(Spacer(1, 2*mm))
    
    # === RINCIAN PERHITUNGAN ===
    story.append(Paragraph("B. RINCIAN PERHITUNGAN ZAKAT", style_section))
    rincian_data = [
        ['Total Harta Bersih', ':', f"Rp {int(laporan.get('total_harta', 0)):,}".replace(',', '.')],
        ['Nisab (85 gram emas)', ':', f"Rp {int(laporan.get('nisab_emas_rupiah', 0)):,}".replace(',', '.')],
        ['Zakat Maal', ':', f"Rp {int(laporan.get('zakat_maal_wajib', 0)):,}".replace(',', '.')],
        ['Zakat Tani', ':', f"Rp {int(laporan.get('zakat_tani', 0)):,}".replace(',', '.')],
        ['Khumus', ':', f"Rp {int(laporan.get('total_khumus', 0)):,}".replace(',', '.')],
    ]
    rincian_table = Table(rincian_data, colWidths=[45*mm, 5*mm, 130*mm])
    rincian_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#475569')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(rincian_table)
    story.append(Spacer(1, 2*mm))
    
    # === TABEL PEMBAYARAN ===
    story.append(Paragraph("C. RINCIAN PEMBAYARAN ZAKAT", style_section))
    
    if pembayaran:
        header = [['No', 'Tanggal', 'Jenis', 'Nominal', 'Lembaga']]
        rows = []
        for i, p in enumerate(pembayaran, 1):
            tgl = p[3].split(' ')[0] if p[3] else '-'
            jenis = (p[1] or '').replace('_', ' ').title()
            nominal = f"Rp {int(p[2]):,}".replace(',', '.')
            lembaga = p[4] or '-'
            rows.append([str(i), tgl, jenis, nominal, lembaga])
        
        rows.append(['', '', 'TOTAL', f"Rp {int(total_zakat):,}".replace(',', '.'), ''])
        
        pembayaran_table = Table(header + rows, colWidths=[10*mm, 22*mm, 35*mm, 35*mm, 78*mm])
        pembayaran_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#065f46')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 8),
            ('FONTSIZE', (0,1), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (3,1), (3,-1), 'RIGHT'),
            ('ALIGN', (2,1), (2,-1), 'LEFT'),
            ('ALIGN', (4,1), (4,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#f0fdf4')),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('TOPPADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(pembayaran_table)
    else:
        story.append(Paragraph(
            "<i>Belum ada pembayaran zakat yang terverifikasi pada periode ini.</i>",
            style_normal
        ))
    story.append(Spacer(1, 4*mm))
    
    # === LEGAL DISCLAIMER ===
    story.append(Paragraph("D. KETERANGAN LEGAL", style_section))
    story.append(Paragraph(
        "Dokumen ini diterbitkan sebagai bukti sah pembayaran zakat sesuai dengan "
        "<b>Undang-Undang No. 36 Tahun 2008 tentang Pajak Penghasilan Pasal 6 ayat (1) huruf d</b> "
        "dan <b>Peraturan Pemerintah No. 60 Tahun 2010</b> tentang Zakat atau Sumbangan Keagamaan "
        "yang Sifatnya Wajib yang Dapat Dikurangkan dari Penghasilan Bruto. "
        "Dokumen ini dapat dilampirkan dalam SPT Tahunan PPh sebagai pengurang penghasilan bruto.",
        style_legal
    ))
    story.append(Spacer(1, 5*mm))
    
    # === TANDA TANGAN & QR ===
    qr_img = Image(qr_buf, width=30*mm, height=30*mm)
    
    ttd_data = [
        [
            qr_img,
            Paragraph(
                f"<b>Raudha Spiritual Accountant</b><br/><br/>"
                f"<br/><br/>"
                f"<b>(Digital Signature)</b><br/>"
                f"Hash: <font name='Courier'>{hash_doc}</font>",
                style_normal
            )
        ]
    ]
    ttd_table = Table(ttd_data, colWidths=[35*mm, 145*mm])
    ttd_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (0,0), (0,0), 'CENTER'),
        ('LEFTPADDING', (1,0), (1,0), 10),
    ]))
    story.append(ttd_table)
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        f"Scan QR code untuk verifikasi keaslian dokumen di raudha.id/verify-doc",
        style_footer
    ))
    story.append(Spacer(1, 3*mm))
    
    # Garis footer
    footer_line = Table([['']], colWidths=[180*mm], rowHeights=[0.5])
    footer_line.setStyle(TableStyle([
        ('LINEABOVE', (0,0), (-1,0), 1, colors.HexColor('#065f46')),
    ]))
    story.append(footer_line)
    story.append(Spacer(1, 1*mm))
    
    story.append(Paragraph(
        f"Dicetak pada: {dt.now().strftime('%d %B %Y, %H:%M WIB')} | "
        f"Dokumen ini sah tanpa tanda tangan basah.",
        style_footer
    ))
    
    # Build PDF
    doc.build(story)
    pdf_buf.seek(0)
    
    # Return sebagai file download
    from flask import send_file
    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"Laporan_Zakat_{nama_user.replace(' ', '_')}_{nomor_dokumen.replace('/', '-')}.pdf"
    )


# =====================================================================
# API — TAGIHAN (Batch 6a)
# =====================================================================

@app.route('/api/tagihan/<int:user_id>', methods=['GET'])
def list_tagihan(user_id):
    """List semua tagihan user."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, jenis, nama, nominal, jatuh_tempo, frekuensi,
                        status, metode_bayar, bukti_bayar_url, tanggal_bayar,
                        catatan, created_at
                 FROM tagihan WHERE user_id=?
                 ORDER BY 
                   CASE status 
                     WHEN 'belum_lunas' THEN 1 
                     WHEN 'terlambat' THEN 0 
                     ELSE 2 
                   END,
                   jatuh_tempo ASC, id DESC""", (user_id,))
    rows = c.fetchall()
    conn.close()
    keys = ["id","jenis","nama","nominal","jatuh_tempo","frekuensi",
            "status","metode_bayar","bukti_bayar_url","tanggal_bayar",
            "catatan","created_at"]
    return jsonify({"status": "success", "tagihan": [dict(zip(keys, r)) for r in rows]})


@app.route('/api/tagihan', methods=['POST'])
@require_telegram_auth
def buat_tagihan():
    data = request.json or {}
    user_id = request.telegram_user_id or int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    jenis = data.get("jenis", "lainnya").strip()
    nama = data.get("nama", "").strip()
    nominal = float(data.get("nominal", 0))
    jatuh_tempo = data.get("jatuh_tempo", "").strip() or None
    frekuensi = data.get("frekuensi", "sekali").strip()
    catatan = data.get("catatan", "").strip()
    
    if not nama or nominal <= 0:
        return jsonify({"status": "error", "message": "Nama & nominal wajib"}), 400
    if jenis not in ("listrik","air","internet","pulsa","cicilan","iuran","hutang","lainnya"):
        jenis = "lainnya"
    if frekuensi not in ("sekali","bulanan","tahunan"):
        frekuensi = "sekali"
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""INSERT INTO tagihan 
                     (user_id, jenis, nama, nominal, jatuh_tempo, frekuensi, catatan, updated_at)
                     VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                  (user_id, jenis, nama, nominal, jatuh_tempo, frekuensi, catatan))
        tagihan_id = c.lastrowid
        tulis_audit(c, user_id, "tagihan", tagihan_id, "CREATE",
                    alasan="Buat tagihan baru")
        conn.commit()
        return jsonify({"status": "success", "message": "Tagihan dibuat", "id": tagihan_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tagihan/<int:tagihan_id>', methods=['PUT'])
def edit_tagihan(tagihan_id):
    """Edit tagihan."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM tagihan WHERE id=?", (tagihan_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Tagihan tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403
        
        c.execute("""UPDATE tagihan SET
                        jenis=?, nama=?, nominal=?, jatuh_tempo=?,
                        frekuensi=?, catatan=?, updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""",
                  (data.get("jenis", "lainnya"), data.get("nama", "").strip(),
                   float(data.get("nominal", 0)), data.get("jatuh_tempo"),
                   data.get("frekuensi", "sekali"), data.get("catatan", "").strip(),
                   tagihan_id))
        tulis_audit(c, user_id, "tagihan", tagihan_id, "UPDATE", alasan="Edit tagihan")
        conn.commit()
        return jsonify({"status": "success", "message": "Tagihan diperbarui"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tagihan/<int:tagihan_id>', methods=['DELETE'])
def hapus_tagihan(tagihan_id):
    """Hapus tagihan."""
    data = request.json or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id FROM tagihan WHERE id=?", (tagihan_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Tagihan tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403
        
        c.execute("DELETE FROM tagihan WHERE id=?", (tagihan_id,))
        tulis_audit(c, user_id, "tagihan", tagihan_id, "DELETE", alasan="Hapus tagihan")
        conn.commit()
        return jsonify({"status": "success", "message": "Tagihan dihapus"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tagihan/<int:tagihan_id>/upload-bukti', methods=['POST'])
def upload_bukti_tagihan(tagihan_id):
    """Upload bukti bayar & tandai lunas."""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "File tidak ditemukan"}), 400
    
    file = request.files['file']
    user_id = request.form.get("user_id", "").strip()
    metode = request.form.get("metode_bayar", "transfer").strip()
    
    if not user_id.isdigit():
        return jsonify({"status": "error", "message": "user_id wajib"}), 400
    user_id = int(user_id)
    
    if not _allowed_file(file.filename):
        return jsonify({"status": "error", "message": "Format tidak didukung"}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"status": "error", "message": "File terlalu besar (maks 5 MB)"}), 400
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("SELECT user_id, status FROM tagihan WHERE id=?", (tagihan_id,))
        row = c.fetchone()
        if not row:
            return jsonify({"status": "error", "message": "Tagihan tidak ditemukan"}), 404
        if row[0] != user_id:
            return jsonify({"status": "error", "message": "Bukan milik Anda"}), 403
        
        ext = file.filename.rsplit('.', 1)[1].lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"bukti_tagihan_{tagihan_id}_{user_id}_{timestamp}.{ext}"
        filepath = os.path.join(UPLOAD_DOKUMEN, filename)
        file.save(filepath)
        
        url = f"/uploads/dokumen_lembaga/{filename}"
        
        c.execute("""UPDATE tagihan SET
                        status='lunas',
                        metode_bayar=?,
                        bukti_bayar_url=?,
                        tanggal_bayar=?,
                        updated_at=CURRENT_TIMESTAMP
                     WHERE id=?""",
                  (metode, url, date.today().strftime("%Y-%m-%d"), tagihan_id))
        tulis_audit(c, user_id, "tagihan", tagihan_id, "UPLOAD_BUKTI",
                    alasan=f"Upload bukti bayar, metode={metode}")
        conn.commit()
        return jsonify({"status": "success", "message": "Tagihan ditandai lunas", "url": url})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tagihan/<int:user_id>/summary', methods=['GET'])
def summary_tagihan(user_id):
    """Ringkasan tagihan user — bulan ini."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    c.execute("""SELECT 
                    COUNT(*),
                    COALESCE(SUM(nominal), 0),
                    COALESCE(SUM(CASE WHEN status='lunas' THEN nominal ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN status IN ('belum_lunas','terlambat') THEN nominal ELSE 0 END), 0)
                 FROM tagihan 
                 WHERE user_id=? 
                   AND (strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
                        OR status != 'lunas')""", (user_id,))
    total, total_nominal, total_lunas, total_belum = c.fetchone()
    
    # Update status terlambat otomatis
    c.execute("""UPDATE tagihan SET status='terlambat'
                 WHERE user_id=? AND status='belum_lunas' 
                   AND jatuh_tempo < date('now')""", (user_id,))
    conn.commit()
    
    conn.close()
    return jsonify({
        "status": "success",
        "summary": {
            "total_tagihan": total,
            "total_nominal": total_nominal,
            "total_lunas": total_lunas,
            "total_belum_lunas": total_belum,
        }
    })

# =====================================================================
# PUBLIC — VERIFIKASI DOKUMEN PDF (Batch 12)
# =====================================================================

@app.route('/verify-doc/<path:nomor>')
def verify_doc_page(nomor):
    """Halaman verifikasi dokumen PDF (publik)."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    
    # Ambil SEMUA pembayaran diverifikasi, urut by id
    c.execute("""SELECT id, user_id, jenis_kewajiban, nominal, verified_at
                 FROM rencana_pembayaran 
                 WHERE status='diverifikasi'
                 ORDER BY id ASC""")
    rows = c.fetchall()
    conn.close()

    # DEBUG: Cetak nomor yang di-generate
    logger.info(f"[VERIFY-DOC] Input nomor: {nomor}")
    logger.info(f"[VERIFY-DOC] Total pembayaran diverifikasi: {len(rows)}")
    for idx, row in enumerate(rows, start=1):
        v_at = row[4] or ""
        try:
            dt_parse = datetime.strptime(v_at[:10], "%Y-%m-%d")
            gen_nomor = f"RDH/ZKT/{dt_parse.year}/{dt_parse.month:02d}/{idx:04d}"
        except (ValueError, TypeError):
            gen_nomor = f"RDH/ZKT/2026/01/{idx:04d}"
        logger.info(f"[VERIFY-DOC] Row {idx}: {row} -> {gen_nomor}")  
    
    # Generate nomor untuk setiap pembayaran, cocokkan dengan input
    match = None
    for idx, row in enumerate(rows, start=1):
        # Format nomor: RDH/ZKT/YYYY/MM/NNNN
        # Ambil tahun/bulan dari verified_at
        v_at = row[4] or ""
        try:
            dt_parse = datetime.strptime(v_at[:10], "%Y-%m-%d")
            gen_nomor = f"RDH/ZKT/{dt_parse.year}/{dt_parse.month:02d}/{idx:04d}"
        except (ValueError, TypeError):
            gen_nomor = f"RDH/ZKT/2026/01/{idx:04d}"
        
        if gen_nomor == nomor:
            match = row
            break
    
    if not match:
        return render_template_string("""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"><title>Verifikasi Dokumen</title>
            <script src="https://cdn.tailwindcss.com"></script></head>
            <body class="bg-slate-50 min-h-screen p-6 flex items-center justify-center">
                <div class="max-w-md mx-auto bg-white rounded-3xl shadow-xl overflow-hidden">
                    <div class="bg-gradient-to-r from-rose-600 to-rose-700 text-white p-6 text-center">
                        <div class="text-6xl mb-2">❌</div>
                        <h1 class="text-xl font-black">Dokumen Tidak Ditemukan</h1>
                        <p class="text-sm opacity-90 mt-1">Nomor: {{ nomor }}</p>
                    </div>
                    <div class="p-6 text-center text-sm text-slate-600">
                        <p>Dokumen dengan nomor ini tidak terdaftar di sistem Raudha.</p>
                        <p class="mt-2 text-xs text-slate-400">Hati-hati terhadap pemalsuan dokumen.</p>
                    </div>
                </div>
            </body></html>
        """, nomor=nomor), 404
    
    pembayaran_id, user_id, jenis, nominal, verified_at = match
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT nama_lengkap FROM users_config WHERE user_id=?", (user_id,))
    user_row = c.fetchone()
    conn.close()
    nama_muzakki = user_row[0] if user_row and user_row[0] else f"User #{user_id}"
    
    raw = f"{nomor}|{user_id}|{int(nominal)}|{verified_at or ''}"
    hash_doc = hashlib.sha256(raw.encode()).hexdigest()[:16].upper()
    
    nominal_str = f"Rp {int(nominal):,}".replace(",", ".")
    verified_str = verified_at or "-"
    jenis_str = (jenis or "").replace("_", " ").title()
    
    return render_template_string("""
        <!DOCTYPE html>
        <html><head>
            <meta charset="UTF-8">
            <title>Verifikasi Dokumen — Raudha</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 min-h-screen p-6">
            <div class="max-w-md mx-auto bg-white rounded-3xl shadow-xl overflow-hidden">
                <div class="bg-gradient-to-r from-emerald-600 to-teal-700 text-white p-6 text-center">
                    <div class="text-6xl mb-2">✅</div>
                    <h1 class="text-xl font-black">Dokumen Terverifikasi</h1>
                    <p class="text-sm opacity-90 mt-1">Surat Keterangan Zakat Sah</p>
                </div>
                <div class="p-6 space-y-3 text-sm">
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Nomor Dokumen</span>
                        <strong class="font-mono text-xs">{{ nomor }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Nama Muzakki</span>
                        <strong>{{ nama }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Jenis Zakat</span>
                        <strong>{{ jenis }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Nominal</span>
                        <strong class="text-emerald-700 text-base">{{ nominal }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Tanggal Verifikasi</span>
                        <strong>{{ verified_at }}</strong>
                    </div>
                    <div class="flex justify-between border-b pb-2">
                        <span class="text-slate-500">Hash Dokumen</span>
                        <strong class="font-mono text-xs">{{ hash_doc }}</strong>
                    </div>
                    <div class="bg-emerald-50 border border-emerald-200 rounded-xl p-3 mt-3">
                        <p class="text-xs text-emerald-800 leading-relaxed text-center">
                            <b>✅ Dokumen Ini Asli</b><br>
                            Diterbitkan oleh Raudha Spiritual Accountant sesuai UU No. 36/2008 Pasal 6 ayat (1) huruf d.
                        </p>
                    </div>
                </div>
            </div>
        </body></html>
    """, nomor=nomor, nama=nama_muzakki, jenis=jenis_str,
        nominal=nominal_str, verified_at=verified_str, hash_doc=hash_doc)


# =====================================================================
# ROOT — RENDER MINI APP
# =====================================================================

@app.route('/')
def index():
    cfg = {
        "harga_emas": HARGA_EMAS_BASE,
        "baseline_awal": BASELINE_AWAL,
        "harga_tani_per_kg": HARGA_TANI_PER_KG,
        "nisab_emas_gram": NISAB_EMAS_GRAM,
        "nisab_pertanian_kg": NISAB_PERTANIAN_KG,
        "kadar_zakat": KADAR_ZAKAT,
        "kadar_tanah_alami": KADAR_TANAH_ALAMI,
        "kadar_tanah_biaya": KADAR_TANAH_BIAYA,
        "kadar_khumus": KADAR_KHUMUS,
        "haul_hari": HAUL_HARI,
    }
    return render_template('index.html', cfg=cfg)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
