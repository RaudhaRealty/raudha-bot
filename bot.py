import logging
import json
import os
import requests
from datetime import date, time
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from data_doa import DATA_DOA

# ==========================================
# POSISI 2: BAGIAN TENGAH (FUNGSI HELPER) -> TARUH DI SINI ⭐
# ==========================================

UKURAN_FONT = {
    "kecil": {"nama": "🔎 Kecil", "pembatas": "▫️▫️▫️"},
    "sedang": {"nama": "🔍 Sedang", "pembatas": "◽◽◽"},
    "besar": {"nama": "🌟 Besar", "pembatas": "✨✨✨"}
}

def format_halaman_doa(jenis_doa, halaman_idx, ukuran="sedang"):
    daftar_lembar = DATA_DOA.get(jenis_doa, [])
    if not daftar_lembar or halaman_idx >= len(daftar_lembar) or halaman_idx < 0:
        return "Teks doa tidak ditemukan.", 1, 1
        
    lembar = daftar_lembar[halaman_idx]
    total_hal = len(daftar_lembar)
    
    # Pengaturan gaya berdasarkan ukuran font pilihan pengguna
    fmt = UKURAN_FONT.get(ukuran, UKURAN_FONT["sedang"])
    
    # Menyusun teks tampilan
    if ukuran == "besar":
        teks_tampilan = (
            f"🕌 **DOA {jenis_doa.upper()}** (Hal. {halaman_idx + 1}/{total_hal})\n"
            f"{fmt['pembatas']}\n\n"
            f"**{lembar['arab']}**\n\n" # Dicetak tebal untuk ukuran besar
            f"*{lembar['latin']}*\n\n"
            f"Artinya: {lembar['arti']}"
        )
    elif ukuran == "kecil":
        teks_tampilan = (
            f"🕌 **Doa {jenis_doa.capitalize()}** ({halaman_idx + 1}/{total_hal})\n"
            f"{lembar['arab']}\n"
            f"_{lembar['latin']}_\n"
            f"Artinya: {lembar['arti']}"
        )
    else: # Sedang (Default)
        teks_tampilan = (
            f"🕌 **Doa {jenis_doa.capitalize()}** (Hal. {halaman_idx + 1}/{total_hal})\n"
            f"{fmt['pembatas']}\n\n"
            f"{lembar['arab']}\n\n"
            f"_{lembar['latin']}_\n\n"
            f"Artinya: {lembar['arti']}"
        )
        
    return teks_tampilan, total_hal

def buat_keyboard_navigasi(jenis_doa, halaman_idx, total_hal, ukuran="sedang"):
    tombol_navigasi = []
    
    # 1. Baris Pertama: Tombol Navigasi Halaman
    if halaman_idx > 0:
        tombol_navigasi.append(InlineKeyboardButton("⬅️ Sebelumnya", callback_data=f"nav_{jenis_doa}_{halaman_idx-1}_{ukuran}"))
    if halaman_idx < total_hal - 1:
        tombol_navigasi.append(InlineKeyboardButton("Selanjutnya ➡️", callback_data=f"nav_{jenis_doa}_{halaman_idx+1}_{ukuran}"))
        
    # 2. Baris Kedua: Tombol Ulang & Ukuran Font
    baris_fitur = []
    if halaman_idx > 0:
        baris_fitur.append(InlineKeyboardButton("🔄 Ulang dari Awal", callback_data=f"nav_{jenis_doa}_0_{ukuran}"))
    
    # Tombol siklus ganti ukuran font (Kecil -> Sedang -> Besar -> Kecil)
    opsi_ukuran_berikutnya = {"kecil": "sedang", "sedang": "besar", "besar": "kecil"}
    ukuran_baru = opsi_ukuran_berikutnya[ukuran]
    nama_tombol_font = f"Font: {UKURAN_FONT[ukuran]['nama']}"
    baris_fitur.append(InlineKeyboardButton(nama_tombol_font, callback_data=f"nav_{jenis_doa}_{halaman_idx}_{ukuran_baru}"))
    
    # Kembali ke menu utama /doa
    tombol_kembali = [InlineKeyboardButton("🕌 Kembali ke Menu Doa", callback_data="menu_doa_utama")]

    # Gabungkan semua susunan tombol
    keyboard = []
    if tombol_navigasi:
        keyboard.append(tombol_navigasi)
    keyboard.append(baris_fitur)
    keyboard.append(tombol_kembali)
    
    return InlineKeyboardMarkup(keyboard)

import konten


# 1. Konfigurasi logging untuk melihat log jika terjadi error
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

import os

# TOKEN BOT (Ganti dengan token HTTP API dari @BotFather)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUBSCRIBERS_FILE = "subscribers.json"


# ============ FUNGSI BANTU UNTUK SUBSCRIBER ============

def load_subscribers():
    """Memuat daftar subscriber dari file JSON."""
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_subscribers(subscribers):
    """Menyimpan daftar subscriber ke file JSON."""
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subscribers, f, indent=2)

def pilih_harian(daftar):
    """Memilih konten berdasarkan tanggal."""
    hari = date.today().toordinal()
    return daftar[hari % len(daftar)]

# ============ COMMAND HANDLERS ============

# (Fungsi /start, /help, /morning, /ayat, /doa, /renungan, /tanam, /quote, /about
#  dari kode sebelumnya TETAP SAMA, tidak perlu diubah. Salin dari file lama Anda.)

# ==================== 2. CONTROLLER MENU UTAMA (/start) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    pesan = (
        f"🌸 Assalamu'alaikum, {user_name} 🌸\n\n"
        "Selamat datang di RAUDHA — Taman Surgawi 🌿\n\n"
        "\"Morning has broken like the first morning...\"\n"
        "— Cat Stevens\n\n"
        "Setiap hari adalah kesempatan baru untuk menanam di taman surgawi.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        
        "🌅 /morning   → Pesan pagi\n"
#       "📿 /ayat      → Ayat hari ini\n"
        "🕌 /doa       → Doa pilihan\n"
#       "🌷 /renungan  → Renungan singkat\n"
	"🕌 /sholat    → Jadwal sholat\n"
        "🌱 /tanam     → Amalan hari ini\n"
	"🏛️ /arsitektur  → Arsitektur Islam\n\n"
#       "🎵 /quote     → Quote inspiratif\n"
        "🔔 /subscribe → Terima Pesan harian\n"
	"📖 /help      → Bantuan\n"
        "⚙️ /about     → Tentang bot\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "A Better Place, A Better World 🌍"
    )
    await update.message.reply_text(pesan)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 **BANTUAN & DARURAT — 🌸 RAUDHA**\n\n"
        "Berikut adalah daftar perintah resmi yang dapat Anda gunakan:\n\n"
        "🌅 /start — Menu utama\n\n"
        "🚨 **NOMOR DARURAT & LAYANAN PUBLIK:**\n\n"
        "👮 /polisi — Hubungi Layanan Kepolisian\n"
        "🚑 /ambulans — Hubungi Ambulans / Medis\n"
        "👨‍🚒 /pemadam — Hubungi DamKar\n\n"  # Ditambahkan \n karena di bawahnya ada teks lagi
        "🔕 /unsubscribe — Berhenti menerima\n"
        "⚙️ /about — Tentang bot"  # Baris terakhir asli tanpa \n
    )  # <-- Tanda kurung penutup variabel text wajib ada di sini
    await update.message.reply_text(text, parse_mode="Markdown")


# --- CONTOH FUNGSI RESPONS MENU DARURAT BARU ---
async def polisi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👮 **Layanan Darurat Kepolisian:** Hubungi **110** atau hubungi Polres terdekat di kota Anda.", parse_mode="Markdown")

async def ambulans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚑 **Layanan Darurat Ambulans / Medis:** Hubungi **118** atau **119** untuk bantuan medis segera.", parse_mode="Markdown")

async def pemadam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👨‍🚒 **Layanan Darurat Pemadam Kebakaran:** Hubungi **113** untuk melaporkan kejadian kebakaran.", parse_mode="Markdown")


async def morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Pesan pembuka selamat pagi yang bersih dan rapi
    pesan = (
        "🌅 **Selamat pagi 🌸**\n\n"
        "\"Morning has broken like the first morning\n"
        "Blackbird has spoken like the first bird\n"
        "Praise for the singing, praise for the morning\n"
        "Praise for them springing fresh from the Word\"\n"
        "— Cat Stevens\n\n"
        "Semoga harimu penuh berkah 🌷\n"
        "*A Better Place, A Better World*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Silakan klik menu di bawah ini untuk inspirasi hari ini:"
    )
    
    # Membuat Inline Keyboard untuk sub-menu harian
    keyboard = [
        [
            InlineKeyboardButton("📿 Ayat Hari Ini", callback_data="sub_morning_ayat"),
            InlineKeyboardButton("🌷 Renungan", callback_data="sub_morning_renungan")
        ],
        [
            InlineKeyboardButton("🎵 Quote Inspiratif", callback_data="sub_morning_quote")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Kirim pesan beserta tombolnya
    await update.message.reply_text(pesan, reply_markup=reply_markup, parse_mode="Markdown")


# Fungsi untuk menangani klik tombol di bawah menu /morning
async def handle_morning_submenus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # 1. JIKA USER KLIK TOMBOL AYAT
    if data == "sub_morning_ayat":
        ayat = pilih_harian(konten.AYAT_HARIAN)
        teks_ayat = (
            "📿 **AYAT HARI INI**\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"\"{ayat['teks']}\"\n\n"
            f"({ayat['sumber']})"
        )
        await query.message.reply_text(teks_ayat, parse_mode="Markdown")
        
    # 2. JIKA USER KLIK TOMBOL RENUNGAN
    elif data == "sub_morning_renungan":
        # Mengambil data dari modul konten Anda seperti skrip lama Anda
        renungan = pilih_harian(konten.RENUNGAN) 
        teks_renungan = (
            "🌷 **RENUNGAN SINGKAT**\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{renungan}"
        )
        await query.message.reply_text(teks_renungan, parse_mode="Markdown")
        
    # 3. JIKA USER KLIK TOMBOL QUOTE
    elif data == "sub_morning_quote":
        # Mengambil data dari modul konten Anda seperti skrip lama Anda
        quote = pilih_harian(konten.QUOTE)
        teks_quote = (
            "🎵 **QUOTE INSPIRATIF**\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{quote}"
        )
        await query.message.reply_text(teks_quote, parse_mode="Markdown")


async def ayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = pilih_harian(konten.AYAT_HARIAN)
    pesan = f"📿 AYAT HARI INI 📿\n\n\"{a['teks']}\"\n\n— {a['sumber']}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi"
    await update.message.reply_text(pesan)

async def doa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = pilih_harian(konten.DOA_HARIAN)
    pesan = f"🕌 DOA HARI INI 🕌\n\n\"{d['teks']}\"\n\nArtinya:\n\"{d['arti']}\"\n\n— {d['sumber']}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi"
    await update.message.reply_text(pesan)

# MEMASUKKAN SCRIPT BARU
# ==========================================
# POSISI 3: BAGIAN INTERAKSI BOT (HANDLERS)
# ==========================================

# 1. Fungsi Utama saat Pengguna mengetik /doa
async def doa_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Gabungkan teks menggunakan tanda petik tiga agar bisa multi-baris dengan aman
    text = (
        "🕌 *Menu Doa Pilihan*\n"
        "Silakan pilih doa yang ingin Anda baca:"
    )
    
    # Gunakan format data "nav_" agar sistem per lembar/halaman bisa bekerja
    keyboard = [
        [
            InlineKeyboardButton("📖 Doa Kumail", callback_data="nav_kumail_0_sedang"),
            InlineKeyboardButton("🌙 Doa Nudbah", callback_data="nav_nudbah_0_sedang")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Perintah kirim pesan dipastikan berada di dalam fungsi doa_menu (menjorok ke dalam)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


# 2. Fungsi yang mendeteksi klik tombol (Navigasi halaman, Font, dan Kembali)
async def handle_interaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Logika jika tombol "Kembali ke Menu Doa" diklik
    if data == "menu_doa_utama":
        text = "🕌 *Menu Doa Pilihan*\nSilakan pilih doa khusus yang ingin Anda baca di bawah ini:"
        keyboard = [
            [
                InlineKeyboardButton("📖 Doa Kumail", callback_data="nav_kumail_0_sedang"),
                InlineKeyboardButton("🌙 Doa Nudbah", callback_data="nav_nudbah_0_sedang")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # Logika jika tombol navigasi halaman atau ganti ukuran font diklik
    if data.startswith("nav_"):
        _, jenis_doa, halaman_str, ukuran = data.split("_")
        halaman_idx = int(halaman_str)
        
        # Mengambil teks doa per lembar dari fungsi helper
        teks_tampilan, total_hal = format_halaman_doa(jenis_doa, halaman_idx, ukuran)
        
        # Membuat tombol navigasi baru (Sebelumnya, Selanjutnya, Font)
        reply_markup = buat_keyboard_navigasi(jenis_doa, halaman_idx, total_hal, ukuran)
        
        # Mengedit pesan lama dengan halaman yang baru (efek membalik halaman)
        await query.edit_message_text(text=teks_tampilan, reply_markup=reply_markup, parse_mode="Markdown")




async def renungan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = pilih_harian(konten.RENUNGAN)
    pesan = f"🌷 RENUNGAN HARI INI 🌷\n\n{r}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi\nA Better Place, A Better World"
    await update.message.reply_text(pesan)

async def tanam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = pilih_harian(konten.AMALAN_HARIAN)
    pesan = f"🌱 TANAM HARI INI 🌱\n\nSetiap amal adalah benih.\nSetiap hari adalah musim tanam.\n\n━━━━━━━━━━━━━━━━━━\nAmalan hari ini:\n{a}\n━━━━━━━━━━━━━━━━━━\n\nSemoga Allah menerima amal kita 🌷"
    await update.message.reply_text(pesan)

async def quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = pilih_harian(konten.QUOTE)
    pesan = f"🎵 QUOTE HARI INI 🎵\n\n\"{q['teks']}\"\n\n— {q['sumber']}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi"
    await update.message.reply_text(pesan)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pesan = f"🌸 RAUDHA — Taman Surgawi\n\nRecreate All The New Day\n(inspired by Cat Stevens — \"Morning Has Broken\")\n\nA Better Place, A Better World\n\n━━━━━━━━━━━━━━━━━━\nRaudha adalah bot yang menemani hari-harimu\ndengan nuansa taman surgawi.\n━━━━━━━━━━━━━━━━━━\n\n\Morning has broken like the first morning..."
    await update.message.reply_text(pesan)

# ============ JADWAL SHOLAT ============

# ============ JADWAL SHOLAT ============

async def sholat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan jadwal sholat berdasarkan kota."""
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "🕌 JADWAL SHOLAT 🕌\n\n"
            "Silakan ketik ulang dengan nama kota.\n\n"
            "Format:\n"
            "`/sholat [nama kota]`\n\n"
            "Contoh:\n"
            "`/sholat Jakarta`\n"
            "`/sholat Bandung`\n"
            "`/sholat Surabaya`",
            parse_mode="Markdown"
        )
        return
    
    kota = " ".join(args)
    
    loading_msg = await update.message.reply_text(f"🕌 Mencari jadwal sholat untuk {kota}...")
    
    try:
        url = (
            f"https://api.aladhan.com/v1/timingsByCity"
            f"?city={kota}&country=Indonesia&method=20&tune=0,8,0,0,0,9,0,0,0"
        )
        
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get("code") != 200:
            await loading_msg.edit_text(
                f"❌ Maaf, kota {kota} tidak ditemukan.\n\n"
                "Coba periksa ejaan atau gunakan nama kota lain."
            )
            return
        
        timings = data["data"]["timings"]

        # Fungsi bantu untuk menambah menit ke format waktu "HH:MM"
        from datetime import datetime, timedelta
        def tambah_menit(waktu_str, menit):
            waktu = datetime.strptime(waktu_str, "%H:%M")
            waktu_baru = waktu + timedelta(minutes=menit)
            return waktu_baru.strftime("%H:%M")

        # Terapkan offset: Subuh +8 menit, Maghrib +9 menit
        timings["Fajr"] = tambah_menit(timings["Fajr"], 8)
        timings["Maghrib"] = tambah_menit(timings["Maghrib"], 9)

        date_info = data["data"]["date"]
        
        hijri = date_info["hijri"]
        tanggal_hijri = f"{hijri['day']} {hijri['month']['en']} {hijri['year']} H"
        tanggal_masehi = date_info["readable"]
        
        pesan = (
            f"🕌 JADWAL SHOLAT — {kota.upper()} 🕌\n"
            f"📅 {tanggal_masehi}\n"
            f"🌙 {tanggal_hijri}\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🌅 Imsak     : {timings['Imsak']}\n"
            f"🌄 Subuh     : {timings['Fajr']}\n"
            f"☀️ Dzuhur    : {timings['Dhuhr']}\n"
            f"🌤️ Ashar     : {timings['Asr']}\n"
            f"🌇 Maghrib   : {timings['Maghrib']}\n"
            f"🌙 Isya      : {timings['Isha']}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📍 Metode: Kemenag RI\n"
            f"🕌 Subuh & Maghrib sesuai kriteria Muhammadiyah\n"
            f"🌿 Raudha — Taman Surgawi"
        )
        
        await loading_msg.edit_text(pesan)
        
    except requests.exceptions.Timeout:
        await loading_msg.edit_text("⏱️ Maaf, server sedang sibuk. Coba lagi beberapa saat lagi.")
    except Exception as e:
        logging.error(f"Error di /sholat: {e}")
        await loading_msg.edit_text("❌ Maaf, terjadi kesalahan. Coba lagi nanti.")


# ============ DOA KUMAIL ============

async def doakumail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mulai menampilkan Doa Kumail dari halaman 1."""
    await kirim_halaman_doa(update, context, 0)


async def kirim_halaman_doa(update: Update, context: ContextTypes.DEFAULT_TYPE, halaman: int):
    """Kirim/edit pesan dengan halaman doa tertentu + tombol navigasi."""
    total = len(konten.DOA_KUMAIL)
    halaman = max(0, min(halaman, total - 1))
    
    item = konten.DOA_KUMAIL[halaman]
    pesan = (
        f"📖 **DOA KUMAIL** 📖\n"
        f"_{item['judul']} — Bagian {halaman + 1} dari {total}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{item['arab']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"**Terjemahan:**\n\n"
        f"{item['terjemahan']}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
        # Baris 1: navigasi
    nav_buttons = []
    if halaman > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Sebelumnya", callback_data=f"doa_prev_{halaman}"))
    if halaman < total - 1:
        nav_buttons.append(InlineKeyboardButton("▶️ Selanjutnya", callback_data=f"doa_next_{halaman}"))
    
    # Baris 2: aksi lain
    action_buttons = [
        InlineKeyboardButton("🔄 Ulang", callback_data="doa_restart"),
        InlineKeyboardButton("🎧 Audio", callback_data="doa_audio"),
    ]
    
    # Gabungkan jadi 2 baris
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append(action_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        # Dari klik tombol — edit pesan yang ada
        await update.callback_query.edit_message_text(
            text=pesan, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        # Dari command /doakumail — kirim pesan baru
        await update.message.reply_text(
            text=pesan, reply_markup=reply_markup, parse_mode="Markdown"
        )


async def doa_navigasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle klik tombol navigasi Doa Kumail."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "doa_restart":
        await kirim_halaman_doa(update, context, 0)
    elif data == "doa_audio":
        pesan_audio = (
            "🎧 AUDIO DOA KUMAIL 🎧\n\n"
            "Berikut rekaman Doa Kumail yang bisa Anda dengarkan:\n\n"
            "🔊 Rekaman Populer:\n"
            "• Abu Thar al-Halawaji (31 menit)\n"
            "• Doa Kumail dengan terjemahan Indonesia\n\n"
            "📺 Link YouTube:\n"
            "https://www.youtube.com/results?search_query=doa+kumail\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💡 Tips: Gunakan headphone untuk kekhusyukan\n\n"
            "🌿 Raudha — Taman Surgawi"
        )
        await query.edit_message_text(
            text=pesan_audio,
            disable_web_page_preview=False,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Kembali ke Doa", callback_data="doa_restart")
            ]])
        )
    elif data.startswith("doa_prev_"):
        halaman = int(data.split("_")[-1])
        await kirim_halaman_doa(update, context, halaman - 1)
    elif data.startswith("doa_next_"):
        halaman = int(data.split("_")[-1])
        await kirim_halaman_doa(update, context, halaman + 1)


# ============ DOA NUDBAH ============

async def doanudbah(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mulai menampilkan Doa Nudbah dari halaman 1."""
    await kirim_halaman_nudbah(update, context, 0)


async def kirim_halaman_nudbah(update: Update, context: ContextTypes.DEFAULT_TYPE, halaman: int):
    """Kirim/edit pesan dengan halaman Doa Nudbah tertentu + tombol navigasi."""
    total = len(konten.DOA_NUDBAH)
    halaman = max(0, min(halaman, total - 1))
    
    item = konten.DOA_NUDBAH[halaman]
    pesan = (
        f"🌙 **DOA NUDBAH** 🌙\n"
        f"_{item['judul']} — Bagian {halaman + 1} dari {total}_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{item['arab']}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"**Terjemahan:**\n\n"
        f"{item['terjemahan']}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    # Baris 1: navigasi
    nav_buttons = []
    if halaman > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Sebelumnya", callback_data=f"nudbah_prev_{halaman}"))
    if halaman < total - 1:
        nav_buttons.append(InlineKeyboardButton("▶️ Selanjutnya", callback_data=f"nudbah_next_{halaman}"))
    
    # Baris 2: aksi lain
    action_buttons = [
        InlineKeyboardButton("🔄 Ulang", callback_data="nudbah_restart"),
        InlineKeyboardButton("🎧 Audio", callback_data="nudbah_audio"),
    ]
    
    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append(action_buttons)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=pesan, reply_markup=reply_markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=pesan, reply_markup=reply_markup, parse_mode="Markdown"
        )


async def nudbah_navigasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle klik tombol navigasi Doa Nudbah."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data == "nudbah_restart":
        await kirim_halaman_nudbah(update, context, 0)
    elif data == "nudbah_audio":
        pesan_audio = (
            "🎧 AUDIO DOA NUDBAH 🎧\n\n"
            "Berikut rekaman Doa Nudbah yang bisa Anda dengarkan:\n\n"
            "🔊 Rekaman Populer:\n"
            "• Doa Nudbah dengan terjemahan\n\n"
            "📺 Link YouTube:\n"
            "https://www.youtube.com/results?search_query=doa+nudbah\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💡 Tips: Gunakan headphone untuk kekhusyukan\n\n"
            "🌿 Raudha — Taman Surgawi"
        )
        await query.edit_message_text(
            text=pesan_audio,
            disable_web_page_preview=False,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Kembali ke Doa", callback_data="nudbah_restart")
            ]])
        )
    elif data.startswith("nudbah_prev_"):
        halaman = int(data.split("_")[-1])
        await kirim_halaman_nudbah(update, context, halaman - 1)
    elif data.startswith("nudbah_next_"):
        halaman = int(data.split("_")[-1])
        await kirim_halaman_nudbah(update, context, halaman + 1)


async def arsitektur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = pilih_harian(konten.ARSITEKTUR)
    pesan = (
        f"🏛️ ARSITEKTUR ISLAM HARI INI 🏛️\n\n"
        f"🕌 {item['judul']}\n"
        f"📍 {item['lokasi']}\n\n"
        f"{item['deskripsi']}\n\n"
        f"🖼️ Lihat foto:\n{item['link']}\n\n"
        f"Sumber: {item['sumber']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🌿 Raudha — Taman Surgawi\n"
        "A Better Place, A Better World"
    )
    await update.message.reply_text(pesan)

# ============ HANDLER UNTUK SUBSCRIBE ============

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_name = update.effective_user.first_name
    subscribers = load_subscribers()
    
    if user_id in subscribers:
        await update.message.reply_text("✅ Kamu sudah terdaftar untuk pesan harian Raudha!")
        return
    
    subscribers[user_id] = {"name": user_name}
    save_subscribers(subscribers)
    
    pesan = (
        f"🔔 Alhamdulillah, {user_name}!\n\n"
        "Kamu resmi berlangganan pesan harian RAUDHA 🌸\n\n"
        "Setiap pagi jam 05.00 WIB, kamu akan menerima:\n"
        "🌅 Pesan 'Morning Has Broken'\n"
        "📿 Ayat hari ini\n"
        "🌱 Amalan hari ini\n\n"
        "Ketik /unsubscribe untuk berhenti kapan saja.\n\n"
        "A Better Place, A Better World 🌍"
    )
    await update.message.reply_text(pesan)
    logging.info(f"User baru berlangganan: {user_id} ({user_name})")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscribers = load_subscribers()
    
    if user_id in subscribers:
        del subscribers[user_id]
        save_subscribers(subscribers)
        await update.message.reply_text("🔕 Kamu telah berhenti berlangganan pesan harian Raudha.\n\nSemoga Allah memberkahi harimu 🌷")
        logging.info(f"User berhenti berlangganan: {user_id}")
    else:
        await update.message.reply_text("Kamu belum terdaftar untuk pesan harian.\n\nKetik /subscribe untuk berlangganan 🌸")

async def cek_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    subscribers = load_subscribers()
    
    if user_id in subscribers:
        await update.message.reply_text("✅ Kamu terdaftar untuk pesan harian Raudha.\n\nKetik /unsubscribe untuk berhenti.")
    else:
        await update.message.reply_text("❌ Kamu belum terdaftar.\n\nKetik /subscribe untuk berlangganan pesan harian 🌸")

async def kirim_pagi(context: ContextTypes.DEFAULT_TYPE):
    """Fungsi yang dijalankan otomatis setiap pagi untuk mengirim pesan."""
    subscribers = load_subscribers()
    
    if not subscribers:
        logging.info("Tidak ada subscriber, pesan pagi tidak dikirim.")
        return
    
    # Ambil konten
    ayat = pilih_harian(konten.AYAT_HARIAN)
    amalan = pilih_harian(konten.AMALAN_HARIAN)
    
    pesan = (
        "🌅 Selamat pagi 🌸\n\n"
        "\"Morning has broken like the first morning\n"
        "Blackbird has spoken like the first bird\n"
        "Praise for the singing, praise for the morning\n"
        "Praise for them springing fresh from the Word\"\n"
        "— Cat Stevens\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📿 Ayat hari ini:\n\"{ayat['teks']}\"\n({ayat['sumber']})\n\n"
        f"🌱 Amalan hari ini:\n{amalan}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Semoga harimu berkah 🌷\n"
        "A Better Place, A Better World"
    )
    
    # Kirim ke semua subscriber
    for user_id in subscribers.keys():
        try:
            await context.bot.send_message(chat_id=int(user_id), text=pesan)
            logging.info(f"Pesan pagi terkirim ke {user_id}")
        except Exception as e:
            logging.error(f"Gagal mengirim ke {user_id}: {e}")

# ============ MAIN ============
# ==========================================
# POSISI 4: BAGIAN PALING BAWAH (MAIN FUNCTION)
# ==========================================
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Command handlers utama
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("morning", morning))
    application.add_handler(CommandHandler("ayat", ayat))

    # Pastikan perintah /morning yang utama tetap aktif
    application.add_handler(CommandHandler("morning", morning))
    
    # TAMBAHKAN BARIS INI UNTUK MENANGKAP KLIK SUB-MENU MORNING:
    application.add_handler(CallbackQueryHandler(handle_morning_submenus, pattern="^sub_morning_"))
    
    # --- PERBAIKAN MENU DOA UTAMA ---
    application.add_handler(CommandHandler("doa", doa_menu))
    
    # Menangkap interaksi navigasi halaman baru, ukuran font, dan tombol kembali
    application.add_handler(CallbackQueryHandler(handle_interaction, pattern="^(nav_|menu_doa_utama)"))
    # ---------------------------------
    
    application.add_handler(CommandHandler("renungan", renungan))
    application.add_handler(CommandHandler("tanam", tanam))
    application.add_handler(CommandHandler("quote", quote))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("arsitektur", arsitektur))
    application.add_handler(CommandHandler("sholat", sholat))

    # --- JALUR LAMA (DI-NONAKTIFKAN) ---
    # Jalur lama dinonaktifkan agar sistem navigasi per lembar yang baru tidak bentrok
    # application.add_handler(CommandHandler("doakumail", doakumail))       
    # application.add_handler(CallbackQueryHandler(doa_navigasi, pattern="^doa_"))  
    # application.add_handler(CommandHandler("doanudbah", doanudbah))
    # application.add_handler(CallbackQueryHandler(nudbah_navigasi, pattern="^nudbah_"))
    # application.add_handler(CallbackQueryHandler(handle_submenu, pattern="^submenu_"))	
    # ------------------------------------
    # Jalur lama /ayat, /renungan, /quote di menu utama silakan dinonaktifkan (beri tanda #)
    # application.add_handler(CommandHandler("ayat", ayat))
    # application.add_handler(CommandHandler("renungan", renungan))
    # application.add_handler(CommandHandler("quote", quote))

    # TAMBAHKAN PERINTAH DARURAT BARU INI:
    application.add_handler(CommandHandler("polisi", polisi_command))
    application.add_handler(CommandHandler("ambulans", ambulans_command))
    application.add_handler(CommandHandler("pemadam", pemadam_command))

    
    # Subscribe handlers
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("cek_subscribe", cek_subscribe))

    # JobQueue: Kirim pesan pagi setiap hari jam 05:00
    job_queue = application.job_queue
    job_queue.run_daily(kirim_pagi, time=time(hour=5, minute=0))	
    logging.info("JobQueue: Pesan pagi dijadwalkan setiap jam 05:00.")

    print("🌸 Bot Raudha sedang berjalan dengan sistem menu baru...")
    application.run_polling()


if __name__ == '__main__':
    main()


# ==========================================
# KONTEN ARSITEKTUR ISLAM
# ==========================================

ARSITEKTUR = [
    {
        "judul": "Masjid Kubah Emas (Dian Al-Mahri)",
        "lokasi": "Depok, Jawa Barat, Indonesia 🇮🇩",
        "deskripsi": (
            "Masjid dengan 6 menara dan 5 kubah yang dilapisi emas setebal 2-3 mm. "
            "Dibuka untuk umum sejak 31 Desember 2006. Dapat menampung sekitar 20.000 jamaah. "
            "Menjadi salah satu masjid termegah di Indonesia."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Masjid_Kubah_Emas",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Mezquita-Catedral de Córdoba",
        "lokasi": "Córdoba, Spanyol 🇪🇸",
        "deskripsi": (
            "Masjid agung Dinasti Umayyah di Eropa yang kemudian dialihfungsikan menjadi katedral. "
            "Terkenal dengan lebih dari 1.000 kolom marmer dan lengkungan ganda (double arches) "
            "yang ikonik. Dibangun mulai tahun 785 M oleh Abdurrahman I."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Mezquita_de_C%C3%B3rdoba",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Faisal Mosque",
        "lokasi": "Islamabad, Pakistan 🇵🇰",
        "deskripsi": (
            "Masjid terbesar di Pakistan, dirancang oleh arsitek Turki Vedat Dalokay. "
            "Selesai dibangun tahun 1986 dengan desain tenda Bedouin modern. "
            "Tidak memiliki kubah tradisional — bentuknya menyerupai tenda padang pasir."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Faisal_Mosque",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Sheikh Lotfollah Mosque",
        "lokasi": "Isfahan, Iran 🇮🇷",
        "deskripsi": (
            "Mahakarya arsitektur Safavid di Naqsh-i Jahan Square. "
            "Dibangun 1603-1619 pada masa Shah Abbas I. "
            "Terkenal dengan kubah dan interior mosaik yang memukau, "
            "serta permainan cahaya matahari yang menakjubkan."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Sheikh_Lotfollah_Mosque",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Masjid Sultan Ahmed (Blue Mosque)",
        "lokasi": "Istanbul, Turki 🇹🇷",
        "deskripsi": (
            "Dikenal sebagai Blue Mosque karena interiornya dihiasi lebih dari 20.000 "
            "ubin keramik Iznik berwarna biru. Dibangun 1609-1616 pada masa Sultan Ahmed I. "
            "Memiliki 6 menara — saat itu dianggap kontroversial karena setara dengan Masjidil Haram."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Sultan_Ahmed_Mosque",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Taj Mahal",
        "lokasi": "Agra, India 🇮🇳",
        "deskripsi": (
            "Mausoleum megah yang dibangun Kaisar Mughal Shah Jahan untuk istrinya, "
            "Mumtaz Mahal. Selesai tahun 1653 setelah 22 tahun pembangunan. "
            "Salah satu dari Tujuh Keajaiban Dunia dan simbol cinta abadi."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Taj_Mahal",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Masjid Al-Haram",
        "lokasi": "Makkah, Arab Saudi 🇸🇦",
        "deskripsi": (
            "Masjid paling suci dalam Islam dan masjid terbesar di dunia. "
            "Di dalamnya terdapat Ka'bah, kiblat umat Islam sedunia. "
            "Dapat menampung lebih dari 2 juta jamaah saat musim haji."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Al-Masjid_al-Haram",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Masjid Nabawi",
        "lokasi": "Madinah, Arab Saudi 🇸🇦",
        "deskripsi": (
            "Masjid kedua paling suci dalam Islam, dibangun oleh Nabi Muhammad ﷺ. "
            "Di dalamnya terdapat makam Nabi ﷺ dan Raudhah — "
            "taman surgawi yang disebut dalam hadits. "
            "Arsitekturnya terus diperluas hingga kini dengan kubah hijau ikonik."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Al-Masjid_an-Nabawi",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Masjid Sultan Omar Ali Saifuddin",
        "lokasi": "Bandar Seri Begawan, Brunei 🇧🇳",
        "deskripsi": (
            "Masjid dengan kubah emas dan laguna buatan yang menyerupai taman surgawi. "
            "Selesai dibangun tahun 1958. Dinobatkan sebagai salah satu masjid "
            "terindah di Asia Tenggara dan dunia."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Sultan_Omar_Ali_Saifuddin_Mosque",
        "sumber": "Wikimedia Commons"
    },
    {
        "judul": "Masjid Putra (Putra Mosque)",
        "lokasi": "Putrajaya, Malaysia 🇲🇾",
        "deskripsi": (
            "Masjid berwarna merah muda (rose-tinted) menghadap danau buatan. "
            "Selesai dibangun tahun 1999. Terinspirasi dari arsitektur Persia "
            "dan Maroko. Menjadi ikon kota administratif Malaysia."
        ),
        "link": "https://commons.wikimedia.org/wiki/Category:Putra_Mosque",
        "sumber": "Wikimedia Commons"
    },
]