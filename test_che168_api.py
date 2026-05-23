"""Quick test of global.che168.com API from GitHub Actions runner."""
import json, sys, requests

BASE = "https://globalapi.che168.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0"}

print("=== 1. Brand list ===")
r = requests.get(f"{BASE}/brand", headers=UA, timeout=15)
print(f"  status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  returncode={d.get('returncode')}")
    brands = d.get("result", {}).get("brands", [])
    print(f"  brands count: {len(brands)}")
    for b in brands[:5]:
        print(f"    {b}")

print("\n=== 2. Search (page 1, 3 cars) ===")
r = requests.get(f"{BASE}/search", params={"page": 1, "pagesize": 3}, headers=UA, timeout=15)
print(f"  status={r.status_code}")
if r.status_code == 200:
    d = r.json()
    print(f"  returncode={d.get('returncode')}")
    result = d.get("result", {})
    print(f"  total: {result.get('totalcount')}")
    cars = result.get("list") or result.get("items") or result.get("cars") or []
    print(f"  cars in page: {len(cars)}")
    if cars:
        first = cars[0]
        print(f"  FIRST CAR KEYS: {sorted(first.keys())}")
        print(f"  FIRST CAR:")
        print(json.dumps(first, indent=2, ensure_ascii=False)[:2000])

print("\n=== 3. Car detail (if we have an ID) ===")
if r.status_code == 200 and cars:
    car_id = first.get("carid") or first.get("id") or first.get("specid")
    if car_id:
        r2 = requests.get(f"{BASE}/carinfo/{car_id}", headers=UA, timeout=15)
        print(f"  carinfo/{car_id} status={r2.status_code}")
        if r2.status_code == 200:
            d2 = r2.json()
            detail = d2.get("result", {})
            print(f"  DETAIL KEYS: {sorted(detail.keys()) if isinstance(detail, dict) else type(detail)}")
            print(json.dumps(detail, indent=2, ensure_ascii=False)[:3000])
