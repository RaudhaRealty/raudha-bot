# debug_initdata.py
from urllib.parse import parse_qsl
import json

# PASTE initData dari HP di sini
init_data = "AAF0TikcAAAAAHROKRx2eflM&user=%7B%22id%22%3A472469108%2C%22first_name%22%3A%22Maz%22%2C%22last_name%22%3A%22%22%2C%22username%22%3A%22Raudha_Realty%22%2C%22language_code%22%3A%22id%22%2C%22allows_write_to_pm%22%3Atrue%2C%22photo_url%22%3A%22https%3A%5C%2F%5C%2Ft.me%5C%2Fi%5C%2Fuserpic%5C%2F320%5C%2FM7iFNd6mrmy5inAl3FkKYkHWd5wYnxtZjvRUwENeqU0.svg%22%7D&auth_date=1793288406&signature=eMHeLZN2QS6-B5ScS6RShor58wU4totzAP2T975W7l3wVxT6HKJZLwd-4g9pKAsR-qCRlFC7CQggZKYOlK0BQ&hash=4b93eb8ea85f5146c41209fb11df5913e76ce9688f19bb08f048e750b618adc2"

# Parse
params = dict(parse_qsl(init_data, keep_blank_values=True))

print("=== PARAMETER initData ===")
for k, v in params.items():
    if k == 'user':
        print(f"user: {v[:100]}...")
    elif k == 'hash':
        print(f"hash: {v}")
    else:
        print(f"{k}: {v}")

print("\n=== USER DATA ===")
if 'user' in params:
    try:
        user = json.loads(params['user'])
        print(json.dumps(user, indent=2))
    except Exception as e:
        print(f"Error parse user: {e}")

print("\n=== HASH ADA? ===")
print("hash:", params.get('hash', 'TIDAK ADA'))