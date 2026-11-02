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
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

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
from modul_sholat import (
    cari_kota, cari_kota_fuzzy, ambil_jadwal_sholat,
    format_jadwal, masjid_terdekat
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
import shutil
from datetime import datetime as _dt

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
MAX_BACKUP_DAYS = 7  # Retensi: 7 hari


# --- 6. INIT DATABASE (SEKALI SAJA) ---
try:
    init_db()
    init_db_keuangan()
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
        "👋 **Salam dan Selamat Datang di Bot Raudha - Recreate All The New Day: "
        "Mari bersama mengkreasi kebaikan setiap hari baru**\n\n"
        "Silakan gunakan tombol interaktif di bawah ini untuk mengakses layanan kami:"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 Buka Raudha Mini App", web_app=WebAppInfo(url=url_mini_app))],
        [InlineKeyboardButton("🌅 Morning", callback_data="menu_morning"),
         InlineKeyboardButton("🤲 Doa", callback_data="menu_doa")],
        [InlineKeyboardButton("🌱 Tanam", callback_data="menu_tanam"),
         InlineKeyboardButton("🏛️ Arsitektur", callback_data="menu_arsitektur")],
        [InlineKeyboardButton("🕌 Sholat", callback_data="menu_sholat"),
         InlineKeyboardButton("💰 Ekonomi Ummat", callback_data="menu_ekonomi")],
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
        text = "🌅 **MORNING MENU - RAUDHA**\n\nMorning has broken - Awali pagi hari dengan dzikir dan inspirasi pagi."
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
            "Silakan pilih program kontribusi di bawah ini:"
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
            "Kami menghadirkan ruang ibadah dan fasilitas sosial yang estetik, "
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
            "Jadwal Sholat disesuaikan dengan standar Kemenag dan Kalender Global Hijriah.\n"
            "📌 **Opsi 1 (Otomatis):** Gunakan lokasi GPS di ponsel Anda.\n"
            "📌 **Opsi 2 (Manual):** Cari berdasarkan nama Kota/Kabupaten."
        )
        keyboard = [
            [InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps"),
             InlineKeyboardButton("🔍 Cari Nama Kota", callback_data="sub_sholat_kota")],
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
        text = (
            "💰 **MENU EKONOMI UMMAT (LAZIS & BMT)**\n\n"
            "Layanan pemberdayaan ekonomi berbasis jama'ah Masjid dan Komunitas Raudha.\n\n"
            "🕌 **LAZIS Raudha:** Penggalangan Zakat, Infaq, Sedekah digital via QRIS\n"
            "🏦 **BMT Raudha:** Sarana Keuangan Mikro, Tabungan Syariah (Mudharabah)\n"
            "⚜️ **GERAI DINAR:** Layanan simpanan, jual-beli emas dan perak."
        )
        keyboard = [
            [InlineKeyboardButton("🕌 Layanan LAZIS (Wacana)", callback_data="wacana_finansial_laziz")],
            [InlineKeyboardButton("🏦 Layanan BMT (Wacana)", callback_data="wacana_finansial_bmt")],
            [InlineKeyboardButton("🏦 Layanan Gerai Dinar (Wacana)", callback_data="wacana_gerai_dinar")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")],
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
            "🌱 Tanam, 🏛️ Arsitektur, 🤲 Spiritualitas."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]

    else:
        text = "Menu tidak ditemukan."
        keyboard = [[InlineKeyboardButton("⬅️ Kembali", callback_data="back_to_main")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit(query, text, reply_markup)


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
    """Hitung jadwal sholat berdasarkan koordinat kota dari data_kota.json."""
    if not update.message:
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ Silakan masukkan nama kota.\n"
            "👉 Contoh: `/kota Banjarnegara` atau `/kota Danakerta`"
        )
        return

    nama_cari = " ".join(context.args).strip().lower()

    if not os.path.exists(PATH_DATA_KOTA):
        await update.message.reply_text("❌ Berkas data_kota.json tidak ditemukan di folder bot.")
        return

    daftar_kota = _muat_data_kota()
    if not daftar_kota:
        await update.message.reply_text("❌ Data kota kosong atau gagal dimuat.")
        return

    kota_ditemukan = None
    for k in daftar_kota:
        if k.get("nama", "").lower() == nama_cari:
            kota_ditemukan = k
            break

    if not kota_ditemukan:
        await update.message.reply_text(
            f"❌ Kota '{' '.join(context.args)}' tidak terdaftar di database lokal.\n"
            f"💡 Coba periksa ejaan huruf Anda (Contoh: Jakarta, Bogor, Purwokerto)."
        )
        return

    nama_resmi = kota_ditemukan["nama"]
    lat = kota_ditemukan["lat"]
    lng = kota_ditemukan["lng"]
    provinsi = kota_ditemukan.get("provinsi", "-")
    catatan = kota_ditemukan.get("catatan", "")

    try:
        import math

        hari_ke = datetime.now().timetuple().tm_yday
        deklinasi = 0.409 * math.sin((2 * math.pi / 365) * (hari_ke - 81))
        lintang_rad = math.radians(lat)

        # WIB = GMT+7, bujur standar 105°
        selisih_waktu = (105 - lng) / 15
        zuhur_desimal = 12.0 + selisih_waktu + (4 / 60)

        def format_jam_desimal(desimal):
            jam = int(desimal)
            menit = int((desimal - jam) * 60)
            return f"{jam:02d}:{menit:02d}"

        cos_h_subuh = (
            math.sin(math.radians(-20)) - math.sin(lintang_rad) * math.sin(deklinasi)
        ) / (math.cos(lintang_rad) * math.cos(deklinasi))
        cos_h_isya = (
            math.sin(math.radians(-18)) - math.sin(lintang_rad) * math.sin(deklinasi)
        ) / (math.cos(lintang_rad) * math.cos(deklinasi))

        cos_h_subuh = max(-1.0, min(1.0, cos_h_subuh))
        cos_h_isya = max(-1.0, min(1.0, cos_h_isya))

        durasi_subuh = math.degrees(math.acos(cos_h_subuh)) / 15
        durasi_isya = math.degrees(math.acos(cos_h_isya)) / 15

        subuh = zuhur_desimal - durasi_subuh
        ashar = zuhur_desimal + 3.25
        maghrib = zuhur_desimal + durasi_isya - (8 / 60)
        isya = zuhur_desimal + durasi_isya

        teks_balasan = (
            f"🕌 *JADWAL SHOLAT — {escape_md(nama_resmi.upper())}*\n"
            f"📍 _Provinsi: {escape_md(provinsi)}_\n"
            f"🌐 _Koordinat: {lat}, {lng}_\n"
            f"📅 _Tanggal: {datetime.now().strftime('%d %B %Y')}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌌 *SUBUH*     :  `{format_jam_desimal(subuh)}` WIB\n"
            f"☀️ *ZUHUR*     :  `{format_jam_desimal(zuhur_desimal)}` WIB\n"
            f"🌇 *ASHAR*     :  `{format_jam_desimal(ashar)}` WIB\n"
            f"🌅 *MAGHRIB*   :  `{format_jam_desimal(maghrib)}` WIB\n"
            f"🌃 *ISYA*      :  `{format_jam_desimal(isya)}` WIB\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        if catatan:
            teks_balasan += f"ℹ️ _Catatan: {escape_md(catatan)}_\n"
        teks_balasan += "\n💡 _Standard Kemenag RI (Kalender Global Hijriah)_"

        await safe_reply(update.message, teks_balasan)

    except Exception as err:
        logger.error(f"Gagal hitung astronomi koordinat: {err}")
        await update.message.reply_text(
            "❌ Terjadi kesalahan internal saat memproses algoritma waktu koordinat bumi."
        )


async def handle_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler otomatis saat user mengirim lokasi GPS."""
    if not update.message or not update.message.location:
        return
    user_loc = update.message.location
    lat, lng = user_loc.latitude, user_loc.longitude
    telegram_id = update.effective_user.id

    try:
        simpan_lokasi_user(telegram_id, lat, lng, kota="Lokasi GPS", sumber="gps")
    except Exception as e:
        logger.warning(f"Gagal simpan lokasi user: {e}")

    masjid = masjid_terdekat(lat, lng)

    teks_balasan = "📍 *Lokasi GPS Anda Berhasil Diterima!*\n\n"
    if masjid:
        teks_balasan += (
            f"🕌 Masjid Terdekat: *{escape_md(masjid['nama'])}*\n"
            f"🗺️ Jarak: ± {round(masjid['jarak'], 2)} km\n"
            f"📍 Alamat: {escape_md(masjid['alamat'])}"
        )
    else:
        teks_balasan += (
            "💡 Gunakan menu utama Mini App untuk melihat peta visual masjid mitra Raudha "
            "di sekitar Anda secara real-time."
        )

    await safe_reply(update.message, teks_balasan)


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
        .connect_timeout(30) \
        .read_timeout(30) \
        .write_timeout(30) \
        .pool_timeout(30) \
        .build()

    # --- COMMAND HANDLERS ---
    app.add_handler(CommandHandler("start", start))
    
    # --- BACKUP COMMANDS (Batch 16a) ---
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("listbackup", cmd_list_backup))
    
    # --- RESTORE COMMANDS (Batch 16b) ---
    app.add_handler(CommandHandler("restore", cmd_restore))
    app.add_handler(CommandHandler("batal", cmd_batal_restore))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.Document.ALL,
        handle_restore_confirm
    ))
    
    # --- COMMAND HANDLERS LAINNYA ---
    app.add_handler(CommandHandler("kota", handle_command_kota))
    app.add_handler(CommandHandler("masuk", handle_masuk))
    app.add_handler(CommandHandler("keluar", handle_keluar))
    # --- MESSAGE HANDLERS ---
    app.add_handler(MessageHandler(filters.LOCATION, handle_location_received))

    # ⚠️ web_app_data HARUS didaftarkan (group default 0)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # --- LOGGING GLOBAL (group=1, exclude web_app_data agar tidak dobel) ---
    async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.debug(f"[GLOBAL LOG] Update masuk: {type(update).__name__}")

    log_filter = filters.ALL & ~filters.StatusUpdate.WEB_APP_DATA
    app.add_handler(MessageHandler(log_filter, log_all_updates), group=1)

    # --- CALLBACK HANDLERS ---
    app.add_handler(CallbackQueryHandler(start, pattern="^back_to_main$"))

    submenu_patterns = (
        "^(menu_morning|menu_doa|menu_tanam|menu_arsitektur|"
        "menu_sholat|menu_ekonomi|menu_help|menu_about|"
        "sub_sholat_gps|sub_sholat_kota|sub_doa_pilihan|"
        "wacana_finansial_laziz|wacana_finansial_bmt|wacana_gerai_dinar)$"
    )
    app.add_handler(CallbackQueryHandler(handle_submenus, pattern=submenu_patterns))

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
