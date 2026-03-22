import SwiftUI

struct StatusView: View {
    var monitor: GeneratorMonitor
    @Binding var showingLog: Bool

    var body: some View {
        NavigationStack {
            ZStack {
                VStack {
                    Spacer()

                    PowerFlowView(state: monitor.status?.currentState ?? .unknown)
                        .padding(.horizontal)

                    Text(sinceText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    VStack(spacing: 4) {
                        Text("Generator Hours: \(formattedRuntimeHours)")
                            .foregroundStyle(.secondary)
                        Text(lastExercisedText)
                            .foregroundStyle(lastExercisedDaysAgo > 7 ? .red : .secondary)
                        Text(lastOutageText)
                            .foregroundStyle(.secondary)
                    }
                    .font(.callout)

                    Spacer()
                }
                .padding()

                if monitor.isLoading {
                    ProgressView()
                        .controlSize(.large)
                }
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Menu {
                        Link(destination: Self.generatorManualURL) {
                            Label("Generator Manual", systemImage: "book")
                        }
                        Link(destination: Self.transferSwitchManualURL) {
                            Label("Transfer Switch Manual", systemImage: "book")
                        }
                    } label: {
                        Label("Manuals", systemImage: "book")
                    }
                    Button("Event Log", systemImage: "list.bullet") {
                        showingLog = true
                    }
                }
            }
            .overlay(alignment: .top) {
                VStack(spacing: 8) {
                    if let error = monitor.errorMessage {
                        ErrorBanner(message: error) {
                            monitor.errorMessage = nil
                        }
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }

                    if monitor.status?.exerciseScheduleCheckNeeded == true {
                        Button {
                            Task { await monitor.dismissExerciseReminder() }
                        } label: {
                            Text("Exercise schedule may need reprogramming after the recent outage.")
                                .font(.caption)
                                .foregroundStyle(.white)
                                .padding(.horizontal)
                                .padding(.vertical)
                                .frame(maxWidth: .infinity)
                                .background(.orange.opacity(0.85), in: .rect(cornerRadius: 10))
                        }
                        .padding(.horizontal)
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
            }
            .animation(.default, value: monitor.errorMessage)
            .animation(.default, value: monitor.status?.exerciseScheduleCheckNeeded)
        }
    }

    // MARK: - Manual URLs (replace with actual URLs)
    private static let generatorManualURL = URL(string: "https://example.com/generator-manual")!
    private static let transferSwitchManualURL = URL(string: "https://example.com/transfer-switch-manual")!

    private var formattedRuntimeHours: String {
        guard let hours = monitor.status?.generatorRuntimeHours else { return "—" }
        return hours.formatted(.number.precision(.fractionLength(1)))
    }

    private var lastExercisedDaysAgo: Int {
        guard let date = monitor.status?.lastExerciseAt else { return 0 }
        return Calendar.current.dateComponents([.day], from: date, to: .now).day ?? 0
    }

    private var lastExercisedText: String {
        guard monitor.status?.lastExerciseAt != nil else { return "Last Exercised —" }
        let days = lastExercisedDaysAgo
        if days == 0 {
            return "Last Exercised Today"
        } else if days == 1 {
            return "Last Exercised 1 Day Ago"
        } else {
            return "Last Exercised \(days) Days Ago"
        }
    }

    private var lastOutageText: String {
        guard let date = monitor.status?.lastOutageAt else { return "Last Outage —" }
        let days = Calendar.current.dateComponents([.day], from: date, to: .now).day ?? 0
        let duration = monitor.status?.lastOutageDurationSeconds
        let durationSuffix = duration.map { " (\(formattedDuration($0)))" } ?? ""
        if days == 0 {
            return "Last Outage Today\(durationSuffix)"
        } else if days == 1 {
            return "Last Outage 1 Day Ago\(durationSuffix)"
        } else {
            return "Last Outage \(days) Days Ago\(durationSuffix)"
        }
    }

    private func formattedDuration(_ seconds: Int) -> String {
        let hours = seconds / 3600
        let minutes = (seconds % 3600) / 60
        if hours > 0 && minutes > 0 {
            return "\(hours)h \(minutes)m"
        } else if hours > 0 {
            return "\(hours)h"
        } else if minutes > 0 {
            return "\(minutes)m"
        } else {
            return "\(seconds)s"
        }
    }

    private var sinceText: String {
        guard let date = monitor.status?.updatedAt else {
            return ""
        }
        let interval = Date.now.timeIntervalSince(date)
        if interval < 60 {
            return "since just now"
        } else if interval < 3600 {
            let minutes = Int(interval / 60)
            return "since \(minutes) minute\(minutes == 1 ? "" : "s") ago"
        } else if Calendar.current.isDateInToday(date) {
            return "since \(date.formatted(date: .omitted, time: .shortened))"
        } else {
            return "since \(date.formatted(.dateTime.month(.abbreviated).day().hour().minute()))"
        }
    }
}

#Preview {
    let monitor = GeneratorMonitor()
//    monitor.errorMessage = "Unable to connect to server"
    return StatusView(monitor: monitor, showingLog: .constant(false))
}
