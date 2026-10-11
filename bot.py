import logging
import json
import os
from datetime import date, time
from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import konten

# Konfigurasi logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


import os

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    pesan = (
        f"🌸 Assalamu'alaikum, {user_name} 🌸\n\n"
        "Selamat datang di RAUDHA — Taman Surgawi 🌿\n\n"
        "\"Morning has broken like the first morning...\"\n"
        "— Cat Stevens\n\n"
        "Setiap hari adalah kesempatan baru untuk menanam taman surgawi kita.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📖 /help      → Bantuan\n"
        "🌅 /morning   → Pesan pagi\n"
        "📿 /ayat      → Ayat hari ini\n"
        "🕌 /doa       → Doa pilihan\n"
        "🌷 /renungan  → Renungan singkat\n"
        "🌱 /tanam     → Amalan hari ini\n"
        "🎵 /quote     → Quote inspiratif\n"
        "🔔 /subscribe → Pesan harian otomatis\n"
        "⚙️ /about     → Tentang bot\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "A Better Place, A Better World 🌍"
    )
    await update.message.reply_text(pesan)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pesan = (
        "📖 BANTUAN — RAUDHA 🌸\n\n"
        "🌅 /start       → Menu utama\n"
        "🌅 /morning     → Pesan pagi\n"
        "📿 /ayat        → Ayat harian\n"
        "🕌 /doa         → Doa pilihan\n"
        "🌷 /renungan    → Renungan singkat\n"
        "🌱 /tanam       → Amalan hari ini\n"
        "🎵 /quote       → Quote inspiratif\n"
        "🏛️ /arsitektur  → Arsitektur Islam  ← TAMBAHKAN\n"
        "🔔 /subscribe   → Berlangganan pesan harian\n"
        "🔕 /unsubscribe → Berhenti berlangganan\n"
        "⚙️ /about       → Tentang bot"
    )
    await update.message.reply_text(pesan)

async def morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(pesan)

async def ayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    a = pilih_harian(konten.AYAT_HARIAN)
    pesan = f"📿 AYAT HARI INI 📿\n\n\"{a['teks']}\"\n\n— {a['sumber']}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi"
    await update.message.reply_text(pesan)

async def doa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = pilih_harian(konten.DOA_HARIAN)
    pesan = f"🕌 DOA HARI INI 🕌\n\n\"{d['teks']}\"\n\nArtinya:\n\"{d['arti']}\"\n\n— {d['sumber']}\n\n━━━━━━━━━━━━━━━━━━\n🌿 Raudha — Taman Surgawi"
    await update.message.reply_text(pesan)

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
    pesan = "🌸 RAUDHA — Taman Surgawi 🌸\n\nRecreate All The New Day\n(inspired by Cat Stevens — \"Morning Has Broken\")\n\nA Better Place, A Better World\n\n━━━━━━━━━━━━━━━━━━\nRaudha adalah bot yang menemani hari-harimu\ndengan nuansa taman surgawi.\n━━━━━━━━━━━━━━━━━━\n\n\"Morning has broken like the first morning...\""
    await update.message.reply_text(pesan)

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

def main():
    application = ApplicationBuilder().token(TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("morning", morning))
    application.add_handler(CommandHandler("ayat", ayat))
    application.add_handler(CommandHandler("doa", doa))
    application.add_handler(CommandHandler("renungan", renungan))
    application.add_handler(CommandHandler("tanam", tanam))
    application.add_handler(CommandHandler("quote", quote))
    application.add_handler(CommandHandler("about", about))
    application.add_handler(CommandHandler("arsitektur", arsitektur))  # ← TAMBAHKAN
    
    # Subscribe handlers
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("cek_subscribe", cek_subscribe))

    # JobQueue: Kirim pesan pagi setiap hari jam 05:00
    job_queue = application.job_queue
    job_queue.run_daily(kirim_pagi, time=time(hour=5, minute=0))	
    logging.info("JobQueue: Pesan pagi dijadwalkan setiap jam 05:00.")

    print("🌸 Bot Raudha sedang berjalan...")
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