"""
Encar.com listing ID collector — DIRECT HTTP (no Oxylabs).

Tests confirmed api.encar.com is reachable from any IP without Oxylabs
proxy. Hits api.encar.com/search/car/list/general directly with
requests.get(). Same SearchResults as before but $0 per request.

Usage:
    python collect_encar.py --pages 10 --page-size 200 --min-year 0

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

import db as DB

SOURCE = "encar"
DEFAULT_ACTION = "(And.Hidden.N._.CarType.A.)"  # all car types, not hidden
DEFAULT_SORT = "MobileModifiedDate"             # newest activity first

API_BASE = "https://api.encar.com/search/car/list/general"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    "Referer": "https://car.encar.com/",
}


def build_api_url(offset: int, limit: int,
                  action: str = DEFAULT_ACTION,
                  sort: str = DEFAULT_SORT) -> str:
    sr = f"|{sort}|{offset}|{limit}"
    qs = urllib.parse.urlencode({
        "count": "true",
        "q": action,
        "sr": sr,
    })
    return f"{API_BASE}?{qs}"


def fetch_batch(offset: int, limit: int) -> tuple[int, list[dict]]:
    """Fetch one batch via direct HTTP. Returns (offset, list_of_cars)."""
    url = build_api_url(offset, limit)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [offset {offset}] HTTP {r.status_code}: {r.text[:120]}")
            return (offset, [])
        content = r.json()
        if not isinstance(content, dict):
            return (offset, [])
        cars = content.get("SearchResults") or []
        print(f"  [offset {offset}] {len(cars)} cars")
        return (offset, cars)
    except Exception as e:
        print(f"  [offset {offset}] exception: {e}")
        return (offset, [])


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
    ap.add_argument("--pages", type=int, default=10,
                    help="How many API batches to fetch")
    ap.add_argument("--page-size", type=int, default=200,
                    help="Cars per batch (API supports up to ~200)")
    ap.add_argument("--batch-size", type=int, default=4,
                    help="Parallel API requests per batch")
    ap.add_argument("--batch-pause", type=int, default=1)
    ap.add_argument("--min-year", type=int, default=0,
                    help="Skip cars with Year < YYYY*100 (0 = no filter)")
    ap.add_argument("--max-mileage-km", type=int, default=0,
                    help="Skip cars with Mileage > N km (0 = no filter)")
    ap.add_argument("--limit", type=int, default=10000,
                    help="Max new IDs to upsert this run")
    args = ap.parse_args()

    total_target = args.pages * args.page_size
    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE} (direct API mode)")
    print(f"Plan: {args.pages} batches × {args.page_size} cars = up to {total_target}")
    print(f"Parallel: {args.batch_size}, pause {args.batch_pause}s")
    print(f"Filters: min_year={args.min_year}, "
          f"max_mileage_km={args.max_mileage_km}, limit={args.limit}\n")

    print("Loading known IDs cache…")
    known = fetch_known_ids()
    print(f"  already in DB (cars + pending): {len(known)}\n")

    # Plan offsets: 0, page_size, 2*page_size, ...
    offsets = [i * args.page_size for i in range(args.pages)]

    all_cars: dict[str, dict] = {}
    started = time.time()
    total_batches = (len(offsets) + args.batch_size - 1) // args.batch_size

    for batch_start in range(0, len(offsets), args.batch_size):
        batch = offsets[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1
        elapsed = int(time.time() - started)
        print(f"Batch {batch_num}/{total_batches} (offsets {batch}, "
              f"elapsed {elapsed}s, collected {len(all_cars)}):")

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {pool.submit(fetch_batch, off, args.page_size): off
                       for off in batch}
            for fut in as_completed(futures):
                _, cars = fut.result()
                for car in cars:
                    cid = str(car.get("Id") or "")
                    if cid and cid not in all_cars:
                        all_cars[cid] = car

        if batch_start + args.batch_size < len(offsets):
            time.sleep(args.batch_pause)

    print(f"\nTotal unique cars across batches: {len(all_cars)}")

    skipped_known = skipped_old = skipped_mileage = 0
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
        mileage = car.get("Mileage")
        if (args.max_mileage_km and isinstance(mileage, (int, float))
                and mileage > args.max_mileage_km):
            skipped_mileage += 1
            continue
        # Metadata: drop heavy `Photos` list, keep small fields
        metadata = {k: v for k, v in car.items() if k != "Photos"}
        to_save.append((cid, metadata))

    print(f"  already in DB: {skipped_known}")
    print(f"  too old (Year < {min_year_int}): {skipped_old}")
    print(f"  too many km (> {args.max_mileage_km}): {skipped_mileage}")
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
