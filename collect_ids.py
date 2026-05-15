"""
Dongchedi listing ID collector — brand × city strategy.

For each (city, brand) pair the script issues one Oxylabs request that
captures /motor/pc/sh/sh_sku_list XHR responses while the page scrolls.
Each brand filter shows its own ranked list (≤220 cars per request),
not just the nationwide top-220 — so the visible pool expands ~10x.

Architecture:
  - 80 brands × 4 cities = 320 URLs (default).
  - Requests issued in small concurrent batches (--batch-size) with
    a short pause between batches to avoid Oxylabs throttling.
  - Pre-fetches known source_ids; reports real-new yield.
  - Filters cars with car_year < --min-year BEFORE writing pending_ids.

Usage:
  python collect_ids.py [--cities ...] [--brands ...] [--scrolls 8]
                        [--batch-size 4] [--batch-pause 3]
                        [--min-year 2022] [--limit 5000]

Env:
  OXY_USER, OXY_PASS         — Oxylabs (required)
  SUPABASE_URL, SUPABASE_KEY — Postgres if set; else SQLite fallback
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

SOURCE = "dongchedi"
SKU_LIST_PATH = "/motor/pc/sh/sh_sku_list"

# URL position 21 = city code (verified empirically).
CITY_CODES = {
    "beijing":   ("110000", "北京 Beijing"),
    "shanghai":  ("310000", "上海 Shanghai"),
    "guangzhou": ("440100", "广州 Guangzhou"),
    "shenzhen":  ("440300", "深圳 Shenzhen"),
    "tianjin":   ("120000", "天津 Tianjin"),
    "all":       ("x",      "全国 Nationwide"),
}
DEFAULT_CITIES = "beijing,shanghai,guangzhou,shenzhen"

# URL position 19 = brand_id (verified empirically).
# Pool of 80 brands — passenger cars only, sorted by importance.
BRAND_POOL = {
    # Premium Euro (10)
    3: "Mercedes-Benz", 4: "BMW", 2: "Audi", 20: "Porsche", 24: "Volvo",
    19: "Land Rover", 22: "Lexus", 30: "Cadillac", 47: "Bentley", 25: "Maybach",
    # Sport / Luxury (5)
    44: "Ferrari", 41: "Rolls-Royce", 80: "Aston Martin", 42: "Lamborghini",
    86: "McLaren",
    # Mainstream foreign (12)
    1: "Volkswagen", 5: "Toyota", 9: "Honda", 10: "Nissan", 7: "Ford",
    12: "Buick", 11: "Hyundai", 13: "Kia", 63: "Tesla", 6: "Chevrolet",
    14: "Jeep", 62: "Lincoln",
    # Niche foreign (8)
    65: "MINI", 48: "smart", 23: "Skoda", 15: "Mazda", 33: "Subaru",
    29: "Infiniti", 273: "Genesis", 61: "Peugeot",
    # Chinese majors (12)
    16: "BYD", 73: "Geely", 18: "Chery", 17: "Haval", 35: "Changan",
    36: "Roewe", 59: "Hongqi", 40: "GAC Trumpchi", 174: "Lynk & Co",
    425: "Tank", 8: "Great Wall", 66: "WEY",
    # Chinese EV / new energy (13)
    112: "NIO", 195: "XPeng", 202: "Li Auto", 535: "Xiaomi", 483: "AITO",
    426: "Zeekr", 242: "Aion", 207: "Leapmotor", 159: "Denza", 395: "Voyah",
    515: "Deepal", 419: "IM Motors", 475: "AVATR",
    # Chinese sub-brands / others (18)
    870: "Changan Qiyuan", 858: "Geely Galaxy", 209: "Jetour", 251: "Exeed",
    366: "Baojun", 27: "Bestune", 264: "Geometry", 238: "ORA",
    176: "Arcfox", 381: "Radar", 861: "Fang Cheng Bao", 546: "YangWang",
    880: "GAC Hyper", 891: "Dongfeng eP", 260: "Jetta", 52: "BAIC Off-road",
    68: "BAIC",
    # Italian premium (2)
    45: "Maserati", 50: "Suzuki",
}


def build_listing_url(city_code: str, brand_id: int | None = None) -> str:
    parts = ['x'] * 28
    if city_code != 'x':
        parts[21] = city_code
    if brand_id is not None:
        parts[19] = str(brand_id)
    return "https://www.dongchedi.com/usedcar/" + "-".join(parts)


def fetch_pair(city_key: str, brand_id: int, scrolls: int) -> tuple[str, int, list[dict]]:
    """Fetch one (city, brand) pair. Returns (city_key, brand_id, list_of_cars)."""
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS")

    code, _ = CITY_CODES[city_key]
    brand_label = BRAND_POOL.get(brand_id, str(brand_id))
    url = build_listing_url(code, brand_id)

    instructions = [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
        for _ in range(scrolls)
    ]
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "xhr": True,
        "browser_instructions": instructions,
    }

    tag = f"{city_key[:9]:9s}/{brand_label[:15]:15s}"
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
        if r.status_code != 200:
            print(f"  [{tag}] HTTP {r.status_code}: {r.text[:120]}")
            return (city_key, brand_id, [])

        data = r.json()
        xhr_results = [res for res in data.get("results", []) if res.get("type") == "xhr"]
        if not xhr_results:
            print(f"  [{tag}] no XHR captured")
            return (city_key, brand_id, [])
        xhr_requests = xhr_results[0].get("content", []) or []

        cars: dict[int, dict] = {}
        api_calls = 0
        for req in xhr_requests:
            if SKU_LIST_PATH not in req.get("url", ""):
                continue
            if req.get("method") != "POST" or req.get("status_code") != 200:
                continue
            body = req.get("response_body", "")
            if not body:
                continue
            try:
                j = json.loads(body)
            except json.JSONDecodeError:
                continue
            api_calls += 1
            items = j.get("data", {}).get("search_sh_sku_info_list", []) or []
            for car in items:
                sku = car.get("sku_id")
                if sku:
                    cars[sku] = car

        print(f"  [{tag}] {api_calls:>2} calls → {len(cars):>3} cars")
        return (city_key, brand_id, list(cars.values()))
    except Exception as e:
        print(f"  [{tag}] exception: {e}")
        return (city_key, brand_id, [])


def fetch_known_ids() -> set[str]:
    known: set[str] = set()
    if DB.USE_POSTGRES:
        r = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
        if r.status_code == 200:
            known.update(row["source_id"] for row in r.json())
        r = DB._pg_request("GET", f"pending_ids?source=eq.{SOURCE}&select=source_id")
        if r.status_code == 200:
            known.update(row["source_id"] for row in r.json())
    else:
        conn = DB.sqlite_conn()
        for row in conn.execute("SELECT source_id FROM cars WHERE source = ?", (SOURCE,)):
            known.add(row[0])
        for row in conn.execute("SELECT source_id FROM pending_ids WHERE source = ?", (SOURCE,)):
            known.add(row[0])
    return known


def save_id(sku_id: str, metadata: dict[str, Any]) -> bool:
    return DB.upsert_pending({
        "source": SOURCE,
        "source_id": str(sku_id),
        "metadata": metadata,
        "found_at": DB.now_iso(),
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cities", type=str, default=DEFAULT_CITIES,
                    help=f"Comma-separated city keys. Available: {','.join(CITY_CODES)}")
    ap.add_argument("--brands", type=str, default="",
                    help="Comma-separated brand IDs, or 'all' (default: all)")
    ap.add_argument("--scrolls", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=4,
                    help="Parallel requests per batch")
    ap.add_argument("--batch-pause", type=int, default=3,
                    help="Seconds between batches")
    ap.add_argument("--min-year", type=int, default=2022)
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    invalid = [c for c in cities if c not in CITY_CODES]
    if invalid:
        sys.exit(f"Unknown cities: {invalid}. Available: {list(CITY_CODES.keys())}")

    if not args.brands or args.brands.lower() == "all":
        brands = list(BRAND_POOL.keys())
    else:
        try:
            brands = [int(b.strip()) for b in args.brands.split(",") if b.strip()]
        except ValueError:
            sys.exit("--brands must be 'all' or comma-separated integer IDs")

    print(f"Backend: {DB.backend_name()}")
    print(f"Cities ({len(cities)}): {cities}")
    print(f"Brands: {len(brands)}")
    print(f"Total requests: {len(cities) * len(brands)}")
    print(f"Batch: {args.batch_size} parallel, pause {args.batch_pause}s")
    print(f"Scrolls/req: {args.scrolls}, min_year: {args.min_year}, limit: {args.limit}")

    jobs: list[tuple[str, int]] = []
    for c in cities:
        for b in brands:
            jobs.append((c, b))

    print(f"\nLoading known IDs cache…")
    known = fetch_known_ids()
    print(f"  already in DB (cars + pending): {len(known)}")

    print(f"\nProcessing {len(jobs)} (city,brand) jobs in batches of {args.batch_size}…")
    all_cars: dict[int, dict] = {}
    started_at = time.time()

    total_batches = (len(jobs) + args.batch_size - 1) // args.batch_size
    for batch_start in range(0, len(jobs), args.batch_size):
        batch = jobs[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        elapsed = int(time.time() - started_at)
        print(f"\nBatch {batch_num}/{total_batches} (elapsed {elapsed}s, "
              f"cars so far: {len(all_cars)}):")

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {
                pool.submit(fetch_pair, c, b, args.scrolls): (c, b)
                for c, b in batch
            }
            for fut in as_completed(futures):
                city_key, brand_id, cars = fut.result()
                for car in cars:
                    sku = car.get("sku_id")
                    if sku and sku not in all_cars:
                        all_cars[sku] = car

        if batch_start + args.batch_size < len(jobs):
            time.sleep(args.batch_pause)

    print(f"\nTotal unique cars across all pairs: {len(all_cars)}")

    skipped_old = 0
    skipped_known = 0
    to_save: list[tuple[str, dict]] = []

    for sku, car in all_cars.items():
        sku_str = str(sku)
        if sku_str in known:
            skipped_known += 1
            continue
        year = car.get("car_year")
        if args.min_year > 0 and isinstance(year, int) and year < args.min_year:
            skipped_old += 1
            continue
        metadata = {
            "car_year": year,
            "brand_id": car.get("brand_id"),
            "brand_name": car.get("brand_name"),
            "series_name": car.get("series_name"),
            "car_name": car.get("car_name"),
            "car_source_city_name": car.get("car_source_city_name"),
            "brand_source_city_name": car.get("brand_source_city_name"),
            "shop_id": car.get("shop_id"),
            "transfer_cnt": car.get("transfer_cnt"),
        }
        to_save.append((sku_str, metadata))

    print(f"  already in DB: {skipped_known}")
    print(f"  too old (year < {args.min_year}): {skipped_old}")
    print(f"  to save: {len(to_save)}")

    saved = 0
    for sku_str, metadata in to_save:
        if save_id(sku_str, metadata):
            saved += 1
        if saved >= args.limit:
            break

    final = DB.count_pending(SOURCE)
    total_elapsed = int(time.time() - started_at)
    print(f"\nDone in {total_elapsed}s. Upserted: {saved} new IDs. "
          f"Total in pending_ids[{SOURCE}]: {final}")


if __name__ == "__main__":
    main()
