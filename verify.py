# test_verify.py
import hmac
import hashlib
from urllib.parse import parse_qsl
import os
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# ======================================================
# PASTE initData YANG ANDA COPY DARI HP DI SINI (di antara tanda kutip)
# ======================================================
init_data_from_hp = "PASTE_DI_SINI_STRING_PANJANG_DARI_HP"
# ======================================================

if not init_data_from_hp or init_data_from_hp == "PASTE_DI_SINI_STRING_PANJANG_DARI_HP":
    print("❌ Anda belum menempelkan initData dari HP.")
    exit()

params = dict(parse_qsl(init_data_from_hp, keep_blank_values=True))
received_hash = params.pop('hash', None)

if not received_hash:
    print("❌ initData tidak memiliki 'hash'.")
    exit()

data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

secret_key = hmac.new(key=b"WebAppData", msg=TELEGRAM_BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
expected_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()

print("Token Prefix:", TELEGRAM_BOT_TOKEN[:20])
print("Received Hash:", received_hash)
print("Expected Hash:", expected_hash)
print("---------------------------------")
if hmac.compare_digest(expected_hash, received_hash):
    print("✅ VERIFIKASI BERHASIL!")
    print("User data:", params.get('user'))
else:
    print("❌ VERIFIKASI GAGAL! Hash tidak cocok.")
    print("Periksa apakah TELEGRAM_BOT_TOKEN di .env sama dengan di BotFather.")
    print("Data check string:", data_check_string)