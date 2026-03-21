# GenStat

A SwiftUI iPhone app for monitoring a Kohler residential standby generator and automatic transfer switch in real time.

<!-- Hero image placeholder -->
![GenStat Screenshot](docs/hero.png)

## Introduction

GenStat provides at-a-glance visibility into the operational state of a home standby generator system. The app displays the current generator status, runtime hours, exercise history, last outage details, and a scrollable log of every state-change event — all pulled from a Supabase backend that is updated every 30 seconds by an external monitoring service running on a Raspberry Pi.

### Key Features

- **Live status display** — Ready, Exercising, Running, Critical, or Unknown with severity-based color coding
- **Generator visualization** — Custom power flow diagram showing which source — utility or generator — is currently supplying the house
- **Runtime tracking** — Total generator hours (outage only, exercise excluded), days since last exercise (highlighted in red when overdue), and last outage with duration
- **Event log** — Chronological history of every state transition with voltage readings and duration, loaded via infinite scroll pagination
- **Foreground refresh** — Automatic refresh on launch and when the app is brought to the foreground, with a manual refresh button
- **Error handling** — Dismissable error banner with automatic recovery on the next successful poll
- **Quick-access manuals** — Toolbar menu linking to generator and transfer switch documentation

---

## ⚠️ Safety Warning

**The monitoring hardware described in this project requires physical access to the interior of an automatic transfer switch enclosure. This is extremely dangerous work.**

An automatic transfer switch contains live mains voltage at all times — including on the utility input terminals — even when the generator is off and the circuit breakers inside the panel are open. The utility feed entering the enclosure from the top cannot be de-energized without disconnecting power at the utility meter. Contact with these terminals will cause severe injury or death.

**This work should only be performed by a licensed electrician.** If you are not a licensed electrician, do not open the transfer switch enclosure, do not route cables through it, and do not connect anything to the terminals or circuit boards inside.

The software components of this project — the Python monitoring script, the iOS app, the Homebridge integration, and the Supabase backend — can all be developed and tested independently without touching the electrical hardware.

---

## Motivation

### The Problem

Residential standby generators run infrequently — typically a weekly exercise cycle and the occasional power outage. Between those events they sit idle, and most homeowners have no easy way to confirm the system is healthy without physically walking to the generator or the transfer switch panel to check the status LEDs.

This creates several blind spots:

- **Missed exercise cycles** — The Kohler RDT transfer switch has a known firmware issue where the weekly exercise schedule is cleared after a transfer event. Without visibility, the schedule may go unset for weeks or months without the homeowner knowing.
- **Silent failures** — If the generator fails to start during an outage, the homeowner may not know until they notice the lights are out. There is no built-in notification system.
- **No outage history** — The transfer switch has no accessible log. There is no way to know when the last outage occurred, how long it lasted, or how many hours the generator has accumulated.
- **Maintenance timing** — Generator manufacturers recommend service intervals based on runtime hours, but tracking those hours manually against a machine that runs for 20 minutes a week is impractical.

### The Solution

GenStat is the consumer-facing half of a complete home generator monitoring system built around an automatic transfer switch that already existed in the home. The backend monitoring service reads real-time data from the transfer switch's RS-232 serial port every 30 seconds, determines the current system state, and writes it to a cloud database. GenStat reads that database and presents the information in a clear, glanceable format on the homeowner's iPhone.

The system catches all four meaningful states:

| State | Meaning |
|---|---|
| **Normal** | Utility power present, generator idle — everything is fine |
| **Weekly Test** | Generator running its exercise cycle — both voltages present |
| **Outage** | Utility power lost, generator supplying the house |
| **Critical** | Utility power lost AND generator not running — immediate attention required |

---

## Monitoring Hardware and Software

### Hardware

The monitoring system is built around a **Raspberry Pi 2B** mounted in the basement near the transfer switch. It connects to the **Kohler RDT-CFNA-0100B** transfer switch via the transfer switch's built-in RS-232 serial port (labeled P7 on the MPAC 500 controller board).

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

### Serial Protocol

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

### Monitoring Software

The monitoring service is a Python script (`generator_monitor.py`) running on the Raspberry Pi as a `systemd` service, so it starts automatically on boot and restarts on failure.

The script:

1. **Reads serial data** from `/dev/serial0` and waits for a complete status block containing both voltage readings and a position indicator
2. **Parses the block** using regex to extract utility voltage, generator voltage, switch position, and exercise/test flags
3. **Determines system state** from voltage readings alone — no flag dependency:
   - Utility voltage ≥ 90V and generator voltage < 90V → **Normal**
   - Both voltages ≥ 90V → **Weekly Test**
   - Utility voltage < 90V and generator voltage ≥ 90V → **Outage**
   - Both voltages < 90V → **Critical**
4. **On state change**, publishes to three destinations:
   - **Supabase** — inserts an event row and upserts the current status row
   - **Homebridge** — HTTP webhook updates two HomeKit occupancy sensors
   - **Ntfy** — push notification to the homeowner's phone (configurable)
5. **Accumulates generator runtime hours** — tracks time spent in `Outage` state only, excluding exercise cycles, and updates a running total in the Supabase `generator_status` table

The script has a `--mock` flag with configurable scenarios (`normal`, `weekly_test`, `outage`, `critical`, `all_states`) for testing without hardware, which was used to validate the full pipeline before the serial hardware arrived.

### Backend Database

All monitoring data is stored in **Supabase** (hosted PostgreSQL with REST API). Two tables are used:

**`generator_status`** — a single row (id = 1) representing the current state of the system, updated on every state change.

**`generator_events`** — an append-only log of every state transition, with voltages and duration in the previous state.

Both tables use Row Level Security with policies allowing anonymous read access (for the iOS app) and anon-role write access (for the monitoring service).

---

## HomeKit Integration

### Overview

In addition to the Supabase backend, the monitoring service integrates with **Apple HomeKit** via **Homebridge**, allowing generator status to appear natively in the iOS Home app alongside other smart home devices.

### Infrastructure

Homebridge runs on a separate Raspberry Pi elsewhere in the home. The monitoring Pi and the Homebridge Pi communicate over the local network via simple HTTP calls — the monitoring Pi sends webhook requests to Homebridge whenever the generator state changes.

```
Monitoring Pi (basement)
    ↓ HTTP webhook (local network)
Homebridge Pi
    ↓ HomeKit protocol
iOS Home app
```

### HomeKit Accessories

The `homebridge-http-webhooks` plugin is used on the Homebridge Pi. It exposes two **occupancy sensors** in HomeKit:

| Accessory | Occupied when | Unoccupied when |
|---|---|---|
| **Generator Active** | Generator is running (weekly test or outage) | Generator is idle |
| **Utility Power** | Utility grid is present | Utility grid is down |

From these two binary sensors all four system states can be inferred:

| Generator Active | Utility Power | System State |
|---|---|---|
| Off | On | Normal |
| On | On | Weekly Test |
| On | Off | Outage |
| Off | Off | Critical |

### Webhook URL Format

The monitoring service calls the Homebridge webhook server using simple HTTP GET requests:

```
# Set generator_active to occupied
http://192.168.1.35:51828/?accessoryId=generator_active&state=true

# Set utility_power to unoccupied
http://192.168.1.35:51828/?accessoryId=utility_power&state=false
```

### Homebridge Configuration

The relevant section of the Homebridge `config.json`:

```json
{
    "platform": "HttpWebHooks",
    "webhook_port": 51828,
    "cache_directory": "/var/lib/homebridge/.webhook-cache",
    "sensors": [
        {
            "id": "generator_active",
            "name": "Generator Active",
            "type": "occupancy"
        },
        {
            "id": "utility_power",
            "name": "Utility Power",
            "type": "occupancy"
        }
    ]
}
```

### Behavior During Network Outage

If the home network is unavailable (e.g. during a power outage where the network equipment is not on a generator-backed circuit), the HomeKit webhook calls will fail silently — the monitoring service logs the error and continues. When the network comes back up, the next state change will update the HomeKit sensors correctly. The Supabase notifications and the GenStat app follow the same pattern — they work when the network is available and catch up on the next successful connection.

---

## Architecture

### Tech Stack

| Layer | Technology |
|---|---|
| UI | SwiftUI (iOS 26+) |
| State | `@Observable` / `@State` |
| Networking | `URLSession` async/await |
| Backend | Supabase (PostgreSQL + REST API) |
| Language | Swift 6.2, strict concurrency |

### Project Structure

```
GenStat/
├── GenStatApp.swift              # App entry point
├── Models/
│   ├── GeneratorState.swift      # Raw DB state enum (normal, weekly_test, outage, critical, unknown)
│   ├── DisplayStatus.swift       # User-facing status enum with labels and colors
│   ├── GeneratorStatus.swift     # Current status snapshot (Codable model)
│   └── GeneratorEvent.swift      # State-change event (Codable model)
├── Services/
│   ├── SupabaseService.swift     # REST API client with ISO 8601 date decoding
│   └── GeneratorMonitor.swift    # @Observable polling controller
├── Views/
│   ├── ContentView.swift         # Root view, owns GeneratorMonitor, manages scene lifecycle
│   ├── StatusView.swift          # Main dashboard: power flow diagram, stats, toolbar
│   ├── PowerFlowView.swift       # Replaceable power flow diagram — takes GeneratorState as input only
│   ├── EventLogView.swift        # Paginated event history list
│   ├── EventRow.swift            # Single event row: date, state transition, duration, voltages
│   └── ErrorBanner.swift         # Dismissable error notification banner
└── Assets.xcassets/
```

### Data Flow

```
Supabase REST API
       │
       ▼
 SupabaseService          Static async methods: fetchStatus(), fetchEvents()
       │
       ▼
 GeneratorMonitor         @Observable, @MainActor — owns state and refresh logic
       │
       ▼
   ContentView            @State owner, passes monitor to child views
    ┌──┴──┐
    ▼     ▼
StatusView  EventLogView  Read monitor properties, trigger refresh
```

### UI Architecture Note

`PowerFlowView` is deliberately isolated — it accepts a single `GeneratorState` value and has no knowledge of networking, Supabase, or app logic. The power flow diagram can be redesigned or replaced without touching any other file in the project.

### Database Schema

**`generator_status`** (single row, id = 1)

| Column | Type | Description |
|---|---|---|
| `id` | `int` | Always 1 |
| `updated_at` | `timestamptz` | Last backend update |
| `current_state` | `text` | One of: normal, weekly_test, outage, critical, unknown |
| `utility_voltage` | `float` | Mains voltage |
| `generator_voltage` | `float` | Generator output voltage |
| `generator_runtime_hours` | `float` | Lifetime runtime hours (outage only, excludes exercise) |
| `last_exercise_at` | `timestamptz` | Last completed exercise |
| `last_outage_at` | `timestamptz` | Most recent outage start |
| `last_outage_duration_seconds` | `int` | Most recent outage duration |

**`generator_events`** (append-only log)

| Column | Type | Description |
|---|---|---|
| `id` | `int` | Auto-incrementing primary key |
| `created_at` | `timestamptz` | When the event was recorded |
| `previous_state` | `text` | State before transition |
| `new_state` | `text` | State after transition |
| `utility_voltage` | `float` | Voltage at time of event |
| `generator_voltage` | `float` | Voltage at time of event |
| `duration_seconds` | `int` | How long the previous state lasted |

### Status Color Scheme

| Status | Color | Meaning |
|---|---|---|
| Ready | Green | Generator is standing by, utility power OK |
| Exercising | Blue | Weekly exercise cycle in progress |
| Running | Orange | Generator is powering the home (outage) |
| Critical | Red | Generator fault or alarm condition |
| Unknown | Gray | Cannot determine state (e.g. network error) |

---

## Requirements

- iOS 26.0 or later
- Xcode 26.0 or later
- Swift 6.2
- A Supabase project with the tables described above and RLS policies enabling anonymous `SELECT` access

---

## Setup

1. Clone the repository
2. Copy `Secrets.xcconfig.template` to `Secrets.xcconfig` and fill in your Supabase project URL and publishable API key (the real `Secrets.xcconfig` is gitignored)
3. Open `GenStat.xcodeproj` in Xcode
4. Ensure your Supabase tables have Row Level Security policies allowing anonymous reads:
   ```sql
   CREATE POLICY "Allow anonymous read" ON generator_status
       FOR SELECT TO anon USING (true);

   CREATE POLICY "Allow anonymous read" ON generator_events
       FOR SELECT TO anon USING (true);
   ```
5. Build and run on a device or simulator

---

## Next Steps

- **Push notifications** — Alert the homeowner immediately when the generator enters a critical state or when an outage begins/ends, rather than relying on foreground refresh
- **Widget / Live Activity** — An iOS widget or Live Activity showing current status on the Lock Screen and Home Screen
- **Historical charts** — Visualize runtime hours, outage frequency, and voltage trends over time using Swift Charts
- **Exercise schedule reminder** — Since the Kohler RDT clears the weekly exercise schedule after a transfer event, the monitoring service already sends a notification reminder. A future enhancement could surface this reminder in the app with a one-tap deep link to the transfer switch manual.
- **Multiple generators** — Support monitoring more than one generator from a single app instance
- **Localization** — Add string catalog entries for all user-facing text
- **Unit tests** — Test `GeneratorMonitor` refresh logic and `SupabaseService` decoding with mock data

---

## License

[Licensed under the MIT License](LICENSE)

---

## Built With Claude

This project was developed collaboratively with [Claude](https://claude.ai), Anthropic's AI assistant, over several sessions in early 2026.

The collaboration followed a clear division of roles. The code — the Python monitoring service, the systemd configuration, the CadQuery enclosure script, the Homebridge webhook integration, the Supabase schema and RLS policies, and the GenStat iOS app specification — was written by Claude. Everything that shaped what got built was driven by the homeowner: defining the goals, asking the questions, providing hardware photographs and measurements, running commands on the Pi and reporting back the actual output, making design decisions when there were options, and pushing back when a proposed solution wasn't right.

The project started as a simple troubleshooting session for a Kohler generator that wouldn't start. Diagnosing a 7-year-old battery failure from fault codes led naturally to the question of ongoing visibility — and that question grew into the full monitoring system documented here. At each stage the homeowner decided what mattered, Claude figured out how to build it, and the back-and-forth between those two things is what produced the result.

It's a reasonable example of what human-AI collaboration looks like in practice: the human brings judgment, context, and real-world grounding; the AI brings breadth of knowledge and the ability to write and iterate on code quickly. Neither half works as well without the other.
