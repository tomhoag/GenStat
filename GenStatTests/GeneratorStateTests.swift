import Testing
import SwiftUI
@testable import GenStat

@Suite("GeneratorState")
struct GeneratorStateTests {

    @Test(arguments: [
        (GeneratorState.unknown, "unknown"),
        (.normal, "normal"),
        (.weeklyTest, "weekly_test"),
        (.outage, "outage"),
        (.critical, "critical")
    ])
    func rawValueMapping(state: GeneratorState, expected: String) {
        #expect(state.rawValue == expected)
    }

    @Test(arguments: ["unknown", "normal", "weekly_test", "outage", "critical"])
    func initFromValidRawValue(rawValue: String) {
        #expect(GeneratorState(rawValue: rawValue) != nil)
    }

    @Test
    func initFromInvalidRawValueReturnsNil() {
        #expect(GeneratorState(rawValue: "invalid") == nil)
        #expect(GeneratorState(rawValue: "") == nil)
        #expect(GeneratorState(rawValue: "Normal") == nil)
    }

    @Test(arguments: [
        (GeneratorState.normal, DisplayStatus.ready),
        (.weeklyTest, .exercising),
        (.outage, .running),
        (.critical, .critical),
        (.unknown, .unknown)
    ])
    func displayStatusMapping(state: GeneratorState, expected: DisplayStatus) {
        #expect(state.displayStatus == expected)
    }

    @Test(arguments: GeneratorState.allCases)
    func displayNameDelegatesToDisplayStatus(state: GeneratorState) {
        #expect(state.displayName == state.displayStatus.label)
    }

    @Test(arguments: GeneratorState.allCases)
    func colorDelegatesToDisplayStatus(state: GeneratorState) {
        #expect(state.color == state.displayStatus.color)
    }
}
