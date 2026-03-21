import Testing
import Foundation
@testable import GenStat

@Suite("GeneratorMonitor")
@MainActor
struct GeneratorMonitorTests {

    // MARK: - Initial State

    @Test
    func initialStateHasCorrectDefaults() {
        let mock = MockDataSource()
        let monitor = GeneratorMonitor(dataSource: mock)

        #expect(monitor.status == nil)
        #expect(monitor.events.isEmpty)
        #expect(monitor.isLoading == false)
        #expect(monitor.isLoadingMore == false)
        #expect(monitor.hasMoreEvents == true)
        #expect(monitor.errorMessage == nil)
    }

    // MARK: - refreshStatus

    @Test
    func refreshStatusPopulatesStatusOnSuccess() async {
        let mock = MockDataSource()
        let expected = TestFixtures.makeStatus(state: .normal)
        mock.statusResult = .success(expected)
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshStatus()

        #expect(monitor.status?.currentState == .normal)
        #expect(monitor.errorMessage == nil)
        #expect(mock.fetchStatusCallCount == 1)
    }

    @Test
    func refreshStatusClearsErrorOnSuccess() async {
        let mock = MockDataSource()
        mock.statusResult = .success(TestFixtures.makeStatus())
        let monitor = GeneratorMonitor(dataSource: mock)
        monitor.errorMessage = "Previous error"

        await monitor.refreshStatus()

        #expect(monitor.errorMessage == nil)
    }

    @Test
    func refreshStatusSetsErrorOnFailure() async {
        let mock = MockDataSource()
        mock.statusResult = .failure(URLError(.notConnectedToInternet))
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshStatus()

        #expect(monitor.status == nil)
        #expect(monitor.errorMessage != nil)
    }

    // MARK: - refreshEvents

    @Test
    func refreshEventsPopulatesEventsOnSuccess() async {
        let mock = MockDataSource()
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 3))
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshEvents()

        #expect(monitor.events.count == 3)
        #expect(mock.fetchEventsCallCount == 1)
    }

    @Test
    func refreshEventsSetsHasMoreWhenFullPage() async {
        let mock = MockDataSource()
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 50))
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshEvents()

        #expect(monitor.hasMoreEvents == true)
    }

    @Test
    func refreshEventsClearsHasMoreWhenPartialPage() async {
        let mock = MockDataSource()
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 10))
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshEvents()

        #expect(monitor.hasMoreEvents == false)
    }

    @Test
    func refreshEventsSetsErrorOnFailure() async {
        let mock = MockDataSource()
        mock.eventsResult = .failure(URLError(.timedOut))
        let monitor = GeneratorMonitor(dataSource: mock)

        await monitor.refreshEvents()

        #expect(monitor.errorMessage != nil)
    }

    // MARK: - loadMoreEvents

    @Test
    func loadMoreEventsAppendsToExistingEvents() async {
        let mock = MockDataSource()
        let monitor = GeneratorMonitor(dataSource: mock)

        // Populate initial events
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 50))
        await monitor.refreshEvents()
        #expect(monitor.events.count == 50)

        // Load more
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 10))
        await monitor.loadMoreEvents()

        #expect(monitor.events.count == 60)
    }

    @Test
    func loadMoreEventsUsesCorrectOffset() async {
        let mock = MockDataSource()
        let monitor = GeneratorMonitor(dataSource: mock)

        // Populate 50 initial events
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 50))
        await monitor.refreshEvents()

        // Load more — offset should be 50
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 5))
        await monitor.loadMoreEvents()

        #expect(mock.lastEventsOffset == 50)
    }

    @Test
    func loadMoreEventsDoesNothingWhenNoMoreEvents() async {
        let mock = MockDataSource()
        let monitor = GeneratorMonitor(dataSource: mock)

        // Load a partial page so hasMoreEvents becomes false
        mock.eventsResult = .success(TestFixtures.makeEvents(count: 10))
        await monitor.refreshEvents()
        #expect(monitor.hasMoreEvents == false)

        let countBefore = mock.fetchEventsCallCount
        await monitor.loadMoreEvents()

        #expect(mock.fetchEventsCallCount == countBefore)
    }

    // MARK: - stopPolling

    @Test
    func stopPollingCancelsTask() async throws {
        let mock = MockDataSource()
        mock.statusResult = .success(TestFixtures.makeStatus())
        mock.eventsResult = .success([])
        let monitor = GeneratorMonitor(dataSource: mock)

        monitor.startPolling()
        // Let the first poll execute
        try await Task.sleep(for: .milliseconds(100))

        monitor.stopPolling()

        let countAfterStop = mock.fetchStatusCallCount
        try await Task.sleep(for: .milliseconds(200))

        // No additional fetches after stopping
        #expect(mock.fetchStatusCallCount == countAfterStop)
    }
}
