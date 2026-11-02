import json
import os
import urllib.request

DATA_DIR = r"C:\Users\Admin\Desktop\bot-raudha"
OUT_FILE = os.path.join(DATA_DIR, "data_kota.json")
BASE = "https://raw.githubusercontent.com/ibnux/data-indonesia/master/kota/"

all_kota = []

for i in range(1, 35):
    pid = str(i).zfill(2)
    url = BASE + pid + ".json"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        for item in data:
            all_kota.append({
                "nama": item.get("name", ""),
                "lat": None,
                "lng": None,
                "provinsi": "",
                "id": item.get("code", "")
            })
        print("OK", pid, "-> total", len(all_kota))
    except Exception as e:
        print("SKIP", pid, "->", e)

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(all_kota, f, ensure_ascii=False, indent=2)

print("\nTotal kota:", len(all_kota))
print("Tersimpan:", OUT_FILE)
print("Ukuran:", os.path.getsize(OUT_FILE), "bytes")