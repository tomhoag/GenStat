import Foundation

/// A recorded state-change event, decoded from the Supabase
/// `generator_events` table.
///
/// Each row represents a transition from one ``GeneratorState`` to
/// another, along with voltage readings at the time of the event.
struct GeneratorEvent: Codable, Identifiable {
    /// The unique row identifier.
    let id: Int

    /// When this event was recorded.
    let createdAt: Date

    /// The generator state before the transition.
    let previousState: GeneratorState

    /// The generator state after the transition.
    let newState: GeneratorState

    /// The utility voltage at the time of the event, if available.
    let utilityVoltage: Float?

    /// The generator output voltage at the time of the event, if available.
    let generatorVoltage: Float?

    /// How long the previous state lasted, in seconds.
    let durationSeconds: Int?
}
