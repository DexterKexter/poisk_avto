"""en.guazi.com detail-page scraper — Playwright-rendered.

For each pending guazi listing, opens the English detail page and extracts
ALL available fields:
  - Brand, model, trim (already English)
  - Price in USD (FOB export price)
  - Year, mileage, color, transmission, fuel, drive type, displacement, HP
  - Steering side (LHD/RHD), keys count
  - Inspection report: overall score, exterior/interior scores, accident
    history, paint readings, tire condition
  - Labels (Inspected, Ready to Ship, Hot Deal, ...)
  - Photos (guazistatic-global CDN — no Chrome ORB issues)
  - Seller/dealer info

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


def extract_detail(page) -> dict:
    """Extract all fields from a rendered en.guazi.com detail page."""
    return page.evaluate(r"""() => {
        const r = {};
        const text = document.body.innerText || '';
        const html = document.body.innerHTML || '';

        r.title = document.title || '';
        const ogTitle = document.querySelector('meta[property="og:title"]');
        if (ogTitle) r.ogTitle = ogTitle.content;

        // Photos
        const photos = [];
        document.querySelectorAll('img[src*="guazi"], img[src*="oversea"], img[src*="qnbdp"]').forEach(img => {
            const src = img.src || img.dataset?.src || '';
            if (src && !src.includes('favicon') && !src.includes('.svg') &&
                !src.includes('icon') && !photos.includes(src) &&
                (src.includes('.jpg') || src.includes('.png') || src.includes('.webp') ||
                 src.includes('qnbdp') || src.includes('ovp/product'))) {
                photos.push(src);
            }
        });
        r.photos = photos;

        // Price (USD)
        const priceMatch = text.match(/(?:FOB|Price|Starting)\s*(?:Price)?\s*:?\s*\$\s*([\d,]+)/i)
            || text.match(/\$\s*([\d,]+(?:\.\d{2})?)/);
        if (priceMatch) r.priceUsd = parseInt(priceMatch[1].replace(/,/g, ''), 10);

        // Specs (key-value pairs from spec tables/lists)
        const specs = {};
        document.querySelectorAll('tr, [class*="spec"], [class*="info"], [class*="param"], [class*="detail"]').forEach(el => {
            const cells = el.querySelectorAll('td, th, span, div, dt, dd, p');
            for (let i = 0; i < cells.length - 1; i += 2) {
                const key = (cells[i].innerText || '').trim().replace(/:$/, '');
                const val = (cells[i + 1].innerText || '').trim();
                if (key && val && key.length < 40 && val.length < 200) specs[key] = val;
            }
        });
        r.specs = specs;

        // Year
        const yearMatch = text.match(/(?:Year|Model Year|Registration)\s*:?\s*(\d{4})/i)
            || r.title?.match(/(\d{4})/);
        if (yearMatch) r.year = parseInt(yearMatch[1], 10);

        // Mileage
        const mileMatch = text.match(/(?:Mileage|Odometer|KM)\s*:?\s*([\d,]+)\s*(?:km|mi)/i);
        if (mileMatch) r.mileageKm = parseInt(mileMatch[1].replace(/,/g, ''), 10);

        // Color
        const colorMatch = text.match(/(?:Exterior Color|Color|Colour)\s*:?\s*([A-Za-z\s]+?)(?:\n|,|$)/i);
        if (colorMatch) r.color = colorMatch[1].trim();

        // Interior
        const intMatch = text.match(/(?:Interior Color|Interior)\s*:?\s*([A-Za-z\s]+?)(?:\n|,|$)/i);
        if (intMatch) r.interiorColor = intMatch[1].trim();

        // Transmission
        const transMatch = text.match(/(?:Transmission|Gearbox)\s*:?\s*([A-Za-z0-9\s-]+?)(?:\n|,|$)/i);
        if (transMatch) r.transmission = transMatch[1].trim();

        // Fuel
        const fuelMatch = text.match(/(?:Fuel|Fuel Type|Energy)\s*:?\s*([A-Za-z\s/+-]+?)(?:\n|,|$)/i);
        if (fuelMatch) r.fuel = fuelMatch[1].trim();

        // Drive
        const driveMatch = text.match(/(?:Drive Type|Drivetrain|Drive)\s*:?\s*(AWD|FWD|RWD|4WD|[A-Za-z\s-]+?)(?:\n|,|$)/i);
        if (driveMatch) r.drive = driveMatch[1].trim();

        // Displacement
        const dispMatch = text.match(/(?:Displacement|Engine|Engine Size)\s*:?\s*(\d+\.?\d*)\s*(?:L|T|cc)/i);
        if (dispMatch) r.displacement = parseFloat(dispMatch[1]);

        // HP
        const hpMatch = text.match(/(\d+)\s*(?:HP|hp|horsepower|PS|kW)/i);
        if (hpMatch) r.horsePower = parseInt(hpMatch[1], 10);

        // Steering
        const steerMatch = text.match(/(?:Steering|Wheel Position)\s*:?\s*(LHD|RHD|Left|Right)/i);
        if (steerMatch) r.steering = steerMatch[1].includes('L') || steerMatch[1].includes('Left') ? 'LHD' : 'RHD';

        // Body type
        const bodyMatch = text.match(/(?:Body Type|Vehicle Type)\s*:?\s*(Sedan|SUV|Hatchback|Coupe|Convertible|Van|MPV|Wagon|Truck|Pickup)/i);
        if (bodyMatch) r.bodyType = bodyMatch[1];

        // Keys
        const keysMatch = text.match(/(\d)\s*(?:key|keys)/i);
        if (keysMatch) r.keysCount = parseInt(keysMatch[1], 10);

        // VIN
        const vinMatch = text.match(/(?:VIN|Vehicle Identification)\s*:?\s*([A-HJ-NPR-Z0-9]{17})/i)
            || html.match(/[A-HJ-NPR-Z0-9]{17}/);
        if (vinMatch) r.vin = vinMatch[1] || vinMatch[0];

        // Owners
        const ownersMatch = text.match(/(\d)\s*(?:owner|previous owner)/i);
        if (ownersMatch) r.ownersCount = parseInt(ownersMatch[1], 10);

        // Reg date
        const regMatch = text.match(/(?:Registration|First Registered?|Reg\.? Date)\s*:?\s*(\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?)/i);
        if (regMatch) r.regDate = regMatch[1];

        // Inspection score
        const inspMatch = text.match(/(?:Inspection|Condition)\s*(?:Score|Rating|Grade)\s*:?\s*(\d+\.?\d*)\s*(?:\/\s*(\d+))?/i);
        if (inspMatch) {
            r.inspectionScore = parseFloat(inspMatch[1]);
            if (inspMatch[2]) r.inspectionMax = parseFloat(inspMatch[2]);
        }

        // Accident
        r.accidentFree = /(?:no accident|accident[- ]?free|0 accident)/i.test(text);
        if (/(?:has accident|accident history|previous accident|repaired)/i.test(text)) r.accidentFree = false;

        // Labels
        const labels = [];
        document.querySelectorAll('[class*="tag"], [class*="label"], [class*="badge"]').forEach(el => {
            const t = (el.innerText || '').trim();
            if (t && t.length < 50 && !t.includes('\n') && !/^\d+$/.test(t)) labels.push(t);
        });
        r.labels = [...new Set(labels)];

        // Seller
        const sellerMatch = text.match(/(?:Dealer|Seller|Shop)\s*:?\s*([^\n]{3,60})/i);
        if (sellerMatch) r.sellerName = sellerMatch[1].trim();

        // Description
        const descEl = document.querySelector('[class*="description"], [class*="remark"]');
        if (descEl) r.description = descEl.innerText?.substring(0, 2000) || '';

        // Raw text for debug
        r.rawTextSample = text.substring(0, 3000);

        return r;
    }""")


def parse_brand_model(alt: str, meta_mark: str) -> tuple[str, str, str]:
    s = alt.strip()
    if s.startswith("Used "):
        s = s[5:]
    m = re.match(r'^(.+?)\s+(\d{4})\s*(.*)', s)
    if m:
        brand_model = m.group(1).strip()
        trim = m.group(3).strip()
        if meta_mark and brand_model.lower().startswith(meta_mark.lower()):
            model = brand_model[len(meta_mark):].strip()
            return meta_mark, model or brand_model, trim
        tokens = brand_model.split(" ", 1)
        return tokens[0], tokens[1] if len(tokens) > 1 else "", trim
    return meta_mark or "", s, ""


FUEL_TO_ENGINE = {
    "petrol": "Petrol", "gasoline": "Petrol", "gas": "Petrol",
    "diesel": "Diesel",
    "electric": "Electric", "bev": "Electric", "ev": "Electric",
    "hybrid": "Hybrid", "hev": "Hybrid", "mhev": "Hybrid",
    "plug-in hybrid": "PHEV", "phev": "PHEV", "plug in": "PHEV",
    "range extender": "EREV", "erev": "EREV", "reev": "EREV",
    "extended range": "EREV",
    "hydrogen": "Hydrogen", "fcev": "Hydrogen",
    "cng": "CNG", "lpg": "LPG",
}


def fuel_to_engine_type(fuel: str | None) -> str | None:
    if not fuel:
        return None
    fl = fuel.lower().strip()
    for key, val in FUEL_TO_ENGINE.items():
        if key in fl:
            return val
    return fuel


def scrape_one(browser_ctx, source_id: str, meta: dict) -> dict | None:
    url = meta.get("url") or f"{BASE_URL}/used-cars/detail/{source_id}/"
    page = browser_ctx.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        d = extract_detail(page)
    except Exception as e:
        print(f"  ! {source_id} page error: {e}", flush=True)
        return None
    finally:
        page.close()

    if not d:
        return None

    alt = meta.get("alt") or d.get("ogTitle") or d.get("title") or ""
    meta_mark = meta.get("mark", "")
    mark, model, trim = parse_brand_model(alt, meta_mark)

    price_usd = d.get("priceUsd") or meta.get("price_usd")
    year = d.get("year") or meta.get("year")
    mileage = d.get("mileageKm") or meta.get("mileage_km")
    engine_type = fuel_to_engine_type(d.get("fuel"))

    inspection_data = {}
    if d.get("inspectionScore") is not None:
        inspection_data["overall_score"] = d["inspectionScore"]
    if d.get("inspectionMax"):
        inspection_data["max_score"] = d["inspectionMax"]
    if d.get("specs"):
        inspection_data["specs"] = d["specs"]

    rec = {
        "source": SOURCE,
        "source_id": source_id,
        "url": url,
        "title": d.get("ogTitle") or d.get("title") or alt,
        "mark": mark,
        "model": model,
        "complectation": trim,
        "year": year,
        "price_original": price_usd,
        "price_currency": "USD",
        "km_age_original": mileage,
        "km_age_unit": "km",
        "km_age": mileage,
        "color": d.get("color"),
        "interior_color_original": d.get("interiorColor"),
        "body_type": d.get("bodyType"),
        "engine_type": engine_type,
        "fuel_original": d.get("fuel"),
        "transmission_type": d.get("transmission"),
        "drive_type": d.get("drive"),
        "displacement": d.get("displacement"),
        "horse_power": d.get("horsePower"),
        "steering": d.get("steering"),
        "keys_count": d.get("keysCount"),
        "vin": d.get("vin"),
        "owners_count": d.get("ownersCount"),
        "reg_date": d.get("regDate"),
        "description": d.get("description"),
        "images": d.get("photos") or [],
        "image_count": len(d.get("photos") or []),
        "inspection_score": d.get("inspectionScore"),
        "accident_free": d.get("accidentFree"),
        "inspection_data": inspection_data if inspection_data else None,
        "labels": d.get("labels") if d.get("labels") else None,
        "export_ready": bool(d.get("labels") and any(
            "export" in l.lower() or "ready" in l.lower() or "inspected" in l.lower()
            for l in d["labels"])),
        "seller_type": "dealer",
        "source_language": "en",
        "source_data": {"raw_text_sample": d.get("rawTextSample", "")[:1000]},
    }
    return {k: v for k, v in rec.items() if v is not None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    if not DB.USE_POSTGRES:
        sys.exit("Need Postgres")

    pending = DB.get_pending_ids(SOURCE, args.limit)
    print(f"Pending guazi detail pages: {len(pending)}", flush=True)
    if not pending:
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 3000},
            locale="en-US",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

        start = time.time()
        ok = fail = 0
        for i, (source_id, meta_json) in enumerate(pending, 1):
            meta = json.loads(meta_json) if isinstance(meta_json, str) else (meta_json or {})
            rec = scrape_one(ctx, source_id, meta)
            if rec:
                if DB.upsert_car(rec):
                    ok += 1
                else:
                    fail += 1
            else:
                DB.mark_failed(SOURCE, source_id)
                fail += 1

            if i % 10 == 0 or i == len(pending):
                rate = i / max(time.time() - start, 1e-3)
                eta = (len(pending) - i) / max(rate, 1e-3)
                print(f"  [{i}/{len(pending)}] ok={ok} fail={fail} "
                      f"{rate:.1f}/s ETA {eta/60:.1f}m", flush=True)

        browser.close()

    print(f"\nDone in {(time.time()-start)/60:.1f}m. "
          f"Scraped: {ok}, failed: {fail}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
