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
from datetime import datetime as _dt
from datetime import datetime


# Import dari modul_sholat (untuk fitur bot lainnya)
from modul_sholat import (
    cari_kota_fuzzy, 
    ambil_jadwal_sholat,
    masjid_terdekat
)
# Import dari jadwal_sholat (untuk fitur API Aladhan)
from jadwal_sholat import cari_kota, get_jadwal, format_jadwal

# Paksa IPv4 untuk koneksi keluar (antisipasi IPv6 tidak stabil)
_original_getaddrinfo = socket.getaddrinfo
def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_only

# --- 1. SET UP PATH & ENV ---
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env")

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
from modul_database import init_db, simpan_lokasi_user
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


# =====================================================================
# 8. HANDLER UTAMA MENU /start
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu utama bot. Dipanggil dari /start maupun tombol 'Kembali ke Menu Utama'."""
    query = update.callback_query

    # Cache-busting: timestamp unik di ujung URL
    url_mini_app = f"{MINI_APP_URL}?t={int(time.time())}"

    text = (
        "👋 **Salam dan Selamat Datang di Raudha - Marbot yang melayani anda dalam mengkreasi kebaikan setiap hari, selaras dengan motto  - Recreate All The New Day:**\n\n"
        "Silakan gunakan tombol interaktif di bawah ini untuk mengakses setiap layanan:"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 Buka Aplikasi Hitung Amal & Zakat", web_app=WebAppInfo(url=url_mini_app))],
        [InlineKeyboardButton("🌅 Raudha Pagi Sehat", callback_data="menu_pagi_sehat"),
         InlineKeyboardButton("🤲 Doa", callback_data="menu_doa")],
        [InlineKeyboardButton("🌱 Tanam", callback_data="menu_tanam"),
         InlineKeyboardButton("🕌 Sholat", callback_data="menu_sholat")],
        [InlineKeyboardButton("🏛️ Arsitektur", callback_data="menu_arsitektur"),
         InlineKeyboardButton("💰 Ekonomi Ummat", callback_data="menu_ekonomi")],
        [InlineKeyboardButton("🚀 Pintasan Layanan Inti", callback_data="menu_quick_links")],
        [InlineKeyboardButton("❓ Help & Subscribe", callback_data="menu_help"),
         InlineKeyboardButton("ℹ️ About", callback_data="menu_about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.answer()
        except Exception:
            pass
        await safe_edit(query, text, reply_markup)
    elif update.message:
        await safe_reply(update.message, text, reply_markup)

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
        text = "🌅 **MORNING MENU - RAUDHA**\n\nMorning has broken - Awali pagi hari dengan dzikir dan inspirasi pagi:"
        keyboard = [
            [InlineKeyboardButton("☀️ Dzikir Pagi Singkat", callback_data="run_dzikir_pagi")],
            [InlineKeyboardButton("📜 Inspirasi Pagi Ini", callback_data="run_inspirasi")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "menu_doa":
        text = (
            "🤲 **MENU DOA - RAUDHA**\n\n"
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
            "📖 **MENU DOA PILIHAN & SHALAWAT**\n\n"
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
            "🌱 **MENU TANAM RAUDHA**\n\n"
            "Selamat datang di gerakan Raudha Tanam: Jadikan Halaman Ini Menjadi Taman - Wasiat.\n\n"
            "Silakan pilih program kontribusi tanam pohon amal  -jariah- di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🌳 Wakaf Produktif Tanaman", url="https://google.com")],
            [InlineKeyboardButton("📖 Pesantren Alam Raudha Mar'i Mar'a", url="https://google.com")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
        ]

    elif data == "menu_arsitektur":
        url_arsitektur = f"{MINI_APP_URL}/arsitektur?t={int(time.time())}"
        text = (
            "🏛️ **LAYANAN ARSITEKTUR & MANAJEMEN PROYEK RAUDHA**\n\n"
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
        mini_app_zakat_url = f"{MINI_APP_URL}?tab=zakat&t={int(time.time())}"
        
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
            "🌱 Tanam - Menanam amal kebaikan secara mudah, 🏛️ Arsitektur - menciptakan tempat ibadah yang nyaman, 🤲 Spiritualitas - manfaatkan sarana teknologi untuk kemudahan ibadah."
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
            [InlineKeyboardButton("💰 Buka Kalkulator Zakat", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=zakat&t={int(time.time())}"))],
            [InlineKeyboardButton("🏛️ Daftarkan Lembaga Amil", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=daftar&t={int(time.time())}"))],
            [InlineKeyboardButton("🧾 Buka Tagihan", web_app=WebAppInfo(url=f"{MINI_APP_URL}?tab=tagihan&t={int(time.time())}"))],
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
    if not update.message or not update.message.location:
        return
    user_loc = update.message.location
    lat, lng = user_loc.latitude, user_loc.longitude
    telegram_id = update.effective_user.id

    # Simpan ke DB
    try:
        simpan_lokasi_user(telegram_id, lat, lng, kota="Lokasi GPS", sumber="gps")
    except Exception as e:
        logger.warning(f"Gagal simpan lokasi user: {e}")

    # Ambil jadwal dari API Aladhan
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

    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Morning", callback_data="menu_morning")]]
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
# NOTIFIKASI REAL-TIME (Batch 7)
# =====================================================================
import sqlite3

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


async def cleanup_backup_manual(context: ContextTypes.DEFAULT_TYPE):
    """Command admin: bersihkan backup manual."""
    if not ADMIN_ID or (update := None) is None:
        pass


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /backup — backup manual dari admin."""
    user_id = update.effective_user.id
    if not ADMIN_ID or user_id != ADMIN_ID:
        await update.message.reply_text("❌ Anda bukan admin.")
        return
    
    await update.message.reply_text("⏳ Memulai backup...")
    await backup_database(context)
    await update.message.reply_text("✅ Backup selesai. Cek chat untuk file backup.")


async def cmd_list_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /listbackup — lihat daftar backup."""
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
        
        text = f"🗄️ *Daftar Backup ({len(files)})*\n\n"
        for f in files[:10]:
            fpath = os.path.join(BACKUP_DIR, f)
            size = os.path.getsize(fpath) / 1024 / 1024
            mtime = _dt.fromtimestamp(os.path.getmtime(fpath)).strftime('%d/%m/%Y %H:%M')
            text += f"• `{f}`\n  {size:.2f} MB — {mtime}\n\n"
        
        if len(files) > 10:
            text += f"_... dan {len(files) - 10} lainnya_"
        
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

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
            [InlineKeyboardButton("🏃‍♀️ Senam Ahad", callback_data="kesehatan_senam")],
            [InlineKeyboardButton("🩺 Cek Tensi Jumat", callback_data="kesehatan_tensi")],
            [InlineKeyboardButton("👨‍⚕️ Konsultasi Dokter", callback_data="kesehatan_konsultasi")],
            [InlineKeyboardButton("📖 Artikel Kesehatan Islami", callback_data="kesehatan_artikel")],
            [InlineKeyboardButton("☀️ Dzikir Pagi", callback_data="run_dzikir_pagi")],
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
        artikel = get_artikel(f"{slug}.txt")
        if not artikel:
            await safe_edit(query, "❌ Artikel tidak ditemukan.", InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="kesehatan_artikel")]]))
            return
        
        text = (
            f"📖 **{artikel['judul'].upper()}**\n\n"
            f"✍️ _Ditulis oleh: {artikel['penulis']}_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{artikel['isi']}"
        )
        await safe_edit(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali ke Daftar Artikel", callback_data="kesehatan_artikel")]]))

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

       
    # --- RESTORE COMMANDS (Batch 16b) ---
    app.add_handler(CommandHandler("restore", cmd_restore))
    app.add_handler(CommandHandler("batal", cmd_batal_restore))
    
        
    # --- COMMAND HANDLERS LAINNYA ---
    app.add_handler(CommandHandler("kota", handle_command_kota))
    app.add_handler(CommandHandler("masuk", handle_masuk))
    app.add_handler(CommandHandler("keluar", handle_keluar))
    # --- MESSAGE HANDLERS ---
    app.add_handler(MessageHandler(filters.LOCATION, handle_location_received))

    # Handler untuk menangkap input nomor WA saat RSVP
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rsvp_telepon))

    # ⚠️ web_app_data HARUS didaftarkan (group default 0)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.Document.ALL, handle_restore_confirm))

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
        
        # Backup harian jam 00:00 WIB (17:00 UTC)
        from datetime import time as _time
        app.job_queue.run_daily(
            backup_database,
            time=_time(hour=17, minute=0, second=0),  # 00:00 WIB
            name="backup_harian"
        )
        
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
