# cek.py
lines = open('templates/index.html', encoding='utf-8').readlines()

fungsi_target = [
    'async function mulaiSetor',
    'function tutupModalLembaga',
    'async function pilihLembaga',
    'function tutupModalRekening',
    'function pilihRekening',
    'function tutupModalKonfirmasi',
    'async function prosesSetor',
]

print("=== CEK FUNGSI SETOR ===")
for target in fungsi_target:
    found = False
    for i, l in enumerate(lines):
        if target in l:
            print(f"OK Baris {i+1}: {target}")
            found = True
            break
    if not found:
        print(f"MISSING: {target}")

print("\n=== TOTAL BARIS ===")
print(len(lines))