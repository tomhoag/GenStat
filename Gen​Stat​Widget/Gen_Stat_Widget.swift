import WidgetKit
import SwiftUI

// MARK: - Generator State (standalone for widget)

/// The raw operational state of the generator as stored in the database.
enum WidgetGeneratorState: String, Codable {
    case unknown     = "unknown"
    case normal      = "normal"
    case weeklyTest  = "weekly_test"
    case outage      = "outage"
    case critical    = "critical"

    var label: String {
        switch self {
        case .normal:     String(localized: "Ready")
        case .weeklyTest: String(localized: "Exercising")
        case .outage:     String(localized: "Running")
        case .critical:   String(localized: "Critical")
        case .unknown:    String(localized: "Unknown")
        }
    }

    var systemImage: String {
        switch self {
        case .normal:     "bolt.fill"
        case .weeklyTest: "arrow.triangle.2.circlepath"
        case .outage:     "bolt.slash.fill"
        case .critical:   "bolt.trianglebadge.exclamationmark"
        case .unknown:    "questionmark.circle"
        }
    }

    var color: Color {
        switch self {
        case .normal:     .green
        case .weeklyTest: .blue
        case .outage:     .orange
        case .critical:   .red
        case .unknown:    .gray
        }
    }
}

// MARK: - Supabase Response Model

/// Minimal status model decoded from the Supabase `generator_status` table.
private struct WidgetGeneratorStatus: Codable {
    let currentState: WidgetGeneratorState
    let updatedAt: Date
    let utilityVoltage: Float?
    let generatorVoltage: Float?
}

// MARK: - Standalone Supabase Client

/// A lightweight Supabase client for the widget extension.
///
/// Reads credentials from the widget's own Info.plist, which expands
/// build settings defined in `Secrets.xcconfig`.
private enum WidgetSupabaseClient {
    static let supabaseURL: String = {
        guard let url = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_URL") as? String,
              !url.isEmpty else {
            return ""
        }
        return url
    }()

    static let supabaseKey: String = {
        guard let key = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_KEY") as? String,
              !key.isEmpty else {
            return ""
        }
        return key
    }()

    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let fractionalStrategy = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
        let standardStrategy = Date.ISO8601FormatStyle()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = try? Date(string, strategy: fractionalStrategy) {
                return date
            }
            if let date = try? Date(string, strategy: standardStrategy) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(string)"
            )
        }
        return decoder
    }()

    /// Fetches the current generator status from Supabase.
    static func fetchStatus() async -> WidgetGeneratorStatus? {
        guard !supabaseURL.isEmpty, !supabaseKey.isEmpty else { return nil }
        guard let url = URL(string: "\(supabaseURL)/rest/v1/generator_status?id=eq.1&limit=1") else {
            return nil
        }

        var request = URLRequest(url: url)
        request.setValue(supabaseKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(supabaseKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse,
                  (200...299).contains(httpResponse.statusCode) else {
                return nil
            }
            let statuses = try decoder.decode([WidgetGeneratorStatus].self, from: data)
            return statuses.first
        } catch {
            return nil
        }
    }
}

// MARK: - Timeline Entry

struct GenStatEntry: TimelineEntry {
    let date: Date
    let state: WidgetGeneratorState
    let updatedAt: Date?
    let utilityVoltage: Float?
    let generatorVoltage: Float?
}

// MARK: - Timeline Provider

struct GenStatProvider: TimelineProvider {
    func placeholder(in context: Context) -> GenStatEntry {
        GenStatEntry(
            date: .now,
            state: .normal,
            updatedAt: .now,
            utilityVoltage: 121.0,
            generatorVoltage: nil
        )
    }

    func getSnapshot(in context: Context, completion: @escaping (GenStatEntry) -> Void) {
        if context.isPreview {
            completion(placeholder(in: context))
            return
        }
        Task {
            let entry = await fetchEntry()
            completion(entry)
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<GenStatEntry>) -> Void) {
        Task {
            let entry = await fetchEntry()
            let nextUpdate = Calendar.current.date(byAdding: .minute, value: 15, to: entry.date)!
            let timeline = Timeline(entries: [entry], policy: .after(nextUpdate))
            completion(timeline)
        }
    }

    private func fetchEntry() async -> GenStatEntry {
        if let status = await WidgetSupabaseClient.fetchStatus() {
            return GenStatEntry(
                date: .now,
                state: status.currentState,
                updatedAt: status.updatedAt,
                utilityVoltage: status.utilityVoltage,
                generatorVoltage: status.generatorVoltage
            )
        }
        return GenStatEntry(
            date: .now,
            state: .unknown,
            updatedAt: nil,
            utilityVoltage: nil,
            generatorVoltage: nil
        )
    }
}

// MARK: - Widget Views

/// System small widget — icon, state label, and "updated" time.
struct GenStatSmallView: View {
    let entry: GenStatEntry

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: entry.state.systemImage)
                .font(.system(size: 36))
                .foregroundStyle(entry.state.color)

            Text(entry.state.label)
                .font(.headline)
                .foregroundStyle(entry.state.color)

            if let updatedAt = entry.updatedAt {
                HStack(spacing: 0) {
                    Text(updatedAt, style: .relative)
                    Text(" ago")
                }
                .font(.caption2)
                .foregroundStyle(.secondary)
            }
        }
        .containerBackground(for: .widget) {
            Color(.systemBackground)
        }
    }
}

/// System medium widget — icon + state on left, voltage details on right.
struct GenStatMediumView: View {
    let entry: GenStatEntry

    var body: some View {
        HStack {
            VStack(spacing: 6) {
                Image(systemName: entry.state.systemImage)
                    .font(.system(size: 36))
                    .foregroundStyle(entry.state.color)

                Text(entry.state.label)
                    .font(.headline)
                    .foregroundStyle(entry.state.color)
            }
            .frame(maxWidth: .infinity)

            VStack(alignment: .leading, spacing: 4) {
                if let utility = entry.utilityVoltage {
                    Label {
                        Text("\(utility, specifier: "%.0f") V")
                            .font(.subheadline)
                    } icon: {
                        Image(systemName: "powerplug")
                            .foregroundStyle(.secondary)
                    }
                }

                if let generator = entry.generatorVoltage {
                    Label {
                        Text("\(generator, specifier: "%.0f") V")
                            .font(.subheadline)
                    } icon: {
                        Image(systemName: "bolt.car")
                            .foregroundStyle(.secondary)
                    }
                }

                if let updatedAt = entry.updatedAt {
                    Label {
                        Text(updatedAt, style: .relative)
                            .font(.caption2)
                    } icon: {
                        Image(systemName: "clock")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity)
        }
        .containerBackground(for: .widget) {
            Color(.systemBackground)
        }
    }
}

/// Accessory circular — icon with state color.
struct GenStatAccessoryCircularView: View {
    let entry: GenStatEntry

    var body: some View {
        ZStack {
            AccessoryWidgetBackground()
            Image(systemName: entry.state.systemImage)
                .font(.title2)
                .widgetAccentable()
        }
        .containerBackground(for: .widget) { }
    }
}

/// Accessory rectangular — icon, state label, and relative time.
struct GenStatAccessoryRectangularView: View {
    let entry: GenStatEntry

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: entry.state.systemImage)
                .font(.title3)
                .widgetAccentable()

            VStack(alignment: .leading, spacing: 2) {
                Text(entry.state.label)
                    .font(.headline)
                    .widgetAccentable()

                if let updatedAt = entry.updatedAt {
                    Text(updatedAt, style: .relative)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .containerBackground(for: .widget) { }
    }
}

// MARK: - Widget Entry View (dispatches by family)

struct GenStatWidgetEntryView: View {
    @Environment(\.widgetFamily) var family
    let entry: GenStatEntry

    var body: some View {
        switch family {
        case .systemSmall:
            GenStatSmallView(entry: entry)
        case .systemMedium:
            GenStatMediumView(entry: entry)
        case .accessoryCircular:
            GenStatAccessoryCircularView(entry: entry)
        case .accessoryRectangular:
            GenStatAccessoryRectangularView(entry: entry)
        default:
            GenStatSmallView(entry: entry)
        }
    }
}

// MARK: - Widget Configuration

struct Gen_Stat_Widget: Widget {
    let kind = "studio.offbyone.KohlerStat.widget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: GenStatProvider()) { entry in
            GenStatWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("Generator Status")
        .description("Shows the current status of your Kohler generator.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryCircular,
            .accessoryRectangular,
        ])
    }
}
