from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Ganti dengan URL halaman landing Mini App Anda yang sebenarnya (harus HTTPS)
#MINI_APP_URL = "https://domain-anda.com/landing"

MINI_APP_URL = os.environ.get(
    "MINI_APP_URL", "https://brush-agreed-spookily.ngrok-free.dev"
)

# ==================== 1. KONFIGURASI ====================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menu utama: tiga tombol layanan"""
    keyboard = [
        [
            InlineKeyboardButton(
                "Layanan LAZIZ",
                callback_data="menu_laziz"  # Sementara callback, nanti bisa diganti web_app
            )
        ],
        [
            InlineKeyboardButton(
                "Layanan BMT",
                callback_data="menu_bmt"
            )
        ],
        [
            InlineKeyboardButton(
                "Layanan Gerai Dinar",
                web_app=WebAppInfo(url=f"{MINI_APP_URL}/dinar")
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Silakan pilih layanan yang ingin Anda akses:",
        reply_markup=reply_markup
    )

# Handler sementara untuk tombol LAZIZ/BMT (placeholder)
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "menu_laziz":
        await query.edit_message_text("Layanan LAZIZ segera hadir.")
    elif query.data == "menu_bmt":
        await query.edit_message_text("Layanan BMT segera hadir.")
    elif query.data == "menu_dinar":
        await query.edit_message_text("Layanan Gerai Dinar segera hadir.")

def main() -> None:
    application = Application.builder().token("TOKEN_ANDA").build()
    application.add_handler(CommandHandler("start", start))
    # Daftarkan callback handler (perlu mengimpor CallbackQueryHandler)
    from telegram.ext import CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.run_polling(allowed_updates=Update.ALL_TYPES)