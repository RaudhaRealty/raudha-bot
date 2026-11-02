import json
import os
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data_kota.json")
ADJUST_SUBUH = 8    # +8 menit sesuai Kalender Global Hijriah Muhammadiyah
ADJUST_MAGHRIB = 10 # +10 menit penyesuaian Masjid Raudha

def tambah_menit(jam_str, menit_tambah):
    """Tambahkan menit ke string 'HH:MM'"""
    try:
        h, m = map(int, jam_str.split(":"))
    except ValueError:
        return jam_str
    total = h * 60 + m + menit_tambah
    total %= (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"

def get_jadwal(lat, lng, method=11):
    """Ambil jadwal sholat dari API Aladhan."""
    url = "https://api.aladhan.com/v1/timings"
    params = {
        "latitude": lat,
        "longitude": lng,
        "method": method,
        "timezonestring": ""  # biarkan API deteksi otomatis per koordinat
    }
    resp = requests.get(url, params=params, timeout=15).json()
    if resp.get("code") != 200:
        raise Exception("API error: " + str(resp))
    return resp["data"]["timings"]

def format_jadwal(nama, provinsi, catatan, lat, lng, timings):
    subuh   = timings.get("Fajr", "--:--")
    syuruq  = timings.get("Sunrise", "--:--")
    dzuhur  = timings.get("Dhuhr", "--:--")
    ashar   = timings.get("Asr", "--:--")
    maghrib = timings.get("Maghrib", "--:--")
    isya    = timings.get("Isha", "--:--")

    lines = [
        f"🕌 JADWAL SHOLAT — {nama.upper()}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"• Subuh   : {subuh}",
        f"• Syuruq  : {syuruq}",
        f"• Dzuhur  : {dzuhur}",
        f"• Ashar   : {ashar}",
        f"• Maghrib : {maghrib}",
        f"• Isya    : {isya}",
        "",
        f"🏙️ Provinsi: {provinsi}",
    ]
    if catatan:
        lines.append(f"ℹ️ {catatan}")
    lines.append(f"📍 Koordinat: {lat}, {lng}")
    lines.append("📡 Sumber: Aladhan API")
    
    return "\n".join(lines)

def cari_kota(query):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    q = query.lower().strip()
    for item in data:
        if item["nama"].lower() == q:
            return item
    return None

if __name__ == "__main__":
    import sys
    kota_input = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else input("Nama kota: ")
    kota = cari_kota(kota_input)
    if not kota:
        print("❌ Kota tidak ditemukan:", kota_input)
    else:
        jadwal = get_jadwal(kota["lat"], kota["lng"])
        print(format_jadwal(
            kota["nama"],
            kota.get("provinsi", ""),
            kota.get("catatan", ""),
            kota["lat"],
            kota["lng"],
            jadwal
        ))