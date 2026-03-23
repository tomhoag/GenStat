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

import time
import logging
import argparse

import serial

from interfaces import State, STATE_MESSAGES
from config_secrets import config
from transfer_switch import KohlerRDTReader, MockKohlerReader, MOCK_SCENARIOS
from persistence_supabase import SupabasePersistence
from notifier_apns import APNsNotifier
from notifier_homebridge import HomebridgeNotifier


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

POLL_INTERVAL = config.getint("monitor", "poll_interval")


# ── State change handler ────────────────────────────────────────────────────

def on_state_change(old_state, new_state, data, duration_seconds, persistence, notifiers):
    """Called whenever the system state changes."""
    log.info(f"State change: {old_state.value} → {new_state.value} (was in {old_state.value} for {duration_seconds}s)")

    persistence.publish_state_change(old_state, new_state, data, duration_seconds)

    for notifier in notifiers:
        notifier.notify_state_change(old_state, new_state, data)


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
    parser.add_argument(
        "--test-push", action="store_true",
        help="Send a test push notification with verbose logging, then exit"
    )
    args = parser.parse_args()

    # Wire up components
    persistence = SupabasePersistence()

    if args.test_push:
        APNsNotifier(persistence).test_push()
        return

    log.info("Generator monitor starting...")

    notifiers = [APNsNotifier(persistence), HomebridgeNotifier()]

    if args.mock:
        reader = MockKohlerReader(scenario=args.scenario, block_delay=args.block_delay)
    else:
        try:
            reader = KohlerRDTReader()
        except serial.SerialException as e:
            log.error(f"Could not open serial port: {e}")
            return

    current_state      = State.UNKNOWN
    state_entered_at   = time.time()

    try:
        while True:
            log.info("Waiting for status block...")
            data = reader.read_status()

            if data is None:
                log.warning("No data received — check serial connection")
                if not args.mock:
                    time.sleep(POLL_INTERVAL)
                continue

            log.info(f"Parsed: {data}")

            new_state = reader.determine_state(data)
            log.info(f"State: {new_state.value} — {STATE_MESSAGES.get(new_state, '')}")

            if new_state != current_state:
                duration = int(time.time() - state_entered_at)
                on_state_change(current_state, new_state, data, duration, persistence, notifiers)
                current_state    = new_state
                state_entered_at = time.time()

            if not args.mock:
                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        reader.close()
        log.info("Connection closed")


if __name__ == "__main__":
    main()
