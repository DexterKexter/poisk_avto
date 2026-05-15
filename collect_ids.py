"""
Dongchedi listing ID collector — parallel version.

Optimization vs. v1:
  - Runs N parallel listing requests with different scroll counts.
    Because dongchedi serves listing in non-deterministic order, each parallel
    request returns a partly-different sample → more unique IDs per run.
  - Pre-fetches existing IDs from cars + pending_ids and skips them,
    so logs show real "new" yield, not just upserts.

Usage:
    python collect_ids.py [--parallel 3] [--scrolls 8] [--limit 5000]

Env vars:
    OXY_USER, OXY_PASS         — Oxylabs credentials (required)
    SUPABASE_URL, SUPABASE_KEY — if set, writes to Postgres; otherwise SQLite
"""

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import db as DB

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

LISTING_URL = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x"
SOURCE = "dongchedi"

CARD_LINK_RE = re.compile(r'/usedcar/(\d{7,})')


def fetch_listing_with_scroll(scrolls: int, worker_id: int = 0) -> str | None:
    """Fetch the listing page via Oxylabs render=html with N scroll_to_bottom actions."""
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: set OXY_USER and OXY_PASS environment variables")

    instructions = [
        {"type": "scroll_to_bottom", "wait_time_s": 2}
        for _ in range(scrolls)
    ]

    payload = {
        "source": "universal",
        "url": LISTING_URL,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "browser_instructions": instructions,
    }

    print(f"  [w{worker_id}] requesting listing with {scrolls} scrolls "
          f"(~{scrolls * 2}s wait)…")
    try:
        r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS), json=payload, timeout=300)
        if r.status_code != 200:
            print(f"  [w{worker_id}] Oxylabs HTTP {r.status_code}: {r.text[:200]}")
            return None
        outer = r.json()
        results = outer.get("results", [])
        if not results:
            print(f"  [w{worker_id}] empty results: {str(outer)[:200]}")
            return None
        content = results[0].get("content", "")
        return content if isinstance(content, str) else None
    except Exception as e:
        print(f"  [w{worker_id}] exception: {e}")
        return None


def extract_card_ids(html: str) -> list[str]:
    return list(dict.fromkeys(CARD_LINK_RE.findall(html)))


def save_id(sku_id: str) -> bool:
    return DB.upsert_pending({
        "source": SOURCE,
        "source_id": sku_id,
        "metadata": None,
        "found_at": DB.now_iso(),
    })


# ---------- Known-ID cache ----------

def fetch_known_ids() -> set[str]:
    """Get all source_ids already in cars + pending_ids for this source.

    Used to compute true "new IDs" yield per run.
    """
    known: set[str] = set()

    if DB.USE_POSTGRES:
        # cars
        r = DB._pg_request("GET", f"cars?source=eq.{SOURCE}&select=source_id")
        if r.status_code == 200:
            known.update(row["source_id"] for row in r.json())
        # pending
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=3,
                    help="Number of parallel listing requests (each returns "
                         "a partly different sample due to non-deterministic order)")
    ap.add_argument("--scrolls", type=int, default=8,
                    help="scroll_to_bottom actions per request "
                         "(lower than v1's 10 to avoid 408 timeout, but more workers)")
    ap.add_argument("--limit", type=int, default=5000,
                    help="Max IDs to upsert this run")
    args = ap.parse_args()

    print(f"Backend: {DB.backend_name()}")
    print(f"Parallel: {args.parallel}, scrolls per request: {args.scrolls}, limit: {args.limit}")

    print("Loading known IDs cache…")
    known = fetch_known_ids()
    print(f"  already in DB (cars + pending): {len(known)}")

    # Launch N parallel listing requests
    print(f"\nFiring {args.parallel} parallel listing requests…")
    all_ids: list[str] = []
    seen_local: set[str] = set()

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {
            pool.submit(fetch_listing_with_scroll, args.scrolls, i + 1): i + 1
            for i in range(args.parallel)
        }
        for fut in as_completed(futures):
            wid = futures[fut]
            html = fut.result()
            if not html:
                print(f"  [w{wid}] no HTML returned")
                continue
            ids = extract_card_ids(html)
            new_this_worker = [i for i in ids if i not in seen_local]
            seen_local.update(ids)
            all_ids.extend(new_this_worker)
            print(f"  [w{wid}] got {len(html)} bytes → {len(ids)} IDs "
                  f"({len(new_this_worker)} new in this run)")

    print(f"\nTotal unique IDs across workers: {len(seen_local)}")

    # Compute truly new (not yet in cars or pending)
    truly_new = [i for i in seen_local if i not in known]
    print(f"Of those, NEW to DB: {len(truly_new)}")

    # Upsert
    saved = 0
    for sku_id in truly_new:
        if save_id(sku_id):
            saved += 1
        if saved >= args.limit:
            break

    final = DB.count_pending(SOURCE)
    print(f"\nDone. Upserted: {saved} new IDs, total in pending_ids[{SOURCE}]: {final}")


if __name__ == "__main__":
    main()
