import logging
import urllib.parse
import os

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

from data_doa import UKURAN_FONT
from modul_sholat import cari_kota, ambil_jadwal_sholat, format_jadwal, masjid_terdekat
from modul_database import simpan_lokasi_user, ambil_lokasi_user, hitung_jarak

# ==================== 1. KONFIGURASI ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# GANTI DENGAN TOKEN DARI @BotFather
TOKEN = "8326864946:AAFgDCXJtjT3KYbHCuHW_ZLqMLTvBpIDjSY"

FOLDER_DOA = "data_doa"


# ==================== 2. FUNGSI PEMBACA FILE DOA ====================
def baca_halaman_doa(nama_file: str) -> list:
    """
    Membaca file .txt doa, memisahkan per halaman dengan penanda '==='.
    Setiap halaman berisi tag [ARAB], [LATIN], [ARTI].
    """
    path = os.path.join(FOLDER_DOA, f"{nama_file}.txt")
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        isi = f.read()

    blok_list = [b.strip() for b in isi.split("===") if b.strip()]
    halaman = []

    for blok in blok_list:
        arab, latin, arti = "", "", ""
        mode = None
        for baris in blok.splitlines():
            tag = baris.strip().upper()
            if tag == "[ARAB]":
                mode = "arab"; continue
            elif tag == "[LATIN]":
                mode = "latin"; continue
            elif tag == "[ARTI]":
                mode = "arti"; continue

            if mode == "arab":
                arab += baris + "\n"
            elif mode == "latin":
                latin += baris + "\n"
            elif mode == "arti":
                arti += baris + "\n"

        halaman.append({
            "arab": arab.strip(),
            "latin": latin.strip(),
            "arti": arti.strip()
        })

    return halaman


def bikin_tombol_paginasi(nama_doa, halaman_sekarang, total, tombol_kembali):
    """Membuat tombol navigasi halaman dinamis."""
    nav_row = []
    if halaman_sekarang > 1:
        nav_row.append(InlineKeyboardButton(
            "⬅️ Sebelumnya",
            callback_data=f"{nama_doa}_hal{halaman_sekarang - 1}"
        ))
    if halaman_sekarang < total:
        nav_row.append(InlineKeyboardButton(
            "Selanjutnya ➡️",
            callback_data=f"{nama_doa}_hal{halaman_sekarang + 1}"
        ))

    keyboard = []
    if nav_row:
        keyboard.append(nav_row)

    # 🔍 TOMBOL BARU: Tampilkan Arab Saja

    keyboard.append([InlineKeyboardButton(
        "🔍 Tampilkan Arab Saja",
        callback_data=f"{nama_doa}_arabonly_{halaman_sekarang}"
    )])

    if halaman_sekarang == total:
        keyboard.append([InlineKeyboardButton(
            f"📥 Unduh PDF {nama_doa.title()} Lengkap",
            url="https://www.google.com"
        )])

    keyboard.append([tombol_kembali])
    return InlineKeyboardMarkup(keyboard)

def bikin_tombol_arab_only(nama_doa, halaman_sekarang, total):
    """Tombol navigasi khusus mode Arab saja."""
    nav_row = []
    if halaman_sekarang > 1:
        nav_row.append(InlineKeyboardButton(
            "⬅️ Sebelumnya",
            callback_data=f"{nama_doa}_arabonly_{halaman_sekarang - 1}"
        ))
    if halaman_sekarang < total:
        nav_row.append(InlineKeyboardButton(
            "Selanjutnya ➡️",
            callback_data=f"{nama_doa}_arabonly_{halaman_sekarang + 1}"
        ))

    keyboard = []
    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton(
        "🔙 Kembali ke Tampilan Lengkap",
        callback_data=f"{nama_doa}_hal{halaman_sekarang}"
    )])

    keyboard.append([InlineKeyboardButton(
        "⬅️ Kembali ke Menu Doa Pilihan",
        callback_data="sub_doa_pilihan"
    )])

    return InlineKeyboardMarkup(keyboard)


async def tampilkan_arab_saja(query, nama_doa, halaman_ke):
    """Menampilkan halaman khusus teks Arab saja, lebih besar & lega."""
    halaman_list = baca_halaman_doa(nama_doa)

    if not halaman_list:
        await query.edit_message_text(
            f"⚠️ File `{nama_doa}.txt` belum tersedia.",
            parse_mode='Markdown'
        )
        return

    total = len(halaman_list)
    if halaman_ke < 1 or halaman_ke > total:
        halaman_ke = 1

    doa = halaman_list[halaman_ke - 1]

    text = (
        f"📖 **ARAB SAJA — {nama_doa.upper()}**\n"
        f"_(Halaman {halaman_ke} / {total})_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{doa['arab']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 _Tips: tekan & tahan teks Arab di atas untuk menyalinnya._"
    )

    reply_markup = bikin_tombol_arab_only(nama_doa, halaman_ke, total)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== 3. MENU UTAMA (/start) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 **Salam dan Selamat datang di Bot Raudha**\n\n"
        "Silakan pilih layanan di bawah ini untuk memulai:"
    )
    keyboard = [
        [
            InlineKeyboardButton("🌅 Morning", callback_data="menu_morning"),
            InlineKeyboardButton("🤲 Doa", callback_data="menu_doa")
        ],
        [
            InlineKeyboardButton("🌱 Tanam", callback_data="menu_tanam"),
            InlineKeyboardButton("🏛️ Arsitektur", callback_data="submenu_arsitektur")
        ],
        [
            InlineKeyboardButton("🕌 Sholat", callback_data="menu_sholat"),
            InlineKeyboardButton("🔔 Subscribe", callback_data="menu_subscribe")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
            InlineKeyboardButton("ℹ️ About", callback_data="menu_about")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 4. SUB-MENU NAVIGASI ====================
async def handle_submenus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    keyboard = []
    text = ""

    if data == "menu_morning":
        text = "🌅 **MORNING MENU - RAUDHA**\n\nAwali hari Anda dengan dzikir dan inspirasi pagi."
        keyboard = [
            [InlineKeyboardButton("☀️ Dzikir Pagi Singkat", callback_data="run_dzikir_pagi")],
            [InlineKeyboardButton("📜 Inspirasi Pagi Ini", callback_data="run_inspirasi")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "menu_doa":
        text = (
            "🤲 **MENU DOA - RAUDHA**\n\n"
            "_Berdoalah kepada-Ku, niscaya akan Aku perkenankan bagimu._\n(QS. Ghafir: 60).\n\n"
            "Silakan pilih rumpun doa yang ingin Anda amalkan di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🏡 Doa Harian Penting", callback_data="run_doa_harian")],
            [InlineKeyboardButton("🛡️ Doa Perlindungan", callback_data="run_doa_lindung")],
            [InlineKeyboardButton("📖 Doa Pilihan & Shalawat", callback_data="sub_doa_pilihan")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "sub_doa_pilihan":
        text = (
            "📖 **MENU DOA PILIHAN & SHALAWAT**\n\n"
            "Kumpulan doa agung, munajat, amalan malam Jum'at, serta untaian shalawat."
        )
        keyboard = [
            [
                InlineKeyboardButton("📜 Doa Kumail", callback_data="run_doa_kumail"),
                InlineKeyboardButton("✨ Doa Ziyarah", callback_data="run_doa_ziyarah")
            ],
            [
                InlineKeyboardButton("🌙 Doa Nudbah", callback_data="run_doa_nudbah"),
                InlineKeyboardButton("📿 Pilihan Shalawat", callback_data="run_doa_shalawat")
            ],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")]
        ]

    elif data == "menu_tanam":
        text = (
            "🌱 **MENU TANAM RAUDHA**\n\n"
            "Selamat datang di gerakan Raudha Tanam.\n\n"
            "Silakan pilih program kontribusi di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🌳 Sedekah Pohon Jariyah", url="https://www.google.com")],
            [InlineKeyboardButton("📖 Panduan Eko-Pesantren", url="https://www.google.com")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "submenu_arsitektur":
        text = (
            "🏛️ **MENU ARSITEKTUR RAUDHA**\n\n"
            "Selamat datang di kompilasi arsitektur dan layanan perencanaan masjid Raudha.\n\n"
            "Silakan jelajahi karya kami:"
        )
        keyboard = [
            [InlineKeyboardButton("🕌 Masjid Terkenal di Dunia", url="https://google.com")],
            [InlineKeyboardButton("📂 Portofolio Desain Raudha", url="https://google.com")],
            [InlineKeyboardButton("💬 Konsultasi dengan Arsitek", url="https://wa.me")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "menu_sholat":
        text = (
            "🕌 **MENU JADWAL SHOLAT & LOKASI**\n\n"
            "📌 **Opsi 1 (Otomatis):** Gunakan lokasi GPS ponsel Anda.\n"
            "📌 **Opsi 2 (Manual):** Cari berdasarkan nama Kota/Kabupaten."
        )
        keyboard = [
            [
                InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps"),
                InlineKeyboardButton("🔍 Cari Nama Kota", callback_data="sub_sholat_kota")
            ],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "sub_sholat_gps":
        text = (
            "📍 **PENCARIAN OTOMATIS VIA GPS**\n\n"
            "Silakan kirim lokasi terkini Anda dengan menekan ikon klip kertas (📎) → **Location**."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]]

    elif data == "sub_sholat_kota":
        text = (
            "🔍 **PENCARIAN MANUAL NAMA KOTA**\n\n"
            "Silakan ketik nama Kota dengan perintah `/kota`.\n\n"
            "👉 *Contoh*: `/kota Banjarnegara`"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]]

    elif data == "menu_subscribe":
        text = (
            "🔔 **LAYANAN LANGGANAN (SUBSCRIBE) RAUDHA**\n\n"
            "Silakan pilih jenis paket langganan di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Langganan Dzikir Pagi & Sore", callback_data="run_sub_dzikir")],
            [InlineKeyboardButton("✅ Langganan Inspirasi & Doa Mingguan", callback_data="run_sub_weekly")],
            [InlineKeyboardButton("❌ Berhenti Berlangganan Semua", callback_data="run_unsubscribe")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "menu_help":
        text = (
            "❓ **BANTUAN & PANDUAN PENGGUNAAN BOT**\n\n"
            "1. Perintah `/start` untuk kembali ke menu utama.\n"
            "2. Gunakan `/kota [Nama Kota]` untuk jadwal sholat manual.\n\n"
            "Hubungi admin jika bot mengalami hambatan:"
        )
        keyboard = [
            [InlineKeyboardButton("📞 Hubungi Admin Support", url="https://wa.me")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    elif data == "menu_about":
        text = (
            "ℹ️ **TENTANG PLATFORM RAUDHA**\n\n"
            "Bot Raudha adalah asisten spiritual virtual penyelarasan tiga esensi kehidupan umat:\n\n"
            "🌱 Tanam — Dedikasi terhadap gerakan pelestarian lingkungan.\n"
            "🏛️ Arsitektur — Perencanaan fisik rumah ibadah (masjid) yang estetis.\n"
            "🤲 Spiritualitas — Tuntunan ibadah dan doa harian.\n\n"
            "Raudha Foundation © 2026"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 5. HANDLER /kota & GPS ====================




async def handle_command_kota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Proses /kota [Nama]. Kalau tanpa argumen, tampilkan menu pilih kota."""
    nama_kota = " ".join(context.args).strip() if context.args else ""

    # Kalau /kota tanpa argumen → tampilkan menu
    if not nama_kota:
        await tampilkan_menu_kota(update.message)
        return

    # Cari kota exact / partial
    kota = cari_kota(nama_kota)

    # Kalau tidak ketemu, coba fuzzy match
    if not kota:
        saran = cari_kota_fuzzy(nama_kota)
        if saran:
            keyboard = []
            for s in saran[:5]:
                keyboard.append([InlineKeyboardButton(
                    f"🏙️ {s['nama']} ({s['provinsi']})",
                    callback_data=f"kota_{s['nama'].lower().replace(' ', '_')}"
                )])
            keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")])
            await update.message.reply_text(
                f"❌ Kota *{nama_kota}* tidak ditemukan.\n\n"
                f"Mungkin maksud Anda salah satu di bawah ini:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
        else:
            keyboard = [
                [InlineKeyboardButton("🔍 Lihat Daftar Kota", callback_data="sub_sholat_kota")],
                [InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps")],
                [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
            ]
            await update.message.reply_text(
                f"❌ Kota *{nama_kota}* tidak ditemukan.\n\n"
                f"Coba:\n"
                f"• Periksa ejaan\n"
                f"• Pilih dari daftar kota\n"
                f"• Kirim lokasi GPS Anda",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return

    # Kota ditemukan → tampilkan jadwal
    await kirim_jadwal_kota(update.message, kota)


async def kirim_jadwal_kota(message, kota):
    """Helper: kirim jadwal sholat untuk kota tertentu."""
    jadwal = ambil_jadwal_sholat(kota["lat"], kota["lng"])
    text = format_jadwal(jadwal, kota["nama"])

    if "provinsi" in kota:
        text += f"\n🏙️ Provinsi: {kota['provinsi']}\n"
    text += f"📍 Koordinat: `{kota['lat']}, {kota['lng']}`\n"

    simpan_lokasi_user(
        message.chat_id,
        kota["lat"], kota["lng"],
        kota=kota["nama"], sumber="kota"
    )

    keyboard = [
        [InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps")],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
    ]
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def tampilkan_menu_kota(message):
    """Helper: tampilkan menu pilih kota populer."""
    text = (
        "🔍 **PENCARIAN KOTA — JADWAL SHOLAT**\n\n"
        "Pilih kota populer di bawah, atau ketik manual:\n"
        "`/kota [Nama Kota]`\n\n"
        "📋 *Contoh*: `/kota Purwokerto`\n\n"
        "Tersedia 100+ kota di database."
    )
    keyboard = [
        [
            InlineKeyboardButton("🏙️ Danakerta", callback_data="kota_danakerta"),
            InlineKeyboardButton("🏙️ Banjarnegara", callback_data="kota_banjarnegara")
        ],
        [
            InlineKeyboardButton("🏙️ Semarang", callback_data="kota_semarang"),
            InlineKeyboardButton("🏙️ Yogyakarta", callback_data="kota_yogyakarta")
        ],
        [
            InlineKeyboardButton("🏙️ Jakarta", callback_data="kota_jakarta"),
            InlineKeyboardButton("🏙️ Bandung", callback_data="kota_bandung")
        ],
        [
            InlineKeyboardButton("🏙️ Surabaya", callback_data="kota_surabaya"),
            InlineKeyboardButton("🏙️ Medan", callback_data="kota_medan")
        ],
        [
            InlineKeyboardButton("🏙️ Makassar", callback_data="kota_makassar"),
            InlineKeyboardButton("🏙️ Denpasar", callback_data="kota_denpasar")
        ],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
    ]
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def handle_kota_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk tombol kota populer (callback_data='kota_xxx')."""
    query = update.callback_query
    await query.answer()

    nama_kota = query.data.replace("kota_", "").replace("_", " ")

    kota = cari_kota(nama_kota)
    if not kota:
        await query.edit_message_text(
            f"❌ Kota *{nama_kota}* tidak ditemukan di database.",
            parse_mode='Markdown'
        )
        return

    jadwal = ambil_jadwal_sholat(kota["lat"], kota["lng"])
    text = format_jadwal(jadwal, kota["nama"])

    if "provinsi" in kota:
        text += f"\n🏙️ Provinsi: {kota['provinsi']}\n"
    text += f"📍 Koordinat: `{kota['lat']}, {kota['lng']}`\n"

    simpan_lokasi_user(
        update.effective_user.id,
        kota["lat"], kota["lng"],
        kota=kota["nama"], sumber="kota"
    )

    keyboard = [
        [InlineKeyboardButton("📍 Kirim Lokasi GPS", callback_data="sub_sholat_gps")],
        [InlineKeyboardButton("🔍 Cari Kota Lain", callback_data="sub_sholat_kota")],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
    ]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return

    jadwal = ambil_jadwal_sholat(kota["lat"], kota["lng"])
    text = format_jadwal(jadwal, kota["nama"])

    # Simpan ke profil user
    simpan_lokasi_user(
        update.effective_user.id,
        kota["lat"], kota["lng"],
        kota=kota["nama"], sumber="kota"
    )

    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Utama",
                                      callback_data="back_to_main")]]
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )



                                                                                ← baris kosong
                                                                                ← baris kosong

async def handle_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    lat, lon = loc.latitude, loc.longitude
    user_id = update.effective_user.id

    # 1. Cek pindah area
    
    lama = ambil_lokasi_user(user_id)

    if lama and lama["lat"] and lama["lng"]:
     
        jarak = hitung_jarak(lat, lon, lama["lat"], lama["lng"])
        if jarak < 5:
            # Masih di area yang sama, tidak perlu update
            pass

    # 2. Simpan lokasi baru
    simpan_lokasi_user(user_id, lat, lon, sumber="gps")

    # 3. Hitung jadwal
    jadwal = ambil_jadwal_sholat(lat, lon)
    text = format_jadwal(jadwal, "Lokasi Anda")
    text += f"\n📍 Koordinat: `{lat:.4f}, {lon:.4f}`\n"

    # 4. Masjid terdekat
    masjid = masjid_terdekat(lat, lon, radius_km=15)
    if masjid:
        text += "\n🕌 **Masjid Terdekat:**\n"
        for m in masjid:
            tanda = "⭐" if m["tipe"] == "raudha" else "•"
            text += f"{tanda} {m['nama']} ({m['jarak']} km)\n"
    else:
        text += "\n_ Tidak ada masjid mitra dalam radius 15 km._\n"

    # 5. Tombol
    param_url = urllib.parse.quote("masjid terdekat")
    maps_url = f"https://www.google.com/maps/search/{param_url}/@{lat},{lon},15z"
    keyboard = [
        [InlineKeyboardButton("🗺️ Buka di Google Maps", url=maps_url)],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
    ]
    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )

# ==================== 6. HANDLER MORNING ====================

async def handle_morning_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Morning", callback_data="menu_morning")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if data == "run_dzikir_pagi":
        text = (
            "☀️ **DZIKIR PAGI SINGKAT (RAUDHA)**\n\n"
            "1. **Ayat Kursi (1x)** — perlindungan hingga sore.\n\n"
            "2. **Al-Ikhlas, Al-Falaq, An-Naas (3x)**\n\n"
            "3. **Subhanallah, Alhamdulillah, Allahu Akbar (33x)**\n\n"
            "4. **Istighfar (100x)**: `Astaghfirullah wa atuubu ilaih`"
        )
    else:
        text = (
            "📜 **INSPIRASI PAGI INI (RAUDHA)**\n\n"
            "✨ **Pilar Hari Ini: Setiap pagi jadikan sebagai kanvas baru.**\n\n"
            "Niatkan aktivitas hari ini untuk ibadah dan Jariah.\n\n"
            "💬 _'Dunia ini laksana bayangan.Jika kamu berusaha menangkapnya, dia akan lari. Tetapi jika kamu membelakanginya, dia tak punya pilihan selain mengikutimu.'_ — Ibnu Al-Qayyim."
        )
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 7. HANDLER DOA (PAGINASI OTOMATIS) ====================

# --- HANDLER DOA: HARIAN, PERLINDUNGAN, ARAB SAJA, PAGINASI ---

async def handle_doa_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # === A. DOA HARIAN (STATIS) ===
    if data == "run_doa_harian":
        text = (
            "🏡 **DOA HARIAN PILIHAN (RAUDHA)**\n\n"
            "1. **Doa Pembuka Kebaikan**\n"
            "`اللَّهُمَّ إِنِّي أَسْأَلُكَ عِلْمًا نَافِعًا وَرِزْقًا طَيِّبًا وَعَمَلًا مُتَقَبَّلًا`\n\n"
            "2. **Doa Sapu Jagat**\n"
            "`رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً وَقِنَا عَذَابَ النَّارِ`"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # === B. DOA PERLINDUNGAN (STATIS) ===
    elif data == "run_doa_lindung":
        text = (
            "🛡️ **DOA PERLINDUNGAN & KESELAMATAN**\n\n"
            "1. **Doa Perlindungan Mutlak (3x)**\n"
            "`بِسْمِ اللَّهِ الَّذِي لَا يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الْأَرْضِ وَلَا فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ`\n\n"
            "2. **Doa Berlindung dari Keburukan Makhluk**\n"
            "`أَعُوذُ بِكَلِمَاتِ اللَّهِ التَّامَّاتِ مِنْ شَرِّ مَا خَلَقَ`"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # === C. MODE ARAB SAJA ===
    elif "_arabonly_" in data:
        nama_doa, _, hal_str = data.rpartition("_arabonly_")
        halaman_ke = int(hal_str)
        await tampilkan_arab_saja(query, nama_doa, halaman_ke)
        return

    # === D. PAGINASI OTOMATIS DARI FILE .TXT ===
    elif data.startswith("run_doa_") or "_hal" in data:
        if data.startswith("run_doa_"):
            nama_doa = data.replace("run_doa_", "")
            halaman_ke = 1
        else:
            nama_doa, _, hal_str = data.rpartition("_hal")
            halaman_ke = int(hal_str)

        tombol_kembali = InlineKeyboardButton(
            "⬅️ Kembali ke Menu Doa Pilihan", callback_data="sub_doa_pilihan"
        )

        halaman_list = baca_halaman_doa(nama_doa)

        if not halaman_list:
            await query.edit_message_text(
                f"⚠️ File `{nama_doa}.txt` belum tersedia di folder `{FOLDER_DOA}/`.",
                parse_mode='Markdown'
            )
            return

        total = len(halaman_list)
        if halaman_ke < 1 or halaman_ke > total:
            halaman_ke = 1

        doa = halaman_list[halaman_ke - 1]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]

        text = (
            f"📜 **DOA {nama_doa.upper()} (Halaman {halaman_ke} / {total})**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\""
        )
        reply_markup = bikin_tombol_paginasi(nama_doa, halaman_ke, total, tombol_kembali)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 8. HANDLER SUBSCRIBE ====================

async def handle_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Subscribe", callback_data="menu_subscribe")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if data == "run_sub_dzikir":
        text = "✅ **Berhasil!** Anda berlangganan Dzikir Pagi & Sore."
    elif data == "run_sub_weekly":
        text = "✅ **Berhasil!** Anda berlangganan Inspirasi & Doa Mingguan."
    else:
        text = "❌ Anda telah berhenti dari semua langganan."

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 9. RUNNER ====================

def main():
    from modul_database import init_db
    from modul_seed_masjid import load_seed_masjid
    init_db()
    load_seed_masjid()

    app = Application.builder().token(TOKEN).build()

    # 1. Command

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kota", handle_command_kota))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location_received))

    # 2. Callback
    
    app.add_handler(CallbackQueryHandler(start, pattern="^back_to_main$"))

    # 3. Submenu (HARUS DI ATAS handler kota_)

    submenu_patterns = (
        "^(menu_morning|menu_doa|menu_tanam|submenu_arsitektur|"
        "menu_sholat|menu_subscribe|menu_help|menu_about|"
        "sub_sholat_gps|sub_sholat_kota|sub_doa_pilihan)$"
    )
    app.add_handler(CallbackQueryHandler(handle_submenus, pattern=submenu_patterns))

    # 4. Kota populer (BARU)
    
    app.add_handler(CallbackQueryHandler(handle_kota_callback, pattern="^kota_[a-z_]+$"))

    morning_patterns = "^(run_dzikir_pagi|run_inspirasi)$"
    app.add_handler(CallbackQueryHandler(handle_morning_actions, pattern=morning_patterns))

    subscribe_patterns = "^(run_sub_dzikir|run_sub_weekly|run_unsubscribe)$"
    app.add_handler(CallbackQueryHandler(handle_subscribe, pattern=subscribe_patterns))

    doa_patterns = (
    "^(run_doa_harian|run_doa_lindung|run_doa_kumail|run_doa_ziyarah|"
    "run_doa_nudbah|run_doa_shalawat|"
    "kumail_hal\\d+|nudbah_hal\\d+|ziyarah_hal\\d+|shalawat_hal\\d+|"
    "kumail_arabonly_\\d+|nudbah_arabonly_\\d+|ziyarah_arabonly_\\d+|shalawat_arabonly_\\d+)$"
)
    app.add_handler(CallbackQueryHandler(handle_doa_actions, pattern=doa_patterns))

    print("Bot Raudha siap digunakan...")
    app.run_polling()


if __name__ == '__main__':
    main()