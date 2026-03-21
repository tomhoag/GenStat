import Foundation
@testable import GenStat

/// A mock data source for testing ``GeneratorMonitor`` without network access.
@MainActor
final class MockDataSource: GeneratorDataFetching {
    var statusResult: Result<GeneratorStatus, any Error> = .failure(URLError(.unknown))
    var eventsResult: Result<[GeneratorEvent], any Error> = .success([])
    var fetchStatusCallCount = 0
    var fetchEventsCallCount = 0
    var lastEventsOffset: Int?
    var lastEventsLimit: Int?

    nonisolated func fetchStatus() async throws -> GeneratorStatus {
        try await MainActor.run {
            fetchStatusCallCount += 1
            return try statusResult.get()
        }
    }

    nonisolated func fetchEvents(offset: Int, limit: Int) async throws -> [GeneratorEvent] {
        try await MainActor.run {
            fetchEventsCallCount += 1
            lastEventsOffset = offset
            lastEventsLimit = limit
            return try eventsResult.get()
        }
    }
}

/// Convenience factory for test fixtures.
enum TestFixtures {
    static func makeStatus(
        state: GeneratorState = .normal,
        utilityVoltage: Float? = 121.5,
        generatorVoltage: Float? = nil
    ) -> GeneratorStatus {
        GeneratorStatus(
            id: 1,
            updatedAt: .now,
            currentState: state,
            utilityVoltage: utilityVoltage,
            generatorVoltage: generatorVoltage,
            generatorRuntimeHours: 156.3,
            lastExerciseAt: .now,
            lastOutageAt: nil,
            lastOutageDurationSeconds: nil
        )
    }

    static func makeEvents(count: Int) -> [GeneratorEvent] {
        (0..<count).map { index in
            GeneratorEvent(
                id: index + 1,
                createdAt: .now,
                previousState: .normal,
                newState: .weeklyTest,
                utilityVoltage: 121.5,
                generatorVoltage: 240.0,
                durationSeconds: 1200
            )
        }
    }
}
