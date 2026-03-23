"""
Supabase persistence backend.

Stores generator state changes and events in a Supabase (PostgreSQL) database
via the REST API.
"""

import json
import logging
import urllib.request

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

def supabase_post(table, payload):
    """POST a JSON payload to a Supabase table."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=SUPABASE_HEADERS, method="POST")
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Supabase insert: {table}")
    except Exception as e:
        log.error(f"Failed to insert to Supabase {table}: {e}")


def supabase_upsert(table, payload):
    """UPSERT a JSON payload to a Supabase table (update or insert by primary key)."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        headers = {
            "apikey"       : SUPABASE_KEY,
            "Content-Type" : "application/json",
            "Prefer"       : "resolution=merge-duplicates,return=minimal",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Supabase upsert: {table}")
    except Exception as e:
        log.error(f"Failed to upsert to Supabase {table}: {e}")


def supabase_get(table, params=""):
    """GET rows from a Supabase table. Returns parsed JSON or None on error."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
        req = urllib.request.Request(url, headers=SUPABASE_HEADERS, method="GET")
        response = urllib.request.urlopen(req, timeout=10)
        return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        log.error(f"Failed to fetch from Supabase {table}: {e}")
        return None


def get_current_runtime_hours():
    """Fetch current generator_runtime_hours from generator_status row 1."""
    rows = supabase_get("generator_status", "id=eq.1&select=generator_runtime_hours")
    if rows and len(rows) > 0:
        return float(rows[0].get("generator_runtime_hours") or 0.0)
    return 0.0


# ── Concrete implementation ──────────────────────────────────────────────────

class SupabasePersistence(PersistenceBackend):
    """Stores state changes and events in Supabase."""

    def publish_state_change(self, old_state, new_state, data, duration_seconds):
        from datetime import datetime, timezone
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
        status = {
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
            # Accumulate runtime hours — outage only, never exercise
            duration_hours = duration_seconds / 3600.0
            current_hours  = get_current_runtime_hours()
            new_hours      = round(current_hours + duration_hours, 4)
            status["generator_runtime_hours"] = new_hours
            log.info(
                f"Generator runtime: +{duration_hours:.4f}h "
                f"({current_hours:.4f} → {new_hours:.4f}h total)"
            )

        supabase_upsert("generator_status", status)
