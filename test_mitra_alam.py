# test_mitra_alam.py — Test inisialisasi Mitra Alam
"""Jalankan dengan: python test_mitra_alam.py"""

import sqlite3
import sys

# Test 1: Init web db (semua tabel + seed)
print("=" * 60)
print("TEST 1: Inisialisasi database (init_web_db)")
print("=" * 60)
try:
    from app import init_web_db
    init_web_db()
    print("✅ Init OK\n")
except Exception as e:
    print(f"❌ GAGAL: {e}")
    sys.exit(1)

# Test 2: Verifikasi semua tabel
print("=" * 60)
print("TEST 2: Daftar semua tabel")
print("=" * 60)
conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
conn.close()

print(f"Total tabel: {len(tables)}\n")
for t in tables:
    print(f"  • {t}")

# Cek tabel Mitra Alam
print()
required = ['komoditas_wakaf', 'pohon_wakaf', 'pohon_log', 'pohon_panen']
missing = [t for t in required if t not in tables]
if missing:
    print(f"❌ Tabel Mitra Alam HILANG: {missing}")
    sys.exit(1)
else:
    print("✅ Semua tabel Mitra Alam ada\n")

# Test 3: Verifikasi modul Mitra Alam & komoditas
print("=" * 60)
print("TEST 3: Modul Mitra Alam & komoditas")
print("=" * 60)
try:
    from modul_mitra_alam import init_db_mitra_alam, get_semua_komoditas
    init_db_mitra_alam()
    
    komoditas = get_semua_komoditas()
    print(f"\nJumlah komoditas: {len(komoditas)}\n")
    for k in komoditas:
        harga = f"Rp {int(k['harga_pohon']):,}".replace(",", ".")
        print(f"  🌱 {k['nama_display']:30s} — {harga}")
    
    if len(komoditas) == 5:
        print("\n✅ Semua test LULUS!")
    else:
        print(f"\n⚠️ Komoditas: {len(komoditas)} (harusnya 5)")
except Exception as e:
    print(f"❌ GAGAL: {e}")
    sys.exit(1)