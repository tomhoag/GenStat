# Generator Monitoring Service

A Python script that reads real-time status data from a Kohler RDT transfer switch via RS-232 serial port and publishes state changes to Supabase, Homebridge (HomeKit), and Ntfy push notifications.

---

## Hardware

The monitoring system is built around a **Raspberry Pi 2B** mounted near the transfer switch. It connects to the **Kohler RDT-CFNA-0100B** transfer switch via the transfer switch's built-in RS-232 serial port (labeled P7 on the MPAC 500 controller board).

The serial chain is:

```
Kohler RDT Transfer Switch
  RS-232 port (DB9 female, P7 on MPAC 500 board)
        ↕  DB9 male-to-female flat ribbon cable
  MAX3232 RS-232 to TTL level converter module
        ↕  jumper wires (TX→RX, RX→TX, GND, 3.3V)
  Raspberry Pi 2B
  GPIO UART pins (/dev/serial0)
```

The MAX3232 module converts the RS-232 voltage levels (±12V) to 3.3V TTL logic levels safe for the Pi's GPIO pins. A flat ribbon cable routes through a gap in the transfer switch enclosure to keep the installation clean and non-invasive — no wiring is modified inside the panel.

A CP2102 USB-to-TTL adapter is used during initial setup and debugging to capture raw serial output on a Mac for verification before switching to the permanent Pi connection.

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

When the state changes, the script publishes to three destinations:

1. **Supabase** — Inserts an event row into `generator_events` and upserts the current status in `generator_status`. Tracks generator runtime hours (outage only, exercise excluded).
2. **Homebridge** — HTTP webhook updates two HomeKit occupancy sensors (`generator_active` and `utility_power`). See the [root README](../README.md#homekit-integration) for HomeKit details.
3. **Ntfy** — Push notification to the homeowner's phone. Priority varies by state (urgent for critical, high for outage, low for exercise).

---

## Requirements

- Python 3.7+
- `pyserial` (see `requirements.txt`)
- Raspberry Pi with UART enabled, or `--mock` mode for development without hardware

---

## Deployment

### 1. Copy files to the Raspberry Pi

Copy the `monitoring/` directory and `Secrets.xcconfig` to the Pi, preserving the directory structure. The script resolves `Secrets.xcconfig` relative to its own location (`../Secrets.xcconfig`), so the layout must be:

```
GenStat/                        ← project root on the Pi
├── Secrets.xcconfig            ← credentials (gitignored, manually copied)
└── monitoring/
    └── generator_monitor.py
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

### 4. Run as a systemd service

To start automatically on boot and restart on failure, create a systemd unit file:

```ini
# /etc/systemd/system/generator-monitor.service
[Unit]
Description=Kohler Generator Monitor
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/GenStat/monitoring/generator_monitor.py
WorkingDirectory=/home/pi/GenStat/monitoring
Restart=always
RestartSec=10
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

The following constants at the top of `generator_monitor.py` can be adjusted:

| Constant | Default | Description |
|---|---|---|
| `SERIAL_PORT` | `/dev/serial0` | Pi UART device |
| `BAUD_RATE` | `19200` | Kohler RDT serial speed |
| `READ_TIMEOUT` | `60` | Seconds to wait for a complete data block |
| `POLL_INTERVAL` | `35` | Seconds between status checks |
| `VOLTAGE_PRESENT` | `90` | Volts — below this is considered "no power" |
| `NTFY_ENABLED` | `False` | Enable Ntfy push notifications |
| `NTFY_URL` | — | Your Ntfy topic URL |
| `HOMEBRIDGE_ENABLED` | `True` | Enable Homebridge webhook updates |
| `HOMEBRIDGE_HOST` | `192.168.1.35` | Homebridge Pi IP address |
| `HOMEBRIDGE_WEBHOOK_PORT` | `51828` | Homebridge webhook port |

---

## License

[Licensed under the MIT License](../GenStat/LICENSE.md)
