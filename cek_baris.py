# cek_baris.py
lines = open('templates/index.html', encoding='utf-8').readlines()

print("=== BARIS 745-765 ===")
for i in range(744, 765):
    if i < len(lines):
        print(f"{i+1:4d}: {repr(lines[i])}")

print("\n=== TOTAL BARIS ===")
print(len(lines))