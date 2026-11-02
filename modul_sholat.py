# modul_sholat.py — Modul Utama Jadwal Sholat & Navigasi Masjid Raudha
import json
import math
import os
import requests
from datetime import datetime, timezone, timedelta
from timezonefinder import TimezoneFinder
import pytz
from modul_database import hitung_jarak

# =====================================================================
# TAMBAHAN: HITUNG JADWAL DARI KOORDINAT (untuk GPS HP user via API Aladhan)
# =====================================================================
def ambil_jadwal_dari_koordinat(lat, lng, nama_kota="Lokasi GPS"):
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        raise ValueError("Koordinat lat/lng tidak valid")

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise ValueError("Koordinat di luar rentang valid")

    # Panggil API Aladhan via file jadwal_sholat.py
    timings = get_jadwal(lat, lng)

    return {
        'kota': {
            'nama': nama_kota,
            'lat': lat,
            'lng': lng,
            'zona_waktu': "Otomatis (Aladhan API)"
        },
        'subuh': timings['Fajr'],
        'zuhur': timings['Dhuhr'],
        'ashar': timings['Asr'],
        'maghrib': timings['Maghrib'],
        'isya': timings['Isha'],
        'sumber': 'Aladhan API (GPS)',
    }

# --- 1. KONFIGURASI & TIMEZONE ---
OFFSET_SUBUH = 8
OFFSET_MAGHRIB = 10
WIB = timezone(timedelta(hours=7))

_KOTA_CACHE = None


# --- 2. LOGIKA PENGELOLAAN DATA KOTA ---
def load_data_kota():
    global _KOTA_CACHE
    if _KOTA_CACHE is None:
        path = os.path.join("data", "data_kota.json")
        if not os.path.exists(path) and os.path.exists("data_kota.json"):
            path = "data_kota.json"
        with open(path, "r", encoding="utf-8") as f:
            _KOTA_CACHE = json.load(f)
    return _KOTA_CACHE


def cari_kota(nama):
    """Cari kota berdasarkan substring. Return dict atau None."""
    nama = (nama or "").lower().strip()
    try:
        data = load_data_kota()
        for k in data:
            if nama in k["nama"].lower():
                return k
        return None
    except Exception:
        return None


def cari_kota_fuzzy(nama, max_hasil=5):
    """Return LIST kota terbaik (untuk kompatibilitas)."""
    if not nama:
        return []
    nama = nama.lower().strip()
    try:
        data = load_data_kota()
    except Exception:
        return []

    def skor(kota_nama):
        kota_nama = kota_nama.lower()
        if kota_nama.startswith(nama):
            return len(nama) / len(kota_nama) + 1
        if nama in kota_nama:
            return len(nama) / len(kota_nama)
        cocok = 0
        for a, b in zip(nama, kota_nama):
            if a == b:
                cocok += 1
            else:
                break
        return cocok / max(len(nama), len(kota_nama))

    hasil = [(skor(k["nama"]), k) for k in data if skor(k["nama"]) > 0.5]
    hasil.sort(key=lambda x: -x[0])
    return [k for _, k in hasil[:max_hasil]]


def cari_kota_terbaik(nama):
    """
    ⭐ Fungsi baru: selalu return SATU dict kota (atau None).
    Cocok untuk app.py yang butuh dict tunggal.
    """
    kota = cari_kota(nama)
    if kota:
        return kota
    hasil = cari_kota_fuzzy(nama, max_hasil=1)
    return hasil[0] if hasil else None


# --- 3. AMBIL DATA JADWAL SHOLAT (API ALADHAN METHOD 20) ---
def ambil_jadwal_sholat(lat, lng, tanggal=None):
    """
    Versi asli (dipakai bot) — menerima lat/lng.
    Return dict dengan key kapital: Subuh, Syuruq, Dzuhur, Ashar, Maghrib, Isya.
    atau {"error": "..."} jika gagal.
    """
    if tanggal is None:
        tanggal = datetime.now(WIB).strftime("%d-%m-%Y")

    url = f"https://api.aladhan.com/v1/timings/{tanggal}"
    params = {
        "latitude": lat,
        "longitude": lng,
        "method": 20,  # Kemenag RI
        "tune": f"{OFFSET_SUBUH},0,0,{OFFSET_MAGHRIB},0,0,0,0,0",
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


def ambil_jadwal_untuk_display(nama_kota, tanggal=None):
    """
    ⭐ Fungsi baru untuk app.py /display.
    Return dict lowercase + info kota, langsung siap dipakai template.

    Contoh return:
    {
        "kota": {"nama": "Banjarnegara", "lat": -7.36, "lng": 109.68, "provinsi": "..."},
        "subuh": "04:30", "zuhur": "11:55", "ashar": "15:15",
        "maghrib": "17:45", "isya": "19:00",
        "syuruq": "05:45",
        "sumber": "aladhan" | "manual",
    }
    """
    kota = cari_kota_terbaik(nama_kota)
    if not kota:
        kota = {
            "nama": "Banjarnegara",
            "lat": -7.3667,
            "lng": 109.6833,
            "provinsi": "Jawa Tengah",
        }

    if tanggal is None:
        tanggal = datetime.now(WIB).strftime("%d-%m-%Y")

    hasil_api = ambil_jadwal_sholat(kota["lat"], kota["lng"], tanggal)

    if "error" not in hasil_api:
        return {
            "kota": kota,
            "subuh":   hasil_api["Subuh"],
            "syuruq":  hasil_api["Syuruq"],
            "zuhur":   hasil_api["Dzuhur"],
            "ashar":   hasil_api["Ashar"],
            "maghrib": hasil_api["Maghrib"],
            "isya":    hasil_api["Isya"],
            "sumber":  "aladhan",
        }

    # Fallback manual
    manual = hitung_jadwal_manual(kota["lat"], kota["lng"])
    return {
        "kota": kota,
        "subuh":   manual["subuh"],
        "syuruq":  manual.get("syuruq", "-"),
        "zuhur":   manual["zuhur"],
        "ashar":   manual["ashar"],
        "maghrib": manual["maghrib"],
        "isya":    manual["isya"],
        "sumber":  "manual",
    }


def hitung_jadwal_manual(lat, lng, tanggal=None):
    """Fallback hisab sederhana — dipindah dari app.py ke sini."""
    if tanggal is None:
        tanggal = datetime.now(WIB).date()
    hari_ke = tanggal.timetuple().tm_yday
    deklinasi = 0.409 * math.sin((2 * math.pi / 365) * (hari_ke - 81))
    lintang_rad = math.radians(lat)

    if lng < 112.5:
        zona = 105
    elif lng < 127.5:
        zona = 120
    else:
        zona = 135

    selisih_waktu = (zona - lng) / 15
    zuhur_desimal = 12.0 + selisih_waktu + (4 / 60)

    def _format_jam(d):
        d = d % 24
        total = int(round(d * 60))
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"

    def _sudut_ke_jam(sudut):
        cos_h = (math.sin(math.radians(sudut))
                 - math.sin(lintang_rad) * math.sin(deklinasi)) / (
                     math.cos(lintang_rad) * math.cos(deklinasi))
        cos_h = max(-1.0, min(1.0, cos_h))
        return math.degrees(math.acos(cos_h)) / 15

    sudut_ashar = math.degrees(
        math.atan(1 / (1 + math.tan(abs(lintang_rad - deklinasi))))
    )

    return {
        "subuh":   _format_jam(zuhur_desimal - _sudut_ke_jam(-20) + OFFSET_SUBUH/60),
        "syuruq":  _format_jam(zuhur_desimal - _sudut_ke_jam(-0.833)),
        "zuhur":   _format_jam(zuhur_desimal),
        "ashar":   _format_jam(zuhur_desimal + _sudut_ke_jam(90 - sudut_ashar)),
        "maghrib": _format_jam(zuhur_desimal + _sudut_ke_jam(-0.833) + OFFSET_MAGHRIB/60),
        "isya":    _format_jam(zuhur_desimal + _sudut_ke_jam(-18)),
    }


# --- 4. KONVERSI HIJRIAH (SATU SUMBER UNTUK BOT & WEB) ---
_BULAN_HIJRIAH = [
    'Muharram', 'Safar', 'Rabiul Awal', 'Rabiul Akhir',
    'Jumadil Awal', 'Jumadil Akhir', 'Rajab', 'Syaban',
    'Ramadhan', 'Syawal', 'Dzulqadah', 'Dzulhijjah',
]


def ke_hijriah(tanggal=None):
    """Return string Hijriah, mis. '15 Rajab 1446 H'. Return '—' jika gagal."""
    if tanggal is None:
        tanggal = datetime.now(WIB).date()
    try:
        from hijri_converter import Gregorian
        h = Gregorian(tanggal.year, tanggal.month, tanggal.day).to_hijri()
        return f"{h.day} {_BULAN_HIJRIAH[h.month - 1]} {h.year} H"
    except Exception:
        return "—"


# --- 5. LOGIKA GEOLOCATION MASJID TERDEKAT ---
def masjid_terdekat(lat, lng, radius_km=15, limit=10):
    """
    Cari masjid dengan prioritas berlapis:
    Tier 1: Masjid Raudha (tipe_masjid='raudha')
    Tier 2: Masjid Jaringan (tipe_masjid='jaringan')
    Urut berdasarkan tier, lalu jarak.
    """
    import sqlite3

    db_path = os.path.join("data", "raudha.db")
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, nama, tipe_masjid, lat, lng, alamat, kota FROM masjid")
    rows = c.fetchall()
    conn.close()

    hasil = []
    for mid, nama, tipe_masjid, mlat, mlng, alamat, kota in rows:
        if mlat is None or mlng is None:
            continue
        jarak = hitung_jarak(lat, lng, mlat, mlng)
        if jarak <= radius_km:
            tier = 1 if tipe_masjid == 'raudha' else 2
            hasil.append({
                "id": mid,
                "nama": nama,
                "tier": tier,
                "tipe_masjid": tipe_masjid,
                "jarak": round(jarak, 2),
                "alamat": alamat,
                "kota": kota,
                "lat": mlat,
                "lng": mlng,
            })

    # Sort: Raudha dulu, lalu jarak
    hasil.sort(key=lambda x: (x["tier"], x["jarak"]))
    return hasil[:limit]


# --- 6. FORMATTER VISUAL CHAT TELEGRAM ---
def format_jadwal(jadwal, nama_lokasi=""):
    if "error" in jadwal:
        return f"⚠️ Gagal mengambil jadwal: {jadwal['error']}"

    header = (
        f"🕌 **JADWAL SHOLAT — {nama_lokasi.upper()}**\n"
        if nama_lokasi else "🕌 **JADWAL SHOLAT**\n"
    )
    header += "_Standar Kemenag + penyesuaian Masjid Raudha_\n"
    header += f"_(Subuh +{OFFSET_SUBUH} mnt, Maghrib +{OFFSET_MAGHRIB} mnt)_\n"
    header += "━━━━━━━━━━━━━━━━━━━━\n\n"

    baris = ""
    for nama, waktu in jadwal.items():
        baris += f"• **{nama:<8}**: `{waktu}` WIB\n"
    return header + baris