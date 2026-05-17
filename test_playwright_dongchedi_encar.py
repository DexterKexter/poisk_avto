"""
test_playwright_dongchedi_encar.py — test if playwright + GitHub Actions IP
can reach dongchedi.com (China) and api.encar.com (Korea) without Oxylabs.

If yes — we migrate, save \$250/month.
If blocked (403 / captcha / geo-block) — we stick with Oxylabs.

Tests:
  1. requests.get on encar API (we know it's open and unauth)
  2. playwright fetch on dongchedi listing page
  3. playwright fetch on a dongchedi card
  4. playwright fetch on encar listing page
"""

import json
import re
import sys
import traceback

import requests

sys.stdout.reconfigure(line_buffering=True)


def test_encar_api_direct() -> None:
    """Direct HTTP GET to encar API from US IP (GitHub Actions)."""
    print("\n========== TEST 1: encar API direct (no proxy, no render) ==========")
    url = ("https://api.encar.com/v1/readside/vehicles"
           "?vehicleIds=41203231"
           "&include=SPEC,ADVERTISEMENT,PHOTOS,CATEGORY,MANAGE,CONTACT,VIN")
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        print(f"  HTTP: {r.status_code}")
        print(f"  Body size: {len(r.text)}")
        print(f"  First 500: {r.text[:500]!r}")
        if r.status_code == 200 and r.text.startswith("["):
            j = json.loads(r.text)
            if isinstance(j, list) and j and isinstance(j[0], dict):
                print(f"  ✅ JSON received, {len(j)} cars, first car keys: "
                      f"{list(j[0].keys())[:10]}")
            return True
    except Exception as e:
        print(f"  EXCEPTION: {e}")
    return False


def test_dongchedi_playwright() -> None:
    """Try opening dongchedi.com from US IP with playwright."""
    print("\n========== TEST 2: dongchedi via playwright (no proxy) ==========")
    from playwright.sync_api import sync_playwright
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0.0.0 Safari/537.36")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="zh-CN",
                                  viewport={"width":1366,"height":768})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        url = "https://www.dongchedi.com/usedcar/22573537"
        print(f"  Loading: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)
            html = page.content()
            title = page.title()
            print(f"  Title: {title!r}")
            print(f"  HTML size: {len(html)}")

            # Check for __NEXT_DATA__
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.{0,200})',
                          html, re.DOTALL)
            if m:
                print(f"  ✅ __NEXT_DATA__ found! Preview: {m.group(1)[:200]}")
            else:
                # Print first 500 chars to see what we got (404? captcha?)
                print(f"  ❌ __NEXT_DATA__ not found")
                print(f"  First 500 chars: {html[:500]!r}")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
        finally:
            browser.close()


def test_dongchedi_listing_playwright() -> None:
    """Try a dongchedi listing page (the brand×city URL we use in collect)."""
    print("\n========== TEST 3: dongchedi listing via playwright ==========")
    from playwright.sync_api import sync_playwright
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0.0.0 Safari/537.36")
    # BMW × Beijing
    url = "https://www.dongchedi.com/usedcar/x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-x-4-x-110000-x-x-x-x-x"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="zh-CN",
                                  viewport={"width":1366,"height":768})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        print(f"  Loading: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)
            html = page.content()
            print(f"  Title: {page.title()!r}")
            print(f"  HTML size: {len(html)}")
            # Look for car cards
            cars_visible = page.evaluate(
                """() => document.querySelectorAll('[class*=card], .pcard, [class*=item]').length"""
            )
            print(f"  Cars/items visible: {cars_visible}")
            print(f"  First 400 chars: {html[:400]!r}")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
        finally:
            browser.close()


def test_encar_listing_playwright() -> None:
    """Try the encar listing page via playwright (this needs Korea IP normally)."""
    print("\n========== TEST 4: encar listing via playwright ==========")
    from playwright.sync_api import sync_playwright
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/131.0.0.0 Safari/537.36")
    url = "https://car.encar.com/list/car"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="ko-KR",
                                  viewport={"width":1366,"height":768})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        print(f"  Loading: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3000)
            html = page.content()
            print(f"  Title: {page.title()!r}")
            print(f"  HTML size: {len(html)}")
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.{0,200})',
                          html, re.DOTALL)
            if m:
                print(f"  ✅ __NEXT_DATA__ found")
            else:
                print(f"  ❌ __NEXT_DATA__ not found")
                print(f"  First 400 chars: {html[:400]!r}")
        except Exception as e:
            print(f"  EXCEPTION: {e}")
        finally:
            browser.close()


def main() -> None:
    print("Testing if we can reach dongchedi/encar from GitHub Actions WITHOUT Oxylabs")
    print(f"Our IP info:")
    try:
        ip = requests.get("https://ifconfig.me/ip", timeout=5).text.strip()
        print(f"  IP: {ip}")
        geo = requests.get(f"https://ipapi.co/{ip}/json/", timeout=5).json()
        print(f"  Country: {geo.get('country_name')}, "
              f"City: {geo.get('city')}, Org: {geo.get('org')}")
    except Exception:
        pass

    test_encar_api_direct()
    test_dongchedi_playwright()
    test_dongchedi_listing_playwright()
    test_encar_listing_playwright()

    print("\nDONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
