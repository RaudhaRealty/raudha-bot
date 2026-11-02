import requests

tagihan_list = [
    {"jenis": "air", "nama": "PDAM", "nominal": 150000, "jatuh_tempo": "2026-11-15", "frekuensi": "bulanan"},
    {"jenis": "internet", "nama": "IndiHome", "nominal": 400000, "jatuh_tempo": "2026-11-20", "frekuensi": "bulanan"},
    {"jenis": "cicilan", "nama": "KPR Rumah", "nominal": 3000000, "jatuh_tempo": "2026-11-01", "frekuensi": "bulanan"},
    {"jenis": "hutang", "nama": "Hutang ke Ahmad", "nominal": 1000000, "jatuh_tempo": "2026-12-31", "frekuensi": "sekali"},
    {"jenis": "pulsa", "nama": "Pulsa Telkomsel", "nominal": 50000, "jatuh_tempo": "2026-11-05", "frekuensi": "bulanan"},
]

for t in tagihan_list:
    t["user_id"] = 123456789
    r = requests.post("http://127.0.0.1:5000/api/tagihan", json=t)
    print(r.json())
    