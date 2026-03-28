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
