"""
recon_autocango.py v12 — confirm pagination and find prices.

We have:
  - card selector: div.car-item
  - detail URL: /sku/usedcar-{brand}-{model}-{ID}
  - text contains: id, year, brand, model, engine, mileage, fuel, transm, color, steering

Need to confirm:
  - pagination via /usedcar/excludeSold=true/page=2 returns different cars
  - where prices are (text on listing didn't show $/¥ explicitly)
  - full structured fields per card via selectors
"""

import json
import os
import re
import sys
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def load(page, url: str) -> list[dict]:
    """Load URL, return cars extracted from div.car-item."""
    print(f"\n→ {url}", flush=True)
    page.goto(url, wait_until="networkidle", timeout=60_000)
    page.wait_for_timeout(2000)

    cars = page.evaluate(
        """() => {
            const cards = Array.from(document.querySelectorAll('div.car-item'));
            return cards.map(card => {
                // Top-level link gives href + id
                const link = card.querySelector('a[href*="/sku/"]');
                const href = link ? link.href : null;
                const idMatch = href ? href.match(/[A-Z]{2,4}\\d{6,10}/) : null;
                const id = idMatch ? idMatch[0] : null;

                // All images in card
                const imgs = Array.from(card.querySelectorAll('img'))
                    .map(i => i.src).filter(s => s && !s.startsWith('data:'));

                // Full text content
                const text = (card.innerText || '').replace(/\\s+/g, ' ').trim();

                // Try to find a price element (text containing $, ¥, FOB, USD)
                let price_text = null;
                for (const el of card.querySelectorAll('*')) {
                    const t = (el.innerText || '').trim();
                    if (t.length < 50 && /\\$|¥|USD|FOB|RMB|￥/i.test(t)) {
                        price_text = t;
                        break;
                    }
                }

                return {id, href, images: imgs.slice(0, 8), text, price_text};
            }).filter(c => c.id);
        }"""
    )
    return cars


def main() -> None:
    print("recon_autocango v12", flush=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(user_agent=UA,
                                  viewport={"width": 1366, "height": 768},
                                  locale="en-US")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = ctx.new_page()

        # Page 1
        cars1 = load(page, "https://www.autocango.com/usedcar/excludeSold=true")
        ids1 = [c["id"] for c in cars1]
        print(f"  Page 1: {len(cars1)} cars, first IDs: {ids1[:5]}", flush=True)

        # Page 2 via path
        cars2 = load(page, "https://www.autocango.com/usedcar/excludeSold=true/page=2")
        ids2 = [c["id"] for c in cars2]
        print(f"  Page 2: {len(cars2)} cars, first IDs: {ids2[:5]}", flush=True)
        overlap = len(set(ids1) & set(ids2))
        print(f"  Overlap with page 1: {overlap}/{len(ids2)}", flush=True)
        if cars2 and overlap < len(ids2) * 0.5:
            print(f"  ✅ Pagination via /page=N works", flush=True)
        else:
            print(f"  ⚠️  Same cars — pagination different", flush=True)

        # Print full first car details for field mapping
        if cars1:
            c = cars1[0]
            print(f"\n===== FIRST CAR FULL DETAILS =====", flush=True)
            print(f"  id: {c['id']}", flush=True)
            print(f"  href: {c['href']}", flush=True)
            print(f"  price_text: {c['price_text']!r}", flush=True)
            print(f"  images ({len(c['images'])}): {c['images'][:3]}", flush=True)
            print(f"\n  Full text:\n  {c['text']}", flush=True)

        # Save all from page 1
        save = os.path.join(OUT_DIR, "autocango_page1.json")
        with open(save, "w", encoding="utf-8") as f:
            json.dump(cars1, f, ensure_ascii=False, indent=2)
        print(f"\nSaved → {save}", flush=True)

        # Visit ONE detail page to see what extra fields it has (esp price)
        if cars1:
            detail_url = cars1[0]["href"]
            print(f"\n===== Visiting detail page: {detail_url} =====", flush=True)
            page.goto(detail_url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2000)
            detail = page.evaluate(
                """() => {
                    const text = document.body.innerText.replace(/\\s+/g, ' ').slice(0, 3000);
                    const prices = [];
                    for (const el of document.querySelectorAll('*')) {
                        const t = (el.innerText || '').trim();
                        if (t.length < 80 && /\\$\\d|¥\\d|USD\\s*\\d|FOB\\s*\\$?\\d|\\d+\\s*USD/i.test(t)) {
                            prices.push(t);
                            if (prices.length >= 10) break;
                        }
                    }
                    return {text, prices};
                }"""
            )
            print(f"  Found price-like strings ({len(detail['prices'])}):", flush=True)
            for pr in detail["prices"][:10]:
                print(f"    {pr!r}", flush=True)
            print(f"\n  First 1500 chars of body text:", flush=True)
            print(f"  {detail['text'][:1500]}", flush=True)

        browser.close()
    print("\nDONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
