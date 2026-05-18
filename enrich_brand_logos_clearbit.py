"""enrich_brand_logos_clearbit.py — fill `brands.logo_url` from the open
car-logos-dataset on GitHub (filippofilip95/car-logos-dataset).

Clearbit's logo API was deprecated by Hubspot in 2024; the GitHub
community dataset has 1000+ optimized PNG logos for car brands,
including major Chinese makes.

Strategy:
  1. Read brands where logo_url IS NULL.
  2. Build candidate slugs from brand name (lower, space→dash, etc).
  3. HEAD-check the raw GitHub URL; save first 200.
  4. PATCH brands.logo_url.

Usage: python enrich_brand_logos_clearbit.py
Env:   SUPABASE_URL, SUPABASE_KEY
"""

import re
import sys
import time

import requests

import db as DB

sys.stdout.reconfigure(line_buffering=True)

CDN = ("https://raw.githubusercontent.com/filippofilip95/"
       "car-logos-dataset/master/logos/optimized/{slug}.png")

# Manual slug overrides where dataset names diverge from canonical brand
SLUG_OVERRIDES = {
    "Lynk & Co": "lynk-co", "Lixiang": "li-auto", "Li Auto": "li-auto",
    "Mercedes-AMG": "mercedes-benz", "Mercedes-Maybach": "mercedes-benz",
    "Renault Korea": "renault", "KG Mobility": "ssangyong",
    "Citroen-DS": "citroen", "DS": "ds-automobiles",
    "GAC Trumpchi": "trumpchi", "ChangAn": "changan", "Changan": "changan",
    "Brilliance Auto": "brilliance",
    "Great Wall": "great-wall", "GWM Ora": "ora",
    "GWM Wey": "wey", "WEY": "wey",
    "Dongfeng Fengguang": "dongfeng", "Dongfeng Aeolus": "dongfeng",
    "BAIC BJEV": "baic", "BAIC ChangHe": "baic", "BAIC WeiWang": "baic",
    "INEOS Grenadier": "ineos", "Ineos": "ineos",
    "MG": "mg-motors", "Skoda": "skoda",
    "Mini": "mini", "MINI": "mini",
    "Smart": "smart",
    "ALPINA": "alpina",
    "Sehol": "jac",
    "Aion": "aion", "AION": "aion",
}


def candidate_slugs(name: str) -> list[str]:
    """Return ordered slug candidates for the GitHub dataset."""
    if name in SLUG_OVERRIDES:
        return [SLUG_OVERRIDES[name]]
    base = name.lower().strip()
    # Replace ampersand, dashes, dots
    base = base.replace("&", "and")
    base = re.sub(r"[^\w\s-]", "", base, flags=re.UNICODE)
    base = re.sub(r"\s+", "-", base).strip("-")
    # Generate variants
    cands = [base]
    if "-" in base:
        cands.append(base.replace("-", ""))
    # First word only ("BAIC ChangHe" → "baic")
    first = base.split("-")[0]
    if first and first not in cands:
        cands.append(first)
    return cands


_cache: dict[str, str | None] = {}


def find_logo(name: str) -> str | None:
    """Return first matching CDN URL or None."""
    for slug in candidate_slugs(name):
        if slug in _cache:
            url = _cache[slug]
        else:
            cdn = CDN.format(slug=slug)
            try:
                r = requests.head(cdn, timeout=8, allow_redirects=True)
                url = cdn if r.status_code == 200 else None
            except Exception:
                url = None
            _cache[slug] = url
        if url:
            return url
    return None


def main() -> None:
    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    r = DB._pg_request(
        "GET", "brands?logo_url=is.null&select=id,name,slug&limit=1000")
    if r.status_code != 200:
        sys.exit(f"DB read fail: {r.status_code}")
    brands = r.json()
    print(f"Brands without logo: {len(brands)}", flush=True)

    updated = miss = 0
    for i, b in enumerate(brands, 1):
        name = b["name"]
        url = find_logo(name)
        if url:
            upd = DB._pg_request(
                "PATCH", f"brands?id=eq.{b['id']}",
                json={"logo_url": url, "updated_at": DB.now_iso()})
            if upd.status_code in (200, 204):
                updated += 1
                if updated <= 10 or updated % 25 == 0:
                    print(f"  [{i}/{len(brands)}] {name:30} ✅", flush=True)
        else:
            miss += 1
            if miss <= 10 or miss % 30 == 0:
                print(f"  [{i}/{len(brands)}] {name:30} ❌ {candidate_slugs(name)}",
                      flush=True)

    print(f"\nDone.  Updated: {updated}  No-match: {miss}", flush=True)


if __name__ == "__main__":
    main()
