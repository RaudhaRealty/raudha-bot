import json
import math
import os
from datetime import datetime, timezone, timedelta
import requests

# ---- Konfigurasi offset Masjid Raudha ----
OFFSET_SUBUH = 8      # menit
OFFSET_MAGHRIB = 10   # menit

WIB = timezone(timedelta(hours=7))

# ---- Load data kota (offline) ----
_KOTA_CACHE = None
def load_data_kota():
    global _KOTA_CACHE
    if _KOTA_CACHE is None:
        path = os.path.join("data", "data_kota.json")
        with open(path, "r", encoding="utf-8") as f:
            _KOTA_CACHE = json.load(f)
    return _KOTA_CACHE


def cari_kota(nama):
    """Cari kota by nama (case-insensitive, partial match)."""
    nama = nama.lower().strip()
    data = load_data_kota()
    hasil = [k for k in data if nama in k["nama"].lower()]
    return hasil[0] if hasil else None


def hitung_jarak(lat1, lng1, lat2, lng2):
    """Haversine — output km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def ambil_jadwal_sholat(lat, lng, tanggal=None):
    """
    Ambil dari Aladhan API (method=20 Kemenag),
    lalu terapkan offset Subuh +8 dan Maghrib +10.
    """
    if tanggal is None:
        tanggal = datetime.now(WIB).strftime("%d-%m-%Y")

    url = f"https://api.aladhan.com/v1/timings/{tanggal}"
    params = {
        "latitude": lat,
        "longitude": lng,
        "method": 20,          # Kemenag Indonesia
        "tune": f"8,0,0,10,0,0,0,0,0"  # Fajr+8, Maghrib+10 (urutan Aladhan)
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()["data"]["timings"]
        return {
            "Subuh":   data["Fajr"],
            "Syuruq":  data["Sunrise"],
            "Dzuhur":  data["Dhuhr"],
            "Ashar":   data["Asr"],
            "Maghrib": data["Maghrib"],
            "Isya":    data["Isha"],
        }
    except Exception as e:
        return {"error": str(e)}


def masjid_terdekat(lat, lng, radius_km=15, limit=5):
    """Query SQLite — Haversine manual."""
    import sqlite3
    conn = sqlite3.connect("data/raudha.db")
    c = conn.cursor()
    c.execute("SELECT nama, tipe, lat, lng, alamat FROM masjid")
    rows = c.fetchall()
    conn.close()

    hasil = []
    for nama, tipe, mlat, mlng, alamat in rows:
        jarak = hitung_jarak(lat, lng, mlat, mlng)
        if jarak <= radius_km:
            hasil.append({"nama": nama, "tipe": tipe,
                          "jarak": round(jarak, 2), "alamat": alamat})

    # Prioritas: Raudha dulu, lalu mitra, lalu jarak
    hasil.sort(key=lambda x: (0 if x["tipe"] == "raudha" else 1, x["jarak"]))
    return hasil[:limit]


def format_jadwal(jadwal, nama_lokasi=""):
    """Format teks siap kirim ke Telegram."""
    if "error" in jadwal:
        return f"⚠️ Gagal mengambil jadwal: {jadwal['error']}"

    header = f"🕌 **JADWAL SHOLAT — {nama_lokasi.upper()}**\n" if nama_lokasi else "🕌 **JADWAL SHOLAT**\n"
    header += f"_Standar Kemenag + penyesuaian Masjid Raudha_\n"
    header += f"_(Subuh +8 mnt, Maghrib +10 mnt)_\n"
    header += "━━━━━━━━━━━━━━━━━━━━\n\n"

    baris = ""
    for nama, waktu in jadwal.items():
        baris += f"• **{nama:<8}**: {waktu}\n"

    return header + baris