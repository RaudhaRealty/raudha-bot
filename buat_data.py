import json, os

PATH = r"C:\Users\Admin\Desktop\bot-raudha\data_kota.json"

kota = [
    {"nama": "Makkah",     "lat": 21.423663, "lng": 39.822785, "provinsi": "Makkah",        "catatan": "Masjidil Haram - Makkah"},
    {"nama": "Madinah",    "lat": 24.467411, "lng": 39.608464, "provinsi": "Madinah",       "catatan": "Masjidil Nabawi - Madinah"},
    {"nama": "Jerusalem",  "lat": 31.776074, "lng": 35.233205, "provinsi": "Jerusalem",     "catatan": "Masjidil Quds - Palestina"},
    {"nama": "Danakerta",  "lat": -7.353458, "lng": 109.544621, "provinsi": "Jawa Tengah",  "catatan": "Markas Raudha - Masjid Al Falah Raudha"},
    {"nama": "Banda Aceh", "lat": 5.52,      "lng": 95.42,     "provinsi": "Aceh"},
    {"nama": "Medan",      "lat": 3.64,      "lng": 98.88,     "provinsi": "Sumatera Utara"},
    {"nama": "Padang",     "lat": -0.79,     "lng": 100.28,    "provinsi": "Sumatera Barat"},
]

with open(PATH, "w", encoding="utf-8") as f:
    json.dump(kota, f, ensure_ascii=False, indent=2)

# verifikasi ulang
with open(PATH, "r", encoding="utf-8") as f:
    dicek = json.load(f)

print("✅ Tertulis & terbaca:", len(dicek), "kota ->", PATH)
print(os.path.getsize(PATH), "bytes")