"""
generator_monitor.py

Monitors Kohler RDT transfer switch via RS-232 serial port.
Reads status data every ~30 seconds and determines system state.

States:
  NORMAL          - Utility power present, generator idle
  WEEKLY_TEST     - Utility present, generator running (exercise/test)
  OUTAGE          - Utility down, generator supplying house
  CRITICAL        - Utility down, generator not running

Serial connection:
  Device : /dev/ttyUSB0  (FTDI USB-to-RS232 adapter)
  Baud   : 19200
  Data   : 8N1
  Flow   : XON/XOFF

Notifications:
  Push notifications are sent directly to iOS devices via APNs HTTP/2
  using httpx + PyJWT. The .p8 signing key must be in the project root.

Run (real hardware):
  python3 generator_monitor.py

Run (mock mode):
  python3 generator_monitor.py --mock
  python3 generator_monitor.py --mock --scenario weekly_test
  python3 generator_monitor.py --mock --scenario all_states --block-delay 3

Available scenarios: normal, weekly_test, outage, critical, all_states
"""

import serial
import time
import os
import re
import logging
import argparse
from enum import Enum


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


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

    def __init__(self, scenario="all_states", block_delay=2):
        if scenario not in MOCK_SCENARIOS:
            raise ValueError(
                f"Unknown scenario '{scenario}'. "
                f"Choose from: {list(MOCK_SCENARIOS.keys())}"
            )
        self.blocks      = MOCK_SCENARIOS[scenario]
        self.block_delay = block_delay
        self._block_idx  = 0
        self._lines      = iter([])
        self._load_next_block()
        log.info(
            f"MockSerial: scenario='{scenario}', "
            f"{len(self.blocks)} block(s), "
            f"{block_delay}s between blocks"
        )

    def _load_next_block(self):
        block = self.blocks[self._block_idx % len(self.blocks)]
        log.info(f"MockSerial: loading block {self._block_idx % len(self.blocks) + 1}/{len(self.blocks)}")
        self._block_idx += 1
        self._lines = iter(block.splitlines(keepends=True))

    def readline(self):
        try:
            return next(self._lines).encode("ascii")
        except StopIteration:
            log.debug(f"MockSerial: block done, pausing {self.block_delay}s...")
            time.sleep(self.block_delay)
            self._load_next_block()
            # Return an empty line as a block boundary signal
            return b"\r\n"

    def close(self):
        log.debug("MockSerial: closed")


# ── Configuration ─────────────────────────────────────────────────────────────

SERIAL_PORT     = "/dev/ttyUSB0"
BAUD_RATE       = 19200
READ_TIMEOUT    = 60        # seconds to wait for a complete data block
POLL_INTERVAL   = 35        # seconds between status checks (data arrives ~30s)

# Voltage thresholds — adjust if needed after seeing real data
VOLTAGE_PRESENT = 90        # volts — below this is considered "no power"

# APNs configuration — sends push notifications directly to iOS devices via HTTP/2
APNS_ENABLED     = True
APNS_KEY_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "AuthKey_Y4GY3CS3CF.p8")
APNS_KEY_ID      = "Y4GY3CS3CF"
APNS_TEAM_ID     = "L6BVR86H7Q"
APNS_BUNDLE_ID   = "studio.offbyone.KohlerStat"
APNS_USE_SANDBOX = True     # False for production

# Homebridge webhook configuration
HOMEBRIDGE_ENABLED      = True
HOMEBRIDGE_HOST         = "192.168.1.35"
HOMEBRIDGE_WEBHOOK_PORT = 51828
HOMEBRIDGE_URL          = f"http://{HOMEBRIDGE_HOST}:{HOMEBRIDGE_WEBHOOK_PORT}"

# Accessory IDs — must match config.json in Homebridge
ACCESSORY_GENERATOR     = "generator_active"
ACCESSORY_UTILITY       = "utility_power"

# ── Secrets ───────────────────────────────────────────────────────────────────
# Credentials are loaded from Secrets.xcconfig in the project root (one level
# up from this file's monitoring/ directory).  That file is gitignored and must
# be created manually — copy Secrets.xcconfig.template and fill in your values.
#
# Expected keys in Secrets.xcconfig:
#   SUPABASE_URL = https://your-project.supabase.co
#   SUPABASE_KEY = sb_publishable_...

def _load_secrets():
    """
    Parse Secrets.xcconfig from the project root and return a dict of key→value.
    The file format is one assignment per line:  KEY = value
    Lines starting with // are comments and are ignored.
    """
    import os
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(script_dir, "..", "Secrets.xcconfig")
    secrets_path = os.path.normpath(secrets_path)

    if not os.path.exists(secrets_path):
        raise FileNotFoundError(
            f"Secrets.xcconfig not found at {secrets_path}\n"
            "Copy Secrets.xcconfig.template to Secrets.xcconfig and fill in your values."
        )

    secrets = {}
    with open(secrets_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                secrets[key.strip()] = value.strip()
    return secrets


_secrets = _load_secrets()

def _require_secret(key):
    value = _secrets.get(key, "")
    if not value or value.startswith("<"):
        raise ValueError(
            f"Secret '{key}' is missing or still set to a placeholder value in Secrets.xcconfig."
        )
    return value


# Supabase configuration
SUPABASE_ENABLED  = True
SUPABASE_URL      = _require_secret("SUPABASE_URL")
SUPABASE_KEY      = _require_secret("SUPABASE_KEY")
SUPABASE_HEADERS  = {
    "apikey"        : SUPABASE_KEY,
    "Content-Type"  : "application/json",
    "Prefer"        : "return=minimal",
}


# ── State definitions ─────────────────────────────────────────────────────────

class State(Enum):
    UNKNOWN       = "unknown"
    NORMAL        = "normal"
    WEEKLY_TEST   = "weekly_test"
    OUTAGE        = "outage"
    CRITICAL      = "critical"

STATE_MESSAGES = {
    State.NORMAL      : "✅ Normal — utility power, generator idle",
    State.WEEKLY_TEST : "🔄 Weekly test — generator running, utility present",
    State.OUTAGE      : "⚡ Outage — generator supplying house",
    State.CRITICAL    : "🚨 CRITICAL — utility down AND generator not running!",
}


# ── Serial data parser ────────────────────────────────────────────────────────

class TransferSwitchData:
    """Parsed data from one status block."""

    def __init__(self):
        self.normal_voltage      = None   # float, utility volts
        self.normal_frequency    = None   # float, utility Hz
        self.emergency_voltage   = None   # float, generator volts
        self.emergency_frequency = None   # float, generator Hz
        self.position            = None   # "normal" or "emergency"
        self.exerciser_active    = False
        self.test_mode_active    = False
        self.raw_lines           = []

    def __repr__(self):
        return (
            f"TransferSwitchData("
            f"utility={self.normal_voltage}V, "
            f"generator={self.emergency_voltage}V, "
            f"position={self.position}, "
            f"exercise={self.exerciser_active}, "
            f"test={self.test_mode_active})"
        )


def parse_block(lines):
    """
    Parse a list of text lines into a TransferSwitchData.
    Field names match Figure 5-9 of Kohler RDT manual TP-6346.
    Adjust regexes here if your firmware uses different text.
    """
    data = TransferSwitchData()
    data.raw_lines = lines

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


def determine_state(data):
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

    utility_up   = data.normal_voltage    >= VOLTAGE_PRESENT
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


# ── Serial reader ─────────────────────────────────────────────────────────────

def read_status_block(ser):
    """
    Read lines from serial port until we have a complete status block.
    Resets when it sees a new 'Code Version' header to avoid block bleed.
    Returns a list of lines, or None on timeout.
    """
    lines               = []
    found_normal_v      = False
    found_emergency_v   = False
    found_position      = False
    deadline            = time.time() + READ_TIMEOUT

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
                lines             = []
                found_normal_v    = False
                found_emergency_v = False
                found_position    = False

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

        except Exception as e:
            log.error(f"Serial read error: {e}")
            return None

    log.warning("Timed out waiting for status block")
    return None


# ── Homebridge webhook ────────────────────────────────────────────────────────

def update_homebridge(accessory_id, state):
    """
    Update a Homebridge occupancy sensor state via HTTP webhook.
    state must be True (occupied) or False (not occupied).
    """
    if not HOMEBRIDGE_ENABLED:
        log.info(f"[homebridge disabled] {accessory_id} = {state}")
        return
    try:
        import urllib.request
        state_str = "true" if state else "false"
        url = f"{HOMEBRIDGE_URL}/?accessoryId={accessory_id}&state={state_str}"
        urllib.request.urlopen(url, timeout=5)
        log.info(f"Homebridge updated: {accessory_id} = {state_str}")
    except Exception as e:
        log.error(f"Failed to update Homebridge: {e}")


# ── Supabase ──────────────────────────────────────────────────────────────────

def supabase_post(table, payload):
    """POST a JSON payload to a Supabase table."""
    if not SUPABASE_ENABLED:
        log.info(f"[supabase disabled] {table}: {payload}")
        return
    try:
        import urllib.request, json
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=SUPABASE_HEADERS, method="POST")
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Supabase insert: {table}")
    except Exception as e:
        log.error(f"Failed to insert to Supabase {table}: {e}")


def supabase_upsert(table, payload):
    """UPSERT a JSON payload to a Supabase table (update or insert by primary key)."""
    if not SUPABASE_ENABLED:
        log.info(f"[supabase disabled] upsert {table}: {payload}")
        return
    try:
        import urllib.request, json
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
    if not SUPABASE_ENABLED:
        return None
    try:
        import urllib.request, json
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


def publish_to_supabase(old_state, new_state, data, duration_seconds):
    """Write state change event and update current status in Supabase."""
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


# ── APNs push notifications ──────────────────────────────────────────────────

_apns_token = None
_apns_token_time = 0


def _get_apns_token():
    """Return a cached APNs JWT, refreshing if older than 45 minutes."""
    global _apns_token, _apns_token_time
    import jwt
    if _apns_token and (time.time() - _apns_token_time) < 2700:
        return _apns_token
    with open(APNS_KEY_PATH, "r") as f:
        key = f.read()
    _apns_token = jwt.encode(
        {"iss": APNS_TEAM_ID, "iat": int(time.time())},
        key,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID},
    )
    _apns_token_time = time.time()
    log.info("APNs JWT refreshed")
    return _apns_token


def _get_device_tokens():
    """Fetch active device tokens from Supabase."""
    rows = supabase_get("device_tokens", "active=eq.true&select=token")
    if not rows:
        return []
    return [row["token"] for row in rows]


def _mark_token_inactive(token):
    """Mark a device token as inactive in Supabase."""
    try:
        import urllib.request, json
        url = f"{SUPABASE_URL}/rest/v1/device_tokens?token=eq.{token}"
        headers = {
            "apikey": SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        data = json.dumps({"active": False}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
        urllib.request.urlopen(req, timeout=10)
        log.info(f"Marked token ...{token[-8:]} inactive")
    except Exception as e:
        log.error(f"Failed to mark token inactive: {e}")


def send_notification(title, message, priority="10"):
    """Send push notification to all registered devices via APNs HTTP/2."""
    if not APNS_ENABLED:
        log.info(f"[apns disabled] {title}: {message}")
        return

    tokens = _get_device_tokens()
    if not tokens:
        log.info("No device tokens registered — skipping push")
        return

    import httpx

    apns_host = (
        "api.development.push.apple.com" if APNS_USE_SANDBOX
        else "api.push.apple.com"
    )
    apns_jwt = _get_apns_token()
    headers = {
        "authorization": f"bearer {apns_jwt}",
        "apns-topic": APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": priority,
    }
    payload = {
        "aps": {
            "alert": {"title": title, "body": message},
            "sound": "default",
        }
    }

    try:
        with httpx.Client(http2=True) as client:
            for token in tokens:
                url = f"https://{apns_host}/3/device/{token}"
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    log.info(f"APNs push sent to ...{token[-8:]}")
                elif resp.status_code == 410:
                    log.warning(f"Token expired: ...{token[-8:]}, marking inactive")
                    _mark_token_inactive(token)
                else:
                    log.error(f"APNs error {resp.status_code}: {resp.text}")
    except Exception as e:
        log.error(f"Failed to send APNs push: {e}")


# ── State change handler ──────────────────────────────────────────────────────

def on_state_change(old_state, new_state, data, duration_seconds=0):
    """Called whenever the system state changes."""
    log.info(f"State change: {old_state.value} → {new_state.value} (was in {old_state.value} for {duration_seconds}s)")

    # ── Publish to Supabase ───────────────────────────────────────────────────
    publish_to_supabase(old_state, new_state, data, duration_seconds)

    # ── Update Homebridge sensors ─────────────────────────────────────────────
    if new_state == State.NORMAL:
        update_homebridge(ACCESSORY_GENERATOR, False)
        update_homebridge(ACCESSORY_UTILITY,   True)
    elif new_state == State.WEEKLY_TEST:
        update_homebridge(ACCESSORY_GENERATOR, True)
        update_homebridge(ACCESSORY_UTILITY,   True)
    elif new_state == State.OUTAGE:
        update_homebridge(ACCESSORY_GENERATOR, True)
        update_homebridge(ACCESSORY_UTILITY,   False)
    elif new_state == State.CRITICAL:
        update_homebridge(ACCESSORY_GENERATOR, False)
        update_homebridge(ACCESSORY_UTILITY,   False)

    # ── Send APNs push notifications ─────────────────────────────────────────
    # Only actionable transitions trigger a notification.
    # Weekly test start/end is routine and does not notify.

    if new_state == State.OUTAGE:
        send_notification(
            "Power Outage",
            f"Utility power lost. Generator is supplying the house.\n"
            f"Generator voltage: {data.emergency_voltage}V",
            priority="10",
        )

    elif new_state == State.CRITICAL:
        send_notification(
            "Generator Critical",
            "Utility power is DOWN and generator is NOT running!\n"
            "Immediate attention required.",
            priority="10",
        )

    elif new_state == State.NORMAL and old_state in (State.OUTAGE, State.CRITICAL):
        send_notification(
            "Power Restored",
            "Utility power is back. Generator has shut down.\n"
            "Remember to verify your weekly exercise schedule.",
            priority="5",
        )


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kohler RDT generator monitor")
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock serial port instead of real hardware"
    )
    parser.add_argument(
        "--scenario", default="all_states",
        choices=list(MOCK_SCENARIOS.keys()),
        help="Mock scenario to run (default: all_states)"
    )
    parser.add_argument(
        "--block-delay", type=float, default=2.0,
        help="Seconds between mock data blocks (default: 2)"
    )
    args = parser.parse_args()

    log.info("Generator monitor starting...")

    if args.mock:
        log.info(f"MOCK MODE — scenario: {args.scenario}")
        ser = MockSerial(scenario=args.scenario, block_delay=args.block_delay)
    else:
        log.info(f"Serial port: {SERIAL_PORT} @ {BAUD_RATE} baud")
        try:
            ser = serial.Serial(
                port     = SERIAL_PORT,
                baudrate = BAUD_RATE,
                bytesize = serial.EIGHTBITS,
                parity   = serial.PARITY_NONE,
                stopbits = serial.STOPBITS_ONE,
                xonxoff  = True,
                timeout  = 5,
            )
            log.info("Serial port opened successfully")
        except serial.SerialException as e:
            log.error(f"Could not open serial port: {e}")
            return

    current_state      = State.UNKNOWN
    state_entered_at   = time.time()

    try:
        while True:
            log.info("Waiting for status block...")
            lines = read_status_block(ser)

            if lines is None:
                log.warning("No data received — check serial connection")
                if not args.mock:
                    time.sleep(POLL_INTERVAL)
                continue

            data = parse_block(lines)
            log.info(f"Parsed: {data}")

            new_state = determine_state(data)
            log.info(f"State: {new_state.value} — {STATE_MESSAGES.get(new_state, '')}")

            if new_state != current_state:
                duration = int(time.time() - state_entered_at)
                on_state_change(current_state, new_state, data, duration)
                current_state    = new_state
                state_entered_at = time.time()

            if not args.mock:
                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        ser.close()
        log.info("Serial port closed")


if __name__ == "__main__":
    main()