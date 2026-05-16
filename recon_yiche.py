"""
recon_yiche.py v7 — replay the EXACT captured URL without render.

v6 captured the full working URL from car.m.yiche.com/:
  mapi.yiche.com/web_api/car_model_api/api/v1/serial/search_hot_serials
    ?cid=508&param={"adCigdcid":"<token>","type":5,"adTime":"...","num":20}

Test if the API accepts:
  A. The captured adCigdcid token verbatim (it's freshly generated)
  B. A fake adCigdcid like "test"
  C. Empty adCigdcid

Then dump the JSON to map field structure.

Env: OXY_USER, OXY_PASS
"""

import datetime
import json
import os
import sys
import urllib.parse

import requests

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"

OUT_DIR = "recon_artifacts"
os.makedirs(OUT_DIR, exist_ok=True)

API_BASE = ("https://mapi.yiche.com/web_api/car_model_api"
            "/api/v1/serial/search_hot_serials")
TODAY = datetime.date.today().isoformat()


def build_url(ad_cigdcid: str, num: int = 20) -> str:
    param = {
        "adCigdcid": ad_cigdcid,
        "type": 5,
        "adTime": TODAY,
        "advertPage": "recon_yiche_v7",
        "num": num,
    }
    return f"{API_BASE}?cid=508&param={urllib.parse.quote(json.dumps(param))}"


def probe(name: str, url: str) -> dict:
    print(f"\n========== {name} ==========")
    print(f"URL: {url[:200]}{'...' if len(url) > 200 else ''}")
    payload = {
        "source": "universal",
        "url": url,
        "geo_location": "China",
    }
    r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                      json=payload, timeout=120)
    if r.status_code != 200:
        print(f"  OXY HTTP {r.status_code}: {r.text[:200]}")
        return {}
    results = r.json().get("results", []) or []
    if not results:
        return {}
    status = results[0].get("status_code")
    content = results[0].get("content")
    print(f"  Target HTTP: {status}")
    if not isinstance(content, str):
        print(f"  Content type: {type(content).__name__}")
        return {"target_status": status}
    print(f"  Size: {len(content)}")
    print(f"  First 400 chars: {content[:400]}")
    try:
        j = json.loads(content)
        if isinstance(j, dict):
            print(f"  ✅ JSON dict, top keys: {list(j.keys())}")
            # Check if it's the "missing params" error vs real data
            if "data" in j and j.get("status") in ("1", 1):
                print(f"  🎯 SUCCESS — real data returned")
                # Print structure of data
                data = j["data"]
                if isinstance(data, dict):
                    print(f"  data keys: {list(data.keys())}")
                    # Find lists/arrays
                    for k, v in data.items():
                        if isinstance(v, list) and v:
                            print(f"  data.{k}: list[{len(v)}]")
                            if isinstance(v[0], dict):
                                print(f"    first item keys: {list(v[0].keys())[:25]}")
                                print(f"    sample: {json.dumps(v[0], ensure_ascii=False)[:500]}")
                                break  # show first list only
                elif isinstance(data, list):
                    print(f"  data: list[{len(data)}]")
                    if data and isinstance(data[0], dict):
                        print(f"    first item keys: {list(data[0].keys())[:25]}")
            return {"target_status": status, "json": j, "size": len(content)}
    except Exception:
        pass
    return {"target_status": status, "size": len(content)}


def main() -> None:
    if not OXY_USER or not OXY_PASS:
        sys.exit("ERROR: OXY_USER / OXY_PASS not set")

    # A. Captured-verbatim token from v6 run (might be expired by now)
    token_captured = ("deJcd5RjrYp42zrhxDF435XKMeaYTYeh"
                      "&page=5JYHbABBXewrmaZsrHRka56H7Jkec6SP1778940830839")
    probe("A_captured_token", build_url(token_captured))

    # B. Fake token (does the server validate?)
    probe("B_fake_token", build_url("test_token_123"))

    # C. Empty token
    probe("C_empty_token", build_url(""))

    # D. No-token variant: bare URL with minimal param
    minimal = f"{API_BASE}?cid=508&param=%7B%22num%22%3A20%7D"
    probe("D_minimal_param", minimal)

    print("\n========== DONE ==========")
    print("If any returned status=1 with data → API works direct, fake token OK")


if __name__ == "__main__":
    main()
