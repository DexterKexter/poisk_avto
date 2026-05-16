"""
Refresh existing cars — detect sold listings and price drops.

For each alive car (sold_at IS NULL) re-fetches the card via Oxylabs and:
  - on parse success: compares new price with stored one. If new < old, logs a
    'price_drop' row in `changes` and updates the car record. Sets
    last_refresh_at and resets refresh_failed_attempts to 0.
  - on fetch/parse failure: increments refresh_failed_attempts. After 3
    consecutive failures (SOLD_FAIL_THRESHOLD) marks sold_at = now and logs
    a 'sold' row in `changes`.

Sort order: oldest last_refresh_at first (nulls first), so we always re-check
cars that haven't been touched in the longest time.

Usage:
    python refresh_cars.py --limit 500 --workers 10
    python refresh_cars.py --all                 # full refresh of base
    python refresh_cars.py --dry-run             # don't write to DB

Env: OXY_USER, OXY_PASS, SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import db as DB
from scrape_dongchedi import (
    SOURCE,
    CARD_URL,
    extract_next_data,
    oxylabs_fetch,
    parse_card,
)


def refresh_one(card_id: str, old_price: float | None) -> tuple[str, str, dict | None, str]:
    """Re-fetch one card. Returns (card_id, status, parsed_record, detail).

    status: 'ok' | 'price_drop' | 'fail'
    """
    url = CARD_URL.format(id=card_id)
    html = oxylabs_fetch(url, render=True)
    if not html:
        return (card_id, "fail", None, "no html")

    nd = extract_next_data(html)
    if not nd:
        return (card_id, "fail", None, "no __NEXT_DATA__")

    rec = parse_card(nd, card_id)
    if not rec:
        return (card_id, "fail", None, "no skuDetail (removed?)")

    new_price = rec.get("price_original")
    if (old_price is not None and new_price is not None
            and float(new_price) < float(old_price)):
        return (card_id, "price_drop", rec, f"{old_price} → {new_price}")
    return (card_id, "ok", rec, "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500,
                    help="Max cars to re-check this run")
    ap.add_argument("--all", action="store_true",
                    help="Refresh ALL alive cars (ignores --limit)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to DB; just print what would change")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        print("WARNING: refresh on SQLite — useful only for local dev.")

    limit = None if args.all else args.limit
    print(f"Backend: {DB.backend_name()}")
    print(f"Fetching alive cars (limit={limit or 'all'})…")
    alive = DB.get_alive_cars(SOURCE, limit)
    print(f"  loaded {len(alive)} alive cars")
    if not alive:
        return

    counts = {"ok": 0, "price_drop": 0, "fail": 0, "sold": 0}
    started = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(refresh_one, str(c["source_id"]), c.get("price_original")): c
            for c in alive
        }
        for i, fut in enumerate(as_completed(futures), 1):
            car = futures[fut]
            cid = str(car["source_id"])
            try:
                _, status, rec, detail = fut.result()
            except Exception as e:
                status, rec, detail = "fail", None, f"exception: {e}"

            if status in ("ok", "price_drop"):
                if not args.dry_run:
                    if status == "price_drop":
                        DB.log_change(
                            SOURCE, cid, "price_drop",
                            {"price_original": car.get("price_original"),
                             "price_currency": car.get("price_currency")},
                            {"price_original": rec["price_original"],
                             "price_currency": rec["price_currency"]},
                        )
                    DB.upsert_car(rec)
                    DB.mark_refresh_success(SOURCE, cid)
                counts[status] += 1
                tag = "DROP" if status == "price_drop" else "ok"
                msg = f" {detail}" if detail else ""
                print(f"  [{i}/{len(alive)}] id={cid} {tag}{msg}")
            else:
                if args.dry_run:
                    counts["fail"] += 1
                    print(f"  [{i}/{len(alive)}] id={cid} FAIL ({detail}) [dry-run]")
                    continue
                new_count = DB.mark_refresh_failed(SOURCE, cid)
                counts["fail"] += 1
                if 0 < new_count >= DB.SOLD_FAIL_THRESHOLD:
                    DB.mark_sold(SOURCE, cid)
                    DB.log_change(
                        SOURCE, cid, "sold",
                        {"last_price": car.get("price_original"),
                         "price_currency": car.get("price_currency"),
                         "consecutive_fails": new_count},
                        {"sold_at": DB.now_iso()},
                    )
                    counts["sold"] += 1
                    print(f"  [{i}/{len(alive)}] id={cid} SOLD ({new_count} fails)")
                else:
                    print(f"  [{i}/{len(alive)}] id={cid} fail #{new_count} "
                          f"({detail})")

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s.")
    print(f"  ok:         {counts['ok']}")
    print(f"  price_drop: {counts['price_drop']}")
    print(f"  fail:       {counts['fail']}")
    print(f"  → sold:     {counts['sold']} (after {DB.SOLD_FAIL_THRESHOLD} consecutive fails)")


if __name__ == "__main__":
    main()
