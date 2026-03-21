import SwiftUI

/// The raw operational state of the generator as stored in the database.
///
/// Each case maps to a `snake_case` string value in the Supabase
/// `generator_status` and `generator_events` tables.
enum GeneratorState: String, Codable {
    case unknown    = "unknown"
    case normal     = "normal"
    case weeklyTest = "weekly_test"
    case outage     = "outage"
    case critical   = "critical"

    /// The user-facing ``DisplayStatus`` corresponding to this state.
    var displayStatus: DisplayStatus {
        switch self {
        case .normal:     .ready
        case .weeklyTest: .exercising
        case .outage:     .running
        case .critical:   .critical
        case .unknown:    .unknown
        }
    }

    /// A localized display name derived from ``displayStatus``.
    var displayName: String { displayStatus.label }

    /// The color associated with this state's ``displayStatus``.
    var color: Color { displayStatus.color }
}
