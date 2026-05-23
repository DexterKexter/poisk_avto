"""Test global.che168.com API — v2 with proper search params."""
import json, sys, requests

BASE = "https://globalapi.che168.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://global.che168.com/en"}

print("=== 1. Brand list ===")
r = requests.get(f"{BASE}/brand", headers=UA, timeout=15)
d = r.json()
all_brands = []
for letter in d.get("result", {}).get("brands", []):
    all_brands.extend(letter.get("brand", []))
print(f"  Total brands: {len(all_brands)}")
for b in all_brands[:3]:
    print(f"    bid={b['bid']} name={b['name']}")

bmw_bid = next((b['bid'] for b in all_brands if b['name'] == 'BMW'), None)
print(f"  BMW bid: {bmw_bid}")

print("\n=== 2. Series for BMW ===")
r = requests.get(f"{BASE}/series", params={"brandid": bmw_bid}, headers=UA, timeout=15)
d = r.json()
result = d.get("result")
if isinstance(result, list):
    print(f"  series: {len(result)}")
    for s in result[:5]: print(f"    {json.dumps(s, ensure_ascii=False)[:200]}")
elif isinstance(result, dict):
    print(f"  keys: {list(result.keys())[:10]}")
    print(f"  sample: {json.dumps(result, ensure_ascii=False)[:800]}")
else:
    print(f"  result type: {type(result)}")

print("\n=== 3. Search ===")
for params in [
    {"brandid": bmw_bid, "page": 1, "pagesize": 3},
    {"bid": bmw_bid, "page": 1, "pagesize": 3},
    {"page": 1, "pagesize": 3, "brandid": bmw_bid, "lang": "en"},
    {"page": 1, "pagesize": 5},
]:
    r = requests.get(f"{BASE}/search", params=params, headers=UA, timeout=15)
    d = r.json()
    rc = d.get("returncode")
    result = d.get("result", {})
    total = result.get("totalcount", 0) if isinstance(result, dict) else 0
    items = (result.get("list") or result.get("cars") or []) if isinstance(result, dict) else []
    print(f"  GET {params} → rc={rc} total={total} items={len(items)}")
    if items:
        first = items[0]
        print(f"  KEYS: {sorted(first.keys())}")
        print(f"  FIRST CAR:\n{json.dumps(first, indent=2, ensure_ascii=False)[:2000]}")
        # Try detail for this car
        car_id = first.get("carid") or first.get("id") or first.get("specid")
        if car_id:
            print(f"\n=== 4. Detail for car {car_id} ===")
            r2 = requests.get(f"{BASE}/carinfo/{car_id}", headers=UA, timeout=15)
            d2 = r2.json()
            detail = d2.get("result", {})
            if isinstance(detail, dict):
                print(f"  DETAIL KEYS: {sorted(detail.keys())}")
                print(f"  DETAIL:\n{json.dumps(detail, indent=2, ensure_ascii=False)[:3000]}")

            print(f"\n=== 5. Report for car {car_id} ===")
            r3 = requests.get(f"{BASE}/report/summary", params={"carid": car_id}, headers=UA, timeout=15)
            d3 = r3.json()
            print(f"  rc={d3.get('returncode')} result keys: {list((d3.get('result') or {}).keys()) if isinstance(d3.get('result'), dict) else type(d3.get('result'))}")
            print(f"  {json.dumps(d3.get('result'), indent=2, ensure_ascii=False)[:1500]}")
        break

if not items:
    print("\n  No items from any search param. Full last response:")
    print(f"  {json.dumps(d, indent=2, ensure_ascii=False)[:1000]}")
