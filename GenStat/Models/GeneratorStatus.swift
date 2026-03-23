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

    /// Total lifetime runtime hours (outage + exercise) reported by the generator controller.
    let generatorRuntimeHours: Float?

    /// Hours the generator has run during weekly exercise cycles.
    let generatorExerciseHours: Float?

    /// When the generator last completed a weekly exercise cycle.
    let lastExerciseAt: Date?

    /// When the most recent utility power outage began.
    let lastOutageAt: Date?

    /// Duration of the most recent outage in seconds.
    let lastOutageDurationSeconds: Int?

    /// Whether the user should verify the RDT exercise schedule after an outage.
    let exerciseScheduleCheckNeeded: Bool?

    /// Runtime hours at which the last service was performed, or nil if no service recorded.
    let lastServiceHours: Float?

    /// The service interval in hours. Defaults to 200 in the database.
    let serviceIntervalHours: Float?

    /// Whether the generator is due for service, as determined by the backend.
    let serviceCheckNeeded: Bool?

    /// Hours remaining until the next service is due, or nil if service data is unavailable.
    var hoursUntilService: Float? {
        guard let lastService = lastServiceHours,
              let interval = serviceIntervalHours,
              let runtime = generatorRuntimeHours else {
            return nil
        }
        return (lastService + interval) - runtime
    }

    /// Hours the generator has run due to utility power outages.
    /// Computed as total runtime minus exercise hours, or nil if either value is unavailable.
    var outageHours: Float? {
        guard let total = generatorRuntimeHours,
              let exercise = generatorExerciseHours else {
            return nil
        }
        return total - exercise
    }

    /// Whether exercise hours data is available for showing the runtime breakdown.
    var hasExerciseBreakdown: Bool {
        generatorExerciseHours != nil
    }
}
