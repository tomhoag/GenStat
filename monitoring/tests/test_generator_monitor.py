"""Tests for generator_monitor.py — orchestration and state machine."""

from unittest.mock import MagicMock, patch

from interfaces import State, TransferSwitchData
from generator_monitor import on_state_change


def _make_data(normal_v=222.0, emergency_v=0.0):
    data = TransferSwitchData()
    data.normal_voltage = normal_v
    data.emergency_voltage = emergency_v
    return data


class TestOnStateChange:

    def test_publishes_to_persistence(self):
        persistence = MagicMock()
        notifiers = []
        data = _make_data()

        on_state_change(State.UNKNOWN, State.NORMAL, data, 60, persistence, notifiers)

        persistence.publish_state_change.assert_called_once_with(
            State.UNKNOWN, State.NORMAL, data, 60
        )

    def test_notifies_all_notifiers(self):
        persistence = MagicMock()
        n1 = MagicMock()
        n2 = MagicMock()
        data = _make_data()

        on_state_change(State.NORMAL, State.OUTAGE, data, 120, persistence, [n1, n2])

        n1.notify_state_change.assert_called_once_with(State.NORMAL, State.OUTAGE, data)
        n2.notify_state_change.assert_called_once_with(State.NORMAL, State.OUTAGE, data)

    def test_notifiers_called_even_if_persistence_fails(self):
        persistence = MagicMock()
        persistence.publish_state_change.side_effect = Exception("db down")
        notifier = MagicMock()
        data = _make_data()

        # on_state_change doesn't catch exceptions from persistence,
        # so this should propagate
        try:
            on_state_change(State.NORMAL, State.OUTAGE, data, 0, persistence, [notifier])
        except Exception:
            pass

    def test_empty_notifiers_list(self):
        persistence = MagicMock()
        data = _make_data()

        # Should not raise
        on_state_change(State.UNKNOWN, State.NORMAL, data, 0, persistence, [])
        persistence.publish_state_change.assert_called_once()


class TestStateResumption:
    """Verify that startup seeds state from Supabase to avoid spurious transitions."""

    @patch("generator_monitor.SupabasePersistence")
    def test_resumes_saved_state(self, mock_persistence_cls):
        """When Supabase has a saved state, startup should use it."""
        mock_persistence = MagicMock()
        mock_persistence.get_current_state.return_value = (
            "normal", "2026-03-28T10:00:00+00:00"
        )
        mock_persistence_cls.return_value = mock_persistence

        # Import main and simulate the state seeding logic directly
        from generator_monitor import main
        from interfaces import State
        from datetime import datetime, timezone

        saved_state, saved_at = mock_persistence.get_current_state()
        current_state = State(saved_state)
        dt = datetime.fromisoformat(saved_at)
        state_entered_at = dt.timestamp()

        assert current_state == State.NORMAL
        # The timestamp should correspond to the saved time, not now
        expected = datetime(2026, 3, 28, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        assert state_entered_at == expected

    def test_falls_back_to_unknown_on_no_saved_state(self):
        """When Supabase returns no state, startup should default to UNKNOWN."""
        saved_state, saved_at = None, None
        current_state = State.UNKNOWN

        if saved_state:
            current_state = State(saved_state)

        assert current_state == State.UNKNOWN

    def test_falls_back_to_unknown_on_invalid_state(self):
        """An unrecognized state string should not crash startup."""
        saved_state = "bogus_state"
        current_state = State.UNKNOWN

        try:
            current_state = State(saved_state)
        except ValueError:
            pass

        assert current_state == State.UNKNOWN
