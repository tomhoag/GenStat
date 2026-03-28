"""Tests for interfaces.py — State enum, STATE_MESSAGES, TransferSwitchData."""

from interfaces import State, STATE_MESSAGES, TransferSwitchData


class TestStateEnum:

    def test_values(self):
        assert State.UNKNOWN.value == "unknown"
        assert State.NORMAL.value == "normal"
        assert State.WEEKLY_TEST.value == "weekly_test"
        assert State.OUTAGE.value == "outage"
        assert State.CRITICAL.value == "critical"

    def test_all_states_have_messages(self):
        """Every state except UNKNOWN should have a display message."""
        for state in State:
            if state == State.UNKNOWN:
                continue
            assert state in STATE_MESSAGES, f"Missing message for {state}"

    def test_unknown_has_no_message(self):
        assert State.UNKNOWN not in STATE_MESSAGES


class TestTransferSwitchData:

    def test_defaults(self):
        data = TransferSwitchData()
        assert data.normal_voltage is None
        assert data.normal_frequency is None
        assert data.emergency_voltage is None
        assert data.emergency_frequency is None
        assert data.position is None
        assert data.exerciser_active is False
        assert data.test_mode_active is False

    def test_repr(self):
        data = TransferSwitchData()
        data.normal_voltage = 222
        data.emergency_voltage = 0
        data.position = "normal"
        r = repr(data)
        assert "utility=222V" in r
        assert "generator=0V" in r
        assert "position=normal" in r
