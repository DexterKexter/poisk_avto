"""
Encar.com listing ID collector.

Fetches car.encar.com/list/car?page=N via Oxylabs (render=html), extracts
__NEXT_DATA__.props.pageProps.initialState.ryvussApi.queries.* — combining
getCarNormal (200), getCarPreferential (40), getCarPremium (10) gives
~250 unique cars per page.

Usage:
    python collect_encar.py --pages 5 --min-year 0 --limit 5000

Env: OXY_USER, OXY_PASS, SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

SOURCE = "encar"
DEFAULT_ACTION = "(And.Hidden.N._.CarType.A.)"  # all car types, not hidden
DEFAULT_SORT = "MobileModifiedDate"             # newest activity first

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def build_listing_url(page: int,
                      action: str = DEFAULT_ACTION,
                      sort: str = DEFAULT_SORT) -> str:
    search = {
        "type": "car",
        "action": action,
        "toggle": {},
        "layer": "",
        "sort": sort,
    }
    qs = urllib.parse.urlencode({
        "page": page,
        "search": json.dumps(search, separators=(",", ":")),
    })
    return f"https://car.encar.com/list/car?{qs}"


def _extract_cars_from_next_data(nd: dict) -> list[dict]:
    """Walk into the ryvussApi queries dict and merge all SearchResults."""
    page_props = nd.get("props", {}).get("pageProps", {})
    ryvuss = page_props.get("initialState", {}).get("ryvussApi", {})
    queries = ryvuss.get("queries", {}) or {}
    cars: dict[str, dict] = {}
    for q_key, q_val in queries.items():
        if not isinstance(q_val, dict):
            continue
        results = (q_val.get("data") or {}).get("SearchResults") or []
        for car in results:
            cid = str(car.get("Id") or "")
            if cid:
                cars[cid] = car
    return list(cars.values())


def fetch_page(page: int) -> tuple[int, list[dict]]:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS")
    url = build_listing_url(page)
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "South Korea",
        "render": "html",
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2} for _ in range(3)
        ],
    }
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                          json=payload, timeout=300)
        if r.status_code != 200:
            print(f"  [page {page}] HTTP {r.status_code}: {r.text[:120]}")
            return (page, [])
        results = r.json().get("results", []) or []
        if not results:
            return (page, [])
        content = results[0].get("content", "")
        if not isinstance(content, str):
            return (page, [])
        m = NEXT_DATA_RE.search(content)
        if not m:
            print(f"  [page {page}] __NEXT_DATA__ not found")
            return (page, [])
        nd = json.loads(m.group(1))
        cars = _extract_cars_from_next_data(nd)
        print(f"  [page {page}] {len(cars)} cars")
        return (page, cars)
    except Exception as e:
        print(f"  [page {page}] exception: {e}")
        return (page, [])


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
    ap.add_argument("--pages", type=int, default=5,
                    help="How many listing pages to fetch (250 cars each)")
    ap.add_argument("--batch-size", type=int, default=2,
                    help="Parallel page requests per batch")
    ap.add_argument("--batch-pause", type=int, default=3)
    ap.add_argument("--min-year", type=int, default=0,
                    help="Skip cars with Year < YYYY*100 (0 = no filter)")
    ap.add_argument("--limit", type=int, default=10000)
    args = ap.parse_args()

    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}")
    print(f"Pages: {args.pages} × ~250 cars = up to {args.pages * 250}")
    print(f"Batch: {args.batch_size} parallel, pause {args.batch_pause}s")
    print(f"Filters: min_year={args.min_year}, limit={args.limit}\n")

    print("Loading known IDs cache…")
    known = fetch_known_ids()
    print(f"  already in DB (cars + pending): {len(known)}\n")

    all_cars: dict[str, dict] = {}
    started = time.time()
    pages = list(range(1, args.pages + 1))

    total_batches = (len(pages) + args.batch_size - 1) // args.batch_size
    for batch_start in range(0, len(pages), args.batch_size):
        batch = pages[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        elapsed = int(time.time() - started)
        print(f"Batch {batch_num}/{total_batches} (pages {batch}, "
              f"elapsed {elapsed}s, collected {len(all_cars)}):")

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(fetch_page, p): p for p in batch}
            for fut in as_completed(futures):
                _, cars = fut.result()
                for car in cars:
                    cid = str(car.get("Id") or "")
                    if cid and cid not in all_cars:
                        all_cars[cid] = car

        if batch_start + args.batch_size < len(pages):
            time.sleep(args.batch_pause)

    print(f"\nTotal unique cars across pages: {len(all_cars)}")

    skipped_known = skipped_old = 0
    to_save: list[tuple[str, dict]] = []
    min_year_int = args.min_year * 100 if args.min_year else 0  # Year format YYYYMM
    for cid, car in all_cars.items():
        if cid in known:
            skipped_known += 1
            continue
        year_int = car.get("Year")
        if min_year_int and isinstance(year_int, int) and year_int < min_year_int:
            skipped_old += 1
            continue
        # Metadata: drop heavy `Photos` list, keep small fields
        metadata = {k: v for k, v in car.items() if k != "Photos"}
        to_save.append((cid, metadata))

    print(f"  already in DB: {skipped_known}")
    print(f"  too old (Year < {min_year_int}): {skipped_old}")
    print(f"  to save: {len(to_save)}")

    saved = 0
    for cid, meta in to_save:
        if save_id(cid, meta):
            saved += 1
        if saved >= args.limit:
            break

    final = DB.count_pending(SOURCE)
    total = int(time.time() - started)
    print(f"\nDone in {total}s. Upserted: {saved} new IDs. "
          f"Total in pending_ids[{SOURCE}]: {final}")


if __name__ == "__main__":
    main()
