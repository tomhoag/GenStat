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

Staleness watchdog:
  If no successful serial read happens for `stale_threshold_minutes`
  (monitor.conf, default 15), the monitor sends an APNs alert and exits.
  launchd's KeepAlive then restarts it — this catches the "process alive
  but serial silently dead" failure mode that KeepAlive alone misses.

Run (real hardware):
  python3 generator_monitor.py

Run (mock mode):
  python3 generator_monitor.py --mock
  python3 generator_monitor.py --mock --scenario weekly_test
  python3 generator_monitor.py --mock --scenario all_states --block-delay 3

Available scenarios: normal, weekly_test, outage, critical, all_states
"""

import argparse
import logging
import time
from datetime import datetime, timezone

import serial

from interfaces import Notifier, PersistenceBackend, State, STATE_MESSAGES, TransferSwitchData
from config_secrets import config
from transfer_switch import KohlerRDTReader, MockKohlerReader, MOCK_SCENARIOS
from persistence_supabase import SupabasePersistence
from notifier_apns import APNsNotifier


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

POLL_INTERVAL = config.getint("monitor", "poll_interval")

# How long the monitor can go without a successful serial read before it
# alerts and restarts itself. Add `stale_threshold_minutes = 15` under
# [monitor] in monitor.conf to override; defaults to 15 if not set.
STALE_THRESHOLD_MINUTES = config.getint(
    "monitor", "stale_threshold_minutes", fallback=15
)


# ── State change handler ────────────────────────────────────────────────────

def on_state_change(old_state: State, new_state: State, data: TransferSwitchData,
                    duration_seconds: int, persistence: PersistenceBackend,
                    notifiers: list[Notifier]) -> None:
    """Called whenever the system state changes."""
    log.info(f"State change: {old_state.value} → {new_state.value} (was in {old_state.value} for {duration_seconds}s)")

    persistence.publish_state_change(old_state, new_state, data, duration_seconds)

    for notifier in notifiers:
        notifier.notify_state_change(old_state, new_state, data)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
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

    notifiers = [APNsNotifier(persistence)]

    if args.mock:
        reader = MockKohlerReader(scenario=args.scenario, block_delay=args.block_delay)
    else:
        try:
            reader = KohlerRDTReader()
        except serial.SerialException as e:
            log.error(f"Could not open serial port: {e}")
            return

    # Seed state from Supabase so a restart doesn't trigger a spurious
    # UNKNOWN → NORMAL transition that overwrites the real updated_at.
    current_state = State.UNKNOWN
    state_entered_at = time.time()

    saved_state, saved_at = persistence.get_current_state()
    if saved_state:
        try:
            current_state = State(saved_state)
            if saved_at:
                dt = datetime.fromisoformat(saved_at)
                state_entered_at = dt.timestamp()
            log.info(f"Resumed state from Supabase: {current_state.value}")
        except ValueError:
            log.warning(f"Unknown state in Supabase: {saved_state}, starting as UNKNOWN")

    # Staleness watchdog: tracks the last time we successfully parsed a
    # status block. Reset to "now" at startup so a monitor that comes up
    # with hardware already broken still gets a bounded grace period
    # before it alerts, rather than alerting instantly on every restart.
    last_successful_read = time.time()
    stale_alert_sent = False

    try:
        while True:
            log.info("Waiting for status block...")
            data = reader.read_status()

            if data is None:
                log.warning("No data received — check serial connection")

                stale_for = time.time() - last_successful_read
                if stale_for >= STALE_THRESHOLD_MINUTES * 60 and not stale_alert_sent:
                    stale_minutes = int(stale_for // 60)
                    log.error(
                        f"No successful serial read in {stale_minutes} minutes — "
                        f"alerting and restarting"
                    )
                    for notifier in notifiers:
                        notifier.notify_stale(stale_minutes)
                    stale_alert_sent = True
                    break  # fall through to finally; launchd's KeepAlive restarts us

                if not args.mock:
                    time.sleep(POLL_INTERVAL)
                continue

            log.info(f"Parsed: {data}")
            last_successful_read = time.time()
            stale_alert_sent = False

            new_state = reader.determine_state(data)
            log.info(f"State: {new_state.value} — {STATE_MESSAGES.get(new_state, '')}")

            if new_state != current_state:
                duration = int(time.time() - state_entered_at)
                on_state_change(current_state, new_state, data, duration, persistence, notifiers)
                current_state = new_state
                state_entered_at = time.time()
            else:
                persistence.retry_pending_status()

            if not args.mock:
                time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        reader.close()
        log.info("Connection closed")


if __name__ == "__main__":
    main()
