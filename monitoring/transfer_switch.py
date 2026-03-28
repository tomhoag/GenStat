"""
Kohler RDT transfer switch reader.

Reads status data from a Kohler RDT transfer switch via RS-232 serial port,
parses the TP-6346 data format, and determines system state from voltage readings.

Includes a mock reader for testing without hardware.
"""
from __future__ import annotations

import re
import time
import logging

import serial

from interfaces import TransferSwitchReader, TransferSwitchData, State
from config_secrets import config

log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

SERIAL_PORT = config.get("serial", "port")
BAUD_RATE = config.getint("serial", "baud_rate")
READ_TIMEOUT = config.getint("serial", "read_timeout")
VOLTAGE_PRESENT = config.getint("serial", "voltage_threshold")


# ── Mock serial port ──────────────────────────────────────────────────────────

# Data blocks that mimic real Kohler RDT serial output (Figure 5-9, TP-6346).
# Each scenario is a list of blocks emitted in order, then cycling.

MOCK_SCENARIOS = {

    "normal": [
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
    ],

    "weekly_test": [
        # before test
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
        # test running — generator up, still on utility
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   240\r\n"
            "Emergency Frequency 60.0\r\n"
            "Normal Position\r\n"
            "Exerciser Active\r\n"
        ),
        # test complete
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
    ],

    "outage": [
        # normal
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
        # utility fails, generator takes over
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      0\r\n"
            "Normal Frequency    0.0\r\n"
            "Emergency Voltage   240\r\n"
            "Emergency Frequency 60.0\r\n"
            "Emergency Position\r\n"
        ),
        # utility restored
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
    ],

    "critical": [
        # normal
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
        # utility fails AND generator fails to start
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      0\r\n"
            "Normal Frequency    0.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
    ],

    "all_states": [
        # 1 — NORMAL: utility present, generator idle
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
        # 2 — WEEKLY_TEST: both voltages present, house on utility
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   240\r\n"
            "Emergency Frequency 60.0\r\n"
            "Normal Position\r\n"
            "Exerciser Active\r\n"
        ),
        # 3 — NORMAL: back to normal after test
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
        # 4 — OUTAGE: utility absent, generator supplying house
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      0\r\n"
            "Normal Frequency    0.0\r\n"
            "Emergency Voltage   240\r\n"
            "Emergency Frequency 60.0\r\n"
            "Emergency Position\r\n"
        ),
        # 5 — CRITICAL: utility absent, generator also absent
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      0\r\n"
            "Normal Frequency    0.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Emergency Position\r\n"
        ),
        # 6 — NORMAL: everything restored
        (
            "Code Version B1.07\r\n"
            "Normal Voltage      222\r\n"
            "Normal Frequency    60.0\r\n"
            "Emergency Voltage   0\r\n"
            "Emergency Frequency 0.0\r\n"
            "Normal Position\r\n"
        ),
    ],
}


class MockSerial:
    """
    Mimics serial.Serial readline() using pre-defined scenario blocks.
    When a block is exhausted it pauses briefly then loads the next,
    cycling through the scenario list indefinitely.
    """

    def __init__(self, scenario: str = "all_states", block_delay: float = 2) -> None:
        if scenario not in MOCK_SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario}'. "
                f"Choose from: {list(MOCK_SCENARIOS.keys())}"
            )
        self.blocks = MOCK_SCENARIOS[scenario]
        self.block_delay = block_delay
        self._block_idx = 0
        self._lines = iter([])
        self._load_next_block()
        log.info(
            f"MockSerial: scenario='{scenario}', "
            f"{len(self.blocks)} block(s), "
            f"{block_delay}s between blocks"
        )

    def _load_next_block(self) -> None:
        block = self.blocks[self._block_idx % len(self.blocks)]
        log.info(f"MockSerial: loading block {self._block_idx % len(self.blocks) + 1}/{len(self.blocks)}")
        self._block_idx += 1
        self._lines = iter(block.splitlines(keepends=True))

    def readline(self) -> bytes:
        try:
            return next(self._lines).encode("ascii")
        except StopIteration:
            log.debug(f"MockSerial: block done, pausing {self.block_delay}s...")
            time.sleep(self.block_delay)
            self._load_next_block()
            # Return an empty line as a block boundary signal
            return b"\r\n"

    def close(self) -> None:
        log.debug("MockSerial: closed")


# ── Serial data parser ────────────────────────────────────────────────────────

def parse_block(lines: list[str]) -> TransferSwitchData:
    """
    Parse a list of text lines into a TransferSwitchData.
    Field names match Figure 5-9 of Kohler RDT manual TP-6346.
    Adjust regexes here if your firmware uses different text.
    """
    data = TransferSwitchData()

    for line in lines:
        line = line.strip()

        m = re.match(r"Normal Voltage\s+([\d.]+)", line, re.IGNORECASE)
        if m:
            data.normal_voltage = float(m.group(1))
            continue

        m = re.match(r"Normal Frequency\s+([\d.]+)", line, re.IGNORECASE)
        if m:
            data.normal_frequency = float(m.group(1))
            continue

        m = re.match(r"Emergency Voltage\s+([\d.]+)", line, re.IGNORECASE)
        if m:
            data.emergency_voltage = float(m.group(1))
            continue

        m = re.match(r"Emergency Frequency\s+([\d.]+)", line, re.IGNORECASE)
        if m:
            data.emergency_frequency = float(m.group(1))
            continue

        if re.match(r"Normal Position", line, re.IGNORECASE):
            data.position = "normal"
            continue

        if re.match(r"Emergency Position", line, re.IGNORECASE):
            data.position = "emergency"
            continue

        if re.match(r"Exerciser Active", line, re.IGNORECASE):
            data.exerciser_active = True
            continue

        if re.match(r"Test Mode Active", line, re.IGNORECASE):
            data.test_mode_active = True
            continue

    return data


def determine_state(data: TransferSwitchData) -> State:
    """
    Determine system state from parsed transfer switch data.
    State is determined by voltage readings only.

      utility present  + generator idle    = NORMAL
      utility present  + generator running = WEEKLY_TEST
      utility absent   + generator running = OUTAGE
      utility absent   + generator idle    = CRITICAL
    """
    if data.normal_voltage is None or data.emergency_voltage is None:
        log.warning("Incomplete data — cannot determine state")
        return State.UNKNOWN

    utility_up = data.normal_voltage >= VOLTAGE_PRESENT
    generator_up = data.emergency_voltage >= VOLTAGE_PRESENT

    if utility_up and not generator_up:
        return State.NORMAL
    if utility_up and generator_up:
        return State.WEEKLY_TEST
    if not utility_up and generator_up:
        return State.OUTAGE
    if not utility_up and not generator_up:
        return State.CRITICAL

    return State.UNKNOWN


def read_status_block(ser) -> list[str] | None:
    """
    Read lines from serial port until we have a complete status block.
    Resets when it sees a new 'Code Version' header to avoid block bleed.
    Returns a list of lines, or None on timeout.
    """
    lines = []
    found_normal_v = False
    found_emergency_v = False
    found_position = False
    deadline = time.time() + READ_TIMEOUT

    while time.time() < deadline:
        try:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue

            # New block starting — reset if we already have some lines
            if "Code Version" in line and lines:
                log.debug("  new block detected, resetting buffer")
                lines = []
                found_normal_v = False
                found_emergency_v = False
                found_position = False

            lines.append(line)
            log.debug(f"  rx: {line}")

            if "Normal Voltage" in line:
                found_normal_v = True
            if "Emergency Voltage" in line:
                found_emergency_v = True
            if "Position" in line:
                found_position = True

            # Return as soon as we have both voltages and position.
            # Exerciser/Test flags will be captured if they appear
            # before the next Code Version header.
            if found_normal_v and found_emergency_v and found_position:
                return lines

        except (OSError, serial.SerialException) as e:
            log.error(f"Serial read error: {e}")
            return None

    log.warning("Timed out waiting for status block")
    return None


# ── Concrete readers ─────────────────────────────────────────────────────────

class KohlerRDTReader(TransferSwitchReader):
    """Reads from a real Kohler RDT transfer switch via RS-232."""

    def __init__(self, port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
        log.info(f"Serial port: {port} @ {baud} baud")
        self._ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=True,
            timeout=5,
        )
        log.info("Serial port opened successfully")

    def read_status(self) -> TransferSwitchData | None:
        lines = read_status_block(self._ser)
        if lines is None:
            return None
        return parse_block(lines)

    def determine_state(self, data: TransferSwitchData) -> State:
        return determine_state(data)

    def close(self) -> None:
        self._ser.close()
        log.info("Serial port closed")


class MockKohlerReader(TransferSwitchReader):
    """Reads from a mock serial port for testing without hardware."""

    def __init__(self, scenario: str = "all_states", block_delay: float = 2.0) -> None:
        log.info(f"MOCK MODE — scenario: {scenario}")
        self._mock = MockSerial(scenario=scenario, block_delay=block_delay)

    def read_status(self) -> TransferSwitchData | None:
        lines = read_status_block(self._mock)
        if lines is None:
            return None
        return parse_block(lines)

    def determine_state(self, data: TransferSwitchData) -> State:
        return determine_state(data)

    def close(self) -> None:
        self._mock.close()
