# bot.py — Spiritual Accountant: Raudha Engine Bot (Versi Final Bersih)
"""
Bot Telegram untuk platform Raudha.
- Menghubungkan user ke Mini App (web_app_data)
- Menyediakan menu interaktif: Morning, Doa, Tanam, Arsitektur, Sholat, Ekonomi
- Menangani lokasi GPS untuk pencarian masjid terdekat
- Menangani jadwal sholat manual via /kota
"""

import logging
import os
import json
import re
import time
import sys
from pathlib import Path
from dotenv import load_dotenv
import socket
import shutil
from datetime import datetime as _dt, datetime, date
import sqlite3
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Import dari modul_sholat (untuk fitur bot lainnya)
from modul_sholat import (
    cari_kota_fuzzy, 
    ambil_jadwal_sholat,
    masjid_terdekat
)
# Import dari jadwal_sholat (untuk fitur API Aladhan)
from jadwal_sholat import cari_kota, get_jadwal, format_jadwal

import socket

# Paksa IPv4: saat me-resolve api.telegram.org, langsung kembalikan alamat IPv4, lewati IPv6
_original_getaddrinfo = socket.getaddrinfo

def _force_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host == 'api.telegram.org':
        # Kembalikan alamat IPv4 Telegram secara langsung (149.154.167.220 adalah salah satu IP Bot API)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('149.154.167.220', port))]
    return _original_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _force_ipv4_getaddrinfo

# --- 1. SET UP PATH & ENV ---
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

# --- FOLDER UPLOAD (sama dengan app.py) ---
UPLOAD_FOLDER = os.path.join(str(BASE_DIR), "uploads")
UPLOAD_DOKUMEN = os.path.join(UPLOAD_FOLDER, "dokumen_lembaga")
os.makedirs(UPLOAD_DOKUMEN, exist_ok=True)

# --- 2. LOGGING ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Sembunyikan log httpx (berisi URL dengan token)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- 3. IMPORT TELEGRAM ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 4. IMPORT MODUL LOKAL ---
from modul_database import (
    init_db, simpan_lokasi_user,
    get_all_masjid, cari_masjid_by_kota, get_masjid_by_id
)
from modul_keuangan.database import init_db_keuangan
from modul_keuangan.kasir import handle_masuk, handle_keluar

# Import dari modul_sholat (untuk fitur lain seperti masjid terdekat)
from modul_sholat import cari_kota_fuzzy, ambil_jadwal_sholat, masjid_terdekat

# Import dari jadwal_sholat (khusus untuk API Aladhan /kota)
from jadwal_sholat import cari_kota, get_jadwal

# Import dari modul_kesehatan 
from modul_kesehatan import (
    init_db_kesehatan, get_program_aktif, daftar_rsvp, batal_rsvp, get_daftar_peserta,
    get_daftar_artikel, get_artikel
)

DB_PATH = os.path.join("data", "raudha.db")

# --- 5. KONSTANTA & VALIDASI ENV ---
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
MINI_APP_URL = (os.getenv("MINI_APP_URL") or "https://ngrok-free.dev").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

if not BOT_TOKEN:
    raise RuntimeError(
        "❌ Token bot tidak ditemukan! "
        "Pastikan variabel 'TELEGRAM_BOT_TOKEN' ada di file .env."
    )

# =====================================================================
# KONFIGURASI BACKUP
# =====================================================================

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
MAX_BACKUP_DAYS = 7  # Retensi: 7 hari

# =====================================================================
# KONFIGURASI BACKUP MINGGUAN + EMAIL
# =====================================================================

BACKUP_WEEKLY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups_weekly")
os.makedirs(BACKUP_WEEKLY_DIR, exist_ok=True)

# SMTP — diisi dari .env
SMTP_HOST = (os.getenv("SMTP_HOST") or "").strip()
SMTP_PORT = int((os.getenv("SMTP_PORT") or "587").strip())
SMTP_USER = (os.getenv("SMTP_USER") or "").strip()
SMTP_PASS = (os.getenv("SMTP_PASS") or "").strip()
SMTP_TO   = (os.getenv("SMTP_TO")   or "").strip()

if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
    logger.warning("⚠️ SMTP belum lengkap — backup email tidak akan dikirim")

# --- 6. INIT DATABASE (SEKALI SAJA) ---
try:
    init_db()
    init_db_keuangan()
    init_db_kesehatan()
    logger.info("✅ Database proyek berhasil diinisialisasi")
except Exception as e:
    logger.error(f"❌ Gagal inisialisasi database: {e}")
    raise

# --- 7. HELPERS ---
def format_idr(nilai):
    """Format angka jadi Rupiah gaya Indonesia: Rp 3.000.000"""
    try:
        return f"Rp {int(round(float(nilai))):,}".replace(",", ".")
    except (ValueError, TypeError):
        return "Rp 0"


def _safe_int(value, default=0):
    """Cast ke int dengan toleransi string angka berkoma/titik."""
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


async def safe_reply(message, text, reply_markup=None, parse_mode='Markdown'):
    """
    Kirim pesan dengan fallback kalau Markdown gagal di-parse
    (misalnya karena ada karakter * atau _ yang tidak berpasangan).
    """
    try:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Markdown gagal, fallback ke plain text: {e}")
        try:
            await message.reply_text(text, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Gagal kirim pesan sama sekali: {e2}")


async def safe_edit(query, text, reply_markup=None, parse_mode='Markdown'):
    """Sama seperti safe_reply, tapi untuk edit_message_text (callback)."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Edit Markdown gagal, fallback: {e}")
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except Exception as e2:
            logger.error(f"Gagal edit pesan: {e2}")

def get_pending_lembaga():
    """Ambil daftar lembaga/masjid yang menunggu verifikasi."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, nama, jenis, kategori_lembaga, created_by FROM lembaga_amil WHERE status='pending'")
    rows = c.fetchall()
    conn.close()
    return rows

def verifikasi_lembaga(lembaga_id, kategori):
    """Ubah status lembaga menjadi verified dan set kategorinya."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE lembaga_amil SET status='verified', kategori_lembaga=? WHERE id=?", (kategori, lembaga_id))
    conn.commit()
    conn.close()

def tugaskan_admin(user_id, masjid_id, jenis_layanan):
    """Tugaskan admin ke masjid tertentu."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT OR IGNORE INTO admin_penugasan (user_id, masjid_id, jenis_layanan, status) 
                 VALUES (?, ?, ?, 'aktif')""", (user_id, masjid_id, jenis_layanan))
    conn.commit()
    conn.close()            



# =====================================================================
# HELPER: Subscription Masjid
# =====================================================================

def is_super_admin(user_id):
    """Cek apakah user adalah Super Admin."""
    return ADMIN_ID and user_id == ADMIN_ID

def get_user_subscription(user_id):
    """Ambil masjid yang di-subscribe user (pertama)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.nama 
        FROM user_subscription us
        JOIN masjid m ON us.masjid_id = m.id
        WHERE us.user_id = ? AND us.status = 'aktif'
        LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def simpan_subscription(user_id, masjid_id):
    """Simpan langganan masjid user."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO user_subscription (user_id, masjid_id) 
        VALUES (?, ?)
    """, (user_id, masjid_id))
    conn.commit()
    conn.close()

def get_user_role(user_id):
    """
    Mengembalikan role user:
    - 'super_admin' dari ADMIN_ID env
    - 'super_admin', 'admin_lembaga' dari users_config (PRIORITAS)
    - 'kesehatan', 'lazis', 'masjid' dari admin_penugasan (FALLBACK)
    """
    # 1. Cek Super Admin dari env
    if is_super_admin(user_id):
        return "super_admin"
    
    # 2. PRIORITAS: Cek users_config (admin_lembaga & super_admin DB)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, status FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        role_db, status = row
        if status == 'active' and role_db in ('super_admin', 'admin_lembaga'):
            return role_db   # ← RETURN LANGSUNG (prioritas)
    
    # 3. FALLBACK: Cek admin_penugasan (kesehatan, lazis, masjid)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT jenis_layanan FROM admin_penugasan WHERE user_id = ? AND status = 'aktif' LIMIT 1",
        (user_id,)
    )
    row2 = c.fetchone()
    conn.close()
    
    if row2:
        return row2[0]
    
    return None

# =====================================================================
# 8. HANDLER UTAMA MENU /start
# =====================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu utama bot. Dipanggil dari /start maupun tombol 'Kembali ke Menu Utama'."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Cek apakah user sudah subscribe masjid
    sub = get_user_subscription(user_id)
    
    # Jika belum subscribe DAN belum skip onboarding → tampilkan onboarding
    if not sub and not context.user_data.get('skip_onboarding'):
        text = (
            "👋 **Salam dan Selamat Datang di Raudha!**\n\n"
            "Sebagai langkah pertama, mari kita temukan *Masjid Acuan* Anda.\n"
            "Info kesehatan, kajian, dan kegiatan akan disesuaikan dengan masjid pilihan Anda."
        )
        keyboard = [
            [InlineKeyboardButton("📍 Gunakan Lokasi Saya", callback_data="onboarding_gps")],
            [InlineKeyboardButton("🕌 Pilih Masjid Manual", callback_data="onboarding_manual")],
            [InlineKeyboardButton("⏭️ Lewati Dulu", callback_data="onboarding_skip")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if query:
            await safe_edit(query, text, reply_markup)
        else:
            await safe_reply(update.message, text, reply_markup)
        return
    
       # ============ MENU UTAMA ============

    url_mini_app = f"{MINI_APP_URL}?ngrok-skip-browser-warning=true&t={int(time.time())}"
    text = (
        "👋 **Salam dan Selamat Datang di Raudha - Marbot yang melayani anda dalam mengkreasi kebaikan setiap hari, selaras dengan motto - Recreate All The New Day:**\n\n"
        "Silakan gunakan tombol interaktif di bawah ini untuk mengakses setiap layanan:"
    )
    
    # Tampilkan nama masjid jika user subscribe
    if sub:
        text += f"\n\n🏠 *Masjid Acuan:* {sub[1]}"
    elif context.user_data.get('skip_onboarding'):
        text += f"\n\n_Anda belum memilih masjid acuan._"
    
    keyboard = [
        [InlineKeyboardButton("🚀 Buka App Hitung Amal & Zakat", web_app=WebAppInfo(url=url_mini_app))],
        [InlineKeyboardButton("🌅 Pagi Sehat", callback_data="menu_pagi_sehat"),
         InlineKeyboardButton("🤲 Doa Pilihan", callback_data="menu_doa")],
        [InlineKeyboardButton("🕌 Masjid & Jaringan", callback_data="menu_masjid"),
         InlineKeyboardButton("🕌 Jam Sholat", callback_data="menu_sholat")],
        [InlineKeyboardButton("🌱 Mitra Alam", callback_data="menu_tanam"),
         InlineKeyboardButton("🏛️ Arsitektur", callback_data="menu_arsitektur")],
        [InlineKeyboardButton("💰 Ekonomi Ummat", callback_data="menu_ekonomi")],
        [InlineKeyboardButton("🚀 Pintas Layanan Inti", callback_data="menu_quick_links")],
        [InlineKeyboardButton("❓ Help & Subscribe", callback_data="menu_help"),
         InlineKeyboardButton("ℹ️ About", callback_data="menu_about")],
    ]
    
    # TAMBAHAN: Tombol Dashboard Berdasarkan Role (Super Admin, Kesehatan, Lazis, Masjid)
    role = get_user_role(update.effective_user.id)
    if role:
        # Tentukan label tombol berdasarkan role
        label_map = {
            "super_admin": "🖥️ Dashboard Super Admin",
            "kesehatan": "🩺 Dashboard Kesehatan",
            "lazis": "💰 Dashboard Lazis",
            "masjid": "🕌 Dashboard Masjid",
            "admin_lembaga": "🖥️ Dashboard Admin Lembaga",  # ← BARU
        }
        tombol_label = label_map.get(role, "🖥️ Dashboard Admin")
        
        # Tambahkan tombol ke keyboard
        keyboard.append([InlineKeyboardButton(tombol_label, web_app=WebAppInfo(url=f"{MINI_APP_URL}/admin"))])
    
    # BARU BUAT reply_markup SETELAH semua tombol ditambahkan
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        try:
            await query.answer()
        except Exception:
            pass
        await safe_edit(query, text, reply_markup)
    elif update.message:
        await safe_reply(update.message, text, reply_markup)

async def handle_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "onboarding_skip":
        # Set flag skip di context, lalu tampilkan menu utama
        context.user_data['skip_onboarding'] = True
        await start(update, context)
        return

    elif data == "onboarding_gps":
        await safe_edit(query, 
            "📍 Silakan kirim lokasi Anda dengan menekan ikon klip (📎) → **Location**.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]))
        return

    elif data == "onboarding_manual":
        # Tampilkan daftar masjid
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, nama, tipe_masjid FROM masjid ORDER BY tipe_masjid DESC, nama ASC LIMIT 10")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            await safe_edit(query, "❌ Belum ada masjid terdaftar.", 
                           InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]))
            return
        
        text = "🕌 **Pilih Masjid Acuan Anda:**"
        keyboard = []
        for mid, nama, tipe in rows:
            icon = "⭐" if tipe == 'raudha' else "•"
            keyboard.append([InlineKeyboardButton(f"{icon} {nama}", callback_data=f"pilih_masjid_{mid}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")])
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
        return

    elif data.startswith("pilih_masjid_"):
        masjid_id = int(data.replace("pilih_masjid_", ""))
        simpan_subscription(user_id, masjid_id)
        context.user_data.pop('skip_onboarding', None)  # Hapus flag skip
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT nama FROM masjid WHERE id=?", (masjid_id,))
        row = c.fetchone()
        conn.close()
        
        nama = row[0] if row else "Masjid"
        await safe_edit(query, 
            f"✅ Anda sekarang mengikuti info dari **{nama}**.\n\nKetik /start untuk melihat menu.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="back_to_main")]]))
        return        

async def handle_masjid_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler menu Masjid & Jaringan."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if data == "menu_masjid":
        # Ambil masjid acuan saat ini
        sub = get_user_subscription(user_id)
        nama_acuan = sub[1] if sub else "Belum memilih"
        
        text = (
            f"🕌 **MASJID & JARINGAN**\n\n"
            f"🏠 *Masjid Acuan Anda:* **{nama_acuan}**\n\n"
            f"Silakan pilih layanan:"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Ganti Masjid Acuan", callback_data="masjid_ganti")],
            [InlineKeyboardButton("🔍 Cari Masjid Berdasarkan Kota", callback_data="masjid_cari_kota")],
            [InlineKeyboardButton("🏛️ Daftar Masjid Raudha", callback_data="masjid_daftar_raudha")],
            [InlineKeyboardButton("🌐 Daftar Masjid Jaringan", callback_data="masjid_daftar_jaringan")],
            [InlineKeyboardButton("➕ Daftarkan Masjid Baru", callback_data="masjid_daftar_baru")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    elif data == "masjid_ganti":
        # Tampilkan daftar masjid untuk dipilih ulang
        masjids = get_all_masjid()
        if not masjids:
            await safe_edit(query, "❌ Belum ada masjid terdaftar.", 
                           InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")]]))
            return
        
        text = "🔄 **Pilih Masjid Acuan Baru:**"
        keyboard = []
        for mid, nama, tipe, kota, alamat in masjids[:10]:
            icon = "⭐" if tipe == 'raudha' else "•"
            keyboard.append([InlineKeyboardButton(
                f"{icon} {nama} ({kota or '-'})",
                callback_data=f"pilih_masjid_{mid}"
            )])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")])
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    elif data == "masjid_cari_kota":
        await safe_edit(query, 
            "🔍 **Cari Masjid Berdasarkan Kota**\n\n"
            "Silakan ketik nama kota dengan format:\n"
            "`/carimasjid [Nama Kota]`\n\n"
            "Contoh: `/carimasjid Banjarnegara`",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")]]))

    elif data == "masjid_daftar_raudha":
        masjids = [m for m in get_all_masjid() if m[2] == 'raudha']
        if not masjids:
            await safe_edit(query, "🏛️ **Masjid Raudha**\n\nBelum ada masjid Raudha yang terdaftar.", 
                           InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")]]))
            return
        
        text = "🏛️ **DAFTAR MASJID RAUDHA**\n\n"
        for mid, nama, tipe, kota, alamat in masjids:
            text += f"⭐ *{nama}*\n"
            if kota:
                text += f"   📍 {kota}\n"
            if alamat:
                text += f"   🏠 {alamat}\n"
            text += f"   [📍 Pilih Masjid Ini](https://t.me/{context.bot.username}?start=subs_{mid})\n\n"
        
        text += "_Klik tombol di bawah untuk memilih masjid._"
        keyboard = []
        for mid, nama, tipe, kota, alamat in masjids:
            keyboard.append([InlineKeyboardButton(f"⭐ {nama}", callback_data=f"pilih_masjid_{mid}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")])
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data == "masjid_daftar_jaringan":
        masjids = [m for m in get_all_masjid() if m[2] == 'jaringan']
        if not masjids:
            await safe_edit(query, "🌐 **Masjid Jaringan**\n\nBelum ada masjid jaringan yang terdaftar.", 
                           InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")]]))
            return
        
        text = "🌐 **DAFTAR MASJID JARINGAN**\n\n"
        for mid, nama, tipe, kota, alamat in masjids[:15]:
            text += f"• *{nama}*\n"
            if kota:
                text += f"   📍 {kota}\n"
        
        keyboard = []
        for mid, nama, tipe, kota, alamat in masjids[:10]:
            keyboard.append([InlineKeyboardButton(f"• {nama} ({kota or '-'})", callback_data=f"pilih_masjid_{mid}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")])
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    elif data == "masjid_daftar_baru":
        text = (
            "➕ **DAFTARKAN MASJID BARU**\n\n"
            "Untuk mendaftarkan masjid sebagai bagian dari jaringan Raudha, "
            "silakan buka Mini App dan isi formulir pendaftaran.\n\n"
            "Tim Super Admin akan memverifikasi pendaftaran Anda."
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Buka Mini App", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=daftar"))],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_masjid")]
        ]
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

async def cmd_cari_masjid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /carimasjid [nama_kota] — cari masjid berdasarkan kota."""
    if not context.args:
        await update.message.reply_text("⚠️ Silakan masukkan nama kota.\nContoh: `/carimasjid Banjarnegara`")
        return
    
    kota = " ".join(context.args).strip()
    masjids = cari_masjid_by_kota(kota)
    
    if not masjids:
        await update.message.reply_text(f"❌ Tidak ada masjid terdaftar di kota '{kota}'.")
        return
    
    text = f"🕌 **Masjid di {kota.title()}**\n\n"
    for mid, nama, tipe, kota_m in masjids[:10]:
        icon = "⭐" if tipe == 'raudha' else "•"
        text += f"{icon} {nama}\n"
    
    keyboard = []
    for mid, nama, tipe, kota_m in masjids[:10]:
        icon = "⭐" if tipe == 'raudha' else "•"
        keyboard.append([InlineKeyboardButton(f"{icon} {nama}", callback_data=f"pilih_masjid_{mid}")])
    keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')        

async def cmd_verifikasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya Super Admin.")
        return

    pending = get_pending_lembaga()
    if not pending:
        await update.message.reply_text("✅ Tidak ada pendaftaran baru.")
        return

    text = "⏳ **DAFTAR PENDAFTARAN BARU**\n\n"
    keyboard = []
    for lid, nama, jenis, kategori, created_by in pending:
        text += f"• *{nama}*\n"
        keyboard.append([InlineKeyboardButton(f"✅ Verifikasi {nama}", callback_data=f"approve_lembaga_{lid}")])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# =====================================================================
# COMMAND: /mode_verifikasi — Switch mode verifikasi wakaf
# =====================================================================

async def cmd_mode_verifikasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /mode_verifikasi [super_only|multi_admin]"""
    if not is_super_admin(update.effective_user.id):
        await update.message.reply_text("❌ Hanya Super Admin.")
        return
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS program_config (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT value FROM program_config WHERE key='wakaf_verification_mode'")
    row = c.fetchone()
    current = row[0] if row else 'super_only'
    conn.close()
    
    if not context.args:
        text = (
            f"⚙️ *MODE VERIFIKASI WAKAF*\n\n"
            f"Mode saat ini: *{current}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Pilihan:*\n"
            f"• `super_only` — hanya Super Admin\n"
            f"• `multi_admin` — Super Admin + Admin Lembaga\n\n"
            f"*Ubah:*\n"
            f"`/mode_verifikasi super_only`\n"
            f"`/mode_verifikasi multi_admin`"
        )
        await safe_reply(update.message, text)
        return
    
    new_mode = context.args[0].strip().lower()
    if new_mode not in ('super_only', 'multi_admin'):
        await update.message.reply_text(
            "❌ Mode harus `super_only` atau `multi_admin`",
            parse_mode='Markdown'
        )
        return
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS program_config (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""INSERT OR REPLACE INTO program_config (key, value, updated_at)
                 VALUES ('wakaf_verification_mode', ?, CURRENT_TIMESTAMP)""", (new_mode,))
    conn.commit()
    conn.close()
    
    icon = "🔒" if new_mode == 'super_only' else "🌐"
    label = "Hanya Super Admin" if new_mode == 'super_only' else "Super Admin + Admin Lembaga"
    
    await update.message.reply_text(
        f"{icon} Mode verifikasi diubah ke *{new_mode}*\n\n"
        f"_{label}_",
        parse_mode='Markdown'
    )
    logger.info(f"⚙️ Mode verifikasi wakaf → {new_mode} oleh {update.effective_user.id}")

# =====================================================================
# COMMAND: /debug_role — Debug role user (temporary)
# =====================================================================

async def cmd_debug_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /debug_role — tampilkan user_id + role untuk debugging."""
    user = update.effective_user
    user_id = user.id
    role = get_user_role(user_id)
    nama = user.first_name or "?"
    username = user.username or "?"
    
    # Ambil info dari users_config
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT nama_lengkap, role, status, lembaga_id FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        db_info = (
            f"  • Nama DB: {row[0] or '-'}\n"
            f"  • Role DB: {row[1] or '-'}\n"
            f"  • Status: {row[2] or '-'}\n"
            f"  • Lembaga: {row[3] or '-'}"
        )
    else:
        db_info = "  ⚠️ Tidak ada di users_config"
    
    text = (
        f"🔍 *DEBUG ROLE*\n\n"
        f"🆔 User ID: `{user_id}`\n"
        f"👤 Nama: {nama}\n"
        f"🔗 Username: @{username}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎭 *Role Aktif:* `{role or 'None'}`\n\n"
        f"*Dari users_config:*\n{db_info}"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')    


async def handle_approve_lembaga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lid = int(query.data.replace("approve_lembaga_", ""))
    
    keyboard = [
        [InlineKeyboardButton("🕌 Masjid/Pondok", callback_data=f"setkat_{lid}_masjid")],
        [InlineKeyboardButton("🩺 Klinik Kesehatan", callback_data=f"setkat_{lid}_kesehatan")],
        [InlineKeyboardButton("💰 Lazis/BMT", callback_data=f"setkat_{lid}_lazis")]
    ]
    await safe_edit(query, "Pilih kategori untuk lembaga ini:", InlineKeyboardMarkup(keyboard))


async def handle_set_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    lid = int(parts[1])
    kat = parts[2]
    
    verifikasi_lembaga(lid, kat)
    await safe_edit(query, f"✅ Lembaga berhasil diverifikasi dengan kategori *{kat}*.", parse_mode='Markdown')


async def cmd_tugaskan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id):
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Format: `/tugaskan [user_id] [masjid_id] [layanan]`\n"
            "Contoh: `/tugaskan 7730813004 1 kesehatan`"
        )
        return

    target_user = int(context.args[0])
    masjid_id = int(context.args[1])
    layanan = context.args[2]
    
    tugaskan_admin(target_user, masjid_id, layanan)
    await update.message.reply_text(f"✅ User {target_user} ditugaskan di Masjid ID {masjid_id} untuk layanan {layanan}.")

# =====================================================================
# HANDLER: MITRA ALAM — DAFTAR KOMODITAS DINAMIS
# =====================================================================

async def handle_mitra_alam_komoditas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan daftar komoditas dengan harga dari database."""
    query = update.callback_query
    await query.answer()
    
    try:
        from modul_mitra_alam import get_semua_komoditas
        komoditas = get_semua_komoditas()
    except Exception as e:
        logger.error(f"Gagal load komoditas: {e}")
        await safe_edit(query, "⚠️ Gagal memuat data komoditas.")
        return
    
    if not komoditas:
        await safe_edit(query, "😔 Belum ada komoditas aktif.")
        return
    
    text = "🌳 *KOMODITAS WAKAF PRODUKTIF TANAMAN*\n\n"
    text += "Setiap pohon ditanam di lahan wakaf masjid/pesantren.\n"
    text += "Dipantau via NFC, hasil panen kembali untuk ummat.\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for k in komoditas:
        harga_str = f"Rp {int(k['harga_pohon']):,}".replace(",", ".")
        text += f"*{k['nama_display']}*\n"
        text += f"  💰 {harga_str}/pohon\n"
        text += f"  🌾 {k['output']}\n"
        text += f"  ⏱️ Panen: {k['siklus_panen']}\n"
        text += f"  💵 {k['nilai_ekonomi']}\n"
        text += f"  🌿 {k['fungsi_ekologis']}\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "_Buka Mini App untuk wakaf & lihat detail._"
    
    url_katalog = f"{MINI_APP_URL}/mitra-alam/katalog?t={int(time.time())}"
    keyboard = [
        [InlineKeyboardButton("🌱 Wakaf Sekarang (Buka Katalog)",
                              web_app=WebAppInfo(url=url_katalog))],
        [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_tanam")],
    ]
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

# =====================================================================
# 8.1. COMMAND IDTV
# =====================================================================

async def cmd_id_tv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /idtv — Menampilkan link TV untuk admin masjid."""
    user_id = update.effective_user.id
    
    # Cek role user dari database
    import sqlite3
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT role, lembaga_id FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    
    if not row or row[0] != 'admin_lembaga' or not row[1]:
        conn.close()
        await update.message.reply_text(
            "❌ Anda belum terdaftar sebagai Admin Lembaga/Masjid.\n"
            "Silakan daftarkan lembaga Anda melalui Mini App terlebih dahulu."
        )
        return
        
    lembaga_id = row[1]
    c.execute("SELECT nama, status FROM lembaga_amil WHERE id=?", (lembaga_id,))
    lembaga = c.fetchone()
    conn.close()
    
    if not lembaga or lembaga[1] != 'verified':
        await update.message.reply_text(
            "⚠️ Lembaga Anda belum diverifikasi oleh Super Admin.\n"
            "Silakan tunggu proses verifikasi selesai."
        )
        return
        
    # Susun URL TV
    url_menu = f"{MINI_APP_URL}/menu"
    url_zakat = f"{MINI_APP_URL}/tv/zakat?masjid={lembaga_id}"
    
    teks = (
        f"📺 *LINK TV MASJID ANDA*\n\n"
        f"🏛️ Masjid: *{lembaga[0]}*\n\n"
        f"1️⃣ *Menu Utama TV:*\n`{url_menu}`\n\n"
        f"2️⃣ *Layar Kas & Zakat:*\n`{url_zakat}`\n\n"
        f"💡 _Buka link Menu Utama di browser Smart TV, lalu simpan sebagai Homepage._"
    )
    
    keyboard = [[InlineKeyboardButton("🔗 Buka Menu TV", url=url_menu)]]
    await update.message.reply_text(teks, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# =====================================================================
# 9. SUB-MENU NAVIGATION
# =====================================================================

async def handle_submenus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler navigasi semua sub-menu (Morning, Doa, Tanam, Arsitektur, Sholat, Ekonomi, Help, About, Wacana)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    keyboard = []
    text = ""

    if data == "menu_morning":
        text = "🌅 MORNING MENU - RAUDHA\n\nMorning has broken - Awali pagi hari dengan dzikir dan inspirasi pagi:"
        keyboard = [
            [InlineKeyboardButton("☀️ Dzikir Pagi Singkat", callback_data="run_dzikir_pagi")],
            [InlineKeyboardButton("📜 Inspirasi Pagi Ini", callback_data="run_inspirasi")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "menu_doa":
        text = (
            "🤲 MENU DOA - RAUDHA\n\n"
            "_Berdoalah kepada-Ku, niscaya akan Aku ijabah/perkenankan bagimu._\n(QS. Ghafir: 60).\n\n"
            "Silakan pilih rumpun doa yang ingin Anda amalkan di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🏡 Doa Harian Penting", callback_data="run_doa_harian")],
            [InlineKeyboardButton("🛡️ Doa Perlindungan Diri", callback_data="run_doa_lindung")],
            [InlineKeyboardButton("📖 Doa Pilihan & Shalawat", callback_data="sub_doa_pilihan")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "sub_doa_pilihan":
        text = (
            "📖 MENU DOA PILIHAN & SHALAWAT\n\n"
            "Kumpulan doa agung, munajat, amalan malam Jum'at, serta untaian shalawat."
        )
        keyboard = [
            [InlineKeyboardButton("📜 Doa Kumail", callback_data="run_doa_kumail"),
             InlineKeyboardButton("✨ Doa Ziyarah", callback_data="run_doa_ziyarah")],
            [InlineKeyboardButton("🌙 Doa Nudbah", callback_data="run_doa_nudbah"),
             InlineKeyboardButton("📿 Pilihan Shalawat", callback_data="run_doa_shalawat")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")],
        ]

    elif data == "menu_tanam":
        text = (
            "🌱 *MITRA ALAM RAUDHA*\n\n"
            "_Jadikan Halaman Ini Menjadi Taman Wasiat_\n\n"
            "Gerakan wakaf produktif berbasis teknologi NFC.\n"
            "Setiap pohon ditanam di lahan wakaf masjid/pesantren, "
            "dipantau pertumbuhannya, dan hasil panennya kembali untuk ummat.\n\n"
            "Silakan pilih program:"
        )
        url_katalog = f"{MINI_APP_URL}/mitra-alam/katalog?t={int(time.time())}"
        url_pesantren = f"{MINI_APP_URL}/pesantren-alam?t={int(time.time())}"
        url_pohon_saya = f"{MINI_APP_URL}/mitra-alam/pohon-saya?t={int(time.time())}"
        
        keyboard = [
            [InlineKeyboardButton("🌳 Wakaf Produktif Tanaman",
                                  web_app=WebAppInfo(url=url_katalog))],
            [InlineKeyboardButton("🏫 Pesantren Alam Raudha Mar'i Mar'a",
                                  web_app=WebAppInfo(url=url_pesantren))],
            [InlineKeyboardButton("📊 Dashboard Pohon Saya",
                                  web_app=WebAppInfo(url=url_pohon_saya))],
            [InlineKeyboardButton("📖 Tentang Program",
                                  callback_data="mitra_alam_about")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama",
                                  callback_data="back_to_main")],
        ]

    elif data == "menu_arsitektur":
        url_arsitektur = f"{MINI_APP_URL}/arsitektur?t={int(time.time())}"
        text = (
            "🏛️ LAYANAN ARSITEKTUR & MANAJEMEN PROYEK RAUDHA\n\n"
            "Kami menyediakan layanan desain unyuk menghadirkan ruang ibadah dan fasilitas sosial yang estetik, "
            "berkah, serta memenuhi standar ketat keselamatan & keamanan bangunan.\n\n"
            "**Keahlian Bersertifikasi Kami:**\n"
            "• Perencanaan Masjid & Pusat Komunitas\n"
            "• Desain Madrasah, Sekolah, & Asrama Sehat\n"
            "• Manajemen Proyek & Pengawasan Konstruksi Lapangan\n\n"
            "Silakan jelajahi layanan ahli kami secara interaktif:"
        )
        keyboard = [
            [InlineKeyboardButton("🏛️ Buka Galeri Desain & Form Pengajuan",
                                  web_app=WebAppInfo(url=url_arsitektur))],
            [InlineKeyboardButton("💬 Konsultasi Ahli via WhatsApp",
                                  url="https://wa.me/6282160690554")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "menu_sholat":
        text = (
            "🕌 **MENU JADWAL SHOLAT & LOKASI**\n\n"
            "Silakan pilih cara melihat jadwal sholat di seluruh dunia:\n\n"
            "📌 **Opsi 1:** Buka Aplikasi Jam Raudha (Sangat Direkomendasikan).\n"
            "Tampilan mewah, otomatis mendeteksi lokasi Anda, dan ada hitung mundur waktu sholat.\n\n"
            "📌 **Opsi 2:** Kirim lokasi GPS via Telegram.\n"
            "📌 **Opsi 3:** Cari manual berdasarkan nama Kota."
        )
        keyboard = [
            # TAMBAHAN: Tombol Link ke Web App
            [InlineKeyboardButton("🖥️ Buka Aplikasi Jam Raudha", web_app=WebAppInfo(url=f"{MINI_APP_URL}/display?mode=hp"))],
            [InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps")],
            [InlineKeyboardButton("🔍 Cari Nama Kota", callback_data="sub_sholat_kota")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "sub_sholat_gps":
        text = (
            "📍 **PENCARIAN OTOMATIS VIA GPS**\n\n"
            "Silakan kirim lokasi terkini Anda dengan menekan ikon klip/lampiran di bawah (📎) → **Location**."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]]

    elif data == "sub_sholat_kota":
        text = (
            "🔍 **PENCARIAN MANUAL NAMA KOTA**\n\n"
            "Silakan ketik nama Kota dengan perintah `/kota`.\n\n"
            "👉 *Contoh*: `/kota Banjarnegara`"
        )
        keyboard = [
            [InlineKeyboardButton("🕌 Temukan Masjid Terdekat", url="https://google.com")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")],
        ]

    elif data == "menu_ekonomi":
        # URL Mini App dengan parameter untuk langsung membuka tab Zakat
        mini_app_zakat_url = f"{MINI_APP_URL}?tab=zakat&ngrok-skip-browser-warning=true&t={int(time.time())}"
        
        text = (
            "💰 **MENU EKONOMI UMMAT (LAZIS & BMT)**\n\n"
            "Layanan pemberdayaan ekonomi berbasis jama'ah Masjid dan Komunitas Raudha.\n\n"
            "Silakan pilih layanan yang ingin Anda akses:"
        )
        keyboard = [
            [InlineKeyboardButton("💰 Buka Kalkulator Zakat", web_app=WebAppInfo(url=mini_app_zakat_url))],
            [InlineKeyboardButton("🪙 Cek Saldo BMT", callback_data="run_saldo_bmt")],
            [InlineKeyboardButton("🧾 Daftar Tagihan Belum Lunas", callback_data="run_tagihan")],
            [InlineKeyboardButton("📊 Laporan Zakat Ringkas", callback_data="run_laporan")],
            [InlineKeyboardButton("🏦 Info Layanan BMT & LAZIS", callback_data="sub_info_ekonomi")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data in ("wacana_finansial_laziz", "wacana_finansial_bmt", "wacana_gerai_dinar"):
        text = (
            "🏦 **HALAMAN SIMULASI PENGEMBANGAN PILAR EKONOMI**\n\n"
            "Layanan finansial Islam berbasis simpanan Dinar, yang dikoneksikan ke gerbang pembayaran digital "
            "untuk membaca QRIS otomatis atau kirim formulir digital pengajuan modal usaha tanpa riba.\n\n"
            "Terima kasih atas masukan berharga Anda untuk pilar Ekonomi Umat bersama Raudha."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Ekonomi", callback_data="menu_ekonomi")]]

    elif data == "menu_help":
        text = (
            "❓ **BANTUAN, PANDUAN & LANGGANAN**\n"
            "• Ketik `/start` untuk menu utama.\n"
            "• Ketik `/kota [Nama Kota]` untuk jadwal sholat.\n"
            "• Ketik `/masuk <jumlah>` untuk catat pemasukan.\n"
            "• Ketik `/saldo` untuk cek saldo.\n\n"
            "🔔 **Langganan:**"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Langganan Dzikir Pagi & Sore", callback_data="run_sub_dzikir")],
            [InlineKeyboardButton("✅ Langganan Inspirasi Doa Mingguan", callback_data="run_sub_weekly")],
            [InlineKeyboardButton("❌ Berhenti Berlangganan", callback_data="run_unsubscribe")],
            [InlineKeyboardButton("📞 Hubungi Admin Support", url="https://wa.me/6282199991748")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")],
        ]

    elif data == "menu_about":
        text = (
            "ℹ️ **TENTANG PLATFORM RAUDHA**\n\n"
            "Bot Raudha adalah asisten virtual penyelarasan tiga esensi kehidupan Ummat:\n"
            "🌱 Mitra Alam - Menanam amal jariah lewat alam, 🏛️ Arsitektur - menciptakan tempat ibadah yang nyaman, 🤲 Spiritualitas - manfaatkan sarana teknologi untuk kemudahan ibadah."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]

    elif data == "menu_quick_links":
        text = (
            "🚀 *PINTU LAYANAN UTAMA*\n\n"
            "Silakan pilih layanan yang ingin Anda akses langsung:\n\n"
            "💰 *Kalkulator Zakat & Asisten Spiritual*\n"
            "Hitung zakat, kelola harta, dan tunaikan kewajiban Anda.\n\n"
            "🏛️ *Daftarkan Lembaga Amil Zakat*\n"
            "Gabung sebagai mitra penyalur zakat resmi difasilitasi Aplikasi Raudha.\n\n"
            "🧾 *Bayar Tagihan & Cicilan*\n"
            "Kelola listrik, air, internet, dan hutang Anda."
        )
        keyboard = [
            [InlineKeyboardButton("💰 Buka Kalkulator Zakat", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=zakat&ngrok-skip-browser-warning=true&t={int(time.time())}"))],
            [InlineKeyboardButton("🏛️ Daftarkan Lembaga Amil", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=daftar&ngrok-skip-browser-warning=true&t={int(time.time())}"))],
            [InlineKeyboardButton("🧾 Buka Tagihan", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=tagihan&ngrok-skip-browser-warning=true&t={int(time.time())}"))],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    else:
        text = "Menu tidak ditemukan."
        keyboard = [[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit(query, text, reply_markup)


async def handle_ekonomi_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk sub-menu Ekonomi Ummat."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    # --- 1. CEK SALDO BMT ---
    if data == "run_saldo_bmt":
        try:
            import requests
            r = requests.get(f"{MINI_APP_URL}/api/bot/laporan/{user_id}", timeout=15)
            d = r.json()
            if d.get("status") == "success":
                laporan = d.get("laporan", {})
                saldo_idr = laporan.get("saldo_bmt_idr", 0)
                saldo_emas = laporan.get("saldo_bmt_emas", 0)
                
                text = (
                    f"🪙 *SALDO BMT ANDA*\n\n"
                    f"💰 Saldo Rupiah: *Rp {int(saldo_idr):,}*\n".replace(",", ".") +
                    f"⚖️ Saldo Emas: *{saldo_emas:.4f} gram*\n\n"
                    f"ℹ️ _Saldo ini adalah estimasi dari data yang tersimpan di sistem Raudha._"
                )
            else:
                text = "❌ Gagal mengambil data saldo."
        except Exception as e:
            text = f"❌ Error: {e}"
            
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Ekonomi", callback_data="menu_ekonomi")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- 2. DAFTAR TAGIHAN ---
    elif data == "run_tagihan":
        try:
            import requests
            r = requests.get(f"{MINI_APP_URL}/api/bot/tagihan/{user_id}", timeout=15)
            d = r.json()
            if d.get("status") == "success":
                tagihan_list = d.get("tagihan", [])
                belum_lunas = [t for t in tagihan_list if t.get("status") in ["belum_lunas", "terlambat"]]
                
                if not belum_lunas:
                    text = "✅ *Tidak ada tagihan yang belum lunas.*"
                else:
                    text = "🧾 *DAFTAR TAGIHAN BELUM LUNAS*\n\n"
                    for t in belum_lunas:
                        nominal = f"Rp {int(t['nominal']):,}".replace(",", ".")
                        status_icon = "⚠️" if t['status'] == "terlambat" else "⏳"
                        text += f"{status_icon} *{t['nama']}*\n   {nominal} — Jatuh tempo: {t.get('jatuh_tempo', '-')}\n\n"
                    text += "💡 _Buka Mini App untuk membayar tagihan._"
            else:
                text = "❌ Gagal mengambil data tagihan."
        except Exception as e:
            text = f"❌ Error: {e}"
            
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Ekonomi", callback_data="menu_ekonomi")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- 3. LAPORAN ZAKAT RINGKAS ---
    elif data == "run_laporan":
        try:
            import requests
            r = requests.get(f"{MINI_APP_URL}/api/bot/laporan/{user_id}", timeout=15)
            d = r.json()
            if d.get("status") == "success":
                l = d.get("laporan", {})
                text = (
                    f"📊 *LAPORAN ZAKAT RINGKAS*\n\n"
                    f"💰 Total Harta: *Rp {int(l.get('total_harta', 0)):,}*\n".replace(",", ".") +
                    f"📉 Zakat Maal: *Rp {int(l.get('zakat_maal_wajib', 0)):,}*\n".replace(",", ".") +
                    f"🌾 Zakat Tani: *Rp {int(l.get('zakat_tani', 0)):,}*\n".replace(",", ".") +
                    f"📿 Khumus: *Rp {int(l.get('total_khumus', 0)):,}*\n".replace(",", ".") +
                    f"\nℹ️ Status Haul: {'✅ Terpenuhi' if l.get('haul_terpenuhi') else '⏳ Belum'}\n"
                    f"💡 _Buka Mini App untuk detail lengkap._"
                )
            else:
                text = "❌ Gagal mengambil data laporan."
        except Exception as e:
            text = f"❌ Error: {e}"
            
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Ekonomi", callback_data="menu_ekonomi")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- 4. INFO LAYANAN GABUNGAN (WACANA) ---
    elif data == "sub_info_ekonomi":
        text = (
            "🏦 *INFO LAYANAN EKONOMI UMMAT*\n\n"
            "Raudha mengintegrasikan tiga pilar ekonomi:\n\n"
            "🕌 *LAZIS Raudha*\n"
            "Penggalangan zakat, infaq, dan sedekah secara digital. Zakat dapat dihitung dan disetor langsung melalui Mini App.\n\n"
            "🏦 *BMT Raudha*\n"
            "Layanan simpanan syariah (mudharabah) dan pembiayaan mikro. Saat ini bekerja sama dengan BTM Banjarnegara dan Koperasi Wanita Fathimah.\n\n"
            "⚜️ *Gerai Emas (Rencana)*\n"
            "Integrasi dengan penyedia emas resmi (Dinaran/Mentari Koin) untuk simpanan emas fisik yang aman, bebas riba, dan tahan inflasi."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Ekonomi", callback_data="menu_ekonomi")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')   


# =====================================================================
# 10. HANDLER KOTA & SHOLAT (MANUAL)
# =====================================================================

PATH_DATA_KOTA = os.path.join(BASE_DIR, "data_kota.json")
_cache_data_kota = {"mtime": None, "data": None}


def norm_nama(nama):
    return re.sub(r"[^a-z0-9]", "", str(nama).lower())


def slugify(nama):
    return re.sub(r"[^a-z0-9]+", "_", str(nama).strip().lower()).strip("_")


def escape_md(s):
    out = str(s)
    for ch in ("\\", "_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


def _muat_data_kota():
    try:
        mtime = os.path.getmtime(PATH_DATA_KOTA)
    except OSError:
        return []
    if _cache_data_kota["mtime"] == mtime and _cache_data_kota["data"] is not None:
        return _cache_data_kota["data"]
    try:
        with open(PATH_DATA_KOTA, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if not content:
            return []
        hasil = None
        try:
            data = json.loads(content)
            if isinstance(data, list):
                hasil = data
        except json.JSONDecodeError:
            pass
        if hasil is None:
            hasil = []
            for line in content.splitlines():
                line = line.strip().rstrip(",")
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and "nama" in obj:
                        hasil.append(obj)
                except json.JSONDecodeError:
                    continue
        _cache_data_kota.update({"mtime": mtime, "data": hasil})
        return hasil
    except Exception as e:
        logger.error(f"Gagal muat data kota: {e}")
        return []

async def handle_command_kota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
        
    if not context.args:
        await update.message.reply_text(
            "⚠️ Silakan masukkan nama kota.\n"
            "👉 Contoh: `/kota Banjarnegara` atau `/kota Danakerta`",
            parse_mode='Markdown'
        )
        return

    nama_cari = " ".join(context.args).strip()
    logger.info(f"[BOT] Mencari kota: {nama_cari}")
    
    try:
        # 1. Cari kota di database
        kota = cari_kota(nama_cari)
        
        if not kota:
            await update.message.reply_text(
                f"❌ Kota '{nama_cari}' tidak terdaftar di database lokal.\n"
                f"💡 Coba periksa ejaan huruf Anda (Contoh: Jakarta, Bogor, Purwokerto)."
            )
            return

        # 2. Ambil jadwal dari Aladhan API
        timings = get_jadwal(kota["lat"], kota["lng"])
        
        # 3. SUSUN PESAN LANGSUNG DI SINI (Tanpa memanggil format_jadwal)
        teks_balasan = (
            f"🕌 *JADWAL SHOLAT — {kota['nama'].upper()}*\n"
            f"🏙️ _Provinsi: {kota.get('provinsi', '-')}_\n"
            f"📅 _Tanggal: {_dt.now().strftime('%d %B %Y')}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌌 *SUBUH*     :  `{timings.get('Fajr', '--:--')}`\n"
            f"🌅 *SYURUQ*    :  `{timings.get('Sunrise', '--:--')}`\n"
            f"☀️ *DZUHUR*    :  `{timings.get('Dhuhr', '--:--')}`\n"
            f"🌇 *ASHAR*     :  `{timings.get('Asr', '--:--')}`\n"
            f"🌆 *MAGHRIB*   :  `{timings.get('Maghrib', '--:--')}`\n"
            f"🌃 *ISYA*      :  `{timings.get('Isha', '--:--')}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 _Sumber: Aladhan API_"
        )

        # 4. Kirim ke user
        await safe_reply(update.message, teks_balasan)
        logger.info(f"[BOT] Sukses mengirim jadwal untuk {nama_cari}")
        
    except Exception as e:
        # JIKA GAGAL, BOT AKAN BERTERIAK DI CHAT & TERMINAL
        error_msg = f"❌ *ERROR SISTEM:*\n`{str(e)}`"
        logger.error(f"[BOT] Gagal memproses /kota {nama_cari}: {e}")
        await update.message.reply_text(error_msg, parse_mode='Markdown')

async def handle_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler saat user kirim lokasi GPS.
    - Simpan lokasi ke database
    - Tampilkan jadwal sholat (Aladhan API)
    - Tawarkan masjid terdekat untuk di-subscribe
    """
    if not update.message or not update.message.location:
        return
    user_loc = update.message.location
    lat, lng = user_loc.latitude, user_loc.longitude
    telegram_id = update.effective_user.id

    # 1. Simpan ke DB
    try:
        simpan_lokasi_user(telegram_id, lat, lng, kota="Lokasi GPS", sumber="gps")
    except Exception as e:
        logger.error(f"Gagal cari masjid terdekat: {e}")
        import traceback
        traceback.print_exc()
        await safe_reply(update.message, f"⚠️ Gagal mencari masjid terdekat: {e}")

    # 2. Ambil jadwal dari API Aladhan
    try:
        timings = get_jadwal(lat, lng)
        teks_jadwal = (
            f"🕌 *JADWAL SHOLAT LOKASI ANDA*\n"
            f"📍 _Koordinat: {lat:.4f}, {lng:.4f}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌌 *Subuh*   : `{timings['Fajr']}`\n"
            f"🌅 *Syuruq*  : `{timings['Sunrise']}`\n"
            f"☀️ *Dzuhur*  : `{timings['Dhuhr']}`\n"
            f"🌇 *Ashar*   : `{timings['Asr']}`\n"
            f"🌆 *Maghrib* : `{timings['Maghrib']}`\n"
            f"🌃 *Isya*    : `{timings['Isha']}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Sumber: Aladhan API (Otomatis)_"
        )
        await safe_reply(update.message, teks_jadwal)
    except Exception as e:
        logger.error(f"Gagal ambil jadwal GPS: {e}")
        await safe_reply(update.message, "⚠️ Maaf, gagal mengambil jadwal sholat dari satelit.")

    # 3. Tawarkan masjid terdekat untuk di-subscribe
    try:
        masjids = masjid_terdekat(lat, lng, radius_km=15, limit=5)
        
        if masjids:
            text = "🕌 **Masjid di Sekitar Anda:**\n\n"
            text += "Klik untuk mengikuti info kesehatan, kajian, dan kegiatan dari masjid tersebut:\n\n"
            keyboard = []
            for m in masjids:
                icon = "⭐" if m.get('tipe_masjid') == 'raudha' else "•"
                keyboard.append([
                    InlineKeyboardButton(
                        f"{icon} {m['nama']} ({m['jarak']} km)",
                        callback_data=f"pilih_masjid_{m['id']}"
                    )
                ])
            keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")])
            
            await safe_reply(update.message, text, InlineKeyboardMarkup(keyboard))
        else:
            await safe_reply(update.message, "😔 Tidak ada masjid dalam radius 15 km.")
    except Exception as e:
        logger.warning(f"Gagal cari masjid terdekat: {e}")
        await safe_reply(update.message, "⚠️ Gagal mencari masjid terdekat.")

# =====================================================================
# 11. HANDLER SUB-ACTION (Morning, Doa, Subscribe)
# =====================================================================

async def handle_morning_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "run_dzikir_pagi":
        teks = (
            "📿 *DZIKIR PAGI SINGKAT*\n\n"
            "أَصْبَحْنَا وَأَصْبَحَ الْمُلْكُ لِلَّهِ وَالْحَمْدُ لِلَّهِ لَا إِلَهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ\n\n"
            "_Artinya: Kami memasuki waktu pagi dan kerajaan hanya milik Allah. "
            "Segala puji bagi Allah, tidak ada Tuhan selain Allah yang Maha Esa, tiada sekutu bagi-Nya._"
        )
    else:
        teks = (
            "📜 *INSPIRASI PAGI INI*\n\n"
            "_\"Janganlah engkau berduka atas apa yang telah berlalu, karena setiap hari baru "
            "membawa ribuan lembar kain putih bersih yang siap engkau lukis dengan tinta kebaikan.\"_ "
            "— Raudha Wasiat Pagi"
        )
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]]
    await safe_edit(query, teks, InlineKeyboardMarkup(keyboard))


async def handle_doa_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    nama_doa = data.replace("run_doa_", "")

    teks_doa = (
        f"📖 *AMALAN DOA {escape_md(nama_doa.upper())} — HALAMAN 1*\n\n"
        "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ\n\n"
        "_Memuat teks bacaan latin dan arti dari folder data_doa..._\n\n"
        "💡 _Tips: Tekan tombol Selanjutnya di bawah untuk membalik lembaran halaman teks doa._"
    )
    keyboard = [
        [InlineKeyboardButton("Selanjutnya ➡️", callback_data=f"{nama_doa}_hal2")],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="sub_doa_pilihan")],
    ]
    await safe_edit(query, teks_doa, InlineKeyboardMarkup(keyboard))


async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(
        query,
        "✅ *Pendaftaran Berhasil!* Anda kini resmi berlangganan broadcast limpahan "
        "fadhilah dzikir harian dari Komunitas Raudha."
    )

# =====================================================================
# HANDLER: MITRA ALAM — TENTANG PROGRAM
# =====================================================================

async def handle_mitra_alam_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Halaman 'Tentang Program' Mitra Alam."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📖 *TENTANG RAUDHA MITRA ALAM*\n\n"
        "Program wakaf produktif berbasis teknologi NFC yang "
        "menghubungkan empat pihak:\n\n"
        "👤 *Muwakif* — jamaah pemberi wakaf\n"
        "🕌 *Masjid/Pesantren* — penerima manfaat (mauquf 'alaih)\n"
        "🌍 *Lahan* — pekarangan masjid / lahan wakaf\n"
        "📡 *Teknologi* — NFC tag di setiap pohon untuk transparansi\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Skema Bagi Hasil Panen:*\n"
        "• 70% → Masjid/Pesantren\n"
        "• 20% → Biaya Perawatan & Operasional\n"
        "• 10% → Pengelolaan Raudha\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Komoditas:*\n"
        "🌴 Kurma Hibrida • ☕ Kopi Wulung • 🪵 Kayu Jati • "
        "🪵 Kayu Balsa • 🌴 Aren\n\n"
        "_Wakaf tidak mengurangi pahala — justru menambah amal jariyah "
        "yang mengalir terus-menerus._"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Mitra Alam",
                                       callback_data="menu_tanam")]]
    await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

# =====================================================================
# NOTIFIKASI REAL-TIME (Batch 7)
# =====================================================================

DB_PATH = os.path.join("data", "raudha.db")
if not os.path.exists(os.path.dirname(DB_PATH)):
    DB_PATH = "raudha.db"


def get_admin_ids_lembaga(lembaga_id):
    """Ambil semua user_id admin lembaga (yang aktif)."""
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT user_id FROM users_config
                 WHERE lembaga_id=? AND role='admin_lembaga' AND status='active'""",
              (lembaga_id,))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def get_nama_lembaga(lembaga_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT nama FROM lembaga_amil WHERE id=?", (lembaga_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else "Lembaga"


def get_nama_user(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT nama_lengkap FROM users_config WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0] if row and row[0] else f"User #{user_id}")


async def cek_pembayaran_baru(context: ContextTypes.DEFAULT_TYPE):
    """Polling setiap 30 detik: cek pembayaran baru (status=dibayar) yang belum dinotifikasi."""
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        
        # Cek tabel notif_log — kalau belum ada, buat
        c.execute("""CREATE TABLE IF NOT EXISTS notif_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipe TEXT, ref_id INTEGER, target_user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tipe, ref_id, target_user_id)
        )""")
        
        # Cari pembayaran 'dibayar' yang belum dinotifikasi
        c.execute("""SELECT rp.id, rp.user_id, rp.lembaga_id, rp.nominal, rp.jenis_kewajiban
                     FROM rencana_pembayaran rp
                     WHERE rp.status='dibayar'
                       AND NOT EXISTS (
                         SELECT 1 FROM notif_log nl 
                         WHERE nl.tipe='pembayaran_baru' 
                           AND nl.ref_id = rp.id
                       )
                     LIMIT 5""")
        rows = c.fetchall()
        conn.close()
        
        for rencana_id, user_id, lembaga_id, nominal, jenis in rows:
            # Kirim ke semua admin lembaga
            admin_ids = get_admin_ids_lembaga(lembaga_id)
            nama_lembaga = get_nama_lembaga(lembaga_id)
            nama_user = get_nama_user(user_id)
            nominal_str = f"Rp {int(nominal):,}".replace(",", ".")
            jenis_str = (jenis or "").replace("_", " ").upper()
            
            for admin_id in admin_ids:
                # Skip kalau admin = pembuat (tidak perlu notif ke diri sendiri)
                if admin_id == user_id:
                    continue
                try:
                    teks = (
                        f"💰 *Pembayaran Baru Masuk!*\n\n"
                        f"🏛️ Lembaga: *{nama_lembaga}*\n"
                        f"👤 Dari: {nama_user}\n"
                        f"📋 Jenis: {jenis_str}\n"
                        f"💵 Nominal: *{nominal_str}*\n\n"
                        f"🔗 Silakan buka Mini App untuk verifikasi."
                    )
                    await context.bot.send_message(
                        chat_id=admin_id, text=teks, parse_mode='Markdown'
                    )
                    logger.info(f"[NOTIF] Pembayaran #{rencana_id} → admin {admin_id}")
                except Exception as e:
                    logger.warning(f"[NOTIF] Gagal kirim ke {admin_id}: {e}")
            
            # Catat notif_log
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            for admin_id in admin_ids:
                if admin_id == user_id:
                    continue
                try:
                    c.execute("""INSERT OR IGNORE INTO notif_log
                                 (tipe, ref_id, target_user_id)
                                 VALUES ('pembayaran_baru', ?, ?)""",
                              (rencana_id, admin_id))
                except Exception as e:
                    logger.warning(f"notif_log error: {e}")
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"[NOTIF] cek_pembayaran_baru error: {e}")


async def cek_pembayaran_diverifikasi(context: ContextTypes.DEFAULT_TYPE):
    """Polling: cek pembayaran 'diverifikasi' yang belum dinotifikasi ke user."""
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        
        c.execute("""CREATE TABLE IF NOT EXISTS notif_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipe TEXT, ref_id INTEGER, target_user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tipe, ref_id, target_user_id)
        )""")
        
        c.execute("""SELECT rp.id, rp.user_id, rp.lembaga_id, rp.nominal, rp.jenis_kewajiban
                     FROM rencana_pembayaran rp
                     WHERE rp.status='diverifikasi'
                       AND NOT EXISTS (
                         SELECT 1 FROM notif_log nl 
                         WHERE nl.tipe='pembayaran_diverifikasi' 
                           AND nl.ref_id = rp.id
                       )
                     LIMIT 5""")
        rows = c.fetchall()
        conn.close()
        
        for rencana_id, user_id, lembaga_id, nominal, jenis in rows:
            nama_lembaga = get_nama_lembaga(lembaga_id)
            nominal_str = f"Rp {int(nominal):,}".replace(",", ".")
            jenis_str = (jenis or "").replace("_", " ").upper()
            
            try:
                teks = (
                    f"✅ *Pembayaran Diverifikasi!*\n\n"
                    f"🏛️ Lembaga: *{nama_lembaga}*\n"
                    f"📋 Jenis: {jenis_str}\n"
                    f"💵 Nominal: *{nominal_str}*\n\n"
                    f"🎉 Terima kasih, zakat Anda telah disalurkan.\n"
                    f"Semoga menjadi amal jariyah. 🤲"
                )
                await context.bot.send_message(
                    chat_id=user_id, text=teks, parse_mode='Markdown'
                )
                logger.info(f"[NOTIF] Verifikasi #{rencana_id} → user {user_id}")
                
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("""INSERT OR IGNORE INTO notif_log
                             (tipe, ref_id, target_user_id)
                             VALUES ('pembayaran_diverifikasi', ?, ?)""",
                          (rencana_id, user_id))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"[NOTIF] Gagal kirim ke {user_id}: {e}")
    except Exception as e:
        logger.error(f"[NOTIF] cek_pembayaran_diverifikasi error: {e}")

# =====================================================================
# NOTIFIKASI WAKAF POHON (MITRA ALAM) — STEP 7
# =====================================================================

async def cek_wakaf_diverifikasi(context: ContextTypes.DEFAULT_TYPE):
    """Polling: notifikasi khusus wakaf pohon yang sudah diverifikasi."""
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        
        c.execute("""CREATE TABLE IF NOT EXISTS notif_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipe TEXT, ref_id INTEGER, target_user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tipe, ref_id, target_user_id)
        )""")
        
        c.execute("""SELECT rp.id, rp.user_id, rp.nominal, rp.keterangan, rp.lembaga_id
                     FROM rencana_pembayaran rp
                     WHERE rp.jenis_kewajiban='wakaf_pohon'
                       AND rp.status='diverifikasi'
                       AND NOT EXISTS (
                         SELECT 1 FROM notif_log nl 
                         WHERE nl.tipe='wakaf_diverifikasi' 
                           AND nl.ref_id = rp.id
                       )
                     LIMIT 5""")
        rows = c.fetchall()
        conn.close()
        
        for rencana_id, user_id, nominal, keterangan, lembaga_id in rows:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("SELECT nama FROM lembaga_amil WHERE id=?", (lembaga_id,))
            row_lem = c.fetchone()
            nama_lembaga = row_lem[0] if row_lem else "Lembaga"
            
            c.execute("""SELECT COUNT(*) FROM pohon_wakaf 
                         WHERE rencana_id=? AND status='aktif'""", (rencana_id,))
            jumlah_pohon = c.fetchone()[0]
            
            c.execute("""SELECT k.nama_display FROM pohon_wakaf p
                         JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                         WHERE p.rencana_id=? LIMIT 1""", (rencana_id,))
            row_kom = c.fetchone()
            nama_komoditas = row_kom[0] if row_kom else "Pohon"
            conn.close()
            
            nominal_str = f"Rp {int(nominal):,}".replace(",", ".")
            
            try:
                teks = (
                    f"🎉 *Wakaf Anda Diverifikasi!*\n\n"
                    f"📋 Transaksi: `#{rencana_id}`\n"
                    f"🌱 Komoditas: *{nama_komoditas}*\n"
                    f"🏛️ Lembaga: *{nama_lembaga}*\n"
                    f"💰 Nominal: *{nominal_str}*\n"
                    f"🌳 Jumlah Pohon: *{jumlah_pohon} pohon*\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✅ *Pembayaran telah diverifikasi*\n"
                    f"🌳 Pohon akan segera ditanam & diberi NFC tag\n"
                    f"📸 Anda akan menerima foto pohon + sertifikat\n"
                    f"🌾 Hasil panen: 70% masjid, 20% perawatan, 10% pengelolaan\n\n"
                    f"_Jazakallahu khairan. Amal jariyah Anda sedang berjalan._ 🤲"
                )
                await context.bot.send_message(
                    chat_id=user_id, text=teks, parse_mode='Markdown'
                )
                logger.info(f"[NOTIF-WAKAF] Verifikasi #{rencana_id} → user {user_id}")
                
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("""INSERT OR IGNORE INTO notif_log
                             (tipe, ref_id, target_user_id)
                             VALUES ('wakaf_diverifikasi', ?, ?)""",
                          (rencana_id, user_id))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"[NOTIF-WAKAF] Gagal kirim ke {user_id}: {e}")
    except Exception as e:
        logger.error(f"[NOTIF-WAKAF] cek_wakaf_diverifikasi error: {e}")


async def cek_wakaf_bukti_baru(context: ContextTypes.DEFAULT_TYPE):
    """Polling: notifikasi ke admin lembaga saat ada bukti wakaf baru."""
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        
        c.execute("""CREATE TABLE IF NOT EXISTS notif_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipe TEXT, ref_id INTEGER, target_user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tipe, ref_id, target_user_id)
        )""")
        
        c.execute("""SELECT rp.id, rp.user_id, rp.nominal, rp.lembaga_id
                     FROM rencana_pembayaran rp
                     WHERE rp.jenis_kewajiban='wakaf_pohon'
                       AND rp.status='dibayar'
                       AND NOT EXISTS (
                         SELECT 1 FROM notif_log nl 
                         WHERE nl.tipe='wakaf_bukti_baru' 
                           AND nl.ref_id = rp.id
                       )
                     LIMIT 5""")
        rows = c.fetchall()
        conn.close()
        
        for rencana_id, user_id, nominal, lembaga_id in rows:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("""SELECT user_id, nama_lengkap FROM users_config 
                         WHERE lembaga_id=? AND role='admin_lembaga' AND status='active'""",
                      (lembaga_id,))
            admin_rows = c.fetchall()
            
            c.execute("SELECT nama FROM lembaga_amil WHERE id=?", (lembaga_id,))
            row_lem2 = c.fetchone()
            nama_lembaga = row_lem2[0] if row_lem2 else "Lembaga"
            
            c.execute("SELECT nama_lengkap FROM users_config WHERE user_id=?", (user_id,))
            row_user = c.fetchone()
            nama_user = row_user[0] if row_user else f"User #{user_id}"
            conn.close()
            
            nominal_str = f"Rp {int(nominal):,}".replace(",", ".")
            
            for admin_id, admin_nama in admin_rows:
                if admin_id == user_id:
                    continue
                try:
                    teks = (
                        f"💰 *Bukti Transfer Wakaf Baru!*\n\n"
                        f"📋 Transaksi: `#{rencana_id}`\n"
                        f"👤 Dari: {nama_user}\n"
                        f"🏛️ Lembaga: *{nama_lembaga}*\n"
                        f"💵 Nominal: *{nominal_str}*\n\n"
                        f"🔗 Buka Mini App → Dashboard Admin → 🌱 Verifikasi Wakaf"
                    )
                    await context.bot.send_message(
                        chat_id=admin_id, text=teks, parse_mode='Markdown'
                    )
                    logger.info(f"[NOTIF-WAKAF] Bukti #{rencana_id} → admin {admin_id}")
                except Exception as e:
                    logger.warning(f"[NOTIF-WAKAF] Gagal ke {admin_id}: {e}")
            
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            for admin_id, _ in admin_rows:
                if admin_id == user_id:
                    continue
                c.execute("""INSERT OR IGNORE INTO notif_log
                             (tipe, ref_id, target_user_id)
                             VALUES ('wakaf_bukti_baru', ?, ?)""",
                          (rencana_id, admin_id))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"[NOTIF-WAKAF] cek_wakaf_bukti_baru error: {e}")


async def cek_pengajuan_lembaga_baru(context: ContextTypes.DEFAULT_TYPE):
    """Polling: cek pengajuan lembaga baru (status=pending) yang belum dinotifikasi."""
    if not ADMIN_ID:
        return
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        
        c.execute("""CREATE TABLE IF NOT EXISTS notif_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipe TEXT, ref_id INTEGER, target_user_id INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tipe, ref_id, target_user_id)
        )""")
        
        c.execute("""SELECT l.id, l.nama, l.jenis, l.created_by
                     FROM lembaga_amil l
                     WHERE l.status='pending'
                       AND NOT EXISTS (
                         SELECT 1 FROM notif_log nl 
                         WHERE nl.tipe='pengajuan_lembaga' 
                           AND nl.ref_id = l.id
                       )
                     LIMIT 5""")
        rows = c.fetchall()
        conn.close()
        
        for lembaga_id, nama, jenis, created_by in rows:
            try:
                teks = (
                    f"🏛️ *Pengajuan Lembaga Baru!*\n\n"
                    f"📛 Nama: *{nama}*\n"
                    f"🏷️ Jenis: {jenis}\n"
                    f"👤 Diajukan oleh: {get_nama_user(created_by)}\n\n"
                    f"🔗 Buka Mini App → tab Admin untuk verifikasi."
                )
                await context.bot.send_message(
                    chat_id=ADMIN_ID, text=teks, parse_mode='Markdown'
                )
                logger.info(f"[NOTIF] Pengajuan lembaga #{lembaga_id} → super admin")
                
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("""INSERT OR IGNORE INTO notif_log
                             (tipe, ref_id, target_user_id)
                             VALUES ('pengajuan_lembaga', ?, ?)""",
                          (lembaga_id, ADMIN_ID))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"[NOTIF] Gagal kirim ke super admin: {e}")
    except Exception as e:
        logger.error(f"[NOTIF] cek_pengajuan_lembaga_baru error: {e}")

# =====================================================================
# BACKUP OTOMATIS (Batch 16a)
# =====================================================================

async def backup_database(context: ContextTypes.DEFAULT_TYPE):
    """
    Backup database harian.
    - Copy file DB ke folder backups/ dengan timestamp.
    - Hapus backup lama (> MAX_BACKUP_DAYS).
    - Kirim ke admin via Telegram (opsional).
    """
    try:
        if not os.path.exists(DB_PATH):
            logger.error(f"[BACKUP] File DB tidak ditemukan: {DB_PATH}")
            return
        
        # 1. Nama file backup dengan timestamp
        timestamp = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_filename = f"raudha_{timestamp}.db"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        # 2. Copy file
        shutil.copy2(DB_PATH, backup_path)
        file_size = os.path.getsize(backup_path) / 1024 / 1024  # MB
        logger.info(f"[BACKUP] Berhasil: {backup_filename} ({file_size:.2f} MB)")
        
        # 3. Hapus backup lama (> MAX_BACKUP_DAYS hari)
        cutoff = _dt.now().timestamp() - (MAX_BACKUP_DAYS * 86400)
        deleted_count = 0
        for f in os.listdir(BACKUP_DIR):
            if not f.startswith("raudha_") or not f.endswith(".db"):
                continue
            fpath = os.path.join(BACKUP_DIR, f)
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted_count += 1
                logger.info(f"[BACKUP] Dihapus (lama): {f}")
        
        if deleted_count > 0:
            logger.info(f"[BACKUP] {deleted_count} backup lama dihapus")
        
        # 4. Kirim ke admin (kalau ADMIN_ID di-set)
        if ADMIN_ID:
            try:
                # Kirim file backup
                with open(backup_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=ADMIN_ID,
                        document=f,
                        filename=backup_filename,
                        caption=(
                            f"🗄️ *Backup Harian Raudha*\n\n"
                            f"📅 Tanggal: {_dt.now().strftime('%d %B %Y, %H:%M WIB')}\n"
                            f"📦 Ukuran: {file_size:.2f} MB\n"
                            f"🗂️ Total backup tersimpan: {len([x for x in os.listdir(BACKUP_DIR) if x.endswith('.db')])}\n\n"
                            f"_Backup ini untuk keamanan data. Simpan dengan baik._"
                        ),
                        parse_mode='Markdown'
                    )
                logger.info(f"[BACKUP] Terkirim ke admin {ADMIN_ID}")
            except Exception as e:
                logger.warning(f"[BACKUP] Gagal kirim ke admin: {e}")
        
    except Exception as e:
        logger.error(f"[BACKUP] Error: {e}")


# =====================================================================
# BACKUP MINGGUAN PERMANEN + EMAIL
# =====================================================================

def kirim_email_backup(filepath, filename):
    """Kirim file backup via email. Return True kalau sukses."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
        logger.warning("[EMAIL] SMTP belum dikonfigurasi, skip")
        return False

    try:
        size_mb = os.path.getsize(filepath) / 1024 / 1024

        msg = MIMEMultipart()
        msg['From']    = SMTP_USER
        msg['To']      = SMTP_TO
        msg['Subject'] = f"🗄️ Backup Raudha Mingguan — {filename}"
        msg.attach(MIMEText(
            f"Assalamu'alaikum,\n\n"
            f"Backup database Raudha otomatis (mingguan).\n\n"
            f"📅 Tanggal : {_dt.now().strftime('%d %B %Y, %H:%M WIB')}\n"
            f"📦 Ukuran  : {size_mb:.2f} MB\n"
            f"📄 File    : {filename}\n\n"
            f"File terlampir. Simpan di tempat aman.\n\n"
            f"— Raudha Spiritual Accountant",
            'plain', 'utf-8'
        ))

        with open(filepath, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        logger.info(f"[EMAIL] Backup terkirim ke {SMTP_TO}")
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Gagal kirim backup: {e}")
        return False


async def backup_mingguan(context: ContextTypes.DEFAULT_TYPE):
    """
    Backup mingguan permanen:
    - Copy DB ke backups_weekly/ (tidak pernah dihapus)
    - Kirim ke admin via Telegram
    - Kirim ke email via SMTP
    """
    try:
        if not os.path.exists(DB_PATH):
            logger.error(f"[BACKUP-MINGGUAN] DB tidak ditemukan: {DB_PATH}")
            return

        timestamp = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename  = f"raudha_weekly_{timestamp}.db"
        filepath  = os.path.join(BACKUP_WEEKLY_DIR, filename)

        shutil.copy2(DB_PATH, filepath)
        size_mb      = os.path.getsize(filepath) / 1024 / 1024
        total_weekly = len([x for x in os.listdir(BACKUP_WEEKLY_DIR) if x.endswith('.db')])
        logger.info(f"[BACKUP-MINGGUAN] {filename} ({size_mb:.2f} MB) — total {total_weekly} file")

        # 1. Kirim ke admin via Telegram
        if ADMIN_ID:
            try:
                with open(filepath, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=ADMIN_ID,
                        document=f,
                        filename=filename,
                        caption=(
                            f"🗄️ *Backup Mingguan Permanen*\n\n"
                            f"📅 {_dt.now().strftime('%d %B %Y, %H:%M WIB')}\n"
                            f"📦 {size_mb:.2f} MB\n"
                            f"🗂️ Total backup mingguan: {total_weekly} file\n\n"
                            f"_Backup ini tidak akan dihapus otomatis._"
                        ),
                        parse_mode='Markdown'
                    )
                logger.info(f"[BACKUP-MINGGUAN] Terkirim ke admin {ADMIN_ID}")
            except Exception as e:
                logger.warning(f"[BACKUP-MINGGUAN] Gagal kirim Telegram: {e}")

        # 2. Kirim via email
        kirim_email_backup(filepath, filename)

    except Exception as e:
        logger.error(f"[BACKUP-MINGGUAN] Error: {e}")


# =====================================================================
# COMMAND BACKUP — HARIAN, LIST, MINGGUAN, TEST EMAIL
# =====================================================================

async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /backup — backup harian manual."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return

    await update.message.reply_text("⏳ Memulai backup...")
    await backup_database(context)
    await update.message.reply_text("✅ Backup selesai. Cek chat untuk file backup.")


async def cmd_list_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /listbackup — lihat daftar backup harian."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return

    try:
        files = [f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')]
        files.sort(reverse=True)

        if not files:
            await update.message.reply_text("📭 Belum ada backup.")
            return

        text = f"🗄️ *Daftar Backup Harian ({len(files)})*\n\n"
        for f in files[:10]:
            fpath = os.path.join(BACKUP_DIR, f)
            size  = os.path.getsize(fpath) / 1024 / 1024
            mtime = _dt.fromtimestamp(os.path.getmtime(fpath)).strftime('%d/%m/%Y %H:%M')
            text += f"• `{f}`\n  {size:.2f} MB — {mtime}\n\n"

        if len(files) > 10:
            text += f"_... dan {len(files) - 10} lainnya_"

        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_backup_mingguan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /backupmingguan — backup mingguan manual."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return

    await update.message.reply_text("⏳ Memulai backup mingguan...")
    await backup_mingguan(context)
    await update.message.reply_text("✅ Backup mingguan selesai. Cek chat & email.")


async def cmd_test_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /testemail — test koneksi SMTP."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return

    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, SMTP_TO]):
        await update.message.reply_text(
            "❌ SMTP belum dikonfigurasi di `.env`.\n\n"
            "Tambahkan:\n"
            "`SMTP_HOST=smtp.gmail.com`\n"
            "`SMTP_PORT=587`\n"
            "`SMTP_USER=raudhamitradana@gmail.com`\n"
            "`SMTP_PASS=xxxx xxxx xxxx xxxx`\n"
            "`SMTP_TO=raudharealty@gmail.com`",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text("⏳ Mengirim test email...")

    try:
        msg = MIMEMultipart()
        msg['From']    = SMTP_USER
        msg['To']      = SMTP_TO
        msg['Subject'] = "✅ Test Email — Raudha Backup"
        msg.attach(MIMEText(
            f"Test koneksi SMTP berhasil.\n\n"
            f"Dikirim: {_dt.now().strftime('%d %B %Y, %H:%M WIB')}\n\n"
            f"Backup otomatis mingguan akan dikirim ke email ini "
            f"setiap Minggu 00:05 WIB.",
            'plain', 'utf-8'
        ))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)

        await update.message.reply_text(
            f"✅ Test email terkirim ke `{SMTP_TO}`.",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Gagal kirim email:\n`{e}`",
            parse_mode='Markdown'
        )


# =====================================================================
# RESTORE DATABASE (Batch 16b)
# =====================================================================

restore_state = {}

async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /restore — mulai proses restore (2 langkah)."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return
    
    restore_state[user_id] = {"step": "awaiting_confirm"}
    
    text = (
        "⚠️ *PERINGATAN RESTORE DATABASE*\n\n"
        "Restore akan *MENIMPA SELURUH DATA*:\n"
        "• User & role\n"
        "• Jurnal zakat\n"
        "• Pembayaran\n"
        "• Tagihan\n"
        "• Lembaga\n\n"
        "Data lama akan *di-backup otomatis* sebelum restore.\n\n"
        "Ketik *KONFIRMASI RESTORE* untuk melanjutkan.\n"
        "Atau ketik /batal untuk membatalkan."
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_batal_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /batal — batalkan restore."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        return
    restore_state.pop(user_id, None)
    await update.message.reply_text("✅ Restore dibatalkan.")


async def handle_restore_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle konfirmasi 'KONFIRMASI RESTORE' dan file upload."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        return
    if user_id not in restore_state:
        return
    
    state = restore_state[user_id]
    
    if state["step"] == "awaiting_confirm":
        if update.message.text and update.message.text.strip() == "KONFIRMASI RESTORE":
            state["step"] = "awaiting_file"
            await update.message.reply_text(
                "✅ Konfirmasi diterima.\n\n"
                "📤 Silakan kirim *file .db* yang ingin di-restore.\n\n"
                "Ketik /batal untuk membatalkan.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ Konfirmasi salah. Ketik *KONFIRMASI RESTORE* (huruf besar).",
                parse_mode='Markdown'
            )
        return
    
    if state["step"] == "awaiting_file":
        if not update.message.document:
            await update.message.reply_text("❌ Kirim file .db sebagai dokumen.")
            return
        
        doc = update.message.document
        if not doc.file_name.endswith('.db'):
            await update.message.reply_text("❌ File harus berekstensi .db")
            return
        
        try:
            file = await context.bot.get_file(doc.file_id)
            timestamp = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
            temp_path = os.path.join(BACKUP_DIR, f"_temp_restore_{timestamp}.db")
            await file.download_to_drive(temp_path)
            logger.info(f"[RESTORE] File diunduh: {temp_path}")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal unduh file: {e}")
            return
        
        try:
            import sqlite3 as _sqlite3
            conn_test = _sqlite3.connect(temp_path)
            c_test = conn_test.cursor()
            c_test.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in c_test.fetchall()]
            conn_test.close()
            
            required_tables = ['users_config', 'jurnal_syariah', 'lembaga_amil', 'rencana_pembayaran', 'tagihan']
            missing = [t for t in required_tables if t not in tables]
            
            if missing:
                os.remove(temp_path)
                await update.message.reply_text(
                    f"❌ File tidak valid. Tabel hilang: {', '.join(missing)}"
                )
                restore_state.pop(user_id, None)
                return
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            await update.message.reply_text(f"❌ File SQLite tidak valid: {e}")
            restore_state.pop(user_id, None)
            return
        
        try:
            backup_filename = f"raudha_pre_restore_{timestamp}.db"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            shutil.copy2(DB_PATH, backup_path)
            logger.info(f"[RESTORE] Backup pre-restore: {backup_filename}")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal backup database lama: {e}")
            os.remove(temp_path)
            restore_state.pop(user_id, None)
            return
        
        try:
            shutil.move(temp_path, DB_PATH)
            logger.info(f"[RESTORE] Database diganti: {DB_PATH}")
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal replace database: {e}")
            restore_state.pop(user_id, None)
            return
        
        restore_state.pop(user_id, None)
        
        text = (
            "✅ *RESTORE BERHASIL!*\n\n"
            f"📅 Waktu: {_dt.now().strftime('%d %B %Y, %H:%M WIB')}\n"
            f"📦 File: `{doc.file_name}`\n"
            f"🗄️ Backup pre-restore: `{backup_filename}`\n\n"
            "⚠️ *Silakan restart bot & Flask* agar data baru terbaca."
        )
        await update.message.reply_text(text, parse_mode='Markdown')
        logger.info(f"[RESTORE] Sukses restore oleh admin {user_id}")




# =====================================================================
# 12. HANDLER WEB_APP_DATA — ACK INSTAN + DETAIL + FORWARD ADMIN
# =====================================================================

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dipanggil saat Mini App memanggil Telegram.WebApp.sendData().
    Alur:
      1. Kirim ACK INSTAN ke user (jangan sampai user lihat chat kosong).
      2. Parsing payload dengan toleransi.
      3. Kirim rincian ke user (terpisah try/except).
      4. Forward ke admin (terpisah try/except — tidak boleh ganggu user).
    """
    message = update.message
    if not message or not message.web_app_data:
        return

    data_mentah = message.web_app_data.data
    logger.info(f"[WEB_APP_DATA] Menerima payload: {data_mentah}")

    # --- LANGKAH 1: ACK INSTAN ---
    try:
        await message.reply_text(
            "✅ *Laporan Anda telah diterima!*\n"
            "🔄 Sistem sedang memverifikasi dan menyinkronkan dengan database pusat...\n"
            "_Mohon tunggu balasan rincian dalam beberapa detik._",
            parse_mode='Markdown',
        )
    except Exception as e:
        logger.error(f"Gagal kirim ACK ke user: {e}")

    # --- LANGKAH 2: PARSING PAYLOAD ---
    try:
        payload = json.loads(data_mentah)
    except json.JSONDecodeError as e:
        logger.error(f"Payload bukan JSON valid: {e}")
        try:
            await message.reply_text("❌ Format laporan tidak dikenali oleh sistem.")
        except Exception:
            pass
        return

    layanan = str(payload.get("layanan", "LAZIS"))
    zakat = _safe_int(payload.get("zakat"))
    khumus = _safe_int(payload.get("khumus"))

    # --- LANGKAH 3: KIRIM RINCIAN KE USER ---
    teks_laporan = (
        f"📥 *[NOTIFIKASI LAZIS RAUDHA]*\n\n"
        f"Rincian deklarasi kepatuhan finansial syariah Anda:\n\n"
        f"🏛️ *Layanan:* {escape_md(layanan)}\n"
        f"💰 *Deklarasi Zakat Maal:* {format_idr(zakat)}\n"
        f"📿 *Deklarasi Khumus:* {format_idr(khumus)}\n\n"
        f"✅ _Data laporan tahunan Anda telah tersimpan._\n"
        f"🔔 _Anda akan menerima update dari admin jika diperlukan._"
    )
    try:
        await message.reply_text(teks_laporan, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Gagal kirim rincian ke user: {e}")
        try:
            await message.reply_text(teks_laporan)
        except Exception as e2:
            logger.error(f"Fallback rincian juga gagal: {e2}")

    # --- LANGKAH 4: FORWARD KE ADMIN (TERPISAH) ---
    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"📢 *Laporan Baru Masuk*\n"
                    f"Dari: {escape_md(update.effective_user.first_name)} "
                    f"(ID: `{message.chat_id}`)\n\n"
                    f"💰 Zakat: {format_idr(zakat)}\n"
                    f"📿 Khumus: {format_idr(khumus)}\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                parse_mode='Markdown',
            )
        except Exception as e:
            logger.warning(f"Gagal forward ke admin (tidak masalah bagi user): {e}")

# =====================================================================
# HANDLER RAUDHA PAGI SEHAT
# =====================================================================

async def handle_pagi_sehat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_pagi_sehat":
        text = "🌅 **RAUDHA PAGI SEHAT**\n\nBersama Aeesha Medical Center & Takmir Masjid Al Falah.\nSilakan pilih layanan kesehatan:"
        keyboard = [
            [InlineKeyboardButton("☀️ Dzikir Pagi", callback_data="run_dzikir_pagi")],
            [InlineKeyboardButton("🏃‍♀️ Senam Ahad Pagi", callback_data="kesehatan_senam")],
            [InlineKeyboardButton("🩺 Cek Tensi Jumat", callback_data="kesehatan_tensi")],
            [InlineKeyboardButton("👨‍⚕️ Konsultasi Dokter", callback_data="kesehatan_konsultasi")],
            [InlineKeyboardButton("📖 Artikel Kesehatan Islami", callback_data="kesehatan_artikel")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    elif data in ["kesehatan_senam", "kesehatan_tensi", "kesehatan_konsultasi"]:
        jenis_map = {"kesehatan_senam": "senam", "kesehatan_tensi": "tensi", "kesehatan_konsultasi": "konsultasi"}
        jenis = jenis_map.get(data)
        programs = get_program_aktif()
        progs = [p for p in programs if p['jenis'] == jenis]
        
        if not progs:
            await safe_edit(query, "😔 Belum ada jadwal untuk layanan ini.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_pagi_sehat")]]))
            return
            
        p = progs[0]
        text = (
            f"🏥 **{p['nama'].upper()}**\n\n"
            f"📅 Tanggal: {p['tanggal']}\n🕐 Waktu: {p['waktu']}\n"
            f"📍 Lokasi: {p['lokasi']}\n🤝 Mitra: {p['mitra']}\n"
            f"👥 Kuota: {p['kuota']} (Tersisa: {p['sisa']})\n\n"
            f"Silakan daftar jika Anda ingin hadir."
        )
        keyboard = [
            [InlineKeyboardButton("✅ Daftar Hadir", callback_data=f"rsvp_v2_{p['id']}")],
            [InlineKeyboardButton("❌ Batal Daftar", callback_data=f"batal_v2_{p['id']}")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="menu_pagi_sehat")]
        ]
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    elif data == "kesehatan_artikel":
        daftar_artikel = get_daftar_artikel()
        if not daftar_artikel:
            text = "📖 **ARTIKEL KESEHATAN ISLAMI**\n\nBelum ada artikel. Tim medis akan segera menambahkan konten."
            await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="menu_pagi_sehat")]]))
            return
        
        text = "📖 **ARTIKEL KESEHATAN ISLAMI**\n\nSilakan pilih artikel yang ingin Anda baca:"
        keyboard = []
        for art in daftar_artikel:
            keyboard.append([InlineKeyboardButton(f"📄 {art['judul']}", callback_data=f"artikel_{art['slug']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data="menu_pagi_sehat")])
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("artikel_"):
        slug = data.replace("artikel_", "")
        artikel = get_artikel(slug) 
        
        if not artikel:
            await safe_edit(query, "❌ Artikel tidak ditemukan.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="kesehatan_artikel")]]))
            return
        
        # Ambil 300 karakter pertama sebagai ringkasan
        isi_ringkas = artikel['isi']
        if len(isi_ringkas) > 300:
            # Potong di spasi terdekat agar tidak terputus di tengah kata
            isi_ringkas = isi_ringkas[:300].rsplit(' ', 1)[0] + "..."
        
        text = (
            f"📖 **{artikel['judul'].upper()}**\n\n"
            f"✍️ _Ditulis oleh: {artikel['penulis']}_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{isi_ringkas}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Ingin membaca selengkapnya?_"
        )
        
        # URL ke Mini App untuk baca full
        url_artikel = f"{MINI_APP_URL}/artikel/{slug}"
        
        keyboard = [
            [InlineKeyboardButton("📖 Baca Selengkapnya di Mini App", web_app=WebAppInfo(url=url_artikel))],
            [InlineKeyboardButton("⬅️ Kembali ke Daftar Artikel", callback_data="kesehatan_artikel")]
        ]
        
        await safe_edit(query, text, InlineKeyboardMarkup(keyboard))   

async def handle_rsvp_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    if data.startswith("rsvp_v2_"):
        program_id = int(data.replace("rsvp_v2_", ""))
        sukses, pesan = daftar_rsvp(program_id, user.id, user.first_name)
        
        # Simpan ID program di memori user, agar bot ingat
        context.user_data['rsvp_program_id'] = program_id
        context.user_data['rsvp_nama'] = user.first_name
        
        # Minta nomor WA
        await query.edit_message_text(
            "📱 *Pendaftaran Program Kesehatan*\n\n"
            "Silakan ketik *Nomor WhatsApp* Anda (contoh: 08123456789).\n\n"
            "Nomor ini digunakan oleh tim medis untuk pengingat H-1.\n\n"
            "_Ketik /batal untuk membatalkan._",
            parse_mode='Markdown'
        )
        
    elif data.startswith("batal_v2_"):
        program_id = int(data.replace("batal_v2_", ""))
        # Panggil batal_rsvp
        if batal_rsvp(program_id, user.id):
            await query.answer("✅ Pendaftaran dibatalkan.", show_alert=True)
        else:
            await query.answer("⚠️ Anda belum terdaftar.", show_alert=True)


async def cmd_peserta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin/takmir.")
        return
        
    programs = get_program_aktif()
    if not programs:
        await update.message.reply_text("Belum ada program.")
        return
        
    p = programs[0]
    peserta = get_daftar_peserta(p['id'])
    text = f"📋 **PESERTA {p['nama'].upper()}**\n\n"
    
    if not peserta:
        text += "Belum ada yang mendaftar."
    else:
        for i, (nama, uid, telp, waktu) in enumerate(peserta, 1):
            text += f"{i}. {nama} ({telp or '-'})\n"
            
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_rsvp_telepon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangkap input nomor WA setelah user klik Daftar Hadir."""
    if 'rsvp_program_id' not in context.user_data:
        return

    nomor_wa = update.message.text.strip()
    program_id = context.user_data['rsvp_program_id']
    nama = context.user_data.get('rsvp_nama', update.effective_user.first_name)

    if not nomor_wa.isdigit() or len(nomor_wa) < 9:
        await update.message.reply_text(
            "❌ Nomor tidak valid. Silakan ketik angka saja (minimal 9 digit).\nContoh: 08123456789"
        )
        return

    sukses, pesan = daftar_rsvp(program_id, update.effective_user.id, nama, nomor_wa)
    
    context.user_data.pop('rsvp_program_id', None)
    context.user_data.pop('rsvp_nama', None)
    
    await update.message.reply_text(pesan, parse_mode='Markdown')   


# =====================================================================
# HANDLER: /pohon — Petugas Input Pohon Fisik (NFC)
# =====================================================================

# State konstan untuk percakapan /pohon
POHON_STATE_UID = "pohon_uid"
POHON_STATE_FOTO = "pohon_foto"
POHON_STATE_TINGGI = "pohon_tinggi"
POHON_STATE_KONDISI = "pohon_kondisi"


def _is_petugas(user_id):
    """Cek apakah user boleh input pohon (super admin atau admin lembaga aktif)."""
    if is_super_admin(user_id):
        return True
    role_info = get_user_role(user_id)
    return role_info.get("role") == "admin_lembaga"


async def cmd_input_pohon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pohon — Mulai proses input pohon fisik (NFC tagging).
    Format: /pohon [uid]  (uid opsional; kalau tidak ada, bot akan tanya)
    """
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    if not _is_petugas(user_id):
        await update.message.reply_text(
            "❌ Hanya petugas Mitra Alam (Super Admin / Admin Lembaga) yang bisa input pohon.\n\n"
            "Silakan hubungi admin untuk didaftarkan."
        )
        return
    
    # Reset state
    context.user_data.clear()
    
    # Kalau ada argumen langsung (uid)
    if context.args:
        uid = context.args[0].strip()
        return await _proses_uid(update, context, uid)
    
    # Kalau tidak ada, tanya
    context.user_data[POHON_STATE_UID] = True  # state = tunggu UID
    
    text = (
        "🌱 *INPUT POHON BARU — STEP 1/4*\n\n"
        "Silakan kirim *UID NFC* pohon yang sudah ditanam.\n\n"
        "📌 *Cara dapat UID:*\n"
        "• Scan NFC tag dengan HP\n"
        "• Atau ketik UID yang tercetak di tag\n"
        "• Contoh: `04A233158C4B80`\n\n"
        "_Ketik /batal untuk membatalkan._"
    )
    await update.message.reply_text(text, parse_mode='Markdown')


async def _proses_uid(update, context, uid):
    """Validasi UID & lanjut ke step foto."""
    # Bersihkan UID: hapus spasi, titik dua, dll.
    # Izinkan: huruf, angka, strip, underscore (fleksibel untuk test & UID fisik)
    uid_clean = re.sub(r'[^A-Za-z0-9_-]', '', uid).upper()
    
    if len(uid_clean) < 6:
        await update.message.reply_text(
            f"❌ UID tidak valid: `{uid}`\n"
            f"Silakan kirim ulang (minimal 6 karakter hex).",
            parse_mode='Markdown'
        )
        return
    
    # Cek UID belum terdaftar
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT id, status FROM pohon_wakaf WHERE nfc_uid=?", (uid_clean,))
    existing = c.fetchone()
    conn.close()
    
    if existing:
        await update.message.reply_text(
            f"⚠️ UID `{uid_clean}` sudah terdaftar!\n"
            f"• ID: #{existing[0]}\n"
            f"• Status: {existing[1]}\n\n"
            f"Kalau ini pohon berbeda, kirim UID lain.\n"
            f"Kalau mau update log, pakai /logpohon `{uid_clean}`.",
            parse_mode='Markdown'
        )
        context.user_data.clear()
        return
    
    # Simpan UID, lanjut ke foto
    context.user_data[POHON_STATE_UID] = uid_clean
    context.user_data[POHON_STATE_FOTO] = True
    
    await update.message.reply_text(
        f"✅ UID: `{uid_clean}`\n\n"
        f"🌱 *STEP 2/4 — FOTO POHON*\n\n"
        f"Silakan kirim *foto pohon* yang baru ditanam.\n"
        f"Pastikan pohon & tag NFC terlihat jelas.\n\n"
        f"_Ketik /batal untuk membatalkan._",
        parse_mode='Markdown'
    )


async def _proses_foto(update, context):
    """Terima foto, simpan URL sementara, lanjut ke tinggi."""
    message = update.message
    
    # Ambil foto terbesar
    photo = message.photo[-1] if message.photo else None
    if not photo:
        await message.reply_text("❌ Kirim foto (bukan dokumen). Coba lagi.")
        return
    
    # Download & simpan
    try:
        file = await context.bot.get_file(photo.file_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = context.user_data.get(POHON_STATE_UID, "unknown")
        filename = f"pohon_{uid}_{timestamp}.jpg"
        filepath = os.path.join(UPLOAD_DOKUMEN, filename)
        await file.download_to_drive(filepath)
        url = f"/uploads/dokumen_lembaga/{filename}"
        logger.info(f"[POHON] Foto tersimpan: {filename}")
    except Exception as e:
        logger.error(f"Gagal simpan foto: {e}")
        await message.reply_text(f"❌ Gagal simpan foto: {e}")
        return
    
    # Simpan URL, lanjut ke tinggi
    context.user_data[POHON_STATE_FOTO] = url
    context.user_data[POHON_STATE_TINGGI] = True
    
    await message.reply_text(
        f"✅ Foto diterima.\n\n"
        f"🌱 *STEP 3/4 — TINGGI POHON*\n\n"
        f"Silakan kirim *tinggi pohon* dalam cm (angka saja).\n"
        f"Contoh: `120` (artinya 120 cm)",
        parse_mode='Markdown'
    )


async def _proses_tinggi(update, context):
    """Terima tinggi, lanjut ke kondisi."""
    text = update.message.text.strip()
    
    try:
        tinggi = int(text)
        if tinggi < 10 or tinggi > 5000:
            raise ValueError()
    except ValueError:
        await update.message.reply_text(
            "❌ Tinggi tidak valid. Kirim angka antara 10-5000 (cm)."
        )
        return
    
    context.user_data[POHON_STATE_TINGGI] = tinggi
    context.user_data[POHON_STATE_KONDISI] = True
    
    keyboard = [
        [InlineKeyboardButton("✅ Sehat", callback_data="pohon_kondisi_sehat")],
        [InlineKeyboardButton("🟡 Cukup", callback_data="pohon_kondisi_cukup")],
        [InlineKeyboardButton("⚠️ Lemah", callback_data="pohon_kondisi_lemah")],
    ]
    await update.message.reply_text(
        f"✅ Tinggi: *{tinggi} cm*\n\n"
        f"🌱 *STEP 4/4 — KONDISI POHON*\n\n"
        f"Pilih kondisi pohon saat ini:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def _proses_kondisi(update, context, kondisi):
    """Finalisasi: simpan pohon ke database + log awal."""
    user_id = update.effective_user.id
    uid = context.user_data.get(POHON_STATE_UID)
    foto_url = context.user_data.get(POHON_STATE_FOTO)
    tinggi = context.user_data.get(POHON_STATE_TINGGI)
    
    if not all([uid, foto_url, tinggi]):
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Data tidak lengkap. Mulai ulang dengan /pohon"
        )
        context.user_data.clear()
        return
    
    # Cari pohon yang status 'menunggu_tanam' untuk diupdate
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("""SELECT id, komoditas_id, lembaga_id, muwakif_id 
                     FROM pohon_wakaf 
                     WHERE status='menunggu_tanam' 
                     ORDER BY id ASC LIMIT 1""")
        row = c.fetchone()
        
        if row:
            # Update pohon yang sudah ada (dari pembayaran verified)
            pohon_id, komoditas_id, lembaga_id, muwakif_id = row
            c.execute("""UPDATE pohon_wakaf SET
                            nfc_uid=?,
                            status='aktif',
                            tanggal_tanam=?,
                            updated_at=CURRENT_TIMESTAMP
                         WHERE id=?""",
                      (uid, date.today().strftime("%Y-%m-%d"), pohon_id))
            action = "diperbarui"
        else:
            # Kalau tidak ada pohon 'menunggu_tanam', buat baru (pohon donasi/umum)
            # Gunakan komoditas default & lembaga default
            c.execute("SELECT id FROM komoditas_wakaf WHERE aktif=1 LIMIT 1")
            kom_row = c.fetchone()
            komoditas_id = kom_row[0] if kom_row else 1
            
            c.execute("SELECT id FROM lembaga_amil WHERE status='verified' LIMIT 1")
            lem_row = c.fetchone()
            lembaga_id = lem_row[0] if lem_row else 1
            
            c.execute("""INSERT INTO pohon_wakaf
                         (nfc_uid, komoditas_id, tanggal_tanam, lembaga_id,
                          muwakif_id, harga_pohon, status, updated_at)
                         VALUES (?, ?, ?, ?, NULL, 0, 'aktif', CURRENT_TIMESTAMP)""",
                      (uid, komoditas_id, date.today().strftime("%Y-%m-%d"), lembaga_id))
            pohon_id = c.lastrowid
            action = "dibuat baru"
        
        # Tambah log awal
        c.execute("""INSERT INTO pohon_log
                     (pohon_id, tanggal, tipe, nilai, foto_url, catatan, petugas_id)
                     VALUES (?, ?, 'foto', ?, ?, 'Penanaman awal + NFC tagging', ?)""",
                  (pohon_id, date.today().strftime("%Y-%m-%d"),
                   f"tinggi={tinggi}cm, kondisi={kondisi}", foto_url, user_id))
        
        c.execute("""INSERT INTO pohon_log
                     (pohon_id, tanggal, tipe, nilai, catatan, petugas_id)
                     VALUES (?, ?, 'tinggi', ?, 'Pengukuran awal', ?)""",
                  (pohon_id, date.today().strftime("%Y-%m-%d"),
                   f"{tinggi} cm", user_id))
        
        c.execute("""INSERT INTO pohon_log
                     (pohon_id, tanggal, tipe, nilai, catatan, petugas_id)
                     VALUES (?, ?, 'kondisi', ?, 'Kondisi awal penanaman', ?)""",
                  (pohon_id, date.today().strftime("%Y-%m-%d"), kondisi, user_id))
        
        conn.commit()
        
        text = (
            f"🎉 *POHON BERHASIL DICATAT!*\n\n"
            f"🆔 Pohon ID: *#{pohon_id}* ({action})\n"
            f"📡 NFC UID: `{uid}`\n"
            f"📏 Tinggi: *{tinggi} cm*\n"
            f"💚 Kondisi: *{kondisi}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌐 *Cek di web:*\n"
            f"`{MINI_APP_URL}/pohon/{uid}`\n\n"
            f"📸 Foto & log tersimpan. Petugas dapat menambah log "
            f"berkala dengan /logpohon `{uid}`.\n\n"
            f"_Jazakallahu khairan untuk kerja lapangannya._ 🤲"
        )
        
        await context.bot.send_message(
            chat_id=user_id, text=text, parse_mode='Markdown'
        )
        logger.info(f"🌱 Pohon #{pohon_id} {action}: UID={uid}, tinggi={tinggi}cm, "
                    f"kondisi={kondisi}, petugas={user_id}")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Gagal simpan pohon: {e}")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Error: {e}"
        )
    finally:
        conn.close()
        context.user_data.clear()


async def handle_pohon_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router: tangkap input user berdasarkan state /pohon."""
    ud = context.user_data
    
    # Kalau state UID aktif (tunggu UID)
    if ud.get(POHON_STATE_UID) is True:
        if update.message.text:
            await _proses_uid(update, context, update.message.text)
        return
    
    # Kalau state FOTO aktif (tunggu foto)
    if ud.get(POHON_STATE_FOTO) is True:
        if update.message.photo:
            await _proses_foto(update, context)
        elif update.message.text:
            await update.message.reply_text("❌ Kirim *foto* pohon (bukan teks). Coba lagi.", parse_mode='Markdown')
        return
    
    # Kalau state TINGGI aktif
    if ud.get(POHON_STATE_TINGGI) is True and isinstance(ud.get(POHON_STATE_TINGGI), bool):
        if update.message.text:
            await _proses_tinggi(update, context)
        return
    
    # Kalau state KONDISI aktif (tunggu klik tombol)
    if ud.get(POHON_STATE_KONDISI) is True:
        if update.message.text:
            await update.message.reply_text(
                "❌ Silakan klik tombol kondisi di atas (Sehat/Cukup/Lemah)."
            )
        return


async def handle_pohon_kondisi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler tombol kondisi pohon."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    kondisi_map = {
        "pohon_kondisi_sehat": "sehat",
        "pohon_kondisi_cukup": "cukup",
        "pohon_kondisi_lemah": "lemah",
    }
    kondisi = kondisi_map.get(data)
    if not kondisi:
        return
    
    # Ganti pesan tombol jadi status
    await safe_edit(query, f"✅ Kondisi dipilih: *{kondisi.title()}*\n\n⏳ Menyimpan...", parse_mode='Markdown')
    
    # Buat fake update message untuk _proses_kondisi
    # (kita panggil langsung dengan context)
    class FakeMessage:
        pass
    
    # Panggil langsung _proses_kondisi (dia pakai context.bot.send_message)
    await _proses_kondisi(update, context, kondisi)


# =====================================================================
# HANDLER: /logpohon — Update Log Berkala Pohon (Step 11)
# =====================================================================

LOG_POHON_ID = "log_pohon_id"
LOG_POHON_INFO = "log_pohon_info"
LOG_TIPE = "log_tipe"


async def cmd_logpohon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /logpohon <uid> — Update log berkala untuk pohon yang sudah ada.
    """
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    if not _is_petugas(user_id):
        await update.message.reply_text(
            "❌ Hanya petugas Mitra Alam (Super Admin / Admin Lembaga) "
            "yang bisa update log pohon."
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "⚠️ Format: `/logpohon [NFC UID]`\n\n"
            "Contoh: `/logpohon TEST003GHI`",
            parse_mode='Markdown'
        )
        return
    
    uid = context.args[0].strip().upper()
    
    # Cek pohon ada
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT p.id, p.nfc_uid, k.nama_display, p.status
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 WHERE p.nfc_uid=?""", (uid,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await update.message.reply_text(
            f"❌ Pohon dengan UID `{uid}` tidak ditemukan.\n\n"
            f"Pastikan UID benar atau input pohon baru dengan `/pohon`.",
            parse_mode='Markdown'
        )
        return
    
    pohon_id, nfc_uid, komoditas, status = row
    
    # Simpan state
    context.user_data.clear()
    context.user_data[LOG_POHON_ID] = pohon_id
    context.user_data[LOG_POHON_INFO] = f"{komoditas} #{pohon_id}"
    
    # Tampilkan menu tipe log
    keyboard = [
        [InlineKeyboardButton("📸 Foto Baru", callback_data="log_tipe_foto")],
        [InlineKeyboardButton("📏 Tinggi", callback_data="log_tipe_tinggi")],
        [InlineKeyboardButton("💚 Kondisi", callback_data="log_tipe_kondisi")],
        [InlineKeyboardButton("🌿 Pemupukan", callback_data="log_tipe_pupuk")],
        [InlineKeyboardButton("⚠️ Penyakit/Hama", callback_data="log_tipe_penyakit")],
        [InlineKeyboardButton("🌾 Panen", callback_data="log_tipe_panen")],
        [InlineKeyboardButton("⬅️ Batal", callback_data="log_tipe_batal")],
    ]
    await update.message.reply_text(
        f"🌳 *POHON: {komoditas} #{pohon_id}*\n"
        f"📡 UID: `{nfc_uid}`\n"
        f"Status: {status}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Pilih *tipe log* yang ingin dicatat:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_log_tipe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pilihan tipe log."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "log_tipe_batal":
        context.user_data.clear()
        await safe_edit(query, "❌ Update log dibatalkan.")
        return
    
    pohon_id = context.user_data.get(LOG_POHON_ID)
    if not pohon_id:
        await safe_edit(query, "⚠️ Sesi kadaluarsa. Mulai ulang `/logpohon`.")
        return
    
    tipe = data.replace("log_tipe_", "")
    context.user_data[LOG_TIPE] = tipe
    pohon_info = context.user_data.get(LOG_POHON_INFO, "Pohon")
    
    if tipe == "foto":
        await safe_edit(query, 
            f"📸 *FOTO BARU untuk {pohon_info}*\n\n"
            f"Silakan kirim *foto pohon* terbaru.\n\n"
            f"_Ketik /batal untuk membatalkan._",
            parse_mode='Markdown')
    
    elif tipe == "tinggi":
        await safe_edit(query,
            f"📏 *TINGGI BARU untuk {pohon_info}*\n\n"
            f"Silakan kirim *tinggi pohon* dalam cm (angka saja).\n"
            f"Contoh: `145`",
            parse_mode='Markdown')
    
    elif tipe == "kondisi":
        keyboard = [
            [InlineKeyboardButton("✅ Sehat", callback_data="log_kondisi_sehat")],
            [InlineKeyboardButton("🟡 Cukup", callback_data="log_kondisi_cukup")],
            [InlineKeyboardButton("⚠️ Lemah", callback_data="log_kondisi_lemah")],
        ]
        await safe_edit(query,
            f"💚 *KONDISI untuk {pohon_info}*\n\n"
            f"Pilih kondisi pohon saat ini:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown')
    
    elif tipe == "pupuk":
        await safe_edit(query,
            f"🌿 *PEMUPUKAN untuk {pohon_info}*\n\n"
            f"Silakan kirim keterangan pemupukan:\n"
            f"Contoh: `Pupuk kandang 5kg, NPK 100g`\n\n"
            f"_Ketik /batal untuk membatalkan._",
            parse_mode='Markdown')
    
    elif tipe == "penyakit":
        await safe_edit(query,
            f"⚠️ *PENYAKIT/HAMA untuk {pohon_info}*\n\n"
            f"Silakan kirim keterangan penyakit/hama:\n"
            f"Contoh: `Daun menguning, kutu putih`\n\n"
            f"_Ketik /batal untuk membatalkan._",
            parse_mode='Markdown')
    
    elif tipe == "panen":
        await safe_edit(query,
            f"🌾 *PANEN untuk {pohon_info}*\n\n"
            f"Silakan kirim hasil panen:\n"
            f"Format: `berat_kg` atau `berat_kg | keterangan`\n"
            f"Contoh: `5` atau `5 | buah manis`\n\n"
            f"_Ketik /batal untuk membatalkan._",
            parse_mode='Markdown')


async def handle_log_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router input untuk /logpohon (foto, tinggi, kondisi, dll)."""
    if not update.message:
        return
    
    pohon_id = context.user_data.get(LOG_POHON_ID)
    if not pohon_id:
        return
    
    tipe = context.user_data.get(LOG_TIPE)
    if not tipe:
        return
    
    pohon_info = context.user_data.get(LOG_POHON_INFO, "Pohon")
    
    # === FOTO ===
    if tipe == "foto" and update.message.photo:
        try:
            file = await context.bot.get_file(update.message.photo[-1].file_id)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pohon_{pohon_id}_log_{timestamp}.jpg"
            filepath = os.path.join(UPLOAD_DOKUMEN, filename)
            await file.download_to_drive(filepath)
            url = f"/uploads/dokumen_lembaga/{filename}"
            
            from modul_mitra_alam import tambah_log
            sukses, pesan = tambah_log(
                pohon_id, tipe="foto", foto_url=url,
                nilai="Foto update", catatan="Update foto berkala",
                petugas_id=update.effective_user.id
            )
            
            if sukses:
                await update.message.reply_text(
                    f"✅ *Foto tersimpan untuk {pohon_info}*\n\n"
                    f"📸 Log foto ditambahkan.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ Gagal: {pesan}")
        except Exception as e:
            logger.error(f"Error simpan foto log: {e}")
            await update.message.reply_text(f"❌ Error: {e}")
        
        context.user_data.clear()
        return
    
    # === TINGGI ===
    if tipe == "tinggi" and update.message.text:
        try:
            tinggi = int(update.message.text.strip())
            if tinggi < 10 or tinggi > 5000:
                raise ValueError()
        except ValueError:
            await update.message.reply_text("❌ Kirim angka tinggi (cm) antara 10-5000.")
            return
        
        # Ambil tinggi sebelumnya
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("""SELECT nilai FROM pohon_log 
                     WHERE pohon_id=? AND tipe='tinggi'
                     ORDER BY tanggal DESC, id DESC LIMIT 1""", (pohon_id,))
        prev = c.fetchone()
        conn.close()
        
        prev_tinggi = None
        if prev:
            try:
                prev_tinggi = int(str(prev[0]).replace(" cm", "").strip())
            except (ValueError, AttributeError):
                pass
        
        from modul_mitra_alam import tambah_log
        sukses, pesan = tambah_log(
            pohon_id, tipe="tinggi", nilai=f"{tinggi} cm",
            catatan="Update tinggi berkala",
            petugas_id=update.effective_user.id
        )
        
        if sukses:
            if prev_tinggi:
                delta = tinggi - prev_tinggi
                delta_str = f"+{delta}cm" if delta > 0 else f"{delta}cm"
                msg = (
                    f"✅ *Tinggi tersimpan untuk {pohon_info}*\n\n"
                    f"📏 *{prev_tinggi}cm → {tinggi}cm* ({delta_str})"
                )
            else:
                msg = (
                    f"✅ *Tinggi tersimpan untuk {pohon_info}*\n\n"
                    f"📏 *{tinggi}cm*"
                )
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Gagal: {pesan}")
        
        context.user_data.clear()
        return
    
    # === PUPUK / PENYAKIT ===
    if tipe in ("pupuk", "penyakit") and update.message.text:
        nilai = update.message.text.strip()
        if not nilai:
            await update.message.reply_text("❌ Keterangan tidak boleh kosong.")
            return
        
        from modul_mitra_alam import tambah_log
        sukses, pesan = tambah_log(
            pohon_id, tipe=tipe, nilai=nilai,
            catatan=f"Update {tipe}",
            petugas_id=update.effective_user.id
        )
        
        if sukses:
            emoji = {"pupuk": "🌿", "penyakit": "⚠️"}[tipe]
            await update.message.reply_text(
                f"✅ *{tipe.title()} tersimpan untuk {pohon_info}*\n\n"
                f"{emoji} {nilai}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Gagal: {pesan}")
        
        context.user_data.clear()
        return
    
    # === PANEN ===
    if tipe == "panen" and update.message.text:
        text = update.message.text.strip()
        hasil_kg = 0
        catatan = text
        
        if "|" in text:
            parts = text.split("|", 1)
            try:
                hasil_kg = float(parts[0].strip())
                catatan = parts[1].strip()
            except ValueError:
                await update.message.reply_text("❌ Format salah. Contoh: `5` atau `5 | keterangan`")
                return
        else:
            try:
                hasil_kg = float(text)
                catatan = "Panen tercatat"
            except ValueError:
                await update.message.reply_text("❌ Format salah. Contoh: `5` atau `5 | keterangan`")
                return
        
        from modul_mitra_alam import tambah_log
        sukses, pesan = tambah_log(
            pohon_id, tipe="panen", nilai=f"{hasil_kg} kg",
            catatan=catatan,
            petugas_id=update.effective_user.id
        )
        
        if sukses:
            await update.message.reply_text(
                f"✅ *Panen tersimpan untuk {pohon_info}*\n\n"
                f"🌾 Hasil: *{hasil_kg} kg*\n"
                f"📝 {catatan}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Gagal: {pesan}")
        
        context.user_data.clear()
        return


async def handle_log_kondisi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pilihan kondisi setelah /logpohon."""
    query = update.callback_query
    await query.answer()
    
    pohon_id = context.user_data.get(LOG_POHON_ID)
    if not pohon_id:
        await safe_edit(query, "⚠️ Sesi kadaluarsa. Mulai ulang `/logpohon`.")
        return
    
    data = query.data
    kondisi_map = {
        "log_kondisi_sehat": "sehat",
        "log_kondisi_cukup": "cukup",
        "log_kondisi_lemah": "lemah",
    }
    kondisi = kondisi_map.get(data)
    if not kondisi:
        return
    
    pohon_info = context.user_data.get(LOG_POHON_INFO, "Pohon")
    
    from modul_mitra_alam import tambah_log
    sukses, pesan = tambah_log(
        pohon_id, tipe="kondisi", nilai=kondisi,
        catatan="Update kondisi berkala",
        petugas_id=update.effective_user.id
    )
    
    if sukses:
        emoji = {"sehat": "✅", "cukup": "🟡", "lemah": "⚠️"}[kondisi]
        await safe_edit(query,
            f"✅ *Kondisi tersimpan untuk {pohon_info}*\n\n"
            f"{emoji} Kondisi: *{kondisi.title()}*",
            parse_mode='Markdown'
        )
    else:
        await safe_edit(query, f"❌ Gagal: {pesan}")
    
    context.user_data.clear()    


# =====================================================================
# HANDLER: /panen — Catat Panen & Bagi Hasil (Step 12)
# =====================================================================

PANEN_POHON_ID = "panen_pohon_id"
PANEN_POHON_INFO = "panen_pohon_info"
PANEN_DATA_TEMP = "panen_data_temp"


async def cmd_panen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /panen <uid> — Catat panen & bagi hasil otomatis (70/20/10).
    """
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    if not _is_petugas(user_id):
        await update.message.reply_text(
            "❌ Hanya petugas Mitra Alam (Super Admin / Admin Lembaga) "
            "yang bisa catat panen."
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "⚠️ Format: `/panen [NFC UID]`\n\n"
            "Contoh: `/panen TEST003GHI`",
            parse_mode='Markdown'
        )
        return
    
    uid = context.args[0].strip().upper()
    
    # Cek pohon ada & status aktif
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT p.id, p.nfc_uid, k.nama_display, p.status, p.lembaga_id
                 FROM pohon_wakaf p
                 JOIN komoditas_wakaf k ON k.id = p.komoditas_id
                 WHERE p.nfc_uid=?""", (uid,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await update.message.reply_text(
            f"❌ Pohon dengan UID `{uid}` tidak ditemukan.\n\n"
            f"Input pohon baru dulu dengan `/pohon`.",
            parse_mode='Markdown'
        )
        return
    
    pohon_id, nfc_uid, komoditas, status, lembaga_id = row
    
    if status == 'mati':
        await update.message.reply_text(
            f"⚠️ Pohon *{komoditas} #{pohon_id}* sudah mati. Tidak bisa panen.",
            parse_mode='Markdown'
        )
        return
    
    # Simpan state
    context.user_data.clear()
    context.user_data[PANEN_POHON_ID] = pohon_id
    context.user_data[PANEN_POHON_INFO] = f"{komoditas} #{pohon_id}"
    
    await update.message.reply_text(
        f"🌾 *CATAT PANEN — {komoditas} #{pohon_id}*\n\n"
        f"📡 UID: `{nfc_uid}`\n"
        f"Status: {status}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Kirim data panen dengan format:\n"
        f"`berat_kg | harga_per_kg`\n\n"
        f"*Contoh:*\n"
        f"`5 | 50000`\n"
        f"artinya 5 kg × Rp 50.000 = Rp 250.000\n\n"
        f"Atau dengan catatan:\n"
        f"`5 | 50000 | buah manis`\n\n"
        f"_Ketik /batal untuk membatalkan._",
        parse_mode='Markdown'
    )


async def handle_panen_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima input panen & tampilkan konfirmasi."""
    if not update.message or not update.message.text:
        return
    
    pohon_id = context.user_data.get(PANEN_POHON_ID)
    if not pohon_id:
        return
    
    pohon_info = context.user_data.get(PANEN_POHON_INFO, "Pohon")
    text = update.message.text.strip()
    
    # Parse input: kg | harga | catatan
    parts = [p.strip() for p in text.split("|")]
    
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ Format salah. Minimal: `kg | harga_per_kg`\n"
            "Contoh: `5 | 50000`",
            parse_mode='Markdown'
        )
        return
    
    try:
        hasil_kg = float(parts[0])
        harga_per_kg = float(parts[1])
        catatan = parts[2] if len(parts) > 2 else "Panen tercatat"
    except ValueError:
        await update.message.reply_text(
            "❌ Angka tidak valid. Contoh: `5 | 50000`",
            parse_mode='Markdown'
        )
        return
    
    if hasil_kg <= 0 or harga_per_kg <= 0:
        await update.message.reply_text("❌ Berat & harga harus > 0.")
        return
    
    total = hasil_kg * harga_per_kg
    bagi_masjid = total * 0.70
    bagi_perawatan = total * 0.20
    bagi_raudha = total * 0.10
    
    # Simpan data sementara
    context.user_data[PANEN_DATA_TEMP] = {
        "hasil_kg": hasil_kg,
        "harga_per_kg": harga_per_kg,
        "total": total,
        "bagi_masjid": bagi_masjid,
        "bagi_perawatan": bagi_perawatan,
        "bagi_raudha": bagi_raudha,
        "catatan": catatan,
    }
    
    # Format rupiah
    def fmt(n):
        return f"Rp {int(n):,}".replace(",", ".")
    
    keyboard = [
        [InlineKeyboardButton("✅ Konfirmasi & Simpan", callback_data="panen_confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="panen_cancel")],
    ]
    
    await update.message.reply_text(
        f"📊 *KONFIRMASI PANEN — {pohon_info}*\n\n"
        f"📦 Hasil: *{hasil_kg} kg*\n"
        f"💵 Harga: *{fmt(harga_per_kg)}/kg*\n"
        f"💰 Total: *{fmt(total)}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Bagi Hasil Otomatis:*\n"
        f"🕌 Masjid (70%): *{fmt(bagi_masjid)}*\n"
        f"🌿 Perawatan (20%): *{fmt(bagi_perawatan)}*\n"
        f"🏛️ Raudha (10%): *{fmt(bagi_raudha)}*\n\n"
        f"📝 Catatan: _{catatan}_\n\n"
        f"_Konfirmasi untuk menyimpan._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_panen_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler tombol konfirmasi/batal panen."""
    query = update.callback_query
    
    # DEBUG LOG
    logger.info(f"[PANEN] Confirm clicked by user {update.effective_user.id}")
    logger.info(f"[PANEN] user_data keys: {list(context.user_data.keys())}")
    logger.info(f"[PANEN] pohon_id: {context.user_data.get(PANEN_POHON_ID)}")
    logger.info(f"[PANEN] temp exists: {context.user_data.get(PANEN_DATA_TEMP) is not None}")
    logger.info(f"[PANEN] callback data: {query.data}")
    
    await query.answer()
    
    data = query.data
    pohon_id = context.user_data.get(PANEN_POHON_ID)
    pohon_info = context.user_data.get(PANEN_POHON_INFO, "Pohon")
    temp = context.user_data.get(PANEN_DATA_TEMP)
    
    if not pohon_id or not temp:
        await safe_edit(query, "⚠️ Sesi kadaluarsa. Mulai ulang `/panen`.")
        return
    
    if data == "panen_cancel":
        context.user_data.clear()
        await safe_edit(query, "❌ Panen dibatalkan.")
        return
    
    if data != "panen_confirm":
        return
    
    # Simpan ke database
    from modul_mitra_alam import catat_panen
    
    tanggal = date.today().strftime("%Y-%m-%d")
    
    sukses, pesan = catat_panen(
        pohon_id=pohon_id,
        tanggal_panen=tanggal,
        hasil_kg=temp["hasil_kg"],
        hasil_nominal=temp["total"],
        catatan=temp["catatan"],
        petugas_id=update.effective_user.id
    )
    
    if not sukses:
        await safe_edit(query, f"❌ Gagal: {pesan}")
        context.user_data.clear()
        return
    
    # Hitung total panen kumulatif
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT COUNT(*), COALESCE(SUM(hasil_nominal), 0),
                        COALESCE(SUM(pembagian_masjid), 0)
                 FROM pohon_panen WHERE pohon_id=?""", (pohon_id,))
    count, total_all, total_masjid = c.fetchone()
    conn.close()
    
    def fmt(n):
        return f"Rp {int(n):,}".replace(",", ".")
    
    await safe_edit(query,
        f"✅ *PANEN TERSIMPAN!*\n\n"
        f"🌳 {pohon_info}\n"
        f"📅 {tanggal}\n\n"
        f"📊 *Panen Ini:*\n"
        f"🌾 {temp['hasil_kg']} kg × {fmt(temp['harga_per_kg'])} = *{fmt(temp['total'])}*\n"
        f"🕌 Masjid: {fmt(temp['bagi_masjid'])}\n"
        f"🌿 Perawatan: {fmt(temp['bagi_perawatan'])}\n"
        f"🏛️ Raudha: {fmt(temp['bagi_raudha'])}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Total Pohon Ini:*\n"
        f"🔄 Panen: *{count}x*\n"
        f"💰 Total hasil: *{fmt(total_all)}*\n"
        f"🕌 Total ke masjid: *{fmt(total_masjid)}*\n\n"
        f"_Jazakallahu khairan untuk kerja lapangannya._ 🤲",
        parse_mode='Markdown'
    )
    
    # Log
    logger.info(f"🌾 Panen #{pohon_id}: {temp['hasil_kg']}kg × {temp['harga_per_kg']} = Rp {temp['total']:,.0f}")
    
    context.user_data.clear()

# =====================================================================
# 13. RUNNER
# =====================================================================

def main():
    try:
        from modul_seed_masjid import load_seed_masjid
        load_seed_masjid()
    except Exception as e:
        logger.warning(f"Seed masjid gagal dimuat: {e}")

    app = Application.builder() \
        .token(BOT_TOKEN) \
        .connect_timeout(60) \
        .read_timeout(60) \
        .write_timeout(60) \
        .pool_timeout(60) \
        .build()

    # --- COMMAND HANDLERS ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("idtv", cmd_id_tv))
    
    # --- BACKUP COMMANDS (Batch 16a) ---
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("listbackup", cmd_list_backup))
    app.add_handler(CommandHandler("backupmingguan", cmd_backup_mingguan))
    app.add_handler(CommandHandler("testemail", cmd_test_email))

       
    # --- RESTORE COMMANDS (Batch 16b) ---
    app.add_handler(CommandHandler("restore", cmd_restore))
    app.add_handler(CommandHandler("batal", cmd_batal_restore))
    
        
    # --- COMMAND HANDLERS LAINNYA ---
    app.add_handler(CommandHandler("kota", handle_command_kota))
    app.add_handler(CommandHandler("masuk", handle_masuk))
    app.add_handler(CommandHandler("keluar", handle_keluar))

    # --- COMMAND HANDLERS VERIFIKASI ---
    app.add_handler(CommandHandler("mode_verifikasi", cmd_mode_verifikasi))

    # --- MESSAGE HANDLERS ---
    app.add_handler(MessageHandler(filters.LOCATION, handle_location_received))

    # Handler untuk menangkap input nomor WA saat RSVP
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rsvp_telepon))

    # ⚠️ web_app_data HARUS didaftarkan (group default 0)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.Document.ALL, handle_restore_confirm))

    # Handler Super Admin
    app.add_handler(CommandHandler("verifikasi", cmd_verifikasi))
    app.add_handler(CommandHandler("tugaskan", cmd_tugaskan))
    app.add_handler(CallbackQueryHandler(handle_approve_lembaga, pattern="^approve_lembaga_"))
    app.add_handler(CallbackQueryHandler(handle_set_kategori, pattern="^setkat_"))

    # --- LOGGING GLOBAL (group=1, exclude web_app_data agar tidak dobel) ---
    async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.debug(f"[GLOBAL LOG] Update masuk: {type(update).__name__}")

    log_filter = filters.ALL & ~filters.StatusUpdate.WEB_APP_DATA
    app.add_handler(MessageHandler(log_filter, log_all_updates), group=1)

    # --- CALLBACK HANDLERS ---
    app.add_handler(CallbackQueryHandler(start, pattern="^back_to_main$"))

    # Handler Raudha Pagi Sehat
    app.add_handler(CommandHandler("peserta", cmd_peserta))
    app.add_handler(CallbackQueryHandler(handle_pagi_sehat, pattern="^(menu_pagi_sehat|kesehatan_senam|kesehatan_tensi|kesehatan_konsultasi|kesehatan_artikel|artikel_)"))
    app.add_handler(CallbackQueryHandler(handle_rsvp_action, pattern="^(rsvp_v2_|batal_v2_)"))   

    submenu_patterns = (
        "^(menu_morning|menu_doa|menu_tanam|menu_arsitektur|"
        "menu_sholat|menu_ekonomi|menu_help|menu_about|"
        "menu_quick_links|"
        "sub_sholat_gps|sub_sholat_kota|sub_doa_pilihan|"
        "wacana_finansial_laziz|wacana_finansial_bmt|wacana_gerai_dinar)$"
    )
    app.add_handler(CallbackQueryHandler(handle_submenus, pattern=submenu_patterns))

    # Handler untuk tombol sub-menu Ekonomi Ummat
    ekonomi_actions = r"^(run_saldo_bmt|run_tagihan|run_laporan|sub_info_ekonomi)$"
    app.add_handler(CallbackQueryHandler(handle_ekonomi_actions, pattern=ekonomi_actions))

    app.add_handler(CallbackQueryHandler(
        handle_morning_actions, pattern="^(run_dzikir_pagi|run_inspirasi)$"))

    app.add_handler(CallbackQueryHandler(
        handle_subscribe, pattern="^(run_sub_dzikir|run_sub_weekly|run_unsubscribe)$"))

    doa_patterns = (
        "^(run_doa_harian|run_doa_lindung|run_doa_kumail|run_doa_ziyarah|"
        "run_doa_nudbah|run_doa_shalawat|"
        r"kumail_hal\d+|nudbah_hal\d+|ziyarah_hal\d+|shalawat_hal\d+|"
        r"kumail_arabonly_\d+|nudbah_arabonly_\d+|ziyarah_arabonly_\d+|shalawat_arabonly_\d+)$"
    )
    app.add_handler(CallbackQueryHandler(handle_doa_actions, pattern=doa_patterns))

    # Handler Onboarding
    app.add_handler(CallbackQueryHandler(handle_onboarding, pattern="^(onboarding_gps|onboarding_manual|onboarding_skip|pilih_masjid_)"))  

    # Handler Masjid & Jaringan
    app.add_handler(CallbackQueryHandler(handle_masjid_menu, pattern="^(menu_masjid|masjid_ganti|masjid_cari_kota|masjid_daftar_raudha|masjid_daftar_jaringan|masjid_daftar_baru)$"))
    app.add_handler(CommandHandler("carimasjid", cmd_cari_masjid))

    # Handler Mitra Alam (menu Tanam)
    app.add_handler(CallbackQueryHandler(handle_mitra_alam_about, pattern="^mitra_alam_about$"))
    app.add_handler(CallbackQueryHandler(handle_mitra_alam_komoditas, pattern="^mitra_alam_komoditas$"))

        # Command /pohon — petugas input NFC
    app.add_handler(CommandHandler("pohon", cmd_input_pohon))
    app.add_handler(CommandHandler("logpohon", cmd_logpohon))
    app.add_handler(CommandHandler("panen", cmd_panen))
   
    app.add_handler(CallbackQueryHandler(handle_pohon_kondisi_callback, pattern="^pohon_kondisi_"))
    app.add_handler(CallbackQueryHandler(handle_log_tipe_callback, pattern="^log_tipe_"))
    app.add_handler(CallbackQueryHandler(handle_log_kondisi_callback, pattern="^log_kondisi_"))
    app.add_handler(CallbackQueryHandler(handle_panen_confirm, pattern="^panen_(confirm|cancel)$")) 

    app.add_handler(CommandHandler("debug_role", cmd_debug_role))
    
    # Router state /pohon (harus SETELAH handler lain agar tidak konflik)
    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO,
        handle_pohon_state
    ), group=2)  # group=2 agar tidak konflik dengan handler RSVP
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
        handle_log_input
    ), group=3)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_panen_input
    ), group=4)

    logger.info("✅ Bot Raudha siap digunakan...")

    # =====================================================================
    # NOTIFIKASI REAL-TIME + BACKUP (Batch 7 & 16a)
    # =====================================================================

    if app.job_queue:
        # Cek pembayaran baru setiap 30 detik
        app.job_queue.run_repeating(cek_pembayaran_baru, interval=30, first=10)
        # Cek verifikasi setiap 30 detik
        app.job_queue.run_repeating(cek_pembayaran_diverifikasi, interval=30, first=15)
        # Cek pengajuan lembaga baru setiap 60 detik
        app.job_queue.run_repeating(cek_pengajuan_lembaga_baru, interval=60, first=20)

        # NOTIF WAKAF POHON (STEP 7)
        app.job_queue.run_repeating(cek_wakaf_diverifikasi, interval=30, first=20)
        app.job_queue.run_repeating(cek_wakaf_bukti_baru, interval=30, first=25)
        
        # Backup harian jam 00:00 WIB (17:00 UTC)
        from datetime import time as _time
        app.job_queue.run_daily(
            backup_database,
            time=_time(hour=17, minute=0, second=0),  # 00:00 WIB
            name="backup_harian"
        )

        # Backup mingguan permanen — Minggu 00:05 WIB (17:05 UTC Sabtu)
        app.job_queue.run_daily(
            backup_mingguan,
            time=_time(hour=17, minute=5, second=0),
            days=(6,),  # 6 = Minggu (0=Senin ... 6=Minggu)
            name="backup_mingguan"
        )
        logger.info("✅ JobQueue backup mingguan aktif (Minggu 00:05 WIB)")
        
        logger.info("✅ JobQueue notifikasi aktif (30s/30s/60s)")
        logger.info("✅ JobQueue backup harian aktif (00:00 WIB)")
    else:
        logger.warning("⚠️ JobQueue tidak aktif — notifikasi & backup tidak akan jalan")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot dihentikan oleh pengguna.")
    except Exception as e:
        logger.error(f"Terjadi kesalahan fatal: {e}")
