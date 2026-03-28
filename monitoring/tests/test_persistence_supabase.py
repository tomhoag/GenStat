"""Tests for persistence_supabase.py — Supabase persistence backend."""

from unittest.mock import patch, MagicMock
import pytest

from interfaces import State, TransferSwitchData
from persistence_supabase import SupabasePersistence


def _make_data(normal_v=222.0, emergency_v=0.0, position="normal"):
    data = TransferSwitchData()
    data.normal_voltage = normal_v
    data.emergency_voltage = emergency_v
    data.position = position
    return data


class TestPublishStateChange:

    @patch("persistence_supabase.db")
    def test_inserts_event(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.UNKNOWN, State.NORMAL, data, 60)

        mock_db.post.assert_called_once()
        event = mock_db.post.call_args[0][1]
        assert event["previous_state"] == "unknown"
        assert event["new_state"] == "normal"
        assert event["utility_voltage"] == 222.0
        assert event["generator_voltage"] == 0.0
        assert event["duration_seconds"] == 60

    @patch("persistence_supabase.db")
    def test_upserts_status(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.UNKNOWN, State.NORMAL, data, 60)

        mock_db.upsert.assert_called_once()
        status = mock_db.upsert.call_args[0][1]
        assert status["id"] == 1
        assert status["current_state"] == "normal"
        assert status["utility_voltage"] == 222.0

    @patch("persistence_supabase.db")
    def test_sets_last_exercise_on_weekly_test(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data(222, 240)

        p.publish_state_change(State.NORMAL, State.WEEKLY_TEST, data, 0)

        status = mock_db.upsert.call_args[0][1]
        assert "last_exercise_at" in status

    @patch("persistence_supabase.db")
    def test_sets_last_outage_on_outage(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data(0, 240, "emergency")

        p.publish_state_change(State.NORMAL, State.OUTAGE, data, 0)

        status = mock_db.upsert.call_args[0][1]
        assert "last_outage_at" in status

    @patch("persistence_supabase.db")
    def test_records_outage_duration_on_recovery(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.OUTAGE, State.NORMAL, data, 3600)

        status = mock_db.upsert.call_args[0][1]
        assert status["last_outage_duration_seconds"] == 3600
        assert status["exercise_schedule_check_needed"] is True

    @patch("persistence_supabase.db")
    def test_does_not_record_outage_duration_on_test_transition(self, mock_db):
        """Transitioning from OUTAGE to WEEKLY_TEST should not set outage duration."""
        mock_db.upsert.return_value = True
        mock_db.get.return_value = [{"generator_runtime_hours": 10.0, "generator_exercise_hours": 5.0}]
        p = SupabasePersistence()
        data = _make_data(222, 240)

        p.publish_state_change(State.OUTAGE, State.WEEKLY_TEST, data, 1800)

        status = mock_db.upsert.call_args[0][1]
        assert "last_outage_duration_seconds" not in status

    @patch("persistence_supabase.db")
    def test_accumulates_runtime_hours_from_outage(self, mock_db):
        mock_db.upsert.return_value = True
        mock_db.get.return_value = [
            {"generator_runtime_hours": 10.0, "generator_exercise_hours": 5.0}
        ]
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.OUTAGE, State.NORMAL, data, 3600)

        status = mock_db.upsert.call_args[0][1]
        assert status["generator_runtime_hours"] == 11.0
        assert "generator_exercise_hours" not in status

    @patch("persistence_supabase.db")
    def test_accumulates_both_hours_from_weekly_test(self, mock_db):
        mock_db.upsert.return_value = True
        mock_db.get.return_value = [
            {"generator_runtime_hours": 10.0, "generator_exercise_hours": 5.0}
        ]
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.WEEKLY_TEST, State.NORMAL, data, 1800)

        status = mock_db.upsert.call_args[0][1]
        assert status["generator_runtime_hours"] == 10.5
        assert status["generator_exercise_hours"] == 5.5

    @patch("persistence_supabase.db")
    def test_does_not_accumulate_hours_from_normal(self, mock_db):
        mock_db.upsert.return_value = True
        p = SupabasePersistence()
        data = _make_data(0, 240, "emergency")

        p.publish_state_change(State.NORMAL, State.OUTAGE, data, 7200)

        status = mock_db.upsert.call_args[0][1]
        assert "generator_runtime_hours" not in status


class TestDirtyRetry:

    @patch("persistence_supabase.db")
    def test_marks_dirty_on_upsert_failure(self, mock_db):
        mock_db.upsert.return_value = False
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.UNKNOWN, State.NORMAL, data, 0)

        assert p._status_dirty is True
        assert p._pending_status is not None

    @patch("persistence_supabase.db")
    def test_retry_succeeds_clears_dirty(self, mock_db):
        mock_db.upsert.side_effect = [False, True]
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.UNKNOWN, State.NORMAL, data, 0)
        assert p._status_dirty is True

        p.retry_pending_status()
        assert p._status_dirty is False
        assert p._pending_status is None

    @patch("persistence_supabase.db")
    def test_retry_noop_when_not_dirty(self, mock_db):
        p = SupabasePersistence()
        p.retry_pending_status()
        mock_db.upsert.assert_not_called()

    @patch("persistence_supabase.db")
    def test_retry_still_dirty_on_repeated_failure(self, mock_db):
        mock_db.upsert.return_value = False
        p = SupabasePersistence()
        data = _make_data()

        p.publish_state_change(State.UNKNOWN, State.NORMAL, data, 0)
        p.retry_pending_status()

        assert p._status_dirty is True


class TestGetCurrentRuntimeHours:

    @patch("persistence_supabase.db")
    def test_returns_values_from_db(self, mock_db):
        mock_db.get.return_value = [
            {"generator_runtime_hours": 42.5, "generator_exercise_hours": 10.25}
        ]
        runtime, exercise = SupabasePersistence._get_current_runtime_hours()
        assert runtime == 42.5
        assert exercise == 10.25

    @patch("persistence_supabase.db")
    def test_returns_zeros_when_no_rows(self, mock_db):
        mock_db.get.return_value = None
        runtime, exercise = SupabasePersistence._get_current_runtime_hours()
        assert runtime == 0.0
        assert exercise == 0.0

    @patch("persistence_supabase.db")
    def test_returns_zeros_when_null_values(self, mock_db):
        mock_db.get.return_value = [
            {"generator_runtime_hours": None, "generator_exercise_hours": None}
        ]
        runtime, exercise = SupabasePersistence._get_current_runtime_hours()
        assert runtime == 0.0
        assert exercise == 0.0
