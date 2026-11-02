import requests

url = "http://127.0.0.1:5000/api/tagihan"
payload = {
    "user_id": 123456789,
    "jenis": "listrik",
    "nama": "PLN Rumah",
    "nominal": 500000,
    "jatuh_tempo": "2026-11-10",
    "frekuensi": "bulanan",
    "catatan": "Token listrik rumah"
}
r = requests.post(url, json=payload)
print(r.json())