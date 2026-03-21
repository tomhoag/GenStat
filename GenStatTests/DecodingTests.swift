import Testing
import Foundation
@testable import GenStat

@Suite("Decoding")
struct DecodingTests {

    private var decoder: JSONDecoder { SupabaseService.decoder }

    // MARK: - Date Decoding

    @Test
    func decodesDateWithFractionalSeconds() throws {
        let json = """
        {
            "id": 1,
            "updated_at": "2024-01-15T10:30:00.123456Z",
            "current_state": "normal"
        }
        """.data(using: .utf8)!

        let status = try decoder.decode(GeneratorStatus.self, from: json)
        #expect(status.updatedAt.timeIntervalSince1970 > 0)
    }

    @Test
    func decodesDateWithoutFractionalSeconds() throws {
        let json = """
        {
            "id": 1,
            "updated_at": "2024-01-15T10:30:00Z",
            "current_state": "normal"
        }
        """.data(using: .utf8)!

        let status = try decoder.decode(GeneratorStatus.self, from: json)
        #expect(status.updatedAt.timeIntervalSince1970 > 0)
    }

    @Test
    func throwsOnInvalidDateFormat() {
        let json = """
        {
            "id": 1,
            "updated_at": "January 15, 2024",
            "current_state": "normal"
        }
        """.data(using: .utf8)!

        #expect(throws: DecodingError.self) {
            try decoder.decode(GeneratorStatus.self, from: json)
        }
    }

    // MARK: - GeneratorStatus Decoding

    @Test
    func decodesCompleteGeneratorStatus() throws {
        let json = """
        {
            "id": 1,
            "updated_at": "2024-01-15T10:30:00Z",
            "current_state": "normal",
            "utility_voltage": 121.5,
            "generator_voltage": 0.0,
            "generator_runtime_hours": 156.3,
            "last_exercise_at": "2024-01-08T14:00:00Z",
            "last_outage_at": "2024-01-01T02:15:00Z",
            "last_outage_duration_seconds": 3600
        }
        """.data(using: .utf8)!

        let status = try decoder.decode(GeneratorStatus.self, from: json)
        #expect(status.id == 1)
        #expect(status.currentState == .normal)
        #expect(status.utilityVoltage == 121.5)
        #expect(status.generatorVoltage == 0.0)
        #expect(status.generatorRuntimeHours == 156.3)
        #expect(status.lastExerciseAt != nil)
        #expect(status.lastOutageAt != nil)
        #expect(status.lastOutageDurationSeconds == 3600)
    }

    @Test
    func decodesGeneratorStatusWithNullOptionals() throws {
        let json = """
        {
            "id": 1,
            "updated_at": "2024-01-15T10:30:00Z",
            "current_state": "outage",
            "utility_voltage": null,
            "generator_voltage": null,
            "generator_runtime_hours": null,
            "last_exercise_at": null,
            "last_outage_at": null,
            "last_outage_duration_seconds": null
        }
        """.data(using: .utf8)!

        let status = try decoder.decode(GeneratorStatus.self, from: json)
        #expect(status.currentState == .outage)
        #expect(status.utilityVoltage == nil)
        #expect(status.generatorVoltage == nil)
        #expect(status.generatorRuntimeHours == nil)
        #expect(status.lastExerciseAt == nil)
        #expect(status.lastOutageAt == nil)
        #expect(status.lastOutageDurationSeconds == nil)
    }

    @Test(arguments: [
        ("normal", GeneratorState.normal),
        ("weekly_test", .weeklyTest),
        ("outage", .outage),
        ("critical", .critical),
        ("unknown", .unknown)
    ])
    func decodesAllGeneratorStates(rawValue: String, expected: GeneratorState) throws {
        let json = """
        {
            "id": 1,
            "updated_at": "2024-01-15T10:30:00Z",
            "current_state": "\(rawValue)"
        }
        """.data(using: .utf8)!

        let status = try decoder.decode(GeneratorStatus.self, from: json)
        #expect(status.currentState == expected)
    }

    @Test
    func decodesGeneratorStatusArray() throws {
        let json = """
        [{
            "id": 1,
            "updated_at": "2024-01-15T10:30:00Z",
            "current_state": "normal",
            "utility_voltage": 121.5
        }]
        """.data(using: .utf8)!

        let statuses = try decoder.decode([GeneratorStatus].self, from: json)
        #expect(statuses.count == 1)
        #expect(statuses.first?.currentState == .normal)
    }

    // MARK: - GeneratorEvent Decoding

    @Test
    func decodesCompleteGeneratorEvent() throws {
        let json = """
        {
            "id": 42,
            "created_at": "2024-01-15T10:30:00.500Z",
            "previous_state": "normal",
            "new_state": "weekly_test",
            "utility_voltage": 240.5,
            "generator_voltage": 241.2,
            "duration_seconds": 1800
        }
        """.data(using: .utf8)!

        let event = try decoder.decode(GeneratorEvent.self, from: json)
        #expect(event.id == 42)
        #expect(event.previousState == .normal)
        #expect(event.newState == .weeklyTest)
        #expect(event.utilityVoltage == 240.5)
        #expect(event.generatorVoltage == 241.2)
        #expect(event.durationSeconds == 1800)
    }

    @Test
    func decodesGeneratorEventWithNullOptionals() throws {
        let json = """
        {
            "id": 1,
            "created_at": "2024-01-15T10:30:00Z",
            "previous_state": "unknown",
            "new_state": "normal",
            "utility_voltage": null,
            "generator_voltage": null,
            "duration_seconds": null
        }
        """.data(using: .utf8)!

        let event = try decoder.decode(GeneratorEvent.self, from: json)
        #expect(event.utilityVoltage == nil)
        #expect(event.generatorVoltage == nil)
        #expect(event.durationSeconds == nil)
    }

    @Test
    func decodesGeneratorEventArray() throws {
        let json = """
        [
            {
                "id": 1,
                "created_at": "2024-01-15T10:30:00Z",
                "previous_state": "normal",
                "new_state": "outage"
            },
            {
                "id": 2,
                "created_at": "2024-01-15T11:00:00Z",
                "previous_state": "outage",
                "new_state": "normal",
                "duration_seconds": 1800
            }
        ]
        """.data(using: .utf8)!

        let events = try decoder.decode([GeneratorEvent].self, from: json)
        #expect(events.count == 2)
        #expect(events[0].newState == .outage)
        #expect(events[1].durationSeconds == 1800)
    }
}
