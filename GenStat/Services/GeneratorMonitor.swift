import Foundation
import UIKit

/// Manages periodic polling of generator status and event data from Supabase.
///
/// `GeneratorMonitor` is an `@Observable` class intended to be owned
/// via `@State` in a root view. It polls the backend every 60 seconds
/// while the app is in the foreground and supports paginated loading
/// of historical events.
///
/// ## Usage
/// ```swift
/// @State private var monitor = GeneratorMonitor()
///
/// // Start when the app enters the foreground
/// monitor.startPolling()
///
/// // Stop when backgrounded
/// monitor.stopPolling()
/// ```
@MainActor
@Observable
class GeneratorMonitor {
    /// The most recently fetched generator status, or `nil` if unavailable or errored.
    var status: GeneratorStatus?

    /// The list of generator events loaded so far, ordered newest first.
    var events: [GeneratorEvent] = []

    /// Whether the initial data load is in progress.
    var isLoading: Bool = false

    /// Whether a pagination request for older events is in progress.
    var isLoadingMore: Bool = false

    /// Whether additional pages of events are available to load.
    var hasMoreEvents: Bool = true

    /// A user-facing error message from the most recent failed request, if any.
    var errorMessage: String?

    private static let pageSize = 50
    private var pollingTask: Task<Void, Never>?
    private let pollingInterval: Duration = .seconds(60)
    private let dataSource: any GeneratorDataFetching

    /// Creates a monitor with the given data source.
    /// - Parameter dataSource: The provider of generator data. Defaults to ``SupabaseService``.
    init(dataSource: any GeneratorDataFetching = SupabaseService()) {
        self.dataSource = dataSource
    }

    /// Begins periodic polling for status and events.
    ///
    /// Cancels any existing polling task before starting a new one.
    /// The first poll fetches data immediately with a loading indicator,
    /// then continues every 60 seconds until ``stopPolling()`` is called
    /// or the task is cancelled.
    func startPolling() {
        stopPolling()
        pollingTask = Task {
            isLoading = true
            errorMessage = nil
            await refreshStatus()
            isLoading = false
            await refreshEvents()

            while !Task.isCancelled {
                try? await Task.sleep(for: pollingInterval)
                guard !Task.isCancelled else { break }
                await refreshStatus()
                await refreshEvents()
            }
        }
    }

    /// Stops the current polling task, if any.
    func stopPolling() {
        pollingTask?.cancel()
        pollingTask = nil
    }

    func refreshStatus() async {
        do {
            status = try await dataSource.fetchStatus()
            errorMessage = nil
            updateAppIcon()
        } catch {
            if !Task.isCancelled {
                status = nil
                errorMessage = error.localizedDescription
            }
        }
    }

    private func updateAppIcon() {
        let displayStatus = DisplayStatus.from(status)
        let desiredIcon = displayStatus.alternateIconName
        let currentIcon = UIApplication.shared.alternateIconName

        guard desiredIcon != currentIcon else { return }
        UIApplication.shared.setAlternateIconName(desiredIcon)
    }

    func refreshEvents() async {
        do {
            let fetched = try await dataSource.fetchEvents(offset: 0, limit: Self.pageSize)
            events = fetched
            hasMoreEvents = fetched.count >= Self.pageSize
        } catch {
            if !Task.isCancelled {
                errorMessage = error.localizedDescription
            }
        }
    }

    /// Loads the next page of older events and appends them to ``events``.
    ///
    /// Does nothing if a page load is already in progress or all events
    /// have been fetched.
    func loadMoreEvents() async {
        guard !isLoadingMore, hasMoreEvents else { return }
        isLoadingMore = true
        do {
            let fetched = try await dataSource.fetchEvents(offset: events.count, limit: Self.pageSize)
            events.append(contentsOf: fetched)
            hasMoreEvents = fetched.count >= Self.pageSize
        } catch {
            if !Task.isCancelled {
                errorMessage = error.localizedDescription
            }
        }
        isLoadingMore = false
    }
}
