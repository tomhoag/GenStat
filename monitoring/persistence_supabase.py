"""
Supabase persistence backend.

Stores generator state changes and events in a Supabase (PostgreSQL) database
via the REST API.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from interfaces import PersistenceBackend, State, TransferSwitchData
from config_secrets import require_secret

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

SUPABASE_URL = require_secret("SUPABASE_URL")
SUPABASE_KEY = require_secret("SUPABASE_KEY")
SUPABASE_HEADERS = {
    "apikey"        : SUPABASE_KEY,
    "Content-Type"  : "application/json",
    "Prefer"        : "return=minimal",
}


# ── Supabase helpers ──────────────────────────────────────────────────────────

def supabase_post(table: str, payload: dict[str, Any]) -> None:
    """POST a JSON payload to a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        resp = httpx.post(url, headers=SUPABASE_HEADERS, json=payload, timeout=10)
        resp.raise_for_status()
        log.info(f"Supabase insert: {table}")
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase insert {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase insert {table} network error: {e}")


def supabase_upsert(table: str, payload: dict[str, Any]) -> None:
    """UPSERT a JSON payload to a Supabase table (update or insert by primary key)."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        **SUPABASE_HEADERS,
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        log.info(f"Supabase upsert: {table}")
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase upsert {table} failed ({e.response.status_code}): {e.response.text}")
    except httpx.RequestError as e:
        log.error(f"Supabase upsert {table} network error: {e}")


def supabase_get(table: str, params: str = "") -> list[dict[str, Any]] | None:
    """GET rows from a Supabase table. Returns parsed JSON or None on error."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    try:
        resp = httpx.get(url, headers=SUPABASE_HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        log.error(f"Supabase fetch {table} failed ({e.response.status_code}): {e.response.text}")
        return None
    except httpx.RequestError as e:
        log.error(f"Supabase fetch {table} network error: {e}")
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
