import Testing
import SwiftUI
@testable import GenStat

@Suite("DisplayStatus")
struct DisplayStatusTests {

    @Test(arguments: [
        (DisplayStatus.ready, "Ready"),
        (.exercising, "Exercising"),
        (.running, "Running"),
        (.critical, "Critical"),
        (.unknown, "Unknown")
    ])
    func labelValues(status: DisplayStatus, expected: String) {
        #expect(status.label == expected)
    }

    @Test(arguments: [
        (DisplayStatus.ready, Color.green),
        (.exercising, .blue),
        (.running, .orange),
        (.critical, .red),
        (.unknown, .gray)
    ])
    func colorValues(status: DisplayStatus, expected: Color) {
        #expect(status.color == expected)
    }

    @Test
    func fromNilReturnsUnknown() {
        #expect(DisplayStatus.from(nil) == .unknown)
    }

    @Test(arguments: [
        (GeneratorState.normal, DisplayStatus.ready),
        (.weeklyTest, .exercising),
        (.outage, .running),
        (.critical, .critical),
        (.unknown, .unknown)
    ])
    func fromStatusMapsCorrectly(
        state: GeneratorState,
        expected: DisplayStatus
    ) {
        let status = GeneratorStatus(
            id: 1,
            updatedAt: .now,
            currentState: state,
            utilityVoltage: nil,
            generatorVoltage: nil,
            generatorRuntimeHours: nil,
            lastExerciseAt: nil,
            lastOutageAt: nil,
            lastOutageDurationSeconds: nil,
            exerciseScheduleCheckNeeded: nil,
            lastServiceHours: nil,
            serviceIntervalHours: nil,
            serviceCheckNeeded: nil
        )
        #expect(DisplayStatus.from(status) == expected)
    }
}
