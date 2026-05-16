"""
recon_yiche.py v5 — capture EXACT API URLs and replay them directly.

v3 captured car_model_api URLs but truncated them at 200 chars in logs.
v4 confirmed area_list works direct but car_model_api needs extra params
(error 11036 "公共参数缺失" = missing common params).

v5 strategy:
  1. Re-capture XHR on car.yiche.com/ with FULL URL printed.
  2. For every URL containing 'car_model_api' — replay it EXACTLY through
     Oxylabs without render (no browser context).
  3. Compare: does the captured URL work without browser? If yes → cheap
     parsing path. If no → we need render=html every time.

Env: OXY_USER, OXY_PASS
"""

import json
import os
import sys

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)


def capture_xhr(url: str) -> list[dict]:
    """Return raw captured XHR requests."""
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
        "locale": "zh-CN",
        "render": "html",
        "xhr": True,
        "browser_instructions": [
            {"type": "scroll_to_bottom", "wait_time_s": 2}
            for _ in range(4)
        ],
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=300)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return []
    results = r.json().get("results", []) or []
    xhr_block = next((res for res in results if res.get("type") == "xhr"), None)
    if not xhr_block:
        return []
    return xhr_block.get("content", []) or []


def replay_direct(url: str) -> dict:
    """Hit the EXACT URL directly (no render)."""
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=120)
    summary = {"oxy_http": r.status_code}
    if r.status_code != 200:
        summary["error"] = r.text[:200]
        return summary
    results = r.json().get("results", []) or []
    if not results:
        summary["error"] = "no results"
        return summary
    summary["target_status"] = results[0].get("status_code")
    content = results[0].get("content")
    if isinstance(content, str):
        summary["size"] = len(content)
        summary["preview"] = content[:600]
        try:
            j = json.loads(content)
            summary["json_top_keys"] = (list(j.keys()) if isinstance(j, dict)
                                         else f"list[{len(j)}]")
        except Exception:
            summary["json"] = False
    return summary


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    target = "https://car.yiche.com/"
    print(f"Capturing XHR from {target}\n")

    captured = capture_xhr(target)
    print(f"Captured {len(captured)} XHR calls\n")

    # Print full URLs of car_model_api calls — no truncation
    print("========== FULL URLs (car_model_api) ==========")
    car_model_urls = []
    for req in captured:
        url = req.get("url", "") or ""
        if "car_model_api" not in url:
            continue
        method = req.get("method")
        status = req.get("status_code")
        size = len(req.get("response_body") or "")
        print(f"\n  {method} {status} ({size} bytes):")
        print(f"  {url}")
        car_model_urls.append((req, url))

    if not car_model_urls:
        print("No car_model_api URLs captured — nothing to replay.")
        # Show all captured URLs as fallback
        print("\n========== ALL captured URLs ==========")
        for req in captured:
            url = req.get("url", "") or ""
            if any(s in url for s in ("sentry", "google", "/log?", "apm-",
                                       "doubleclick", "miaozhen")):
                continue
            print(f"  {req.get('method')} {req.get('status_code')} | {url}")
        return

    # Save captured bodies too
    save_path = os.path.join(OUT_DIR, "yiche_v5_xhr_full.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump([{
            "url": req.get("url"),
            "method": req.get("method"),
            "status": req.get("status_code"),
            "response_body_preview": (req.get("response_body") or "")[:2000],
        } for req, _ in car_model_urls], f, ensure_ascii=False, indent=2)
    print(f"\nFull XHR saved → {save_path}")

    # Replay each car_model_api URL directly
    print("\n========== REPLAY DIRECT (no render) ==========")
    for i, (req, url) in enumerate(car_model_urls, 1):
        print(f"\n--- {i}. {url[:100]}...")
        s = replay_direct(url)
        print(f"    Direct: target_status={s.get('target_status')}, "
              f"size={s.get('size')}, top_keys={s.get('json_top_keys')}")
        if s.get("size") and s["size"] < 100:
            print(f"    Body: {s.get('preview', '')[:200]}")

        # Compare with XHR result
        orig_size = len(req.get("response_body") or "")
        orig_body = req.get("response_body") or ""
        print(f"    XHR-captured size: {orig_size}")
        # If direct size matches XHR size — same data, no auth required
        if s.get("size") == orig_size:
            print(f"    ✅ SAME — API works directly without browser context!")
        elif s.get("size", 0) > 1000 and s.get("json_top_keys"):
            print(f"    ✅ Direct returns data (different size, but valid JSON)")
        else:
            print(f"    ❌ Direct returns less/error than XHR")
            # Print XHR body for comparison
            print(f"    XHR body preview: {orig_body[:300]}")

    print("\n========== DONE ==========")


if __name__ == "__main__":
    main()
