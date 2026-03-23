# Generator Monitoring Service

A Python service that reads real-time status data from a Kohler RDT transfer switch via RS-232 serial port and publishes state changes to Supabase, Homebridge (HomeKit), and Apple Push Notification service (APNs).

---

## Architecture

The monitoring service is organized into pluggable layers with defined interfaces, allowing different transfer switch protocols or backend persistence to be swapped in without modifying unrelated code.

```
monitoring/
├── generator_monitor.py        # Orchestrator: CLI, main loop, state machine
├── interfaces.py               # ABCs + shared types (State, TransferSwitchData)
├── config_secrets.py            # Configuration and secrets loading
├── monitor.conf                # Operational settings (serial, APNs, Homebridge, network)
├── supabase_client.py          # Shared Supabase HTTP client with retry logic
├── transfer_switch.py           # Kohler RDT reader, mock reader, serial parsing
├── persistence_supabase.py      # Supabase persistence backend
├── notifier_apns.py             # APNs push notification notifier
├── notifier_homebridge.py       # Homebridge webhook notifier
├── requirements.txt
├── install.sh
└── README.md
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

Each notifier implements its own policy for which transitions warrant a notification. The orchestrator does not need to know notification-specific logic. Notifiers that need device tokens (e.g., `APNsNotifier`) receive the `PersistenceBackend` via constructor injection rather than accessing the database directly.

### Concrete Implementations

| Interface | Implementation | File |
|---|---|---|
| `TransferSwitchReader` | `KohlerRDTReader` | `transfer_switch.py` |
| `TransferSwitchReader` | `MockKohlerReader` | `transfer_switch.py` |
| `PersistenceBackend` | `SupabasePersistence` | `persistence_supabase.py` |
| `Notifier` | `APNsNotifier` | `notifier_apns.py` |
| `Notifier` | `HomebridgeNotifier` | `notifier_homebridge.py` |

### Infrastructure

**`supabase_client.py`** provides the shared Supabase HTTP access layer with `post()`, `upsert()`, `get()`, `patch()` operations and exponential backoff retry on transient network failures. Both `SupabasePersistence` and device token management use this single client.

**`config_secrets.py`** loads two configuration sources:
- `monitor.conf` — operational settings (serial port, APNs, Homebridge, network retry parameters)
- `Secrets.xcconfig` — credentials for Supabase (gitignored)

### Extending

To add a new transfer switch protocol (e.g., CT clamps), implement `TransferSwitchReader` in a new file. To swap Supabase for another database, implement `PersistenceBackend` — notifiers will automatically use the new backend for device tokens since they access tokens through the interface, not Supabase directly. The orchestrator wires components together in `main()`.

---

## Hardware

The monitoring system is built around a **Raspberry Pi 2B** mounted near the transfer switch. It connects to the **Kohler RDT-CFNA-0100B** transfer switch via the transfer switch's built-in RS-232 serial port.

The serial chain is:

```
Kohler RDT Transfer Switch
  RS-232 port (DB9 female, P7 on MPAC 500 board)
        ↕  DB9 male-to-female flat ribbon cable
  FTDI USB-to-RS232 adapter (DB9 male, FTDI chipset)
        ↕  USB
  Raspberry Pi 2B
  /dev/ttyUSB0
```

A flat ribbon cable routes from P7 through a gap in the transfer switch enclosure to the FTDI adapter. The FTDI adapter handles RS-232 level conversion internally and connects to the Pi via USB — no separate level converter or GPIO wiring is required.

The same FTDI adapter can be plugged into a Mac for initial verification of the serial data format before deploying to the Pi.

> For full transfer switch documentation see the [Kohler RDT Manual (TP-6346)](http://www.fireelectronics.com/docs/Kohler%20Literature/lit/tp6346.pdf).

---

## Serial Protocol

The Kohler MPAC 500 controller outputs status data automatically over RS-232 every 30 seconds with no query required. The serial parameters are:

- **Baud rate:** 19200
- **Data bits:** 8
- **Parity:** None
- **Stop bits:** 1
- **Flow control:** XOn/XOff

Each transmission alternates between two data sets. The first contains time delay and exerciser settings. The second — the one the monitoring service uses — contains live measurements:

```
Code Version B1.07
Normal Voltage      222
Normal Frequency    60.0
Emergency Voltage   0
Emergency Frequency 0.0
Normal Position
```

`Normal Voltage` is the utility source voltage. `Emergency Voltage` is the generator output voltage. `Normal Position` / `Emergency Position` indicates which source is currently supplying the load. `Exerciser Active` or `Test Mode Active` may appear as additional lines during exercise or test cycles.

> Source: [Kohler RDT Manual, Section 5.6 Controller Monitoring Using
Hyper Terminal](http://www.fireelectronics.com/docs/Kohler%20Literature/lit/tp6346.pdf#page52)

---

## State Determination

The script determines system state from voltage readings alone — no flag dependency:

| Utility Voltage | Generator Voltage | State |
|---|---|---|
| ≥ 90V | < 90V | **Normal** |
| ≥ 90V | ≥ 90V | **Weekly Test** |
| < 90V | ≥ 90V | **Outage** |
| < 90V | < 90V | **Critical** |

---

## What Happens on State Change

When the state changes, the orchestrator calls each registered component:

1. **Persistence** (`SupabasePersistence`) — Inserts an event row into `generator_events` and upserts the current status in `generator_status`. Tracks generator runtime hours (outage only, exercise excluded).
2. **Notifiers** — Each notifier decides independently whether to act:
   - `APNsNotifier` — Sends iOS push notifications for actionable transitions only: outage start, critical failure, and power restored. Weekly test is routine and does not notify.
   - `HomebridgeNotifier` — Updates two HomeKit occupancy sensors (`generator_active` and `utility_power`) on every state change. See the [root README](../README.md#homekit-integration) for HomeKit details.

---

## Requirements

- Python 3.7+
- `pyserial`, `httpx[http2]`, `PyJWT[crypto]` (see `requirements.txt`)
- Raspberry Pi with USB serial adapter, or `--mock` mode for development without hardware
- APNs signing key (`.p8` file) in the project root for push notifications

---

## Deployment

### 1. Copy files to the Raspberry Pi

Copy the `monitoring/` directory, `Secrets.xcconfig`, and the APNs signing key to the Pi, preserving the directory structure:

```
GenStat/                        ← project root on the Pi
├── Secrets.xcconfig            ← credentials (gitignored, manually copied)
├── AuthKey_Y4GY3CS3CF.p8      ← APNs signing key (gitignored, manually copied)
└── monitoring/
    ├── generator_monitor.py
    ├── interfaces.py
    ├── config_secrets.py
    ├── monitor.conf
    ├── supabase_client.py
    ├── transfer_switch.py
    ├── persistence_supabase.py
    ├── notifier_apns.py
    └── notifier_homebridge.py
```

### 2. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 3. Run

**Real hardware:**

```bash
python3 generator_monitor.py
```

**Mock mode (no hardware required):**

```bash
python3 generator_monitor.py --mock
python3 generator_monitor.py --mock --scenario weekly_test
python3 generator_monitor.py --mock --scenario all_states --block-delay 3
```

Available mock scenarios: `normal`, `weekly_test`, `outage`, `critical`, `all_states`

**Test push notification:**

```bash
python3 generator_monitor.py --test-push
```

### 4. Run as a systemd service

To start automatically on boot and restart on failure, create a systemd unit file:

```ini
# /etc/systemd/system/generator-monitor.service
# Note: verify all paths match your Pi's actual directory structure before installing
[Unit]
Description=Kohler Generator Monitor
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/GenStat/monitoring/generator_monitor.py
WorkingDirectory=/home/pi/GenStat/monitoring
Restart=on-failure
RestartSec=30
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable generator-monitor
sudo systemctl start generator-monitor
```

---

## Configuration

All operational settings are in **`monitor.conf`** (INI format). Edit this file to change behavior without modifying code:

```ini
[serial]
port = /dev/ttyUSB0
baud_rate = 19200
read_timeout = 60
voltage_threshold = 90

[monitor]
poll_interval = 35

[apns]
enabled = true
key_id = Y4GY3CS3CF
team_id = 4MUC8K263B
bundle_id = studio.offbyone.KohlerStat
use_sandbox = true

[homebridge]
enabled = true
host = 192.168.1.35
port = 51828
generator_id = generator_active
utility_id = utility_power

[network]
timeout = 10
max_retries = 3
retry_delay = 2
```

Credentials (Supabase URL and API key) are stored separately in `Secrets.xcconfig` in the project root — see the [root README](../README.md#setup) for details.

---

## License

[Licensed under the MIT License](../GenStat/LICENSE.md)
