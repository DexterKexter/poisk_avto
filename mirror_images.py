"""mirror_images.py — download blocked-by-ORB images and re-host in
Supabase Storage so they load in Chrome.

Why:
  che168 serves photos from `*.autoimg.cn` without the
  Cross-Origin-Resource-Policy header, so Chrome's ORB blocks them when
  fetched cross-origin (Next.js <Image>, even goes through next/image
  optimiser). Other hosts (encar, guazi, autocango) ship CORP and work.

Strategy:
  1. Find every car whose `images` jsonb contains an autoimg.cn URL.
  2. For each such URL, download with the autohome Referer header.
  3. PUT into `car-images` bucket at `cars/{source}/{source_id}/{idx}.jpg`.
  4. Rewrite `cars.images` so the autoimg URL is replaced by the
     Supabase public URL. Re-running the script is a no-op for already
     mirrored rows.

Run:
  python mirror_images.py                 # all eligible rows
  python mirror_images.py --limit 20      # smoke-test
  python mirror_images.py --source che168 # restrict by source
Env: SUPABASE_URL, SUPABASE_KEY (service_role)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

BUCKET = "car-images"
BLOCKED_HOST_SUBSTRING = "autoimg.cn"  # the host pattern we mirror
PUBLIC_URL = f"{DB.SUPABASE_URL}/storage/v1/object/public/{BUCKET}"
DOWNLOAD_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Referer": "https://www.autohome.com.cn/",
    "Accept": "image/avif,image/webp,image/jpeg,image/png,*/*;q=0.8",
}

EXT_BY_MIME = {
    "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/png": "png", "image/webp": "webp", "image/avif": "avif",
}


def _storage_url(path: str) -> str:
    return f"{DB.SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"


def _storage_headers(content_type: str | None = None) -> dict:
    h = {
        "apikey": DB.SUPABASE_KEY,
        "Authorization": f"Bearer {DB.SUPABASE_KEY}",
        # x-upsert lets us idempotently re-PUT the same object
        "x-upsert": "true",
        "Cache-Control": "public, max-age=31536000, immutable",
    }
    if content_type:
        h["Content-Type"] = content_type
    return h


def mirror_one(orig_url: str, dst_path: str) -> str | None:
    """Download orig_url and PUT into Storage. Return public URL or None."""
    try:
        r = requests.get(orig_url, headers=DOWNLOAD_HEADERS, timeout=30,
                         allow_redirects=True)
    except Exception as e:
        print(f"  ! GET fail {orig_url}: {e}", flush=True)
        return None
    if r.status_code != 200:
        print(f"  ! GET {r.status_code} {orig_url}", flush=True)
        return None
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not ct.startswith("image/"):
        print(f"  ! not image ({ct}) {orig_url}", flush=True)
        return None
    ext = EXT_BY_MIME.get(ct, "jpg")
    # respect the requested extension in dst_path; default jpg
    final_path = dst_path.rsplit(".", 1)[0] + "." + ext

    put = requests.put(_storage_url(final_path),
                       data=r.content,
                       headers=_storage_headers(ct),
                       timeout=60)
    if put.status_code not in (200, 201):
        print(f"  ! PUT {put.status_code} {final_path}: {put.text[:200]}",
              flush=True)
        return None
    return f"{PUBLIC_URL}/{final_path}"


def needs_mirror(images: list[str]) -> bool:
    return any(BLOCKED_HOST_SUBSTRING in (u or "") for u in images)


def mirror_car(car: dict) -> tuple[int, int]:
    """Mirror all blocked URLs in a car's `images`. Updates DB. Returns
    (succeeded, total_blocked)."""
    source = car["source"]
    source_id = car["source_id"]
    images: list[str] = car.get("images") or []
    new_images: list[str] = list(images)
    succeeded = 0
    blocked_total = 0
    for idx, url in enumerate(images):
        if not url or BLOCKED_HOST_SUBSTRING not in url:
            continue
        blocked_total += 1
        # extension hint from URL
        ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower() or "jpg"
        if ext not in EXT_BY_MIME.values():
            ext = "jpg"
        dst = f"cars/{source}/{source_id}/{idx}.{ext}"
        mirrored = mirror_one(url, dst)
        if mirrored:
            new_images[idx] = mirrored
            succeeded += 1

    if succeeded:
        # write back only the rewritten array
        r = DB._pg_request(
            "PATCH", f"cars?source=eq.{source}&source_id=eq.{source_id}",
            json={"images": new_images, "updated_at": DB.now_iso()},
        )
        if r.status_code not in (200, 204):
            print(f"  ! DB update failed for {source}/{source_id}: "
                  f"{r.status_code} {r.text[:200]}", flush=True)
    return succeeded, blocked_total


def fetch_cars_to_mirror(limit: int | None, source_filter: str | None
                         ) -> list[dict]:
    """Pull candidate cars then filter client-side. `images` is jsonb so
    PostgREST `ilike` is not supported; sources that ship autoimg URLs
    are che168/autohome only, so we restrict by source first to keep the
    payload small."""
    select = "source,source_id,images"
    params = ["select=" + select, "order=updated_at.desc"]
    # autoimg.cn URLs come from che168 (and historically autohome). Cap
    # the query to those sources unless caller asked for something else.
    if source_filter:
        params.append(f"source=eq.{source_filter}")
    else:
        params.append("source=in.(che168,autohome)")
    # Pull in pages of 1000 (PostgREST default ceiling).
    page_size = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        page_params = params + [f"limit={page_size}", f"offset={offset}"]
        r = DB._pg_request("GET", "cars?" + "&".join(page_params))
        if r.status_code != 200:
            sys.exit(f"DB read fail: {r.status_code} {r.text[:200]}")
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    # Client-side filter for autoimg.cn presence
    out = [c for c in rows if needs_mirror(c.get("images") or [])]
    if limit:
        out = out[:limit]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--source", default=None,
                    help="restrict to a single source (e.g. che168)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres (Supabase) for storage mirror")

    cars = fetch_cars_to_mirror(args.limit, args.source)
    print(f"Cars needing mirror: {len(cars)}", flush=True)
    if not cars:
        return

    start = time.time()
    done_cars = ok_imgs = bad_imgs = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(mirror_car, c): c for c in cars}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                ok, total = fut.result()
            except Exception as e:
                print(f"  ! {c['source']}/{c['source_id']} crashed: {e}",
                      flush=True)
                ok, total = 0, 0
            done_cars += 1
            ok_imgs += ok
            bad_imgs += (total - ok)
            if done_cars % 10 == 0 or done_cars == len(cars):
                rate = done_cars / max(time.time() - start, 1e-3)
                eta = (len(cars) - done_cars) / max(rate, 1e-3)
                print(f"  [{done_cars}/{len(cars)}] cars done, "
                      f"imgs ok={ok_imgs} fail={bad_imgs}, "
                      f"{rate:.1f} cars/s, ETA {eta/60:.1f} min",
                      flush=True)

    elapsed = time.time() - start
    print(f"\nDone in {elapsed/60:.1f} min. "
          f"Cars: {done_cars}, images ok: {ok_imgs}, fail: {bad_imgs}",
          flush=True)


if __name__ == "__main__":
    main()
