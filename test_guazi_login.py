"""Test en.guazi.com — extract listings + detail page data (no login needed)."""
import json, os, sys
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 3000}, locale="en-US")
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    page = ctx.new_page()

    # 1. Listing page
    print("=== 1. BMW listing page ===", flush=True)
    page.goto("https://en.guazi.com/used-cars/bmw/", wait_until="networkidle", timeout=45_000)
    page.wait_for_timeout(5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)

    cards = page.evaluate(r"""() => {
        const results = [];
        // Find all links to /products/ pages
        const links = document.querySelectorAll('a[href*="/products/"]');
        for (const a of links) {
            const href = a.getAttribute('href') || '';
            const img = a.querySelector('img[alt]');
            if (!img) continue;
            const alt = img.alt || '';
            // Price from card
            const cardRoot = a.closest('[class*="card"]') || a.parentElement?.parentElement || a;
            const text = cardRoot.innerText || '';
            const priceM = text.match(/\$\s*([\d,]+)/);
            const kmM = text.match(/([\d,]+)\s*km/i);
            const yearM = alt.match(/(\d{4})/);
            results.push({
                href, alt,
                price: priceM ? priceM[1] : null,
                km: kmM ? kmM[1] : null,
                year: yearM ? parseInt(yearM[1]) : null,
                imgSrc: img.src || '',
            });
        }
        // Dedupe by href
        const seen = new Set();
        return results.filter(r => {
            if (seen.has(r.href)) return false;
            seen.add(r.href);
            return true;
        });
    }""")

    print(f"  Cards found: {len(cards)}", flush=True)
    for c in cards[:8]:
        print(f"    alt={c['alt'][:60]}  price=${c['price']}  km={c['km']}  year={c['year']}", flush=True)
        print(f"      href={c['href'][:100]}", flush=True)

    # 2. Detail page — visit first card
    if cards:
        href = cards[0]['href']
        detail_url = href if href.startswith('http') else f"https://en.guazi.com{href}"
        print(f"\n=== 2. Detail page: {detail_url[:100]} ===", flush=True)
        page.goto(detail_url, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(5000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(3000)

        detail = page.evaluate(r"""() => {
            const text = document.body.innerText || '';
            const r = {title: document.title};

            // Photos
            r.photos = Array.from(document.querySelectorAll('img[src]'))
                .map(i => i.src)
                .filter(s => s.includes('guazi') && (s.includes('.jpg') || s.includes('.webp') || s.includes('.png') || s.includes('qnbdp')))
                .filter(s => !s.includes('icon') && !s.includes('.svg') && !s.includes('favicon'));
            r.photoCount = r.photos.length;
            r.photos = r.photos.slice(0, 5);  // sample

            // All visible text sections
            r.bodyLen = text.length;

            // Extract key-value pairs from spec sections
            const specs = {};
            document.querySelectorAll('[class*="spec"], [class*="detail"], [class*="info"], [class*="param"]').forEach(el => {
                const items = el.querySelectorAll('div, span, p, td, dt, dd, li');
                items.forEach(item => {
                    const t = (item.innerText || '').trim();
                    const kv = t.match(/^(.{2,30})\s*[:：]\s*(.+)$/);
                    if (kv) specs[kv[1].trim()] = kv[2].trim();
                });
            });
            r.specs = specs;

            // Price
            const pm = text.match(/(?:Starting|FOB|Current)\s*(?:Price)?\s*:?\s*\$\s*([\d,]+)/i)
                || text.match(/\$\s*([\d,]+)/);
            if (pm) r.priceUsd = pm[1];

            // Structured fields from body text
            const fields = {};
            for (const [label, re] of [
                ['Year', /(?:Year|Model Year)\s*[:：]?\s*(\d{4})/i],
                ['Mileage', /(?:Mileage|Odometer)\s*[:：]?\s*([\d,]+)\s*km/i],
                ['Color', /(?:Exterior Color|Color)\s*[:：]?\s*([A-Za-z\s]+?)(?:\n|$)/i],
                ['Transmission', /(?:Transmission|Gearbox)\s*[:：]?\s*([A-Za-z0-9\s-]+?)(?:\n|$)/i],
                ['Fuel', /(?:Fuel|Energy)\s*[:：]?\s*([A-Za-z\s/+-]+?)(?:\n|$)/i],
                ['Drive', /(?:Drive|Drivetrain)\s*[:：]?\s*(\S+)/i],
                ['Engine', /(?:Engine|Displacement)\s*[:：]?\s*(\d+\.?\d*\s*[LTl])/i],
                ['Steering', /(?:Steering|Wheel)\s*[:：]?\s*(LHD|RHD|Left|Right)/i],
                ['VIN', /(?:VIN)\s*[:：]?\s*([A-HJ-NPR-Z0-9]{17})/i],
                ['Seats', /(\d)\s*seat/i],
                ['Keys', /(\d)\s*key/i],
            ]) {
                const m = text.match(re);
                if (m) fields[label] = m[1].trim();
            }
            r.fields = fields;

            // Inspection / Grade
            const grade = text.match(/Grade\s*[:：]?\s*([A-F][+-]?)/i);
            if (grade) r.grade = grade[1];
            r.accidentFree = /no accident|accident.?free/i.test(text);

            // Labels/tags
            r.labels = Array.from(document.querySelectorAll('[class*="tag"], [class*="label"], [class*="badge"]'))
                .map(e => (e.innerText||'').trim())
                .filter(t => t && t.length < 50 && !t.includes('\n') && !/^\d+$/.test(t));
            r.labels = [...new Set(r.labels)];

            // Body text sample for debug
            r.textSample = text.substring(0, 3000);
            return r;
        }""")

        print(f"  Title: {detail.get('title')}", flush=True)
        print(f"  Photos: {detail.get('photoCount')}", flush=True)
        for ph in (detail.get('photos') or [])[:3]:
            print(f"    {ph[:120]}", flush=True)
        print(f"  Price: ${detail.get('priceUsd')}", flush=True)
        print(f"  Grade: {detail.get('grade')}", flush=True)
        print(f"  Accident free: {detail.get('accidentFree')}", flush=True)
        print(f"  Labels: {detail.get('labels')}", flush=True)
        print(f"  Fields: {json.dumps(detail.get('fields', {}), indent=2)}", flush=True)
        print(f"  Specs: {json.dumps(detail.get('specs', {}), indent=2, ensure_ascii=False)[:1000]}", flush=True)
        print(f"\n  Body text (first 2000):\n{detail.get('textSample','')[:2000]}", flush=True)
    else:
        print("\n  No cards found — cannot test detail page", flush=True)

    browser.close()
