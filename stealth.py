"""Two-tier protected-page fetcher.

China-hosted marketplaces (autocango, guazi, che168) front their listings
with progressively-aggressive anti-bot:
  - Tencent EdgeOne TEO CAPTCHA on autocango (since ~2026-05-18)
  - Rate-limit + fingerprint check on guazi/che168 detail pages
  - Geo-redirect to en.guazi.com placeholder for US-based runners

Strategy: try Scrapling (Camoufox-based real browser with anti-fingerprinting)
first — it's free and the fingerprint is good enough that many WAFs don't
even show the captcha. If that returns a challenge page or fails, fall
back to Oxylabs Realtime API (CN geo + JS render) — paid but reliable
for everything except solver-required CAPTCHAs.

Both layers are no-ops when their respective deps/credentials aren't
available, so local dev without setup just gets None.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

# ---------- Challenge detection ----------

# Cheap textual markers that distinguish a real listing/detail page from
# a WAF challenge page or geo-fallback placeholder. Lowercased once.
_CHALLENGE_MARKERS = (
    "security verification",
    "captcha",
    "请完成下方验证",
    "请完成安全验证",
    "rate limit",
    "blocked",
    "human verification",
    "gcaptcha.eo.gtimg.com",  # Tencent TEO captcha widget script src
)


def looks_like_challenge(html: str | None) -> bool:
    """Returns True if the response is a WAF challenge instead of real
    content. Checks only the head of the document so this stays O(1)
    on multi-MB pages."""
    if not html or len(html) < 200:
        return True
    head = html[:5000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


# ---------- Scrapling (Camoufox stealth) ----------

# Cache the fetcher import: if Scrapling isn't installed we don't want
# to pay the import-cost on every call, and we don't want to spam the
# log either.
_SCRAPLING_FETCHER: Any = None
_SCRAPLING_LOADED = False


def _get_scrapling_fetcher() -> Any:
    global _SCRAPLING_FETCHER, _SCRAPLING_LOADED
    if _SCRAPLING_LOADED:
        return _SCRAPLING_FETCHER
    _SCRAPLING_LOADED = True
    try:
        # Scrapling's StealthyFetcher uses Camoufox under the hood —
        # a custom Firefox build with anti-fingerprinting patches.
        from scrapling.fetchers import StealthyFetcher  # type: ignore
        _SCRAPLING_FETCHER = StealthyFetcher
    except Exception as e:
        print(f"  stealth: scrapling unavailable ({e})", flush=True)
        _SCRAPLING_FETCHER = None
    return _SCRAPLING_FETCHER


def scrapling_fetch_html(url: str, wait_selector: str | None = None) -> str | None:
    """Fetch via Scrapling's StealthyFetcher (Camoufox). Returns rendered
    HTML or None on failure. wait_selector lets the caller wait for a
    specific element (e.g. `div.car-item`) so the page is actually
    populated before we read the DOM."""
    fetcher = _get_scrapling_fetcher()
    if fetcher is None:
        return None
    try:
        kwargs: dict[str, Any] = {
            "headless": True,
            "network_idle": True,
            "humanize": True,  # mouse jitter, micro-scroll
            "timeout": 60_000,
        }
        if wait_selector:
            kwargs["wait_selector"] = wait_selector
        page = fetcher.fetch(url, **kwargs)
        if page is None:
            return None
        status = getattr(page, "status", None)
        if status is not None and status >= 400:
            return None
        html = getattr(page, "html_content", None) or getattr(page, "body", None)
        return html if isinstance(html, str) and html else None
    except Exception as e:
        print(f"  stealth/scrapling: {e}", flush=True)
        return None


# ---------- Oxylabs Realtime API ----------

OXY_USER = os.environ.get("OXY_USER", "")
OXY_PASS = os.environ.get("OXY_PASS", "")
OXY_URL = "https://realtime.oxylabs.io/v1/queries"


def oxylabs_fetch_html(url: str) -> str | None:
    """Fetch via Oxylabs Realtime universal scraper — CN geo + JS render.
    Returns rendered HTML or None. Skips silently when creds aren't set."""
    if not (OXY_USER and OXY_PASS):
        return None
    payload = {
        "source": "universal", "url": url,
        "geo_location": "China", "render": "html",
    }
    for attempt in range(3):
        try:
            r = requests.post(OXY_URL, auth=(OXY_USER, OXY_PASS),
                              json=payload, timeout=120)
            if r.status_code != 200:
                time.sleep(2 ** attempt); continue
            results = r.json().get("results") or []
            if not results:
                time.sleep(2 ** attempt); continue
            content = results[0].get("content") or ""
            if not content or len(content) < 5000:
                time.sleep(2 ** attempt); continue
            if looks_like_challenge(content):
                time.sleep(2 ** attempt); continue
            return content
        except Exception:
            time.sleep(2 ** attempt)
    return None


# ---------- Unified fetch ----------

def fetch_protected_html(url: str, *, wait_selector: str | None = None,
                          allow_scrapling: bool = True,
                          allow_oxylabs: bool = True) -> str | None:
    """Try Scrapling first (free, often enough), fall back to Oxylabs
    (paid). Returns the first non-challenge HTML response or None.

    The caller can disable a tier explicitly — e.g. autocango's listing
    pages historically need Oxylabs CN-geo (US runners get the captcha),
    so callers can short-circuit to it.
    """
    if allow_scrapling:
        html = scrapling_fetch_html(url, wait_selector=wait_selector)
        if html and not looks_like_challenge(html):
            return html
    if allow_oxylabs:
        html = oxylabs_fetch_html(url)
        if html:
            return html
    return None
