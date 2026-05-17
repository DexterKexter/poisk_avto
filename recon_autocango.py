"""
recon_autocango.py — try scrapling StealthyFetcher to bypass WAF.

Previous attempts via Oxylabs POST returned a "Security Verification"
HTML page (autocango uses a WAF). Render+xhr was flaky (6 → 0 → 4 → 0
XHR captures across runs). The data IS in SSR Nuxt 3 payload but
compressed by integer-pointers.

Scrapling's StealthyFetcher launches a stealth-patched Chromium
(camoufox-style) that should pass the WAF and let us either:
  A. Read the rendered HTML with all car data inline.
  B. Use the browser context (with WAF cookies set) to call
     /api/web/usedcar/search and get clean JSON.

This recon tries both.

Env: nothing (scrapling launches a local browser; no Oxylabs cost)
"""

import json
import os
import sys
import traceback

sys.stdout.reconfigure(line_buffering=True)

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)


def main() -> None:
    print("Starting scrapling-based recon for autocango", flush=True)
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        print(f"scrapling import failed: {e}", flush=True)
        sys.exit(1)

    listing_url = "https://www.autocango.com/usedcar/excludeSold=true"

    # === Phase A: load the listing page with StealthyFetcher ===
    print(f"\n========== Phase A: StealthyFetcher GET {listing_url} ==========",
          flush=True)
    try:
        page = StealthyFetcher.fetch(
            listing_url,
            headless=True,
            network_idle=True,
            humanize=True,           # mimic human cursor/scroll
            block_resources=False,   # need JS to execute
        )
    except Exception as e:
        print(f"  EXCEPTION: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    print(f"  Status: {page.status}", flush=True)
    html = getattr(page, "body", None) or getattr(page, "html_content", None) or ""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    print(f"  HTML size: {len(html)}", flush=True)
    print(f"  First 1500 chars:\n  {html[:1500]}", flush=True)

    # Check if we passed WAF
    if "Security Verification" in html:
        print(f"\n  ❌ Still hit WAF challenge", flush=True)
    elif len(html) > 100000:
        print(f"\n  ✅ Got full page ({len(html)} chars) — WAF bypassed!", flush=True)
        head_path = os.path.join(OUT_DIR, "scrapling_listing.html")
        with open(head_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  Full HTML → {head_path}", flush=True)

    # Look for IDs to confirm we got data
    import re
    ids = sorted(set(re.findall(r'\b[A-Z]{2,4}\d{6,10}\b', html)))
    print(f"\n  ID-like tokens found: {len(ids)}", flush=True)
    if ids:
        print(f"  First 5: {ids[:5]}", flush=True)

    # === Phase B: try POST to /api/web/usedcar/search with same browser context ===
    # StealthyFetcher v0.2+ doesn't natively support POST. We try via Playwright
    # directly using the stealth-patched browser.
    print(f"\n========== Phase B: POST API via playwright session ==========",
          flush=True)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page2 = context.new_page()
            # First visit listing to set WAF cookies
            print("  Visiting listing page to obtain cookies…", flush=True)
            page2.goto(listing_url, wait_until="networkidle", timeout=60_000)
            cookies = context.cookies()
            print(f"  Got {len(cookies)} cookies: "
                  f"{[c['name'] for c in cookies][:10]}", flush=True)

            # Now POST inside the browser context
            print("  Calling /api/web/usedcar/search via in-page fetch()…",
                  flush=True)
            result = page2.evaluate(
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
            print(f"  API call result: ok={result.get('ok')} "
                  f"status={result.get('status')}", flush=True)
            body = result.get("body", "")
            if body:
                print(f"  Body size: {len(body)}", flush=True)
                print(f"  First 500 chars: {body[:500]}", flush=True)
                try:
                    j = json.loads(body)
                    print(f"\n  ✅ JSON received!", flush=True)
                    print(f"  Top keys: {list(j.keys()) if isinstance(j, dict) else type(j).__name__}",
                          flush=True)
                    save = os.path.join(OUT_DIR, "scrapling_api_response.json")
                    with open(save, "w", encoding="utf-8") as f:
                        json.dump(j, f, ensure_ascii=False, indent=2)
                    print(f"  Saved → {save}", flush=True)
                    # Find car list
                    def find_list(o, path="$", depth=0):
                        if depth > 5:
                            return None
                        if isinstance(o, dict):
                            for k, v in o.items():
                                if isinstance(v, list) and v and isinstance(v[0], dict):
                                    return f"{path}.{k}", v
                                r = find_list(v, f"{path}.{k}", depth + 1)
                                if r:
                                    return r
                        return None
                    found = find_list(j)
                    if found:
                        path, cars = found
                        print(f"  🎯 Cars at {path} ({len(cars)} items)",
                              flush=True)
                        print(f"  First car keys: {list(cars[0].keys())[:30]}",
                              flush=True)
                        print(f"\n  ===== FIRST CAR =====", flush=True)
                        print(json.dumps(cars[0], ensure_ascii=False, indent=2)[:4000],
                              flush=True)
                        print(f"  ===== END =====", flush=True)
                except Exception as e:
                    print(f"  Not JSON: {e}", flush=True)
            elif result.get("error"):
                print(f"  Fetch error: {result['error']}", flush=True)

            browser.close()
    except Exception as e:
        print(f"  EXCEPTION in Phase B: {e}", flush=True)
        traceback.print_exc()

    print("\n========== DONE ==========", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("FATAL:", flush=True)
        traceback.print_exc()
        sys.exit(1)
