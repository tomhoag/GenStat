"""
Supabase persistence backend.

Stores generator state changes and events in a Supabase (PostgreSQL) database
via the REST API.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from interfaces import PersistenceBackend, State, TransferSwitchData
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

NETWORK_TIMEOUT   = config.getint("network", "timeout")
MAX_RETRIES       = config.getint("network", "max_retries")
RETRY_DELAY       = config.getint("network", "retry_delay")


# ── HTTP helpers with retry ──────────────────────────────────────────────────

def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response | None:
    """
    Make an HTTP request with exponential backoff retry on transient failures.
    Returns the response on success, or None if all retries are exhausted.
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


# ── Supabase helpers ──────────────────────────────────────────────────────────

def supabase_post(table: str, payload: dict[str, Any]) -> None:
    """POST a JSON payload to a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        _request_with_retry("POST", url, headers=SUPABASE_HEADERS, json=payload)
        log.info(f"Supabase insert: {table}")
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase insert {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase insert {table} network error after {MAX_RETRIES} attempts: {e}")


def supabase_upsert(table: str, payload: dict[str, Any]) -> None:
    """UPSERT a JSON payload to a Supabase table (update or insert by primary key)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        **SUPABASE_HEADERS,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    try:
        _request_with_retry("POST", url, headers=headers, json=payload)
        log.info(f"Supabase upsert: {table}")
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase upsert {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase upsert {table} network error after {MAX_RETRIES} attempts: {e}")


def supabase_get(table: str, params: str = "") -> list[dict[str, Any]] | None:
    """GET rows from a Supabase table. Returns parsed JSON or None on error."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    try:
        resp = _request_with_retry("GET", url, headers=SUPABASE_HEADERS)
        return resp.json() if resp else None
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase fetch {table} failed ({e.response.status_code}): {e.response.text}")
        return None
    except httpx.RequestError as e:
        log.error(f"Supabase fetch {table} network error after {MAX_RETRIES} attempts: {e}")
        return None


def get_current_runtime_hours() -> tuple[float, float]:
    """Fetch current generator_runtime_hours and generator_exercise_hours from generator_status row 1."""
    rows = supabase_get("generator_status", "id=eq.1&select=generator_runtime_hours,generator_exercise_hours")
    if rows and len(rows) > 0:
        runtime  = float(rows[0].get("generator_runtime_hours") or 0.0)
        exercise = float(rows[0].get("generator_exercise_hours") or 0.0)
        return runtime, exercise
    return 0.0, 0.0


# ── Concrete implementation ──────────────────────────────────────────────────

class SupabasePersistence(PersistenceBackend):
    """Stores state changes and events in Supabase."""

    def publish_state_change(self, old_state: State, new_state: State,
                             data: TransferSwitchData, duration_seconds: int) -> None:
        now = datetime.now(timezone.utc).isoformat()

        # Insert event record
        event = {
            "previous_state"   : old_state.value,
            "new_state"        : new_state.value,
            "utility_voltage"  : data.normal_voltage,
            "generator_voltage": data.emergency_voltage,
            "duration_seconds" : duration_seconds,
        }
        supabase_post("generator_events", event)

        # Build status update
        status: dict[str, Any] = {
            "id"               : 1,
            "updated_at"       : now,
            "current_state"    : new_state.value,
            "utility_voltage"  : data.normal_voltage,
            "generator_voltage": data.emergency_voltage,
        }

        # Track last exercise and outage timestamps
        if new_state == State.WEEKLY_TEST:
            status["last_exercise_at"] = now
        if new_state == State.OUTAGE:
            status["last_outage_at"] = now
        if old_state == State.OUTAGE and new_state != State.WEEKLY_TEST:
            status["last_outage_duration_seconds"] = duration_seconds
            status["exercise_schedule_check_needed"] = True

        # Accumulate runtime hours when leaving any running state (outage or exercise)
        if old_state in (State.OUTAGE, State.WEEKLY_TEST):
            duration_hours = duration_seconds / 3600.0
            current_runtime, current_exercise = get_current_runtime_hours()
            new_runtime = round(current_runtime + duration_hours, 4)
            status["generator_runtime_hours"] = new_runtime
            log.info(
                f"Generator runtime: +{duration_hours:.4f}h "
                f"({current_runtime:.4f} → {new_runtime:.4f}h total)"
            )

            # Accumulate exercise hours only when leaving weekly_test
            if old_state == State.WEEKLY_TEST:
                new_exercise = round(current_exercise + duration_hours, 4)
                status["generator_exercise_hours"] = new_exercise
                log.info(
                    f"Generator exercise: +{duration_hours:.4f}h "
                    f"({current_exercise:.4f} → {new_exercise:.4f}h total)"
                )

        supabase_upsert("generator_status", status)
