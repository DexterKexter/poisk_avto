"""
recon_autocango.py — raw playwright with realistic UA, no scrapling.

Strategy:
  Phase A. Open /usedcar/excludeSold=true via Chromium with realistic UA.
           If WAF challenge appears, wait for it to resolve automatically
           (Cloudflare often passes after a JS challenge takes a few seconds).
           Then dump rendered HTML + look for inline JSON / IDs.

  Phase B. Within the same browser context (cookies set by Phase A),
           call /api/web/usedcar/search with fetch() and capture JSON.

Env: nothing (uses local Chromium via playwright)
"""

import json
import os
import re
import sys
import time
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

LISTING_URL = "https://www.autocango.com/usedcar/excludeSold=true"
API_URL = "https://www.autocango.com/api/web/usedcar/search"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


def main() -> None:
    print("recon_autocango: raw playwright", flush=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        # Hide webdriver flag
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = context.new_page()

        # ===== Phase A =====
        print(f"\nPhase A: GET {LISTING_URL}", flush=True)
        try:
            page.goto(LISTING_URL, wait_until="networkidle", timeout=60_000)
        except Exception as e:
            print(f"  goto exception: {e}", flush=True)

        # If WAF challenge, wait for it to clear (Cloudflare JS takes ~5s)
        title = page.title()
        print(f"  Page title: {title!r}", flush=True)
        if "Security" in title or "Just a moment" in title:
            print(f"  Detected WAF challenge — waiting 10s for auto-resolve…",
                  flush=True)
            time.sleep(10)
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            title = page.title()
            print(f"  Title after wait: {title!r}", flush=True)

        html = page.content()
        print(f"  HTML size: {len(html)}", flush=True)
        with open(os.path.join(OUT_DIR, "playwright_listing.html"),
                  "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Saved → recon_artifacts/playwright_listing.html", flush=True)

        ids = sorted(set(re.findall(r'\b[A-Z]{2,4}\d{6,10}\b', html)))
        print(f"  ID-like tokens found: {len(ids)}", flush=True)
        if ids:
            print(f"  First 5: {ids[:5]}", flush=True)
        print(f"  First 1500 chars:\n  {html[:1500]}", flush=True)

        cookies = context.cookies()
        print(f"\n  Cookies set: {len(cookies)}", flush=True)
        for c in cookies[:10]:
            print(f"    {c['name']} = {c['value'][:50]}…", flush=True)

        # ===== Phase B =====
        print(f"\nPhase B: POST {API_URL} via in-page fetch()", flush=True)
        try:
            result = page.evaluate(
                """async () => {
                    try {
                        const r = await fetch('/api/web/usedcar/search', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Accept': 'application/json',
                            },
                            body: JSON.stringify({
                                page: 1, pageSize: 20, excludeSold: true
                            }),
                        });
                        const text = await r.text();
                        return {ok: r.ok, status: r.status, body: text};
                    } catch (e) {
                        return {error: e.toString()};
                    }
                }"""
            )
        except Exception as e:
            print(f"  evaluate exception: {e}", flush=True)
            result = None

        if result and "body" in result:
            print(f"  status: {result.get('status')}, ok: {result.get('ok')}",
                  flush=True)
            body = result["body"] or ""
            print(f"  body size: {len(body)}", flush=True)
            print(f"  first 500 chars: {body[:500]}", flush=True)
            try:
                j = json.loads(body)
                print(f"\n  ✅ JSON received", flush=True)
                print(f"  Top keys: {list(j.keys()) if isinstance(j, dict) else type(j).__name__}",
                      flush=True)
                save = os.path.join(OUT_DIR, "playwright_api_response.json")
                with open(save, "w", encoding="utf-8") as f:
                    json.dump(j, f, ensure_ascii=False, indent=2)
                print(f"  Saved → {save}", flush=True)

                def find_list(o, path="$", depth=0):
                    if depth > 6: return None
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                return f"{path}.{k}", v
                            r = find_list(v, f"{path}.{k}", depth + 1)
                            if r: return r
                    return None
                f2 = find_list(j)
                if f2:
                    path, cars = f2
                    print(f"  🎯 Cars at {path} ({len(cars)} items)", flush=True)
                    print(f"  First car keys: {list(cars[0].keys())[:30]}", flush=True)
                    print(f"\n  ===== FIRST CAR =====", flush=True)
                    print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:4000],
                          flush=True)
            except Exception as e:
                print(f"  Not JSON: {e}", flush=True)
        elif result and "error" in result:
            print(f"  Fetch error: {result['error']}", flush=True)

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
