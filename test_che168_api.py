"""Test global.che168.com API — v3: exhaustive search param combos."""
import json, requests

BASE = "https://globalapi.che168.com/api/v1"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://global.che168.com/en"}

# 1. Get BMW brand id + series ids
r = requests.get(f"{BASE}/brand", headers=UA, timeout=15)
all_brands = []
for letter in r.json().get("result", {}).get("brands", []):
    all_brands.extend(letter.get("brand", []))
bmw_bid = next((b['bid'] for b in all_brands if b['name'] == 'BMW'), None)
print(f"BMW bid={bmw_bid}")

r = requests.get(f"{BASE}/series", params={"brandid": bmw_bid}, headers=UA, timeout=15)
series_data = r.json().get("result", {}).get("list", [])
all_series = []
for group in series_data:
    all_series.extend(group.get("item", []))
print(f"BMW series: {len(all_series)}")
for s in all_series[:5]:
    print(f"  sid={s['sid']} name={s['sname']}")
bmw5_sid = next((s['sid'] for s in all_series if '5' in s['sname'] and 'Series' in s['sname']), None)
print(f"BMW 5 Series sid={bmw5_sid}")

# 2. Exhaustive search param combos
print("\n=== Search combos ===")
combos = [
    {"page": 1, "pagesize": 3},
    {"page": 1, "pagesize": 3, "brandid": bmw_bid},
    {"page": 1, "pagesize": 3, "seriesid": bmw5_sid},
    {"page": 1, "pagesize": 3, "brandid": bmw_bid, "seriesid": bmw5_sid},
    {"pageindex": 1, "pagesize": 3},
    {"pageindex": 0, "pagesize": 3},
    {"pageindex": 1, "pagesize": 3, "brandid": bmw_bid},
    {"page": 1, "pagesize": 3, "country": "KZ"},
    {"page": 1, "pagesize": 3, "language": "en"},
    {"page": 1, "pagesize": 3, "region": "overseas"},
    {"page": 1, "pagesize": 3, "type": "export"},
    {"page": 1, "pagesize": 10, "sorttype": 1},
]
for params in combos:
    r = requests.get(f"{BASE}/search", params=params, headers=UA, timeout=10)
    d = r.json()
    result = d.get("result", {})
    total = result.get("totalcount", 0) if isinstance(result, dict) else 0
    cars = (result.get("carlist") or result.get("list") or []) if isinstance(result, dict) else []
    tag = "***HIT***" if cars else ""
    print(f"  {params} → total={total} cars={len(cars)} {tag}")
    if cars:
        print(f"  FIRST: {json.dumps(cars[0], indent=2, ensure_ascii=False)[:1500]}")
        break

# 3. Try POST
print("\n=== POST search ===")
for body in [
    {"page": 1, "pagesize": 3},
    {"page": 1, "pagesize": 3, "brandid": bmw_bid},
    {"pageindex": 1, "pagesize": 3},
]:
    r = requests.post(f"{BASE}/search", json=body,
                      headers={**UA, "Content-Type": "application/json"}, timeout=10)
    d = r.json()
    result = d.get("result", {})
    total = result.get("totalcount", 0) if isinstance(result, dict) else 0
    cars = (result.get("carlist") or []) if isinstance(result, dict) else []
    print(f"  POST {body} → total={total} cars={len(cars)}")
    if cars:
        print(f"  FIRST: {json.dumps(cars[0], indent=2, ensure_ascii=False)[:1500]}")
        break

# 4. Try other endpoints that might have cars
print("\n=== Other endpoints ===")
for url, params in [
    (f"{BASE}/recommend", {"page": 1, "pagesize": 3}),
    (f"{BASE}/recommend", {"brandid": bmw_bid}),
    (f"{BASE}/getlocaltion", {}),
    (f"{BASE}/specparam", {"specid": bmw5_sid}),
]:
    try:
        r = requests.get(url, params=params, headers=UA, timeout=10)
        d = r.json()
        rc = d.get("returncode")
        result = d.get("result")
        rtype = type(result).__name__
        rlen = len(result) if isinstance(result, (list, dict)) else 0
        print(f"  GET {url.split('/')[-1]} {params} → rc={rc} result={rtype}({rlen})")
        if isinstance(result, dict) and rlen > 0:
            print(f"    keys: {list(result.keys())[:10]}")
            print(f"    sample: {json.dumps(result, ensure_ascii=False)[:500]}")
        elif isinstance(result, list) and rlen > 0:
            print(f"    first: {json.dumps(result[0], ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"  GET {url.split('/')[-1]} → ERROR: {e}")
