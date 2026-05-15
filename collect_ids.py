"""
Dongchedi listing ID collector — XHR-capture version.

Architecture:
  Uses Oxylabs "xhr": true to capture /motor/pc/sh/sh_sku_list POST calls
  the browser makes while scrolling. Each call returns 20 cars as JSON
  with car_year, mileage, city, brand etc. already populated.

  Vs. HTML-regex version:
    + Structured data, no regex fragility
    + Pre-filter by year BEFORE writing pending_ids
    + Cuts wasted card-page parsing later

  Same Oxylabs cost per request. Same 4-city parallel strategy.

Filtering:
  Default: only cars with car_year >= MIN_YEAR (2022) are queued.
  Override with --min-year 0 to disable.

Usage:
    python collect_ids.py [--cities beijing,shanghai,guangzhou,shenzhen]
                          [--scrolls 10] [--min-year 2022] [--limit 5000]

Env vars:
    OXY_USER, OXY_PASS         — Oxylabs credentials (required)
    SUPABASE_URL, SUPABASE_KEY — if set, writes to Postgres; otherwise SQLite
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

SOURCE = "dongchedi"

CITY_CODES = {
    "beijing":   ("110000", "北京 Beijing"),
    "shanghai":  ("310000", "上海 Shanghai"),
    "guangzhou": ("440100", "广州 Guangzhou"),
    "shenzhen":  ("440300", "深圳 Shenzhen"),
    "tianjin":   ("120000", "天津 Tianjin"),
    "all":       ("x",      "全国 Nationwide"),
}

DEFAULT_CITIES = "beijing,shanghai,guangzhou,shenzhen"
DEFAULT_MIN_YEAR = 2022

SKU_LIST_PATH = "/motor/pc/sh/sh_sku_list"


def build_listing_url(city_code: str) -> str:
    parts = ['x'] * 28
    if city_code != 'x':
        parts[21] = city_code
    return "https://www.dongchedi.com/usedcar/" + "-".join(parts)


def fetch_listing_xhr(city_key: str, scrolls: int) -> tuple[str, list[dict]]:
    """Fetch one city's listing via Oxylabs XHR capture.
    Returns (city_key, list_of_cars) from all sh_sku_list responses."""
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS")

    code, label = CITY_CODES[city_key]
    url = build_listing_url(code)

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

    print(f"  [{city_key:9s}] {label} + {scrolls} scrolls + XHR capture…")
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
        if r.status_code != 200:
            print(f"  [{city_key:9s}] HTTP {r.status_code}: {r.text[:200]}")
            return (city_key, [])

        data = r.json()
        results = data.get("results", [])
        xhr_results = [res for res in results if res.get("type") == "xhr"]
        if not xhr_results:
            print(f"  [{city_key:9s}] No XHR results returned")
            return (city_key, [])

        xhr_requests = xhr_results[0].get("content", []) or []

        cars_by_sku: dict[int, dict] = {}
        api_calls = 0
        for req in xhr_requests:
            url_str = req.get("url", "")
            if SKU_LIST_PATH not in url_str:
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
                    cars_by_sku[sku] = car

        print(f"  [{city_key:9s}] {api_calls} sh_sku_list calls → "
              f"{len(cars_by_sku)} unique cars")
        return (city_key, list(cars_by_sku.values()))
    except Exception as e:
        print(f"  [{city_key:9s}] exception: {e}")
        return (city_key, [])


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
    ap.add_argument("--scrolls", type=int, default=10,
                    help="scroll_to_bottom actions per city")
    ap.add_argument("--min-year", type=int, default=DEFAULT_MIN_YEAR,
                    help="Skip cars older than this year (0 = no filter)")
    ap.add_argument("--limit", type=int, default=5000,
                    help="Max IDs to upsert this run")
    args = ap.parse_args()

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    invalid = [c for c in cities if c not in CITY_CODES]
    if invalid:
        sys.exit(f"Unknown cities: {invalid}. Available: {list(CITY_CODES.keys())}")

    print(f"Backend: {DB.backend_name()}")
    print(f"Cities ({len(cities)}): {cities}")
    print(f"Scrolls/city: {args.scrolls}, min_year: {args.min_year}, limit: {args.limit}")

    print("\nLoading known IDs cache…")
    known = fetch_known_ids()
    print(f"  already in DB (cars + pending): {len(known)}")

    print(f"\nFiring {len(cities)} parallel XHR-capture requests…")
    all_cars: dict[int, dict] = {}
    per_city_stats: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=len(cities)) as pool:
        futures = {pool.submit(fetch_listing_xhr, c, args.scrolls): c for c in cities}
        for fut in as_completed(futures):
            city_key, cars = fut.result()
            per_city_stats[city_key] = len(cars)
            for car in cars:
                sku = car.get("sku_id")
                if sku and sku not in all_cars:
                    all_cars[sku] = car

    print(f"\nTotal unique cars across cities: {len(all_cars)}")

    # Filter
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
    print(f"\nDone. Upserted: {saved} new IDs. Total in pending_ids[{SOURCE}]: {final}")
    print("\nPer-city yield (unique cars from XHR capture):")
    for city, count in per_city_stats.items():
        print(f"  {city:9s}: {count} cars")


if __name__ == "__main__":
    main()
