# cek_simpan.py
lines = open('templates/index.html', encoding='utf-8').readlines()

# Cari baris 'function simpanDataSyariah'
start = None
for i, l in enumerate(lines):
    if 'function simpanDataSyariah' in l:
        start = i
        break

if start is None:
    print("❌ Fungsi simpanDataSyariah TIDAK DITEMUKAN")
else:
    print(f"=== simpanDataSyariah mulai baris {start+1} ===")
    # Tampilkan 60 baris dari start
    for i in range(start, min(start + 60, len(lines))):
        print(f"{i+1:4d}: {repr(lines[i])}")