import re
from telegram import Update
from telegram.ext import ContextTypes
from modul_keuangan.database import catat_transaksi, ambil_saldo_aktif

def rp(n):
    """Format angka jadi Rupiah Indonesia."""
    return f"Rp {int(round(float(n))):,}".replace(",", ".")

def bersihkan_angka(teks_angka):
    angka_murni = re.sub(r'[^\d]', '', teks_angka)
    return float(angka_murni) if angka_murni else 0.0

async def handle_masuk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ /masuk <jumlah> [kategori] [keterangan]\n"
        )
        return

async def handle_keluar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "⚠️ /keluar <jumlah> [kategori] [keterangan]\n"
        )
        return