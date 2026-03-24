"""
Supabase HTTP client.

Provides a single access layer for all Supabase REST API operations,
with retry logic for transient network failures. Used by both the
persistence backend and any module that needs Supabase data.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote

import httpx

from config_secrets import config, require_secret

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

SUPABASE_URL = require_secret("SUPABASE_URL")
SUPABASE_KEY = require_secret("SUPABASE_KEY")
SUPABASE_HEADERS = {
    "apikey"        : SUPABASE_KEY,
    "Content-Type"  : "application/json",
    "Prefer"        : "return=minimal",
}

NETWORK_TIMEOUT = config.getint("network", "timeout")
MAX_RETRIES     = config.getint("network", "max_retries")
RETRY_DELAY     = config.getint("network", "retry_delay")


# ── HTTP with retry ──────────────────────────────────────────────────────────

def request_with_retry(method: str, url: str, **kwargs) -> httpx.Response | None:
    """
    Make an HTTP request with exponential backoff retry on transient failures.
    Returns the response on success. Raises on exhausted retries or HTTP errors.
    """
    kwargs.setdefault("timeout", NETWORK_TIMEOUT)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise  # don't retry client/server errors — let caller handle
        except httpx.RequestError as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY * (2 ** (attempt - 1))
                log.warning(f"Network error (attempt {attempt}/{MAX_RETRIES}), retrying in {delay}s: {e}")
                time.sleep(delay)
            else:
                raise


# ── Supabase operations ──────────────────────────────────────────────────────

def post(table: str, payload: dict[str, Any]) -> None:
    """POST a JSON payload to a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        request_with_retry("POST", url, headers=SUPABASE_HEADERS, json=payload)
        log.info(f"Supabase insert: {table}")
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase insert {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase insert {table} network error after {MAX_RETRIES} attempts: {e}")


def upsert(table: str, payload: dict[str, Any]) -> bool:
    """UPSERT a JSON payload to a Supabase table (update or insert by primary key).

    Returns True on success, False on failure.
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        **SUPABASE_HEADERS,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    try:
        request_with_retry("POST", url, headers=headers, json=payload)
        log.info(f"Supabase upsert: {table}")
        return True
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase upsert {table} failed ({e.response.status_code}): {e.response.text}")
        return False
    except httpx.RequestError as e:
        log.error(f"Supabase upsert {table} network error after {MAX_RETRIES} attempts: {e}")
        return False


def get(table: str, params: str = "") -> list[dict[str, Any]] | None:
    """GET rows from a Supabase table. Returns parsed JSON or None on error."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    try:
        resp = request_with_retry("GET", url, headers=SUPABASE_HEADERS)
        return resp.json() if resp else None
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase fetch {table} failed ({e.response.status_code}): {e.response.text}")
        return None
    except httpx.RequestError as e:
        log.error(f"Supabase fetch {table} network error after {MAX_RETRIES} attempts: {e}")
        return None


def patch(table: str, params: str, payload: dict[str, Any]) -> None:
    """PATCH rows in a Supabase table matching the query params."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    try:
        request_with_retry("PATCH", url, headers=SUPABASE_HEADERS, json=payload)
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase patch {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase patch {table} network error after {MAX_RETRIES} attempts: {e}")


# ── Device token operations ──────────────────────────────────────────────────

def get_device_tokens() -> list[str]:
    """Fetch active device tokens from the device_tokens table."""
    rows = get("device_tokens", "active=eq.true&select=token")
    return [row["token"] for row in rows] if rows else []


def mark_token_inactive(token: str) -> None:
    """Mark a device token as inactive."""
    patch("device_tokens", f"token=eq.{quote(token, safe='')}", {"active": False})
    log.info(f"Marked token ...{token[-8:]} inactive")
