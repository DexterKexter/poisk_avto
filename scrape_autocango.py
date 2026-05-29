"""
Autocango.com card scraper — playwright + DOM extraction.

For each pending ID, opens https://www.autocango.com/sku/usedcar-<...>-<ID>
via headless Chromium, scrapes detail page fields (specs, options, photos,
both MSRP CNY and Export USD prices).

Usage:
    python scrape_autocango.py --limit 500

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
from typing import Any

import db as DB
import stealth

SOURCE = "autocango"
SOURCE_LANGUAGE = "en"
PRICE_CURRENCY = "USD"
KM_AGE_UNIT = "km"
BASE_URL = "https://www.autocango.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


# Drivetrain mapping
DRIVE_MAP = {
    "2WD": "FWD",
    "4WD": "AWD",
    "FWD": "FWD",
    "RWD": "RWD",
    "AWD": "AWD",
}

# Fuel → engine_type
FUEL_MAP = {
    "Petrol": "Petrol",
    "Gasoline": "Petrol",
    "Diesel": "Diesel",
    "BEV": "Electric",
    "Electric": "Electric",
    "Hybrid": "Hybrid",
    "PHEV": "PHEV",
    "EREV": "EREV",
    "LPG": "LPG",
    "CNG": "CNG",
}

TRANSMISSION_MAP = {
    "AT": "Automatic",
    "MT": "Manual",
    "CVT": "CVT",
    "DCT": "DCT",
    "AMT": "AMT",
    "Auto": "Automatic",
    "Automatic": "Automatic",
    "Manual": "Manual",
}


def tr(value: str, mapping: dict, default: str = "") -> str:
    if not value:
        return default
    return mapping.get(value.strip(), value.strip()) or default


def build_detail_url(meta: dict, source_id: str) -> str:
    """Reconstruct detail URL from saved metadata."""
    href = (meta or {}).get("href")
    if href:
        return href
    type_slug = (meta or {}).get("type_slug") or "usedcar"
    brand = (meta or {}).get("brand_slug") or "Unknown"
    model = (meta or {}).get("model_slug") or "Model"
    model = model.replace(" ", "-")
    return f"{BASE_URL}/sku/{type_slug}-{brand}-{model}-{source_id}"



_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")


def _html_to_text(html: str) -> str:
    """Strip HTML to a single-spaced text, mimicking innerText closely
    enough for the regex extractors below."""
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html,
                  flags=re.DOTALL | re.IGNORECASE)
    text = _TAG_RE.sub("\n", html)
    import html as _html_mod
    text = _html_mod.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract_detail_from_html(html: str) -> dict:
    """Python port of extract_detail_js() — runs the same regex extractors
    against the rendered HTML's text content. Returns the same dict shape
    so parse_detail_to_car() can stay unchanged."""
    text = _html_to_text(html)

    def get(pattern: str):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    title_m = re.search(r'<h1[^>]*>(.*?)</h1>', html,
                        re.DOTALL | re.IGNORECASE)
    if not title_m:
        title_m = re.search(
            r'<[^>]+class="[^"]*car-title[^"]*"[^>]*>(.*?)</', html,
            re.DOTALL | re.IGNORECASE,
        )
    title = _TAG_RE.sub("", title_m.group(1)).strip() if title_m else ""

    img_urls = re.findall(
        r'<img[^>]+src="(https?://[^"]+\.(?:jpe?g|png|webp)[^"]*)"',
        html, flags=re.IGNORECASE,
    )
    images, seen = [], set()
    for u in img_urls:
        clean = u.split("?")[0]
        if (clean.startswith("data:") or "rule-traffic-light" in clean
                or "logo" in clean.lower()):
            continue
        if clean in seen:
            continue
        seen.add(clean); images.append(clean)
        if len(images) >= 30:
            break

    export_usd = None
    m = re.search(r"\$\s*([\d,]+)\b", text)
    if m:
        try: export_usd = int(m.group(1).replace(",", ""))
        except ValueError: pass
    msrp_cny = None
    m = re.search(r"MSRP[^\d]*¥\s*([\d,]+)", text)
    if m:
        try: msrp_cny = int(m.group(1).replace(",", ""))
        except ValueError: pass

    description = ""
    ds = text.find("Description")
    de = text.find("Contact your AutoCango")
    if ds > 0 and de > ds:
        description = text[ds + 11:de].strip()
        description = re.sub(r"Availability Check：[^\n]+", "", description)
        description = description.replace("Condition：", "").strip()

    accessories = []
    acc_s = text.find("Accessories")
    acc_e = text.find("Relevant Car Specs")
    if acc_s > 0 and acc_e > acc_s:
        for line in text[acc_s + 11:acc_e].split("\n"):
            line = line.strip()
            if line and len(line) < 50:
                accessories.append(line)
            if len(accessories) >= 50:
                break

    city = None
    m = re.search(
        r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+"
        r"(?:Anhui|Beijing|Chongqing|Fujian|Gansu|Guangdong|Guangxi|"
        r"Guizhou|Hainan|Hebei|Heilongjiang|Henan|Hubei|Hunan|Jiangsu|"
        r"Jiangxi|Jilin|Liaoning|Ningxia|Qinghai|Shaanxi|Shandong|"
        r"Shanghai|Shanxi|Sichuan|Tianjin|Xinjiang|Tibet|Yunnan|Zhejiang)"
        r"\s+China\b",
        text,
    )
    if m:
        city = m.group(1)

    return {
        "title": title,
        "images": images,
        "export_usd": export_usd,
        "msrp_cny": msrp_cny,
        "description": description[:4000],
        "accessories": accessories[:50],
        "city": city,

        "ref_id":        get(r"Ref ID\s+([A-Z0-9]+)"),
        "steering":      get(r"Steering\s+(Left|Right)"),
        "model_code":    get(r"Model Code\s+(\S+)"),
        "body_type":     get(r"Body Type\s+([A-Za-z\/-]+)"),
        "color":         get(r"Exterior Color\s+([A-Za-z]+)"),
        "fuel":          get(r"Fuel\s+([A-Za-z]+)"),
        "transmission":  get(r"Transmission\s+([A-Za-z\-]+)"),
        "drivetrain":    get(r"Drivetrain\s+([A-Za-z0-9]+)"),

        "model_year":    get(r"Model Year\s+(\d{4})"),
        "mileage":       get(r"Mlg\(km\)\s+([\d,]+)"),
        "engine_cc":     get(r"Engine\(cc\)\s+(\d+|-)"),
        "seats":         get(r"Seats\s+(\d+)"),
        "weight_kg":     get(r"Weight\(kg\)\s+(\d+|-)"),
        "max_cap_kg":    get(r"Max\.Cap\(kg\)\s+(\d+|-)"),
        "battery_cap":   get(r"Batt\.Cap\.\(kWh\)\s+([\d.]+|-)"),
        "range_km":      get(r"Range\(km\)\s+(\d+|-)"),
        "motor_power":   get(r"Motor Power\(kW\)\s+(\d+|-)"),

        "reg_year_month": get(r"Reg\.\s*Year\s+(\d{4}-\d{1,2})"),
        "engine":        get(r"Engine\s+(\d+\.\d+[TL]\s+\d+HP\s+L\d+)"),
        "dimensions":    get(r"Dim\.\(mm\)\s+(\d+\*\d+\*\d+)"),
        "volume_m3":     get(r"M³\s+([\d.]+|-)"),
        "brand":         get(r"\bBrand\s+([A-Z][A-Za-z\- ]+?)\s+Series\b"),
        "series":        get(r"\bSeries\s+([A-Za-z0-9 .\-]+?)\s+(?:Model Year|Engine)"),
    }


def extract_detail_js() -> str:
    """JS that pulls everything we need from the detail page using strict regex."""
    return r"""() => {
        const text = (document.body.innerText || '').replace(/[ \t]+/g, ' ');

        // Strict regex extractors: capture just the value, not the next label
        const get = (re) => {
            const m = text.match(re);
            return m ? m[1].trim() : null;
        };

        // Title
        const title = (document.querySelector('h1, .car-title')?.innerText || '').trim();

        // Images — real photos only. Strip aliyun's x-image-process query
        // so we get full-resolution originals (not the 900px thumbnails).
        const images = Array.from(document.querySelectorAll('img'))
            .map(i => i.src)
            .filter(s => s && /\.(jpe?g|png|webp)/i.test(s)
                          && !s.startsWith('data:')
                          && !s.includes('rule-traffic-light')
                          && !s.includes('logo'))
            // Drop ?x-image-process=... — gives full-res original
            .map(s => s.split('?')[0]);

        // Prices: $X,XXX (export) and MSRP ¥X,XXX
        let export_usd = null, msrp_cny = null;
        const usdMatch = text.match(/\$\s*([\d,]+)\b/);
        if (usdMatch) export_usd = parseInt(usdMatch[1].replace(/,/g, ''), 10);
        const cnyMatch = text.match(/MSRP[^\d]*¥\s*([\d,]+)/);
        if (cnyMatch) msrp_cny = parseInt(cnyMatch[1].replace(/,/g, ''), 10);

        // Description: between "Description" and "Contact your AutoCango"
        let description = '';
        const descStart = text.indexOf('Description');
        const descEnd = text.indexOf('Contact your AutoCango');
        if (descStart > 0 && descEnd > descStart) {
            description = text.substring(descStart + 11, descEnd).trim()
                .replace(/Availability Check：[^\n]+/, '')
                .replace(/Condition：/g, '').trim();
        }

        // Accessories: between "Accessories" and "Relevant Car Specs"
        let accessories = [];
        const accStart = text.indexOf('Accessories');
        const accEnd = text.indexOf('Relevant Car Specs');
        if (accStart > 0 && accEnd > accStart) {
            accessories = text.substring(accStart + 11, accEnd)
                .split('\n').map(s => s.trim())
                .filter(s => s && s.length < 50);
        }

        // City: usually in breadcrumb or "City Province China" near top
        const cityMatch = text.match(/\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)\s+(?:Anhui|Beijing|Chongqing|Fujian|Gansu|Guangdong|Guangxi|Guizhou|Hainan|Hebei|Heilongjiang|Henan|Hubei|Hunan|Jiangsu|Jiangxi|Jilin|Liaoning|Ningxia|Qinghai|Shaanxi|Shandong|Shanghai|Shanxi|Sichuan|Tianjin|Xinjiang|Tibet|Yunnan|Zhejiang)\s+China\b/);
        const city = cityMatch ? cityMatch[1] : null;

        return {
            title,
            images: images.slice(0, 30),
            export_usd, msrp_cny,
            description: description.slice(0, 4000),
            accessories: accessories.slice(0, 50),
            city,

            // Single-word / single-token fields — strict regex stops at whitespace
            ref_id:        get(/Ref ID\s+([A-Z0-9]+)/),
            steering:      get(/Steering\s+(Left|Right)/),
            model_code:    get(/Model Code\s+(\S+)/),
            body_type:     get(/Body Type\s+([A-Za-z\/-]+)/),
            color:         get(/Exterior Color\s+([A-Za-z]+)/),
            fuel:          get(/Fuel\s+([A-Za-z]+)/),
            transmission:  get(/Transmission\s+([A-Za-z\-]+)/),
            drivetrain:    get(/Drivetrain\s+([A-Za-z0-9]+)/),

            // Numeric fields — strict digits only
            model_year:    get(/Model Year\s+(\d{4})/),
            mileage:       get(/Mlg\(km\)\s+([\d,]+)/),
            engine_cc:     get(/Engine\(cc\)\s+(\d+|-)/),
            seats:         get(/Seats\s+(\d+)/),
            doors:         get(/Doors\s+(\d+)/),
            weight_kg:     get(/Weight\(kg\)\s+(\d+|-)/),
            max_cap_kg:    get(/Max\.Cap\(kg\)\s+(\d+|-)/),
            battery_cap:   get(/Batt\.Cap\.\(kWh\)\s+([\d.]+|-)/),
            range_km:      get(/Range\(km\)\s+(\d+|-)/),
            motor_power:   get(/Motor Power\(kW\)\s+(\d+|-)/),

            // Composite fields needing more lenient parse
            // "Reg. Year 2019-06" — capture YYYY-MM
            reg_year_month: get(/Reg\.\s*Year\s+(\d{4}-\d{1,2})/),
            // "Engine 2.0T 201HP L4" — keep as-is
            engine:        get(/Engine\s+(\d+\.\d+[TL]\s+\d+HP\s+L\d+)/),
            // "Dim.(mm) 4810*1910*1770"
            dimensions:    get(/Dim\.\(mm\)\s+(\d+\*\d+\*\d+)/),
            // "M³ 16.27"
            volume_m3:     get(/M³\s+([\d.]+|-)/),
            // "Brand GAC Trumpchi" — multi-word until "Series"
            brand:         get(/\bBrand\s+([A-Z][A-Za-z\- ]+?)\s+Series\b/),
            // "Series GS8" — single token usually
            series:        get(/\bSeries\s+([A-Za-z0-9 .\-]+?)\s+(?:Model Year|Engine)/),
        };
    }"""


def safe_int(value) -> int | None:
    if not value or value == "-":
        return None
    try:
        return int(re.sub(r'[^\d]', '', str(value)))
    except Exception:
        return None


def parse_detail_to_car(source_id: str, detail: dict, meta: dict) -> dict:
    """Map scraped detail page fields to cars schema."""
    ts = DB.now_iso()

    # Parse dimensions
    dim_m = re.match(r'(\d+)\*(\d+)\*(\d+)', detail.get("dimensions", "") or "")
    length = int(dim_m.group(1)) if dim_m else None
    width = int(dim_m.group(2)) if dim_m else None
    height = int(dim_m.group(3)) if dim_m else None

    # Parse reg date: "2019-06"
    reg_date = None
    rym = detail.get("reg_year_month") or ""
    rm = re.match(r'(\d{4})-(\d{1,2})', rym)
    if rm:
        reg_date = f"{rm.group(1)}-{int(rm.group(2)):02d}-01"

    # Engine — parse displacement (L) and horsepower
    eng = detail.get("engine", "") or ""
    disp_match = re.search(r'(\d+\.\d+)\s*[TL]', eng)
    displacement_l = float(disp_match.group(1)) if disp_match else None
    hp_match = re.search(r'(\d+)\s*HP', eng)
    horsepower = int(hp_match.group(1)) if hp_match else None

    # Year — prefer model_year if present
    year = safe_int(detail.get("model_year"))
    if not year and reg_date:
        year = int(reg_date[:4])

    # Brand/model strings
    brand = (detail.get("brand") or meta.get("brand_slug") or "").strip()
    series = (detail.get("series") or "").strip()
    if not series and meta.get("model_slug"):
        series = meta["model_slug"]

    title = detail.get("title") or ""
    if not title:
        title = f"{brand} {series}".strip()

    # Price: detail's export_usd is per-car USD export price
    price_usd = detail.get("export_usd") or meta.get("price_usd")
    msrp_cny = detail.get("msrp_cny")

    return {
        "source": SOURCE,
        "source_id": str(source_id),
        "url": build_detail_url(meta, source_id),
        "title": title,

        "mark_original": brand,
        "mark": brand,
        "series_original": series,
        "model": f"{series}".strip(),
        "complectation": "",
        "year": year,

        "price_original": price_usd,
        "price_currency": PRICE_CURRENCY if price_usd else None,
        "new_price_original": msrp_cny,
        "new_price_currency": "CNY" if msrp_cny else None,

        "km_age_unit": KM_AGE_UNIT,
        "km_age": safe_int(detail.get("mileage")),

        "color_original": detail.get("color", "") or "",
        "color": detail.get("color", "") or "",

        "body_type": detail.get("body_type", "") or "",
        "engine_type": tr(detail.get("fuel", ""), FUEL_MAP),
        "fuel_original": detail.get("fuel", "") or "",
        "transmission_original": detail.get("transmission", "") or "",
        "transmission_type": tr(detail.get("transmission", ""), TRANSMISSION_MAP),
        "drive_original": detail.get("drivetrain", "") or "",
        "drive_type": tr(detail.get("drivetrain", ""), DRIVE_MAP),

        "displacement": displacement_l,
        "horse_power": horsepower,

        "wheelbase_mm": None,

        "city_original": detail.get("city", "") or "",
        "city": detail.get("city", "") or "",
        "reg_date": reg_date,

        "description": detail.get("description", "") or "",

        "images": detail.get("images", []),
        "image_count": len(detail.get("images", []) or []),

        "seller_type": "Exporter",
        "shop_name": "AutoCango",
        "shop_short_name": "",
        "shop_address": "",
        "shop_id": "",

        "vin": None,  # autocango doesn't expose VIN on listing

        "published_at": None,  # not exposed
        "listing_updated_at": None,

        "source_data": {
            "ref_id": detail.get("ref_id"),
            "steering": detail.get("steering"),
            "model_code": detail.get("model_code"),
            "engine_cc": safe_int(detail.get("engine_cc")),
            "battery_capacity_kwh": detail.get("battery_cap"),
            "range_km": detail.get("range_km"),
            "seats": safe_int(detail.get("seats")),
            "volume_m3": detail.get("volume_m3"),
            "weight_kg": safe_int(detail.get("weight_kg")),
            "max_cap_kg": safe_int(detail.get("max_cap_kg")),
            "accessories": detail.get("accessories", []),
            "compliant_180day": meta.get("compliant_180day"),
            "type_slug": meta.get("type_slug"),
            "msrp_cny": msrp_cny,
        },

        "first_seen": ts,
        "last_seen": ts,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    
    print(f"Backend: {DB.backend_name()}")
    print(f"Source: {SOURCE}")

    # Open a sync_log row so the admin dashboard can show this run.
    run_id = DB.sync_log_start(SOURCE, os.environ.get("GITHUB_RUN_URL"))
    ok = fail = 0
    error_message: str | None = None
    try:
        existing = DB.count_cars(SOURCE)
        print(f"cars[{SOURCE}] already: {existing}")

        ids = DB.get_pending_ids(SOURCE, args.limit)
        print(f"Loaded {len(ids)} pending IDs\n")
        if not ids:
            print("Nothing to scrape. Run collect_autocango.py first.")
            return

        # Fetch metadata for each ID so we can reconstruct URLs
        metas: dict[str, dict] = {}
        if DB.USE_POSTGRES:
            for chunk_start in range(0, len(ids), 100):
                chunk = ids[chunk_start:chunk_start + 100]
                ids_in = ",".join(f'"{i}"' for i in chunk)
                r = DB._pg_request(
                    "GET",
                    f"pending_ids?source=eq.{SOURCE}"
                    f"&source_id=in.({ids_in})"
                    f"&select=source_id,metadata"
                )
                if r.status_code == 200:
                    for row in r.json():
                        metas[row["source_id"]] = row.get("metadata") or {}

        started = time.time()

        for i, cid in enumerate(ids, 1):
            meta = metas.get(cid, {})
            url = build_detail_url(meta, cid)
            # Two-tier stealth: Camoufox → Oxylabs CN-geo. wait_selector
            # holds the browser open until the detail content lands so we
            # don't parse half-rendered HTML.
            html = stealth.fetch_protected_html(
                url, wait_selector="h1, .car-title",
            )
            if not html or stealth.looks_like_challenge(html):
                fail += 1
                DB.mark_failed(SOURCE, cid)
                print(f"  [{i}/{len(ids)}] {cid} FETCH/CHALLENGE FAIL")
                continue
            try:
                detail = extract_detail_from_html(html)
            except Exception as e:
                fail += 1
                DB.mark_failed(SOURCE, cid)
                print(f"  [{i}/{len(ids)}] {cid} PARSE FAIL: {e}")
                continue

            rec = parse_detail_to_car(cid, detail, meta)
            if DB.upsert_car(rec):
                ok += 1
                print(f"  [{i}/{len(ids)}] {cid} OK {rec['mark']} {rec['model']} "
                      f"{rec['year']} ${rec['price_original']} {rec['km_age']}km")
            else:
                fail += 1
                DB.mark_failed(SOURCE, cid)
                print(f"  [{i}/{len(ids)}] {cid} DB FAIL")

        elapsed = int(time.time() - started)
        print(f"\nDone in {elapsed}s. OK: {ok}, FAIL: {fail}")
        print(f"Total cars[{SOURCE}]: {DB.count_cars(SOURCE)}")
    except Exception as e:
        error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        raise
    finally:
        DB.sync_log_finish(run_id, added=ok, failed=fail, error_message=error_message)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
