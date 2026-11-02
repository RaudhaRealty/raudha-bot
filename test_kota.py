import os, json, re

PATH_DATA_KOTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_kota.json")

def norm_nama(nama):
    return re.sub(r"[^a-z0-9]", "", str(nama).lower())

print(f"📁 Path : {PATH_DATA_KOTA}")
print(f"📦 Ada  : {os.path.exists(PATH_DATA_KOTA)}")

if not os.path.exists(PATH_DATA_KOTA):
    raise SystemExit(f"❌ File belum ada: {PATH_DATA_KOTA}\n   Buat/unduh dulu (lihat langkah 1 atau 2).")

with open(PATH_DATA_KOTA, 'r', encoding='utf-8') as f:
    data = json.load(f)

with open(PATH_DATA_KOTA, 'r', encoding='utf-8') as f:
    content = f.read().strip()

try:
    data = json.loads(content)
    print(f"✅ JSON array valid — {len(data)} kota")
except json.JSONDecodeError as e:
    print(f"❌ JSON array TIDAK valid: {e}")
    print("   → Butuh fallback JSONL, atau tambahkan [ ] di awal/akhir file")
    data = []
    for line in content.splitlines():
        line = line.strip().rstrip(',')
        if line:
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    print(f"   Fallback JSONL: {len(data)} kota terbaca")

for tes in ["danakerta", "Banda Aceh", "banda aceh", "makkah", "jakarta"]:
    tn = norm_nama(tes)
    ketemu = next((k["nama"] for k in data if norm_nama(k.get("nama","")) == tn), None)
    print(f"   '{tes}' → {ketemu or '❌ TIDAK KETEMU'}")