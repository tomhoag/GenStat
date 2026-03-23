# Generator Monitoring Service

The monitoring service runs on a Raspberry Pi connected to your Kohler transfer switch and watches your generator around the clock. When utility power drops, the generator kicks in, or something goes wrong, it logs the event to Supabase, updates HomeKit, and sends a push notification to your phone — typically within seconds.

---

## Quick Start

Already have the Pi set up with the serial adapter? Here's the fastest path to running:

```bash
# 1. Copy files to the Pi
scp monitoring/*.py monitoring/monitor.conf monitoring/requirements.txt \
    tomhoag@192.168.1.140:~/GenStat/monitoring/

# 2. SSH in and install dependencies
pip3 install -r requirements.txt

# 3. Test without hardware first
python3 generator_monitor.py --mock --scenario all_states

# 4. Verify push notifications work
python3 generator_monitor.py --test-push

# 5. Run for real
python3 generator_monitor.py
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

When the system transitions between states, three things happen:

1. **The event is recorded** — a row is inserted into Supabase with the previous state, new state, voltages, and how long the previous state lasted. Generator runtime hours are accumulated automatically.

2. **HomeKit is updated** — two occupancy sensors in Homebridge (`generator_active` and `utility_power`) are set to reflect the new state, so it shows up in the Home app. See the [root README](../README.md#homekit-integration) for details.

3. **You get a push notification** (for important transitions only):
   - **Outage starts** — "Utility power lost. Generator is supplying the house."
   - **Critical failure** — "Generator is NOT running! Immediate attention required."
   - **Power restored** — "Utility power is back. Check your exercise schedule."
   - Weekly test start/end is routine and doesn't notify.

---

## ⚠️ Safety Warning

> [!CAUTION]
> **The monitoring hardware requires physical access to the interior of an automatic transfer switch enclosure. This is extremely dangerous work that can result in severe injury or death.**
>
> An automatic transfer switch contains live mains voltage at all times — including on the utility input terminals — even when the generator is off and the circuit breakers inside the panel are open. The utility feed entering the enclosure from the top cannot be de-energized without disconnecting power at the utility meter. Contact with these terminals will cause severe injury or death.
>
> **All electrical work associated with this project must be performed by a licensed electrician.** If you are not a licensed electrician, do not open the transfer switch enclosure, do not route cables through it, and do not connect anything to the terminals or circuit boards inside.
>
> The software components of this project — the Python monitoring script, the iOS app, the Homebridge integration, and the Supabase backend — can all be developed and tested independently without touching the electrical hardware.

---

## Hardware

The system is built around a **Raspberry Pi 2B** mounted near the transfer switch, connected to the **Kohler RDT-CFNA-0100B** via its built-in RS-232 serial port.

```
Kohler RDT Transfer Switch
  RS-232 port (DB9 female, P7 on MPAC 500 board)
        ↕  DB9 male-to-female flat ribbon cable
  Null modem adapter (DB9, crosses TX/RX lines)
        ↕
  FTDI USB-to-RS232 adapter (DB9 male, FTDI chipset)
        ↕  USB
  Raspberry Pi 2B
  /dev/ttyUSB0
```

The chain has four components between the transfer switch and the Pi:

1. **Flat ribbon cable** — a DB9 male-to-female cable that routes from the P7 connector on the MPAC 500 board out through a gap in the transfer switch enclosure. This gets the serial signal outside the panel without permanent modification.
2. **Null modem adapter** — a DB9 crossover that swaps the TX and RX lines. The RDT's serial port is wired as DTE (like a computer), and so is the FTDI adapter — without the null modem, they'd both be transmitting on the same pin and listening on the same pin. The crossover fixes this.
3. **FTDI USB-to-RS232 adapter** — converts the RS-232 signal levels to USB. Handles level conversion internally, so no separate MAX232 or GPIO wiring is needed.
4. **USB to the Pi** — the FTDI adapter shows up as `/dev/ttyUSB0`.

The same chain (minus the Pi) can be plugged into a Mac for initial verification of the serial data format before deploying.

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
- Raspberry Pi with USB serial adapter, or `--mock` mode for development without hardware
- APNs signing key (`.p8` file) in the project root for push notifications
- A configured `Secrets.xcconfig` with Supabase credentials — see the [root README](../README.md#setup)

---

## Deployment

### File layout on the Pi

```
~/GenStat/
├── Secrets.xcconfig            ← Supabase credentials (manually copied)
├── AuthKey_Y4GY3CS3CF.p8      ← APNs signing key (manually copied)
└── monitoring/
    ├── generator_monitor.py    ← entry point
    ├── monitor.conf            ← all operational settings
    ├── interfaces.py
    ├── config_secrets.py
    ├── supabase_client.py
    ├── transfer_switch.py
    ├── persistence_supabase.py
    ├── notifier_apns.py
    └── notifier_homebridge.py
```

### Running

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

### Running as a systemd service

To start automatically on boot and restart on failure:

```ini
# /etc/systemd/system/generator-monitor.service
# Adjust paths and User to match your Pi setup
[Unit]
Description=Kohler Generator Monitor
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/tomhoag/GenStat/monitoring/generator_monitor.py
WorkingDirectory=/home/tomhoag/GenStat/monitoring
Restart=on-failure
RestartSec=30
User=tomhoag

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

## Troubleshooting

**Serial port not found (`/dev/ttyUSB0`)**
The FTDI adapter may have been assigned a different device name. Run `ls /dev/ttyUSB*` to find it, then update `monitor.conf`.

**No push notification received**
Run `python3 generator_monitor.py --test-push` and check the output. Common causes:
- Device token in Supabase is stale (app was reinstalled) — delete old tokens from the `device_tokens` table and relaunch the app
- Focus mode on the iPhone is blocking notifications — add GenStat to the allowed apps list
- `use_sandbox = true` in `monitor.conf` but the app was built with a production profile (or vice versa)

**Supabase connection errors**
Verify `Secrets.xcconfig` has the correct URL and key. The service retries transient network failures automatically (configurable via `[network]` in `monitor.conf`), but persistent auth errors mean the credentials are wrong.

**Homebridge not updating**
Check that the Homebridge Pi is reachable at the IP and port in `monitor.conf`. The service logs errors but continues running if Homebridge is unavailable.

**Service crashes and restarts**
Check the journal: `journalctl -u generator-monitor -f`. The systemd unit is configured to restart on failure with a 30-second delay.

---

## Architecture

<details>
<summary>For developers working on the codebase — click to expand</summary>

### File Structure

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

Each notifier implements its own policy for which transitions warrant a notification. Notifiers that need device tokens (e.g., `APNsNotifier`) receive the `PersistenceBackend` via constructor injection rather than accessing the database directly.

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

</details>

---

## License

[Licensed under the MIT License](../GenStat/LICENSE.md)
