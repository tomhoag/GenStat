"""
Supabase persistence backend.

Implements the PersistenceBackend interface using the Supabase REST API
via the shared supabase_client module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import supabase_client as db
from interfaces import PersistenceBackend, State, TransferSwitchData

log = logging.getLogger(__name__)


class SupabasePersistence(PersistenceBackend):
    """Stores state changes, events, and device tokens in Supabase."""

    def __init__(self) -> None:
        self._status_dirty = False
        self._pending_status: dict[str, Any] | None = None

    def publish_state_change(self, old_state: State, new_state: State,
                             data: TransferSwitchData, duration_seconds: int) -> None:
        now = datetime.now(timezone.utc).isoformat()

        # Insert event record
        event = {
            "previous_state": old_state.value,
            "new_state": new_state.value,
            "utility_voltage": data.normal_voltage,
            "generator_voltage": data.emergency_voltage,
            "duration_seconds": duration_seconds,
        }
        db.post("generator_events", event)

        # Build status update
        status: dict[str, Any] = {
            "id": 1,
            "updated_at": now,
            "current_state": new_state.value,
            "utility_voltage": data.normal_voltage,
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
            current_runtime, current_exercise = self._get_current_runtime_hours()
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

        if db.upsert("generator_status", status):
            self._status_dirty = False
            self._pending_status = None
        else:
            log.warning("generator_status upsert failed — marking dirty for retry")
            self._status_dirty = True
            self._pending_status = status

    def retry_pending_status(self) -> None:
        if not self._status_dirty or self._pending_status is None:
            return
        self._pending_status["updated_at"] = datetime.now(timezone.utc).isoformat()
        if db.upsert("generator_status", self._pending_status):
            log.info("Dirty generator_status retry succeeded")
            self._status_dirty = False
            self._pending_status = None
        else:
            log.warning("Dirty generator_status retry still failing")

    def get_device_tokens(self) -> list[str]:
        return db.get_device_tokens()

    def mark_token_inactive(self, token: str) -> None:
        db.mark_token_inactive(token)

    def get_current_state(self) -> tuple[str | None, str | None]:
        """Fetch current state and updated_at from generator_status row 1.

        Returns (current_state, updated_at) or (None, None) on failure.
        """
        rows = db.get("generator_status", "id=eq.1&select=current_state,updated_at")
        if rows and len(rows) > 0:
            return rows[0].get("current_state"), rows[0].get("updated_at")
        return None, None

    def _get_current_runtime_hours(self) -> tuple[float, float]:
        """Fetch current runtime and exercise hours from generator_status row 1."""
        rows = db.get("generator_status", "id=eq.1&select=generator_runtime_hours,generator_exercise_hours")
        if rows and len(rows) > 0:
            runtime = float(rows[0].get("generator_runtime_hours") or 0.0)
            exercise = float(rows[0].get("generator_exercise_hours") or 0.0)
            return runtime, exercise
        return 0.0, 0.0
