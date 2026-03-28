import Foundation

/// Formats a duration in seconds as a compact human-readable string
/// (e.g. "2h 15m", "45m", "30s").
func formattedDuration(_ seconds: Int) -> String {
    let hours = seconds / 3600
    let minutes = (seconds % 3600) / 60
    if hours > 0 && minutes > 0 {
        return String(localized: "\(hours)h \(minutes)m")
    } else if hours > 0 {
        return String(localized: "\(hours)h")
    } else if minutes > 0 {
        return String(localized: "\(minutes)m")
    } else {
        return String(localized: "\(seconds)s")
    }
}
