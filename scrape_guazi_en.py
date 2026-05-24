"""en.guazi.com detail-page scraper — Playwright.

Opens each /products/{slug}.html page, extracts ALL available fields:
brand/model/trim (English), price (USD), grade, photos, specs,
inspection summary, accident history.

No chinese_maps. No LLM. No image mirror.

Env: SUPABASE_URL, SUPABASE_KEY
"""

import argparse
import json
import os
import re
import sys
import time
import traceback

import db as DB

sys.stdout.reconfigure(line_buffering=True)

SOURCE = "guazi"
BASE_URL = "https://en.guazi.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

FUEL_TO_ENGINE = {
    "petrol": "Petrol", "gasoline": "Petrol", "gas": "Petrol",
    "diesel": "Diesel", "electric": "Electric", "bev": "Electric",
    "hybrid": "Hybrid", "plug-in": "PHEV", "phev": "PHEV",
    "range extender": "EREV", "erev": "EREV", "extended range": "EREV",
    "hydrogen": "Hydrogen", "new energy": "Electric",
}


def fuel_to_engine_type(fuel: str | None) -> str | None:
    if not fuel:
        return None
    fl = fuel.lower().strip()
    for key, val in FUEL_TO_ENGINE.items():
        if key in fl:
            return val
    return None


def extract_detail(page) -> dict:
    """Extract everything from a rendered en.guazi.com product page."""
    return page.evaluate(r"""() => {
        const r = {};
        const text = document.body.innerText || '';

        r.title = document.title || '';

        // Photos
        r.photos = Array.from(document.querySelectorAll('img[src]'))
            .map(i => i.src)
            .filter(s => s.includes('guazi') && !s.includes('.svg') && !s.includes('icon')
                && !s.includes('favicon') && (s.includes('.jpg') || s.includes('.webp')
                || s.includes('.png') || s.includes('qnbdp') || s.includes('ovp/product')));
        r.photos = [...new Set(r.photos)];

        // Price
        const pm = text.match(/(?:Starting|FOB|Current|Buy|Price)\s*(?:Price|Now)?\s*:?\s*\$\s*([\d,]+)/i)
            || text.match(/\$\s*([\d,]+)/);
        if (pm) r.priceUsd = parseInt(pm[1].replace(/,/g, ''), 10);

        // Grade
        const gm = text.match(/Grade\s*:?\s*([A-F][+-]?)/i);
        if (gm) r.grade = gm[1].toUpperCase();

        // Fields from body text
        for (const [key, re] of [
            ['year', /(?:Year|Model Year)\s*[:：]?\s*(\d{4})/i],
            ['mileageKm', /(?:Mileage|Odometer)\s*[:：]?\s*([\d,]+)\s*km/i],
            ['color', /(?:Exterior Color|Color|Colour)\s*[:：]?\s*([A-Za-z\s-]+?)(?:\n|,|$)/i],
            ['interiorColor', /(?:Interior)\s*[:：]?\s*([A-Za-z\s-]+?)(?:\n|,|$)/i],
            ['transmission', /(?:Transmission|Gearbox)\s*[:：]?\s*([A-Za-z0-9\s-]+?)(?:\n|,|$)/i],
            ['fuel', /(?:Fuel|Energy|Power)\s*[:：]?\s*([A-Za-z\s/+-]+?)(?:\n|,|$)/i],
            ['drive', /(?:Drive|Drivetrain)\s*[:：]?\s*(AWD|FWD|RWD|4WD|2WD|[A-Za-z\s-]+?)(?:\n|,|$)/i],
            ['displacement', /(?:Displacement|Engine)\s*[:：]?\s*(\d+\.?\d*)\s*[LTl]/i],
            ['horsePower', /(\d+)\s*(?:HP|hp|PS|kW)/i],
            ['steering', /(?:Steering|Wheel)\s*[:：]?\s*(LHD|RHD|Left|Right)/i],
            ['bodyType', /(?:Body|Type)\s*[:：]?\s*(Sedan|SUV|Hatchback|Coupe|Convertible|Van|MPV|Wagon|Pickup)/i],
            ['seats', /(\d)\s*(?:seat|Seat)/],
            ['keys', /(\d)\s*(?:key|Key)/],
            ['vin', /(?:VIN)\s*[:：]?\s*([A-HJ-NPR-Z0-9]{17})/i],
        ]) {
            const m = text.match(re);
            if (m) r[key] = key === 'displacement' ? parseFloat(m[1])
                : key === 'mileageKm' ? parseInt(m[1].replace(/,/g, ''), 10)
                : /^\d+$/.test(m[1]) ? parseInt(m[1], 10) : m[1].trim();
        }

        // Steering normalization
        if (r.steering) {
            r.steering = (r.steering.includes('L') || r.steering.includes('Left')) ? 'LHD' : 'RHD';
        }

        // Accident
        r.accidentFree = /no accident|accident.?free|0 accident/i.test(text);
        if (/has accident|accident history|previous accident/i.test(text)) r.accidentFree = false;

        // Labels
        r.labels = Array.from(document.querySelectorAll('[class*="tag"], [class*="label"], [class*="badge"]'))
            .map(e => (e.innerText || '').trim())
            .filter(t => t && t.length > 1 && t.length < 50 && !t.includes('\n'));
        r.labels = [...new Set(r.labels)];

        // Specs table
        const specs = {};
        document.querySelectorAll('[class*="spec"], [class*="detail"], [class*="param"]').forEach(el => {
            el.querySelectorAll('div, span, p, li').forEach(item => {
                const t = (item.innerText || '').trim();
                const kv = t.match(/^(.{2,30})\s*[:：]\s*(.+)$/);
                if (kv) specs[kv[1].trim()] = kv[2].trim();
            });
        });
        r.specs = specs;

        // Description
        const descEl = document.querySelector('[class*="description"], [class*="remark"]');
        if (descEl) r.description = (descEl.innerText || '').substring(0, 2000);

        // Seller
        const sm = text.match(/(?:Dealer|Seller|Sold by)\s*[:：]?\s*([^\n]{3,60})/i);
        if (sm) r.sellerName = sm[1].trim();

        r.bodyLen = text.length;
        return r;
    }""")


def split_brand_model(brand_model: str) -> tuple[str, str]:
    """Split 'BMW 3 Series' → ('BMW', '3 Series')."""
    if not brand_model:
        return "", ""
    # Known two-word brands
    for prefix in ["Land Rover", "Aston Martin", "Alfa Romeo", "Rolls-Royce",
                    "Mercedes-Benz", "Lynk & Co", "Li Auto", "Great Wall",
                    "GAC Trumpchi", "Geely Galaxy"]:
        if brand_model.lower().startswith(prefix.lower()):
            return prefix, brand_model[len(prefix):].strip()
    parts = brand_model.split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def scrape_one(ctx, source_id: str, meta: dict) -> dict | None:
    href = meta.get("href", "")
    url = f"{BASE_URL}{href}" if href.startswith("/") else (href or f"{BASE_URL}/products/{source_id}.html")

    page = ctx.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(4000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        d = extract_detail(page)
    except Exception as e:
        print(f"  ! {source_id} error: {e}", flush=True)
        return None
    finally:
        page.close()

    if not d or d.get("bodyLen", 0) < 500:
        return None

    # Merge listing-page meta with detail-page data
    brand_model = meta.get("brand_model", "")
    mark, model = split_brand_model(brand_model)
    trim = meta.get("trim", "")
    grade = d.get("grade") or meta.get("grade")
    year = d.get("year") or meta.get("year")
    mileage = d.get("mileageKm") or meta.get("mileage_km")
    color = d.get("color") or meta.get("color")
    displacement = d.get("displacement") or meta.get("displacement")
    drive = d.get("drive") or meta.get("drive")
    transmission = d.get("transmission") or meta.get("transmission")
    seats = d.get("seats") or meta.get("seats")

    engine_type = fuel_to_engine_type(d.get("fuel"))
    # "New Energy" in model name usually means PHEV or Electric
    if not engine_type and "new energy" in (model or "").lower():
        engine_type = "PHEV"

    inspection_data = {}
    if grade:
        inspection_data["grade"] = grade
    if d.get("specs"):
        inspection_data["specs"] = d["specs"]

    photos = d.get("photos") or []
    if meta.get("photo") and meta["photo"] not in photos:
        photos.insert(0, meta["photo"])

    rec = {
        "source": SOURCE,
        "source_id": source_id,
        "url": url,
        "title": d.get("title") or f"Used {mark} {model} {year}",
        "mark": mark,
        "model": model,
        "complectation": trim,
        "year": year,
        "price_original": d.get("priceUsd") or meta.get("price_usd"),
        "price_currency": "USD",
        "km_age_original": mileage,
        "km_age_unit": "km",
        "km_age": mileage,
        "color": color,
        "interior_color_original": d.get("interiorColor"),
        "body_type": d.get("bodyType"),
        "engine_type": engine_type,
        "fuel_original": d.get("fuel"),
        "transmission_type": transmission,
        "drive_type": drive,
        "displacement": displacement,
        "horse_power": d.get("horsePower"),
        "steering": d.get("steering"),
        "keys_count": d.get("keys"),
        "vin": d.get("vin"),
        "description": d.get("description"),
        "images": photos,
        "image_count": len(photos),
        "inspection_score": {"A": 9.0, "B": 7.0, "C": 5.0, "D": 3.0}.get(grade),
        "accident_free": d.get("accidentFree"),
        "inspection_data": inspection_data if inspection_data else None,
        "labels": d.get("labels") if d.get("labels") else None,
        "export_ready": True,
        "seller_type": "dealer",
        "source_language": "en",
    }
    return {k: v for k, v in rec.items() if v is not None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    pending = DB.get_pending_ids(SOURCE, args.limit)
    print(f"Pending guazi-en detail pages: {len(pending)}", flush=True)
    if not pending:
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 3000}, locale="en-US")
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        def get_meta(sid: str) -> dict:
            r = DB._pg_request(
                "GET", f"pending_ids?source=eq.{SOURCE}&source_id=eq.{sid}&select=meta")
            if r.status_code == 200:
                rows = r.json()
                if rows and rows[0].get("meta"):
                    m = rows[0]["meta"]
                    return json.loads(m) if isinstance(m, str) else m
            return {}

        start = time.time()
        ok = fail = 0
        for i, source_id in enumerate(pending, 1):
            meta = get_meta(source_id)
            rec = scrape_one(ctx, source_id, meta)
            if rec:
                if DB.upsert_car(rec):
                    ok += 1
                else:
                    fail += 1
            else:
                DB.mark_failed(SOURCE, source_id)
                fail += 1

            if i % 5 == 0 or i == len(pending):
                rate = i / max(time.time() - start, 1e-3)
                eta = (len(pending) - i) / max(rate, 1e-3)
                print(f"  [{i}/{len(pending)}] ok={ok} fail={fail} "
                      f"{rate:.2f}/s ETA {eta/60:.1f}m", flush=True)

        browser.close()

    print(f"\nDone in {(time.time()-start)/60:.1f}m. ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
