# GenStat iOS App

A SwiftUI iPhone app for monitoring a Kohler residential standby generator and automatic transfer switch in real time.

## Key Features

- **Live status display** — Ready, Exercising, Running, Critical, or Unknown with severity-based color coding
- **Generator visualization** — Custom power flow diagram showing which source — utility or generator — is currently supplying the house
- **Runtime tracking** — Total generator hours (outage only, exercise excluded), days since last exercise (highlighted in red when overdue), and last outage with duration
- **Event log** — Chronological history of every state transition with voltage readings and duration, loaded via infinite scroll pagination
- **Foreground refresh** — Automatic refresh on launch and when the app is brought to the foreground, with a manual refresh button
- **Dynamic app icon** — App icon changes automatically to reflect the current generator state (green for ready, orange for running, red for critical, blue for exercising, gray for unknown)
- **Error handling** — Dismissable error banner with automatic recovery on the next successful poll
- **Quick-access manuals** — Toolbar menu linking to generator and transfer switch documentation

---

## Architecture

### Tech Stack

| Layer | Technology |
|---|---|
| UI | SwiftUI (iOS 26+) |
| State | `@Observable` / `@State` |
| Networking | `URLSession` async/await |
| Backend | Supabase (PostgreSQL + REST API) |
| Testing | Swift Testing framework |
| Language | Swift 6.0, strict concurrency |

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

- iOS 26.2 or later
- Xcode 26.3 or later
- Swift 6.0
- A Supabase project with the tables described in the [root README](../README.md#database-schema) and RLS policies enabling anonymous `SELECT` access

---

## Build

1. Create `Secrets.xcconfig` in the project root (see [root README](../README.md#setup))
2. Open `GenStat.xcodeproj` in Xcode
3. Build and run on a device or simulator

---

## Testing

The project includes 32 unit tests using the Swift Testing framework (`import Testing`), organized across five test files in the `GenStatTests/` target:

| File | Tests | Coverage |
|---|---|---|
| `GeneratorStateTests.swift` | 6 | Raw values, init, displayStatus/displayName/color mapping |
| `DisplayStatusTests.swift` | 4 | Labels, colors, `from(nil)`, `from(status)` mapping |
| `DecodingTests.swift` | 10 | ISO 8601 dates, GeneratorStatus/GeneratorEvent JSON |
| `GeneratorMonitorTests.swift` | 12 | Refresh logic, polling, error handling, pagination |
| `MockDataSource.swift` | — | Mock `GeneratorDataFetching` and `TestFixtures` factory |

Tests use dependency injection via the `GeneratorDataFetching` protocol to avoid network calls. Run all tests from the GenStat scheme in Xcode.

---

## License

[Licensed under the MIT License](LICENSE.md)
