"""
kolesa.kz brand/model catalog collector.

Harvests the full kolesa.kz car catalog into dedicated reference tables
(kolesa_brands / kolesa_models). This is NOT an import source — it is the
Kazakhstan price-reference catalog used to match our imported cars against
local kolesa.kz listings (see the kolesa-match edge function).

Two data sources:
  - Brands: GET /a/ajax-get-marks/?category_id=2  → JSON {id,name,nameInRussian,
            synonyms,rank}. ~224 marks in one request.
  - Models: GET /cars/{slug}/  → HTML containing /cars/{slug}/{model}/ SEO links.
            kolesa's models JSON endpoint rejects the marks-API ids, so we parse
            the brand page instead. Model display names are derived from slugs.

kolesa rate-limits aggressively (HTTP 503) so requests are paced + retried.

Usage:
    python scrape_kolesa_catalog.py [--limit-brands N] [--delay 2.5]
                                    [--only toyota,bmw] [--skip-models]

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import os
import re
import sys
import time

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

CATEGORY_ID = 2  # cars
MARKS_API = f"https://kolesa.kz/a/ajax-get-marks/?category_id={CATEGORY_ID}"
BRAND_PAGE = "https://kolesa.kz/cars/{slug}/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://kolesa.kz/cars/",
}
# kolesa's /a/ajax-* JSON endpoints 404 without this header; the regular
# /cars/{slug}/ HTML pages, however, return a stripped response when it's set.
XHR_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest"}

# kolesa serves Cyrillic-named (Soviet) brands under transliterated slugs that
# slugify() can't derive. "ВАЗ (Lada)" lives at /cars/vaz/ on kolesa.
CYRILLIC_SLUGS = {
    "ВАЗ (Lada)": "vaz", "ГАЗ": "gaz", "ЗАЗ": "zaz", "ЗИЛ": "zil",
    "ИЖ": "izh", "ЛуАЗ": "luaz", "Москвич": "moskvich", "ТагАЗ": "tagaz",
    "УАЗ": "uaz", "СМЗ": "smz", "ЕрАЗ": "eraz", "РАФ": "raf", "ВИС": "vis",
    "Ретро-автомобили": "retro-avtomobili",
}


# Brands whose kolesa slug isn't derivable from the name by rule.
SLUG_OVERRIDES = {
    "Renault Samsung": "samsung",
}


def slugify(name: str, split_camel: bool = True) -> str:
    s = name.strip()
    if split_camel:  # DongFeng -> Dong-Feng -> dong-feng (kolesa convention)
        s = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", s)
    s = s.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def brand_slug_candidates(name: str) -> list[str]:
    """Ordered kolesa URL-slug candidates to try for a brand name."""
    cands: list[str] = []
    for c in (CYRILLIC_SLUGS.get(name), SLUG_OVERRIDES.get(name),
              slugify(name, split_camel=True),    # dong-feng
              slugify(name, split_camel=False),   # dongfeng
              re.sub(r"[^a-z0-9]+", "", name.lower())):  # dongfeng (no seps)
        if c and c not in cands:
            cands.append(c)
    return cands


def prettify_model(slug: str) -> str:
    """Derive a display name from a kolesa model slug."""
    return slug.replace("-", " ").title()


def fetch(url: str, *, as_json: bool, retries: int = 3,
          delay: float = 2.5, timeout: int = 15) -> object | None:
    """GET with polite pacing + 503 retry/backoff.

    JSON (ajax) endpoints need the XHR header; HTML pages must not have it.
    Short timeout + capped retries so a rate-limited/hung brand fails fast
    instead of blackholing the run (we converge via resumable re-runs).
    """
    headers = XHR_HEADERS if as_json else HEADERS
    last_code = 0
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            last_code = r.status_code
            if r.status_code == 200:
                return (r.json() if as_json else r.text), 200
            if r.status_code in (403, 429, 503):
                wait = min(delay * (2 ** attempt), 20)
                print(f"    {r.status_code} on {url[:60]} — backoff {wait:.0f}s")
                time.sleep(wait)
                continue
            return None, r.status_code  # 404 etc — permanent, don't retry
        except Exception as e:
            print(f"    error on {url[:60]}: {e}")
            last_code = -1
            time.sleep(min(delay * (2 ** attempt), 20))
    return None, last_code


def fetch_done_brand_ids() -> set[int]:
    """Brand ids already fetched (model_count IS NOT NULL). NULL = not yet
    fetched or failed → eligible for a resume pass."""
    done: set[int] = set()
    r = DB._pg_request("GET", "kolesa_brands?select=id&model_count=not.is.null")
    if r.status_code == 200:
        done = {row["id"] for row in r.json()}
    return done


def fetch_brands() -> list[dict]:
    data, _ = fetch(MARKS_API, as_json=True)
    if not isinstance(data, dict) or data.get("status") != "success":
        return []
    return data.get("data") or []


def crawl_models(brand: dict, delay: float) -> tuple[int, str]:
    """Try slug candidates until one loads. Returns (model_count, status).

    status: 'ok' (a page loaded, models saved — count may be 0),
            'notfound' (every candidate 404'd — genuinely no page → count 0),
            'blocked' (rate-limited/error — leave NULL, retry next pass).
    """
    any_404 = False
    for slug in brand_slug_candidates(brand["name"]):
        html, code = fetch(BRAND_PAGE.format(slug=slug), as_json=False, delay=delay)
        if code == 200 and html is not None:
            n = upsert_models(brand["id"], extract_models(html, slug))
            return n, "ok"
        if code == 404:
            any_404 = True
            continue
        # 503/429/timeout/other → rate-limited; stop trying candidates
        return 0, "blocked"
    return 0, ("notfound" if any_404 else "blocked")


# City / service segments that share the /cars/{brand}/{x} shape but aren't models.
NOISE_SEGMENTS = {
    "new", "page", "all", "avtokredit",
    "aktau", "aktobe", "almaty", "astana", "atyrau", "janaozen", "jezkazgan",
    "karaganda", "kokshetau", "kostanai", "kyzylorda", "pavlodar",
    "petropavlovsk", "semei", "shymkent", "taldykorgan", "taraz", "turkestan",
    "uralsk", "ust-kamenogorsk", "kentau", "ekibastuz", "rudny", "temirtau",
}


def extract_models(html: str, slug: str) -> list[str]:
    """Pull distinct model slugs from /cars/{slug}/{model} links in HTML.

    kolesa renders these without a trailing slash, terminated by a quote,
    slash, query or backslash, so we match up to the next boundary char.
    """
    text = html.replace("\\/", "/")
    found = re.findall(
        rf'/cars/{re.escape(slug)}/([a-z0-9][a-z0-9_-]*?)(?=["/?\\\s])', text)
    return sorted({m for m in found if m not in NOISE_SEGMENTS})


def upsert_brand(brand: dict, slug: str) -> bool:
    rec = {
        "id": brand["id"],
        "name": brand.get("name") or brand.get("nameInRussian") or slug,
        "name_ru": brand.get("nameInRussian") or None,
        "synonyms": brand.get("synonyms") or None,
        "slug": slug,
        "rank": brand.get("rank"),
        "updated_at": DB.now_iso(),
    }
    r = DB._pg_request("POST", "kolesa_brands?on_conflict=id", json=rec)
    return r.status_code in (200, 201, 204)


def upsert_models(brand_id: int, model_slugs: list[str]) -> int:
    if not model_slugs:
        return 0
    rows = [{
        "brand_id": brand_id,
        "slug": s,
        "name": prettify_model(s),
        "updated_at": DB.now_iso(),
    } for s in model_slugs]
    r = DB._pg_request(
        "POST", "kolesa_models?on_conflict=brand_id,slug", json=rows)
    return len(rows) if r.status_code in (200, 201, 204) else 0


def set_model_count(brand_id: int, count: int) -> None:
    DB._pg_request("PATCH", f"kolesa_brands?id=eq.{brand_id}",
                   json={"model_count": count})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-brands", type=int, default=0,
                    help="Only process the first N brands (0 = all)")
    ap.add_argument("--only", type=str, default="",
                    help="Comma-separated brand slugs to restrict to")
    ap.add_argument("--delay", type=float, default=2.5,
                    help="Base delay between brand-page requests (seconds)")
    ap.add_argument("--skip-models", action="store_true",
                    help="Only refresh the brand list, skip model pages")
    ap.add_argument("--resume", action="store_true",
                    help="Skip brands that already have model_count>0 (for "
                         "convergent multi-pass runs against kolesa rate limits)")
    ap.add_argument("--max-consecutive-fails", type=int, default=8,
                    help="Stop after this many back-to-back page failures "
                         "(rate-limit wall) so a resume run can continue")
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres (SUPABASE_URL + SUPABASE_KEY)")

    print("Fetching kolesa brand list…")
    brands = fetch_brands()
    if not brands:
        sys.exit("Could not fetch brands from kolesa")
    print(f"  {len(brands)} brands")

    only = {s.strip() for s in args.only.split(",") if s.strip()}

    # Phase 1: upsert ALL brands first (cheap, marks API only) so the brand
    # table is always complete regardless of model-crawl rate limits.
    brands_saved = 0
    for brand in brands:
        if only and slugify(brand["name"]) not in only:
            continue
        if upsert_brand(brand, brand_slug_candidates(brand["name"])[0]):
            brands_saved += 1
    print(f"  phase 1: {brands_saved} brands upserted")

    if args.skip_models:
        print("Done (skip-models).")
        return

    # Phase 2: crawl models for brands not yet fetched (model_count IS NULL).
    done_ids = fetch_done_brand_ids() if args.resume else set()
    if args.resume:
        print(f"  resume: {len(done_ids)} brands already fetched — skipping them")

    models_total = processed = skipped = consec_block = 0
    started = time.time()

    for brand in brands:
        if only and slugify(brand["name"]) not in only:
            continue
        if args.resume and brand["id"] in done_ids:
            skipped += 1
            continue
        if args.limit_brands and processed >= args.limit_brands:
            break
        processed += 1

        n, status = crawl_models(brand, args.delay)
        if status == "blocked":
            consec_block += 1
            print(f"  [{brand['name']}] blocked (rate-limit) "
                  f"{consec_block}/{args.max_consecutive_fails} — left for retry")
            if consec_block >= args.max_consecutive_fails:
                print("  rate-limit wall — stopping so a --resume re-run continues")
                break
            time.sleep(args.delay)
            continue
        consec_block = 0

        # ok or notfound → a definitive answer; record count (0 allowed).
        set_model_count(brand["id"], n)
        models_total += n
        elapsed = int(time.time() - started)
        print(f"  [{brand['name']}] -> {n} models [{status}] "
              f"({processed} done, total {models_total}, {elapsed}s)")
        time.sleep(args.delay)

    elapsed = int(time.time() - started)
    print(f"\nDone in {elapsed}s. Models: {models_total} across {processed} "
          f"brands (skipped {skipped} already-done)")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
