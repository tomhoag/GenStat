import SwiftUI

/// A user-facing representation of the generator's operational status.
///
/// Maps raw ``GeneratorState`` values to human-readable labels and
/// severity-based colors used throughout the UI.
enum DisplayStatus: Equatable {
    case ready
    case exercising
    case running
    case critical
    case unknown

    /// A human-readable label for this status.
    var label: String {
        switch self {
        case .ready:      String(localized: "Ready")
        case .exercising: String(localized: "Exercising")
        case .running:    String(localized: "Running")
        case .critical:   String(localized: "Critical")
        case .unknown:    String(localized: "Unknown")
        }
    }

    /// The severity-based color for this status.
    ///
    /// Uses green for ready, blue for exercising, orange for running,
    /// red for critical, and gray for unknown.
    var color: Color {
        switch self {
        case .ready:      .green
        case .exercising: .blue
        case .running:    .orange
        case .critical:   .red
        case .unknown:    .gray
        }
    }

    /// Creates a ``DisplayStatus`` from an optional ``GeneratorStatus``.
    /// - Parameter status: The current generator status, or `nil` if unavailable.
    /// - Returns: The corresponding display status, defaulting to ``unknown`` when `nil`.
    static func from(_ status: GeneratorStatus?) -> DisplayStatus {
        guard let status else { return .unknown }
        switch status.currentState {
        case .normal:     return .ready
        case .weeklyTest: return .exercising
        case .outage:     return .running
        case .critical:   return .critical
        case .unknown:    return .unknown
        }
    }
}
