"""Tests for transfer_switch.py — parsing, state determination, mock reader."""

import pytest

from interfaces import State, TransferSwitchData
from transfer_switch import (
    parse_block, determine_state, read_status_block,
    MockSerial, MockKohlerReader, MOCK_SCENARIOS, VOLTAGE_PRESENT,
)


# ── parse_block ──────────────────────────────────────────────────────────────

class TestParseBlock:

    def test_normal_block(self):
        lines = [
            "Code Version B1.07",
            "Normal Voltage      222",
            "Normal Frequency    60.0",
            "Emergency Voltage   0",
            "Emergency Frequency 0.0",
            "Normal Position",
        ]
        data = parse_block(lines)
        assert data.normal_voltage == 222.0
        assert data.normal_frequency == 60.0
        assert data.emergency_voltage == 0.0
        assert data.emergency_frequency == 0.0
        assert data.position == "normal"
        assert data.exerciser_active is False
        assert data.test_mode_active is False

    def test_outage_block(self):
        lines = [
            "Code Version B1.07",
            "Normal Voltage      0",
            "Normal Frequency    0.0",
            "Emergency Voltage   240",
            "Emergency Frequency 60.0",
            "Emergency Position",
        ]
        data = parse_block(lines)
        assert data.normal_voltage == 0.0
        assert data.emergency_voltage == 240.0
        assert data.position == "emergency"

    def test_exerciser_active(self):
        lines = [
            "Normal Voltage      222",
            "Normal Frequency    60.0",
            "Emergency Voltage   240",
            "Emergency Frequency 60.0",
            "Normal Position",
            "Exerciser Active",
        ]
        data = parse_block(lines)
        assert data.exerciser_active is True
        assert data.test_mode_active is False

    def test_test_mode_active(self):
        lines = [
            "Normal Voltage      222",
            "Emergency Voltage   240",
            "Normal Position",
            "Test Mode Active",
        ]
        data = parse_block(lines)
        assert data.test_mode_active is True

    def test_empty_lines(self):
        data = parse_block([])
        assert data.normal_voltage is None
        assert data.emergency_voltage is None

    def test_case_insensitive(self):
        lines = [
            "normal voltage      120",
            "emergency voltage   0",
            "NORMAL POSITION",
        ]
        data = parse_block(lines)
        assert data.normal_voltage == 120.0
        assert data.emergency_voltage == 0.0
        assert data.position == "normal"


# ── determine_state ──────────────────────────────────────────────────────────

class TestDetermineState:

    def _make_data(self, normal_v, emergency_v):
        data = TransferSwitchData()
        data.normal_voltage = normal_v
        data.emergency_voltage = emergency_v
        return data

    def test_normal(self):
        assert determine_state(self._make_data(222, 0)) == State.NORMAL

    def test_weekly_test(self):
        assert determine_state(self._make_data(222, 240)) == State.WEEKLY_TEST

    def test_outage(self):
        assert determine_state(self._make_data(0, 240)) == State.OUTAGE

    def test_critical(self):
        assert determine_state(self._make_data(0, 0)) == State.CRITICAL

    def test_unknown_when_missing_normal(self):
        assert determine_state(self._make_data(None, 240)) == State.UNKNOWN

    def test_unknown_when_missing_emergency(self):
        assert determine_state(self._make_data(222, None)) == State.UNKNOWN

    def test_threshold_boundary_at_90(self):
        """Exactly at the threshold counts as present."""
        assert determine_state(self._make_data(VOLTAGE_PRESENT, 0)) == State.NORMAL

    def test_threshold_boundary_below_90(self):
        assert determine_state(self._make_data(VOLTAGE_PRESENT - 1, 0)) == State.CRITICAL


# ── MockSerial ───────────────────────────────────────────────────────────────

class TestMockSerial:

    def test_invalid_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            MockSerial(scenario="nonexistent")

    def test_all_scenarios_exist(self):
        for name in MOCK_SCENARIOS:
            mock = MockSerial(scenario=name, block_delay=0)
            # Should be able to read at least one line
            line = mock.readline()
            assert isinstance(line, bytes)
            mock.close()

    def test_readline_returns_bytes(self):
        mock = MockSerial(scenario="normal", block_delay=0)
        line = mock.readline()
        assert isinstance(line, bytes)
        mock.close()

    def test_cycles_through_blocks(self):
        mock = MockSerial(scenario="normal", block_delay=0)
        # Read all lines of the single block
        lines = []
        for _ in range(20):  # more than enough
            line = mock.readline()
            lines.append(line)
        # Should contain the block content at least twice (cycling)
        content = b"".join(lines).decode("ascii")
        assert content.count("Normal Voltage") >= 2
        mock.close()


# ── read_status_block ────────────────────────────────────────────────────────

class TestReadStatusBlock:

    def test_reads_complete_block(self):
        mock = MockSerial(scenario="normal", block_delay=0)
        lines = read_status_block(mock)
        assert lines is not None
        text = "\n".join(lines)
        assert "Normal Voltage" in text
        assert "Emergency Voltage" in text
        assert "Position" in text
        mock.close()

    def test_resets_on_new_code_version(self):
        """If a Code Version header appears mid-block, parsing resets."""
        mock = MockSerial(scenario="normal", block_delay=0)
        lines = read_status_block(mock)
        assert lines is not None
        # The block should be clean (one set of readings)
        voltage_count = sum(1 for l in lines if "Normal Voltage" in l)
        assert voltage_count == 1
        mock.close()


# ── MockKohlerReader ─────────────────────────────────────────────────────────

class TestMockKohlerReader:

    def test_read_status_returns_data(self):
        reader = MockKohlerReader(scenario="normal", block_delay=0)
        data = reader.read_status()
        assert data is not None
        assert data.normal_voltage == 222.0
        assert data.emergency_voltage == 0.0
        reader.close()

    def test_determine_state(self):
        reader = MockKohlerReader(scenario="normal", block_delay=0)
        data = reader.read_status()
        state = reader.determine_state(data)
        assert state == State.NORMAL
        reader.close()

    def test_all_states_scenario(self):
        """The all_states scenario should cycle through multiple states."""
        reader = MockKohlerReader(scenario="all_states", block_delay=0)
        states_seen = set()
        for _ in range(6):
            data = reader.read_status()
            if data:
                states_seen.add(reader.determine_state(data))
        reader.close()
        assert State.NORMAL in states_seen
        assert State.WEEKLY_TEST in states_seen
        assert State.OUTAGE in states_seen
        assert State.CRITICAL in states_seen

    def test_outage_scenario(self):
        reader = MockKohlerReader(scenario="outage", block_delay=0)
        states = []
        for _ in range(3):
            data = reader.read_status()
            if data:
                states.append(reader.determine_state(data))
        reader.close()
        assert states == [State.NORMAL, State.OUTAGE, State.NORMAL]
