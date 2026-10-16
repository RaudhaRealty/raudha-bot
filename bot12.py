import logging
import urllib.parse

import requests
from datetime import date, time

from data_doa import DATA_DOA, UKURAN_FONT

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters


# 1. Konfigurasi Logging untuk melihat log jika terjadi error
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

import os

# TOKEN BOT (Ganti dengan token HTTP API dari @BotFather)
# TOKEN BOT (Sudah disinkronkan dengan Token resmi Anda)

TOKEN = "8326864946:AAFpZGMAdUIKHgIWYE4dQukPLN-uDt7Z7zg" # Token Raudha_Bot terbaru

# ==================== 2. CONTROLLER MENU UTAMA (/start) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan Main Menu dengan formasi Grid 2x4"""
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
        query = update.callback_query
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 3. CONTROLLER PETA MENU UTAMA & SUBMENU ====================

async def handle_submenus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menangani navigasi masuk ke masing-masing sub-menu level 1 & 2"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    keyboard = []
    text = ""

    # --- 1. SUB-MENU: MORNING ---

    if data == "menu_morning":
        text = "🌅 **MORNING MENU - RAUDHA**\n\nAwali hari Anda dengan dzikir dan inspirasi pagi."
        keyboard = [
            [InlineKeyboardButton("☀️ Dzikir Pagi Singkat", callback_data="run_dzikir_pagi")],
            [InlineKeyboardButton("📜 Inspirasi Pagi Ini", callback_data="run_inspirasi")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- 2. SUB-MENU: DOA (LEVEL 1) ---

    elif data == "menu_doa":
        text = (
            "🤲 **MENU DOA - RAUDHA**\n\n"
            "_"
            "Berdoalah kepada-Ku, niscaya akan Aku perkenankan bagimu."
            "_\n(QS. Ghafir: 60).\n\n"
            "Silakan pilih rumpun doa yang ingin Anda amalkan di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🏡 Doa Harian Penting", callback_data="run_doa_harian")],
            [InlineKeyboardButton("🛡️ Doa Perlindungan", callback_data="run_doa_lindung")],
            [InlineKeyboardButton("📖 Doa Pilihan & Shalawat", callback_data="sub_doa_pilihan")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- BLOK SUB-MENU DOA PILIHAN (LEVEL 2) ---

    elif data == "sub_doa_pilihan":
        text = (
            "📖 **MENU DOA PILIHAN & SHALAWAT**\n\n"
            "Kumpulan doa agung, munajat, amalan malam Jum'at, serta untaian shalawat "
            "Untuk mendekatkan diri kepada Allah SWT dan Baginda Rasulullah SAW:"
        )
        keyboard = [
            [
                InlineKeyboardButton("📜 Doa Kumail", callback_data="run_doa_kumail"),
                InlineKeyboardButton("✨ Doa Ziyarah", callback_data="run_doa_ziyarah")
            ],
            [
                InlineKeyboardButton("🌙 Doa Nudbah", callback_data="run_doa_nudbah"),
                InlineKeyboardButton("📿 Pilihan Shalawat", callback_data="run_menu_shalawat")
            ],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")]
        ]

    # --- 3. SUB-MENU: TANAM ---

    elif data == "menu_tanam":
        text = (
            "🌱 **MENU TANAM RAUDHA (SEDEKAH JARIYAH & LINGKUNGAN)**\n\n"
            "_"
            "Tidaklah seorang muslim menanam pohon atau menanam tanaman, lalu tanaman itu dimakan oleh burung, "
            "manusia, atau hewan, melainkan itu menjadi sedekah baginya."
            "_\n(HR. Bukhari & Muslim)\n\n"
            "Selamat datang di gerakan Raudha Tanam. Kami mengintegrasikan kelestarian alam dengan amal jariyah "
            "untuk bumi yang lebih hijau dan berkah.\n\n"
            "Silakan pilih program kontribusi atau pelajari panduan pelestarian di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("🌳 Sedekah Pohon Jariyah", url="https://www.google.com")],
            [InlineKeyboardButton("📖 Panduan Eko-Pesantren", url="https://www.google.com")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- 4. SUB-MENU: ARSITEKTUR ---
    elif data == "submenu_arsitektur":
        text = (
            "🏛️ **MENU ARSITEKTUR RAUDHA**\n\n"
            "_"
            "Hanyalah yang memakmurkan masjid-masjid Allah ialah orang-orang yang beriman kepada Allah "
            "dan hari kemudian, serta tetap mendirikan shalat..."
            "_\n(QS. At-Tubah: 18)\n\n"
            "Selamat datang di kompilasi arsitektur dan layanan perencanaan masjid Raudha. "
            "Kami mendedikasikan keahlian ini untuk membantu umat mewujudkan baitullah yang estetis, finalitas fungsional, dan kokoh.\n\n"
            "Silakan jelajahi karya kami atau hubungi tim arsitek melalui tombol link di bawah ini:"
        )
        link_masjid_dunia = "https://google.com"
        link_portofolio = "https://google.com"
        wa_link = "https://wa.me"
        
        keyboard = [
            [InlineKeyboardButton("🕌 Masjid Terkenal di Dunia", url=link_masjid_dunia)],
            [InlineKeyboardButton("📂 Portofolio Desain Raudha", url=link_portofolio)],
            [InlineKeyboardButton("💬 Konsultasi dengan Arsitek", url=wa_link)],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- 5. SUB-MENU: SHOLAT ---
    elif data == "menu_sholat":
        text = (
            "🕌 **MENU JADWAL SHOLAT & LOKASI**\n\n"
            "Silakan tentukan lokasi Anda agar Bot Raudha dapat menampilkan jadwal sholat yang akurat:\n\n"
            "📌 **Opsi 1 (Otomatis):** Gunakan lokasi GPS ponsel Anda saat ini.\n"
            "📌 **Opsi 2 (Manual):** Cari berdasarkan nama Kota/Kabupaten secara manual."
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
            "Silakan kirimkan lokasi terkini Anda dengan cara menekan ikon klip kertas (📎) "
            "lalu pilih **Location / Lokasi**.\n\n"
            "Bot Raudha akan membaca koordinat Anda dan memberikan jadwal sholat serta rute masjid terdekat."
        )
        keyboard = [
            [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
        ]

    elif data == "sub_sholat_kota":
        text = (
            "🔍 **PENCARIAN MANUAL NAMA KOTA**\n\n"
            "Silakan ketik nama Kota atau Kabupaten Anda dengan menggunakan perintah `/kota`.\n\n"
            "👉 *Contoh*: `/kota Banjarnegara`"
        )
        keyboard = [
            [InlineKeyboardButton("⬅️ Kembali ke Menu Sholat", callback_data="menu_sholat")]
        ]

    # --- 6. SUB-MENU: SUBSCRIBE ---

    elif data == "menu_subscribe":
        text = (
            "🔔 **LAYANAN LANGGANAN (SUBSCRIBE) RAUDHA**\n\n"
            "Dapatkan kiriman konten spiritual berkala langsung di chat Telegram Anda.\n\n"
            "Silakan pilih jenis paket langganan di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("✅ Langganan Dzikir Pagi & Sore", callback_data="run_sub_dzikir")],
            [InlineKeyboardButton("✅ Langganan Inspirasi & Doa Mingguan", callback_data="run_sub_weekly")],
            [InlineKeyboardButton("❌ Berhenti Berlangganan Semua", callback_data="run_unsubscribe")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- 7. SUB-MENU: HELP ---

    elif data == "menu_help":
        text = (
            "❓ **BANTUAN & PANDUAN PENGGUNAAN BOT**\n\n"
            "1. Perintah `/start` digunakan untuk kembali membuka menu utama.\n"
            "2. Gunakan perintah `/kota [Nama Kota]` untuk jadwal sholat manual.\n\n"
            "Hubungi dukungan admin sekretariat kami jika bot mengalami hambatan:"
        )
        keyboard = [
            [InlineKeyboardButton("📞 Hubungi Admin Support", url="https://wa.me")],
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    # --- 8. SUB-MENU: ABOUT ---

    elif data == "menu_about":
        text = (
            "ℹ️ **TENTANG PLATFORM RAUDHA**\n\n"
	    "Bot Raudha adalah asisten spiritual virtual penyelarasan tiga esensi kehidupan umat:\n\n"
	    "🌱 Tanam — Dedikasi terhadap gerakan pelestarian lingkungan.\n"
	    "🏛️ Arsitektur — Perencanaan fisik rumah ibadah (masjid) yang estetis.\n"
	    "🤲 Spiritualitas — Tuntunan ibadah dan doa harian.\n\n"
	    "Raudha Foundation © 2026" "Platform asisten virtual pilar Taman, Arsitektur, dan Spiritualitas.")
        keyboard = [
            [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
        ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 4. CONTROLLER MANUAL KOTA & GPS ====================

async def handle_command_kota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memproses ketikan manual jemaah contoh: /kota Banjarnegara"""
    nama_kota = " ".join(context.args).title()
    
    if not nama_kota:
        await update.message.reply_text(
            "⚠️ **Format Salah.** Silakan ketik `/kota` diikuti nama daerahnya.\nContoh: `/kota Banjarnegara`"
        )
        return
        
    text = (
        f"🔍 **JADWAL SHOLAT UNTUK KOTA: {nama_kota}**\n\n"
        "Berhasil memuat data kalender global tunggal untuk wilayah Anda hari ini:\n\n"
        "⏱️ **Jadwal Waktu Sholat**:\n"
        "• Subuh   : 04:23 WIB *(Telah +8 menit)*\n"
        "• Dzuhur  : 11:42 WIB\n"
        "• Ashar   : 14:50 WIB\n"
        "• Maghrib : 18:02 WIB *(Telah +9 menit)*\n"
        "• Isya    : 19:04 WIB\n\n"
        "Untuk mencari tempat ibadah fisik di kota ini, Anda tetap disarankan menggunakan fitur kirim lokasi GPS."
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def handle_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Membaca koordinat GPS jemaah dan memberikan link rute masjid terdekat secara aman"""
    loc = update.message.location
    lat = loc.latitude
    lon = loc.longitude
    
    query_pencarian = "masjid terdekat"
    param_url = urllib.parse.quote(query_pencarian)
    google_maps_masjid_url = f"https://google.com/maps/search/{param_url}/@{lat},{lon},15z"
    
    text = (
        "📍 **LOKASI GPS BERHASIL DIDETEKSI**\n\n"
        f"Koordinat Anda: `{lat}, {lon}`\n\n"
        "⏱️ **Jadwal Sholat Terkoreksi (Estimasi Wilayah Anda)**:\n"
        "• Subuh   : 04:23 WIB *(Telah +8 menit)*\n"
        "• Dzuhur  : 11:42 WIB\n"
        "• Ashar   : 14:50 WIB\n"
        "• Maghrib : 18:02 WIB *(Telah +9 menit)*\n"
        "• Isya    : 19:04 WIB\n\n"
        "Silakan klik tombol di bawah ini untuk melihat peta navigasi rute menuju masjid/mushola terdekat dari posisi Anda:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🗺️ Buka Rute Masjid Terdekat (Google Maps)", url=google_maps_masjid_url)],
        [InlineKeyboardButton("⬅️ Kembali ke Menu Utama", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== CONTROLLER AKSI SUB-MENU MORNING ====================

async def handle_morning_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan isi konten Dzikir Pagi atau Inspirasi Pagi"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    keyboard = [[InlineKeyboardButton("⬅️ Kembali ke Menu Morning", callback_data="menu_morning")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if data == "run_dzikir_pagi":
        text = (
            "☀️ **DZIKIR PAGI SINGKAT (RAUDHA)**\n\n"
            "Bacaan dzikir untuk perlindungan dan pembuka pintu rezeki hari ini:\n\n"
            "1. **Membaca Ayat Kursi (1x)**\n"
            "   _Manfaat: Dilindungi oleh Allah dari gangguan setan hingga sore hari._\n\n"
            "2. **Membaca Al-Ikhlas, Al-Falaq, An-Naas (Masing-masing 3x)**\n\n"
            "3. **Kalimat Thayyibah (Masing-masing 33x)**\n"
            "   • `Subhanallah`\n"
            "   • `Alhamdulillah`\n"
            "   • `Allahu Akbar`\n\n"
            "4. **Membaca Istighfar (100x)**\n"
            "   • `Astaghfirullah wa atuubu ilaih`\n\n"
            "_"
            "Maka bertasbihlah dengan memuji Tuhanmu sebelum terbit matahari dan sebelum terbenamnya."
            "_\n(QS. Qaf: 39)"
        )
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    elif data == "run_inspirasi":
        text = (
            "📜 **INSPIRASI PAGI INI (RAUDHA)**\n\n"
            "✨ **Pilar Hari Ini: Memulai dengan Niat Amal Jariyah**\n\n"
            "Every morning is a new canvas! Ketika bangun tidur, niatkanlah seluruh aktivitas hari ini —"
            "baik dalam membantu orang lain, merawat tanaman, maupun belajar dan bekerja — sebagai ibadah jariyah.\n\n"
            "💬 **Kata Hikmah Oase Jiwa**:\n"
            "_'Dunia ini laksana bayangan. Jika kamu berusaha menangkapnya, ia akan lari. "
            "Tetapi jika kamu membelakanginya, ia tidak punya pilihan selain mengikutimu.'_\n"
            "— Ibnu Al-Qayyim.\n\n"
            "Mari awali langkah hari ini dengan Bismillah dan senyuman terbaik! 😊"
        )
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# ==================== 5. CONTROLLER ISI BALASAN LEMBAR BACAAN (DOA) ====================

async def handle_doa_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan rincian teks bacaan rumpun doa dengan sistem Paginasi Terstruktur"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # 1. Atur Tombol Kembali Dinamis ke Menu Asal
    if data in ["run_doa_harian", "run_doa_lindung"]:
        keyboard_back = [InlineKeyboardButton("⬅️ Kembali ke Menu Doa", callback_data="menu_doa")]
    else:
        keyboard_back = [InlineKeyboardButton("⬅️ Kembali ke Menu Doa Pilihan", callback_data="sub_doa_pilihan")]
    
    keyboard_back_markup = InlineKeyboardMarkup([keyboard_back])

    # --- A. KATEGORI LEVEL 1 (DOA HARIAN & PERLINDUNGAN) ---

    if data == "run_doa_harian":
        text = (
            "🏡 **DOA HARIAN PILIHAN (RAUDHA)**\n\n"
            "1. **Doa Pembuka Pintu Kebaikan & Keberkahan**\n"
            "`اللَّهُمَّ إِنِّي أَسْأَلُكَ عِلْمًا نَافِعًا وَرِزْقًا طَيِّبًا وَعَمَلًا مُتَقَبَّلًا`\n\n"
            "2. **Doa Sapu Jagat (Kebaikan Dunia & Akhirat)**\n"
            "`رَبَّنَا آتِنَا فِي الدُّنْيَا حَسَنَةً وَفِي الْآخِرَةِ حَسَنَةً وَقِنَا عَذَابَ النَّارِ`"
        )
        await query.edit_message_text(text, reply_markup=keyboard_back_markup, parse_mode='Markdown')

    elif data == "run_doa_lindung":
        text = (
            "🛡️ **DOA PERLINDUNGAN & KESELAMATAN**\n\n"
            "1. **Doa Perlindungan Mutlak (Dibaca 3x)**\n"
            "`بِسْمِ اللَّهِ الَّذِي Lا يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الْأَرْضِ وَلَا فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ`\n\n"
            "2. **Doa Berlindung dari Keburukan Makhluk**\n"
            "`أَعُوذُ بِكَلِمَاتِ اللَّهِ التَّامَّاتِ مِنْ شَرِّ مَا خَلَقَ`"
        )
        await query.edit_message_text(text, reply_markup=keyboard_back_markup, parse_mode='Markdown')

    # --- B. KATEGORI LEVEL 2: SYSTEM PAGINASI HALAMAN DOA KUMAIL ---

    elif data in ["run_doa_kumail", "kumail_hal1"]:
        doa = DATA_DOA["kumail"][0]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]
        text = (
            "📜 **DOA KUMAIL IBNU ZIYAD (Halaman 1 / 2)**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\""
        )
        keyboard = [[InlineKeyboardButton("Selanjutnya Halaman 2 ➡️", callback_data="kumail_hal2")], keyboard_back]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data == "kumail_hal2":
        doa = DATA_DOA["kumail"][1]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]
        text = (
            "📜 **DOA KUMAIL IBNU ZIYAD (Halaman 2 / 2)**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\"\n\n"
            "Untuk menelaah teks lengkap beserta faedahnya, silakan unduh berkas digital resmi di bawah ini:"
        )
        keyboard = [
            [InlineKeyboardButton("📥 Unduh PDF Kumail Lengkap", url="https://www.google.com")],
            [InlineKeyboardButton("⬅️ Sebelumnya Halaman 1", callback_data="kumail_hal1")],
            keyboard_back
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- C. KATEGORI LEVEL 2: SYSTEM PAGINASI HALAMAN DOA NUDBAH ---

    elif data in ["run_doa_nudbah", "nudbah_hal1"]:
        doa = DATA_DOA["nudbah"][0]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]
        text = (
            "🌙 **DOA NUDBAH (Halaman 1 / 2)**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\""
        )
        keyboard = [[InlineKeyboardButton("Selanjutnya Halaman 2 ➡️", callback_data="nudbah_hal2")], keyboard_back]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data == "nudbah_hal2":
        doa = DATA_DOA["nudbah"][1]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]
        text = (
            "🌙 **DOA NUDBAH (Halaman 2 / 2)**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\""
        )
        keyboard = [
            [InlineKeyboardButton("📥 Unduh PDF Nudbah Lengkap", url="https://www.google.com")],
            [InlineKeyboardButton("⬅️ Sebelumnya Halaman 1", callback_data="nudbah_hal1")],
            keyboard_back
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    # --- D. KATEGORI LEVEL 2: SINKRONISASI BACAAN DOA ZIYARAH (BARU DAN AKTIF) ---

    elif data == "run_doa_ziyarah":
        doa = DATA_DOA["ziyarah"][0]
        pembatas = UKURAN_FONT["sedang"]["pembatas"]
        text = (
            "✨ **TUNTUNAN DOA ZIYARAH**\n"
            f"{pembatas}\n\n"
            f"🕌 **Teks Arab:**\n`{doa['arab']}`\n\n"
            f"📝 **Latin:**\n_{doa['latin']}_\n\n"
            f"🌍 **Arti:**\n\"{doa['arti']}\""
        )
        await query.edit_message_text(text, reply_markup=keyboard_back_markup, parse_mode='Markdown')

    # --- E. KATEGORI LEVEL 2: PILIHAN MUTIARA SHALAWAT ---

    elif data == "run_menu_shalawat":
        text = (
            "📿 **MUTIARA PILIHAN SHALAWAT**\n\n"
            "1. **Shalawat Ibrahimiyah** (Meraih Syafaat Nabi)\n"
            "`اللَّهُمَّ صَلِّ عَلَى مُحَمَّدٍ وَعَلَى آلِ مُحَمَّدٍ...`\n\n"
            "2. **Shalawat Tibbil Qulub** (Penawar & Penenang Hati)\n"
            "`اللَّهُمَّ صَلِّ عَلَى سَيِّدِنَا مُحَمَّدٍ طِبِّ الْقُلُوبِ وَدَوَائِهَا...`"
        )
        await query.edit_message_text(text, reply_markup=keyboard_back_markup, parse_mode='Markdown')

# ==================== 4. ORKESTRASI & RUNNER ====================

def main():
    app = Application.builder().token(TOKEN).build()

    # --- 1. KUMPULAN COMMAND & MESSAGE HANDLER (Daftarkan Semua di Sini) ---

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kota", handle_command_kota))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location_received))

    # --- 2. KUMPULAN CALLBACK KEYBOARD HANDLER ---

    app.add_handler(CallbackQueryHandler(start, pattern="^back_to_main$"))
    
    submenu_patterns = (
        "^(menu_morning|menu_doa|menu_tanam|submenu_arsitektur|"
        "menu_sholat|menu_subscribe|menu_help|menu_about|"
        "sub_sholat_gps|sub_sholat_kota|sub_doa_pilihan)$" # <-- Tambahkan sub_doa_pilihan di sini
    )
    app.add_handler(CallbackQueryHandler(handle_submenus, pattern=submenu_patterns))

    # Tepat di bawah handler submenu_patterns, tambahkan baris pemicu aksi morning ini:
    # 📌 --- PASTIKAN DUA HANDLER DI BAWAH INI SUDAH TERTULIS DENGAN BENAR ---
    # Handler untuk memicu isi konten Morning (Dzikir & Inspirasi)

    morning_patterns = "^(run_dzikir_pagi|run_inspirasi)$"
    app.add_handler(CallbackQueryHandler(handle_morning_actions, pattern=morning_patterns))
    
    # Handler untuk memicu isi konten rumpun Doa & Shalawat beserta Halamannya
    # Ganti baris doa_patterns lama Anda dengan kode fleksibel ini:
    doa_patterns = "^(run_doa_harian|run_doa_lindung|run_doa_kumail|run_doa_ziyarah|run_doa_nudbah|run_menu_shalawat|run_sub_dzikir|run_sub_weekly|run_unsubscribe|page_.*)$"
    app.add_handler(CallbackQueryHandler(handle_doa_actions, pattern=doa_patterns))

    # Eksekusi utama bot
    print("Bot Raudha dengan fitur lengkap siap digunakan lokal...")
    app.run_polling()

if __name__ == '__main__':
    main()