import Foundation

/// A snapshot of the generator's current status, decoded from the
/// Supabase `generator_status` table.
///
/// The single row (id = 1) is updated approximately every 30 seconds
/// by the backend monitoring service.
struct GeneratorStatus: Codable {
    /// The row identifier (always 1 for the single-row status table).
    let id: Int

    /// When this status record was last updated by the backend.
    let updatedAt: Date

    /// The generator's current operational state.
    let currentState: GeneratorState

    /// The current utility (mains) voltage in volts, if available.
    let utilityVoltage: Float?

    /// The current generator output voltage in volts, if available.
    let generatorVoltage: Float?

    /// Total lifetime runtime hours reported by the generator controller.
    let generatorRuntimeHours: Float?

    /// When the generator last completed a weekly exercise cycle.
    let lastExerciseAt: Date?

    /// When the most recent utility power outage began.
    let lastOutageAt: Date?

    /// Duration of the most recent outage in seconds.
    let lastOutageDurationSeconds: Int?

    /// Whether the user should verify the RDT exercise schedule after an outage.
    let exerciseScheduleCheckNeeded: Bool?
}
