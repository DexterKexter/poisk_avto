"""
Database access layer for poisk_avto.

Uses Supabase Postgres via REST API (PostgREST) — no psycopg2 needed.
Falls back to SQLite for local development if SUPABASE_URL not set.

Env vars:
    SUPABASE_URL  — e.g. https://xxxx.supabase.co
    SUPABASE_KEY  — service_role key (long JWT starting with eyJ...)

If both unset, uses local cars.db (SQLite).

Schema is multi-source compatible:
  *_original     : value in source language (e.g. zh, ko, ja)
  source_language: 'zh' / 'ko' / 'ja' / 'en'
  price stored as price_original + price_currency only; no USD/CNY normalization here
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

USE_POSTGRES = bool(SUPABASE_URL and SUPABASE_KEY)
SQLITE_PATH = "cars.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Postgres (Supabase via REST) ----------

def _pg_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }


def _pg_request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = kwargs.pop("headers", {}) or {}
    headers = {**_pg_headers(), **headers}
    return requests.request(method, url, headers=headers, timeout=60, **kwargs)


def pg_upsert_car(rec: dict) -> bool:
    """Insert or update a car row. Uses ON CONFLICT (source, source_id) DO UPDATE."""
    r = _pg_request(
        "POST",
        "cars?on_conflict=source,source_id",
        headers={"Prefer": "return=minimal,resolution=merge-duplicates"},
        json=rec,
    )
    if r.status_code not in (200, 201, 204):
        print(f"  PG upsert FAIL {r.status_code}: {r.text[:300]}")
        return False
    return True


def pg_upsert_pending(rec: dict) -> bool:
    """Insert or update a pending_ids row."""
    r = _pg_request(
        "POST",
        "pending_ids?on_conflict=source,source_id",
        headers={"Prefer": "return=minimal,resolution=merge-duplicates"},
        json=rec,
    )
    if r.status_code not in (200, 201, 204):
        print(f"  PG pending FAIL {r.status_code}: {r.text[:300]}")
        return False
    return True


QUARANTINE_THRESHOLD = 3


def pg_get_pending_ids(source: str, limit: int) -> list[str]:
    """Get pending source_ids not yet in cars and not quarantined."""
    r = _pg_request(
        "GET",
        f"pending_ids?source=eq.{source}"
        f"&failed_attempts=lt.{QUARANTINE_THRESHOLD}"
        f"&select=source_id&limit={limit * 3}",
    )
    if r.status_code != 200:
        print(f"  PG fetch pending FAIL: {r.text[:200]}")
        return []
    pending = [row["source_id"] for row in r.json()]

    r = _pg_request("GET", f"cars?source=eq.{source}&select=source_id")
    if r.status_code != 200:
        return pending[:limit]
    scraped = {row["source_id"] for row in r.json()}

    new_ones = [sid for sid in pending if sid not in scraped]
    return new_ones[:limit]


def pg_mark_failed(source: str, source_id: str) -> bool:
    """Increment failed_attempts and update last_failed_at via RPC-like PATCH."""
    r = _pg_request(
        "GET",
        f"pending_ids?source=eq.{source}&source_id=eq.{source_id}"
        f"&select=failed_attempts",
    )
    current = 0
    if r.status_code == 200 and r.json():
        current = r.json()[0].get("failed_attempts") or 0

    r = _pg_request(
        "PATCH",
        f"pending_ids?source=eq.{source}&source_id=eq.{source_id}",
        json={
            "failed_attempts": current + 1,
            "last_failed_at": now_iso(),
        },
    )
    return r.status_code in (200, 204)


def pg_count(table: str, where: str = "") -> int:
    path = f"{table}?select=count"
    if where:
        path += f"&{where}"
    r = _pg_request(
        "GET", path,
        headers={"Prefer": "count=exact"},
    )
    cr = r.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            return int(cr.split("/")[1])
        except (ValueError, IndexError):
            pass
    return 0


# ---------- SQLite fallback (mirrors Postgres schema) ----------

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cars (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_language TEXT,
    url TEXT, title TEXT,

    mark_original TEXT, mark TEXT,
    series_original TEXT, model TEXT, complectation TEXT,
    year INTEGER,

    price_original REAL, price_currency TEXT,
    new_price_original REAL, new_price_currency TEXT,

    km_age_original REAL, km_age_unit TEXT, km_age REAL,

    color_original TEXT, color TEXT,
    body_type TEXT,
    engine_type TEXT, fuel_original TEXT,
    transmission_original TEXT, transmission_type TEXT,
    drive_original TEXT, drive_type TEXT,
    displacement REAL, horse_power INTEGER,
    acceleration_time TEXT,
    length_mm INTEGER, width_mm INTEGER, height_mm INTEGER, wheelbase_mm INTEGER,

    city_original TEXT, city TEXT,
    reg_city_original TEXT, reg_city TEXT,
    reg_date TEXT,

    owners_count INTEGER, maintenance TEXT, interior_color_original TEXT,
    description TEXT,
    images TEXT, image_count INTEGER,

    seller_type TEXT, shop_name TEXT, shop_short_name TEXT,
    shop_address TEXT, shop_id TEXT, shop_cars_count INTEGER, sales_range TEXT,

    source_data TEXT, spu_id TEXT,
    first_seen TEXT, last_seen TEXT,

    PRIMARY KEY (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_cars_mark ON cars(mark);
CREATE INDEX IF NOT EXISTS idx_cars_year ON cars(year);
CREATE INDEX IF NOT EXISTS idx_cars_price ON cars(price_currency, price_original);
CREATE INDEX IF NOT EXISTS idx_cars_source_language ON cars(source_language);

CREATE TABLE IF NOT EXISTS pending_ids (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    metadata TEXT,
    found_at TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    last_failed_at TEXT,
    PRIMARY KEY (source, source_id)
);
"""


_sqlite_conn = None


def sqlite_conn() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        _sqlite_conn.executescript(SQLITE_SCHEMA)
        for stmt in (
            "ALTER TABLE pending_ids ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pending_ids ADD COLUMN last_failed_at TEXT",
        ):
            try:
                _sqlite_conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        _sqlite_conn.commit()
    return _sqlite_conn


def sqlite_upsert_car(rec: dict) -> bool:
    conn = sqlite_conn()
    rec = dict(rec)
    # JSON fields → strings for SQLite
    if isinstance(rec.get("images"), (list, dict)):
        rec["images"] = json.dumps(rec["images"], ensure_ascii=False)
    if isinstance(rec.get("source_data"), (list, dict)):
        rec["source_data"] = json.dumps(rec["source_data"], ensure_ascii=False)

    cols = list(rec.keys())
    placeholders = ",".join(":" + c for c in cols)
    col_list = ",".join(cols)
    update_list = ",".join(
        f"{c}=excluded.{c}" for c in cols
        if c not in ("source", "source_id", "first_seen")
    )
    sql = (
        f"INSERT INTO cars ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(source, source_id) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, rec)
    conn.commit()
    return True


def sqlite_upsert_pending(rec: dict) -> bool:
    conn = sqlite_conn()
    rec = dict(rec)
    if isinstance(rec.get("metadata"), (list, dict)):
        rec["metadata"] = json.dumps(rec["metadata"], ensure_ascii=False)
    conn.execute(
        "INSERT OR REPLACE INTO pending_ids (source, source_id, metadata, found_at) "
        "VALUES (:source, :source_id, :metadata, :found_at)",
        rec,
    )
    conn.commit()
    return True


def sqlite_get_pending_ids(source: str, limit: int) -> list[str]:
    conn = sqlite_conn()
    rows = conn.execute(
        """
        SELECT source_id FROM pending_ids
        WHERE source = ?
          AND failed_attempts < ?
          AND source_id NOT IN (SELECT source_id FROM cars WHERE source = ?)
        ORDER BY found_at DESC
        LIMIT ?
        """,
        (source, QUARANTINE_THRESHOLD, source, limit),
    ).fetchall()
    return [r[0] for r in rows]


def sqlite_mark_failed(source: str, source_id: str) -> bool:
    conn = sqlite_conn()
    conn.execute(
        "UPDATE pending_ids "
        "SET failed_attempts = failed_attempts + 1, last_failed_at = ? "
        "WHERE source = ? AND source_id = ?",
        (now_iso(), source, source_id),
    )
    conn.commit()
    return True


def sqlite_count(table: str, where_sql: str = "", params: tuple = ()) -> int:
    conn = sqlite_conn()
    sql = f"SELECT COUNT(*) FROM {table}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return conn.execute(sql, params).fetchone()[0]


# ---------- Unified API ----------

def upsert_car(rec: dict) -> bool:
    if USE_POSTGRES:
        return pg_upsert_car(rec)
    return sqlite_upsert_car(rec)


def upsert_pending(rec: dict) -> bool:
    if USE_POSTGRES:
        return pg_upsert_pending(rec)
    return sqlite_upsert_pending(rec)


def get_pending_ids(source: str, limit: int) -> list[str]:
    if USE_POSTGRES:
        return pg_get_pending_ids(source, limit)
    return sqlite_get_pending_ids(source, limit)


def mark_failed(source: str, source_id: str) -> bool:
    if USE_POSTGRES:
        return pg_mark_failed(source, source_id)
    return sqlite_mark_failed(source, source_id)


def count_cars(source: str = "") -> int:
    if USE_POSTGRES:
        where = f"source=eq.{source}" if source else ""
        return pg_count("cars", where)
    if source:
        return sqlite_count("cars", "source = ?", (source,))
    return sqlite_count("cars")


def count_pending(source: str = "") -> int:
    if USE_POSTGRES:
        where = f"source=eq.{source}" if source else ""
        return pg_count("pending_ids", where)
    if source:
        return sqlite_count("pending_ids", "source = ?", (source,))
    return sqlite_count("pending_ids")


def backend_name() -> str:
    return "Postgres (Supabase)" if USE_POSTGRES else f"SQLite ({SQLITE_PATH})"
