# Generator Monitoring Service

The monitoring service runs on a host connected to your Kohler transfer switch and watches your generator around the clock. When utility power drops, the generator kicks in, or something goes wrong, it logs the event to Supabase and sends a push notification to your phone — typically within seconds.

It can run on a **Raspberry Pi** (systemd) or on **macOS** (`launchd`) — see [Deployment](#deployment) for both.

---

## Quick Start

Already have the host set up with the serial adapter? Here's the fastest path to running:

```bash
# 1. Pull the latest code (SSH in first if this is a Pi)
cd ~/GenStat && git pull

# 2. Install dependencies into the venv
~/GenStat/venv/bin/pip install -r monitoring/requirements.txt

# 3. Test without hardware first
cd monitoring
~/GenStat/venv/bin/python generator_monitor.py --mock --scenario all_states

# 4. Verify push notifications work
~/GenStat/venv/bin/python generator_monitor.py --test-push

# 5. Run for real
#    Raspberry Pi:  sudo systemctl restart generator-monitor
#    macOS:          sudo launchctl kickstart -k system/studio.offbyone.genstat
```

If the test push doesn't arrive, see [Troubleshooting](#troubleshooting) below.

---

## How It Works

The service reads voltage data from the transfer switch over RS-232 every ~30 seconds and determines which of four states the system is in:

| Utility Voltage | Generator Voltage | State | What It Means |
|---|---|---|---|
| ≥ 90V | < 90V | **Normal** | Grid power is fine, generator is idle |
| ≥ 90V | ≥ 90V | **Weekly Test** | Generator is exercising, grid still powering the house |
| < 90V | ≥ 90V | **Outage** | Grid is down, generator is running |
| < 90V | < 90V | **Critical** | Grid is down AND generator isn't running — needs attention |

State is determined by voltage readings alone — no firmware flags required.

### What happens when the state changes

When the system transitions between states, two things happen:

1. **The event is recorded** — a row is inserted into Supabase with the previous state, new state, voltages, and how long the previous state lasted. Generator runtime hours are accumulated automatically.

2. **You get a push notification** (for important transitions only):
   - **Outage starts** — "Utility power lost. Generator is supplying the house."
   - **Critical failure** — "Generator is NOT running! Immediate attention required."
   - **Power restored** — "Utility power is back. Check your exercise schedule."
   - Weekly test start/end is routine and doesn't notify.

### Staleness watchdog

If the monitor goes `stale_threshold_minutes` (default 15, see [Configuration](#configuration)) without a single successful serial read, it sends a push alert ("GenStat Not Responding") and exits. On both deployments the process supervisor (`systemd` with `Restart=on-failure`, or `launchd` with `KeepAlive`) then restarts it automatically.

This exists because the supervisor alone only restarts a *crashed* process — a process that stays alive but silently stops receiving serial data (e.g. after a USB adapter reset) looks "healthy" to the supervisor indefinitely. The watchdog turns that failure mode into a normal restart-and-alert instead of a silent, unbounded outage.

---

## ⚠️ Safety Warning

> [!CAUTION]
> **The monitoring hardware requires physical access to the interior of an automatic transfer switch enclosure. This is extremely dangerous work that can result in severe injury or death.**
>
> An automatic transfer switch contains live mains voltage at all times — including on the utility input terminals — even when the generator is off and the circuit breakers inside the panel are open. The utility feed entering the enclosure from the top cannot be de-energized without disconnecting power at the utility meter. Contact with these terminals will cause severe injury or death.
>
> **All electrical work associated with this project must be performed by a licensed electrician.** If you are not a licensed electrician, do not open the transfer switch enclosure, do not route cables through it, and do not connect anything to the terminals or circuit boards inside.
>
> The software components of this project — the Python monitoring script, the iOS app, and the Supabase backend — can all be developed and tested independently without touching the electrical hardware.

---

## Hardware

The system reads from the **Kohler RDT-CFNA-0100B** via its built-in RS-232 serial port. The host at the end of the chain can be either a **Raspberry Pi** (dedicated, low-power, always-on) or a **Mac** (e.g. a Mac mini already running other services) — the serial chain itself is identical either way.

```
Kohler RDT Transfer Switch
  RS-232 port (DB9 female, P7 on MPAC 500 board)
        ↕  DB9 male-to-female flat ribbon cable
  Null modem adapter (DB9, crosses TX/RX lines)
        ↕
  FTDI USB-to-RS232 adapter (DB9 male, FTDI chipset)
        ↕  USB
  Host (Raspberry Pi or Mac)
  /dev/ttyUSB0 (Linux)  or  /dev/cu.usbserial-XXXX (macOS)
```

The chain has four components between the transfer switch and the host:

1. **Flat ribbon cable** — a DB9 male-to-female cable that routes from the P7 connector on the MPAC 500 board out through a gap in the transfer switch enclosure. This gets the serial signal outside the panel without permanent modification.
2. **Null modem adapter** — a DB9 crossover that swaps the TX and RX lines. The RDT's serial port is wired as DTE (like a computer), and so is the FTDI adapter — without the null modem, they'd both be transmitting on the same pin and listening on the same pin. The crossover fixes this.
3. **FTDI USB-to-RS232 adapter** — converts the RS-232 signal levels to USB. Handles level conversion internally, so no separate MAX232 or GPIO wiring is needed.
4. **USB to the host** — the FTDI adapter shows up as `/dev/ttyUSB0` on Linux, or `/dev/cu.usbserial-<serial>` on macOS. The macOS device name is tied to the specific adapter and can change if a different FTDI adapter is used — check `ls /dev/cu.*` and update `monitor.conf` if so.

> For full transfer switch documentation see the [Kohler RDT Manual (TP-6346)](http://www.fireelectronics.com/docs/Kohler%20Literature/lit/tp6346.pdf).

### Serial Protocol

The Kohler MPAC 500 controller outputs status data automatically every ~30 seconds with no query required:

- **Baud:** 19200 | **Data:** 8N1 | **Flow:** XOn/XOff

Each transmission alternates between two data blocks. The one the service uses contains live measurements:

```
Code Version B1.07
Normal Voltage      222
Normal Frequency    60.0
Emergency Voltage   0
Emergency Frequency 0.0
Normal Position
```

`Normal Voltage` is the utility source. `Emergency Voltage` is the generator output. `Normal Position` / `Emergency Position` indicates which source is powering the house. `Exerciser Active` or `Test Mode Active` may appear as additional lines during exercise or test cycles.

> Source: [Kohler RDT Manual, Section 5.6](http://www.fireelectronics.com/docs/Kohler%20Literature/lit/tp6346.pdf#page52)

---

## Requirements

- Python 3.9+
- `pyserial`, `httpx[http2]`, `PyJWT[crypto]` (see `requirements.txt`)
- A host with a USB serial adapter — a Raspberry Pi, a Mac, or any always-on machine — or `--mock` mode for development without hardware
- APNs signing key (`.p8` file) in the project root for push notifications
- A configured `Secrets.xcconfig` with Supabase credentials — see the [root README](../README.md#setup)

---

## Deployment

### File layout (both platforms)

```
~/GenStat/
├── Secrets.xcconfig            ← Supabase credentials (manually copied)
├── AuthKey_Y4GY3CS3CF.p8      ← APNs signing key (manually copied)
├── venv/                       ← Python virtual environment
└── monitoring/
    ├── generator_monitor.py    ← entry point
    ├── monitor.conf            ← all operational settings
    ├── interfaces.py
    ├── config_secrets.py
    ├── supabase_client.py
    ├── transfer_switch.py
    ├── persistence_supabase.py
    ├── notifier_apns.py
    └── tests/                  ← pytest test suite
```

### Running directly (either platform)

```bash
# Real hardware
python3 generator_monitor.py

# Mock mode (no hardware required) — great for development
python3 generator_monitor.py --mock
python3 generator_monitor.py --mock --scenario outage
python3 generator_monitor.py --mock --scenario all_states --block-delay 3

# Test push notification delivery
python3 generator_monitor.py --test-push
```

Available mock scenarios: `normal`, `weekly_test`, `outage`, `critical`, `all_states`

### macOS (`launchd`) — current deployment

Runs as a `LaunchDaemon` so it starts at boot and restarts automatically (`KeepAlive`) if it ever exits — including exits triggered by the staleness watchdog.

```xml
<!-- /Library/LaunchDaemons/studio.offbyone.genstat.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
        <string>studio.offbyone.genstat</string>
    <key>ProgramArguments</key>
        <array>
            <string>/Users/<user>/GenStat/venv/bin/python</string>
            <string>/Users/<user>/GenStat/monitoring/generator_monitor.py</string>
        </array>
    <key>WorkingDirectory</key>
        <string>/Users/<user>/GenStat/monitoring</string>
    <key>UserName</key>
        <string><user></string>
    <key>RunAtLoad</key>
        <true/>
    <key>KeepAlive</key>
        <true/>
    <key>StandardOutPath</key>
        <string>/Users/<user>/GenStat/monitoring/genstat.log</string>
    <key>StandardErrorPath</key>
        <string>/Users/<user>/GenStat/monitoring/genstat.log</string>
</dict>
</plist>
```

```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/studio.offbyone.genstat.plist
sudo launchctl kickstart -k system/studio.offbyone.genstat

# Check it's running
launchctl list | grep offbyone
tail -f /Users/<user>/GenStat/monitoring/genstat.log
```

To restart after a code change, always use `launchctl kickstart -k` rather than manually `kill`-ing and re-launching the process by hand — a manually started process and the daemon's own respawned copy can end up running simultaneously and fighting over the serial port (`"device reports readiness to read but returned no data (device disconnected or multiple access on port?)"` in the log is the symptom).

### Raspberry Pi (`systemd`) — legacy / alternative

The original deployment target, still supported for anyone running this on a dedicated Pi rather than a general-purpose Mac.

```ini
# /etc/systemd/system/generator-monitor.service
# Adjust paths and User to match your Pi setup
[Unit]
Description=Kohler Generator Monitor
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/home/<user>/GenStat/venv/bin/python /home/<user>/GenStat/monitoring/generator_monitor.py
WorkingDirectory=/home/<user>/GenStat/monitoring
Restart=on-failure
RestartSec=30
User=<user>

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable generator-monitor
sudo systemctl start generator-monitor

# Check it's running
sudo systemctl status generator-monitor
```

`install.sh` automates writing and enabling this unit — run it once as root on a fresh Pi (`sudo bash install.sh`).

---

## Configuration

All operational settings live in **`monitor.conf`** (INI format). Edit this file to change behavior without modifying code:

```ini
[serial]
port = /dev/ttyUSB0
baud_rate = 19200
read_timeout = 60
voltage_threshold = 90

[monitor]
poll_interval = 35
stale_threshold_minutes = 15

[apns]
enabled = true
key_id = Y4GY3CS3CF
team_id = 4MUC8K263B
bundle_id = studio.offbyone.KohlerStat
use_sandbox = true

[network]
timeout = 10
max_retries = 3
retry_delay = 2
```

- **`serial.port`** — `/dev/ttyUSB0` on a Pi; on macOS this is a `/dev/cu.usbserial-XXXX` path that's specific to the physical adapter (check `ls /dev/cu.*`).
- **`monitor.stale_threshold_minutes`** — how long the monitor can go without a successful serial read before it alerts and restarts itself (see [Staleness watchdog](#staleness-watchdog)). Omitting this key defaults to 15.

Credentials (Supabase URL and API key) are stored separately in `Secrets.xcconfig` in the project root — see the [root README](../README.md#setup) for details.

---

## Displaying Status on iPhone

Two ways to see current status on your phone:

1. **The Xcode iOS app** — full native UI, reads the same `generator_status` table. If it's not published to the App Store, a free-tier ("personal team") signature expires after 7 days and needs reinstalling via cable; a paid Apple Developer account + TestFlight avoids that entirely.
2. **`scriptable/GenStat.js`** — a [Scriptable](https://apps.apple.com/us/app/scriptable/id1405459188) (free) Home Screen widget that fetches `generator_status` directly via the Supabase REST API using the publishable/anon key. No Xcode, no signing, no expiry — just paste the script into the Scriptable app and add it as a widget. Good lightweight alternative while the native app is unpublished.

---

## Troubleshooting

**Serial port not found**
The FTDI adapter may have been assigned a different device name. On a Pi, run `ls /dev/ttyUSB*`; on macOS run `ls /dev/cu.usbserial-*`. Update `monitor.conf` with whatever it finds.

**Log shows "No data received" indefinitely, but the process never restarts**
This was a real failure mode before the staleness watchdog was added — `KeepAlive`/`Restart=on-failure` only restart a process that actually exits, and a process stuck retrying a dead serial connection never does. Make sure you're running a version of `generator_monitor.py` with the watchdog (check for `STALE_THRESHOLD_MINUTES` near the top of the file); if it's there and you still see this, `stale_threshold_minutes` may be set unexpectedly high in `monitor.conf`.

**Log shows `"device reports readiness to read but returned no data (device disconnected or multiple access on port?)"`**
Two processes are both holding the serial port open — almost always caused by manually starting the script (`nohup`/foreground) while the supervisor (`launchd`/`systemd`) is also running its own copy. Check for duplicates with `ps aux | grep generator_monitor`, kill the stray one, and use the supervisor's own restart command (`launchctl kickstart -k ...` or `systemctl restart ...`) instead of manual `kill`+relaunch going forward.

**Supabase errors like `[Errno 8] nodename nor servname provided, or not known`**
This is a DNS resolution failure for the Supabase hostname, not a credentials problem. A common cause on the free tier: the project auto-pauses after a period of no API activity (which can happen if the monitor itself was silently down for a while — see the watchdog above) and a paused project's subdomain stops resolving. Check the project's status in the Supabase dashboard and un-pause it if needed; DNS can take a minute or two to come back after resuming.

**No push notification received**
Run `python3 generator_monitor.py --test-push` and check the output. Common causes:
- Device token in Supabase is stale (app was reinstalled) — delete old tokens from the `device_tokens` table and relaunch the app
- Focus mode on the iPhone is blocking notifications — add GenStat to the allowed apps list
- `use_sandbox = true` in `monitor.conf` but the app was built with a production profile (or vice versa)

**Supabase connection errors**
Verify `Secrets.xcconfig` has the correct URL and key. The service retries transient network failures automatically (configurable via `[network]` in `monitor.conf`), but persistent auth errors mean the credentials are wrong.

**Service crashes and restarts**
- Raspberry Pi: check the journal with `journalctl -u generator-monitor -f`.
- macOS: check the log directly with `tail -f monitoring/genstat.log`, and confirm the daemon is loaded with `launchctl list | grep offbyone`.

---

## Architecture

<details>
<summary>For developers working on the codebase — click to expand</summary>

### File Structure

```
monitoring/
├── generator_monitor.py        # Orchestrator: CLI, main loop, state machine, staleness watchdog
├── interfaces.py               # ABCs + shared types (State, TransferSwitchData)
├── config_secrets.py           # Configuration and secrets loading
├── monitor.conf                # Operational settings (serial, APNs, network, staleness)
├── supabase_client.py          # Shared Supabase HTTP client with retry logic
├── transfer_switch.py          # Kohler RDT reader, mock reader, serial parsing
├── persistence_supabase.py     # Supabase persistence backend
├── notifier_apns.py            # APNs push notification notifier
├── requirements.txt
├── install.sh                  # Raspberry Pi / systemd installer
├── README.md
└── tests/                      # pytest test suite

scriptable/
└── GenStat.js                  # iPhone Home Screen widget (Scriptable app)
```

### Interfaces (`interfaces.py`)

Three abstract base classes define the contract between layers:

**`TransferSwitchReader`** — reads hardware status and determines state
- `read_status() → TransferSwitchData | None`
- `determine_state(data) → State`
- `close()`

**`PersistenceBackend`** — stores state changes, events, and device tokens
- `publish_state_change(old_state, new_state, data, duration_seconds)`
- `get_device_tokens() → list[str]`
- `mark_token_inactive(token)`

**`Notifier`** — sends notifications on state transitions
- `notify_state_change(old_state, new_state, data)`
- `notify_stale(minutes_since_last_read)` — sent by the staleness watchdog before it restarts the process

Each notifier implements its own policy for which transitions warrant a notification. Notifiers that need device tokens (e.g., `APNsNotifier`) receive the `PersistenceBackend` via constructor injection rather than accessing the database directly.

### Concrete Implementations

| Interface | Implementation | File |
|---|---|---|
| `TransferSwitchReader` | `KohlerRDTReader` | `transfer_switch.py` |
| `TransferSwitchReader` | `MockKohlerReader` | `transfer_switch.py` |
| `PersistenceBackend` | `SupabasePersistence` | `persistence_supabase.py` |
| `Notifier` | `APNsNotifier` | `notifier_apns.py` |

### Infrastructure

**`supabase_client.py`** provides the shared Supabase HTTP access layer with `post()`, `upsert()`, `get()`, `patch()` operations and exponential backoff retry on transient network failures. Both `SupabasePersistence` and device token management use this single client.

**`config_secrets.py`** loads two configuration sources:
- `monitor.conf` — operational settings (serial port, APNs, network retry parameters, staleness threshold)
- `Secrets.xcconfig` — credentials for Supabase (gitignored)

### Extending

To add a new transfer switch protocol (e.g., CT clamps), implement `TransferSwitchReader` in a new file. To swap Supabase for another database, implement `PersistenceBackend` — notifiers will automatically use the new backend for device tokens since they access tokens through the interface, not Supabase directly. The orchestrator wires components together in `main()`.

</details>

---

## License

[Licensed under the MIT License](../GenStat/LICENSE.md)
