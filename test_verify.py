# test_verify.py
from init_data_py import validate_by_hash
import os
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# PASTE initData dari HP di sini
init_data_from_hp = "query_id=AAF0TikcAAAAAHROKRx2eflM&user=%7B%22id%22%3A472469108%2C%22first_name%22%3A%22Maz%22%2C%22last_name%22%3A%22%22%2C%22username%22%3A%22Raudha_Realty%22%2C%22language_code%22%3A%22id%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FM7iFNd6mrmy5inAl3FkKYkHWd5wYnxtZjvRUwENeqU0.svg%22%7D&auth_date=1793288406&signature=eMHeLZN2QS6-B5ScS6RShor58wU4totzAP2T975W7l3wVxT6HKJZLwd-4g9pKAsR-qCRlFC7CQggZKYOlK0BQ&hash=4b93eb8ea85f5146c41209fb11df5913e76ce9688f19bb08f048e750b618adc2"
try:
    # Library ini otomatis menangani escaping dan validasi
    validated_data = validate_by_hash(init_data_from_hp, TELEGRAM_BOT_TOKEN)
    print("✅ VERIFIKASI BERHASIL!")
    print("User ID:", validated_data.user.id)
    print("Nama:", validated_data.user.first_name)
except Exception as e:
    print("❌ VERIFIKASI GAGAL!")
    print("Error:", e)