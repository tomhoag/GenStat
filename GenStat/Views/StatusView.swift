import SwiftUI

struct StatusView: View {
    var monitor: GeneratorMonitor
    @Binding var showingLog: Bool
    @State private var showExerciseConfirmation = false
    @State private var showServiceConfirmation = false

    var body: some View {
        NavigationStack {
            ZStack {
                VStack(spacing: 16) {
                    PowerFlowView(state: monitor.status?.currentState ?? .unknown)
                        .padding(.horizontal)

                    Text(sinceText)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)

                    HStack(spacing: 0) {
                        VoltageCell(
                            label: "Utility",
                            voltage: monitor.status?.utilityVoltage,
                            systemImage: "powerplug"
                        )
                        Divider()
                            .frame(height: 40)
                        VoltageCell(
                            label: "Generator",
                            voltage: monitor.status?.generatorVoltage,
                            systemImage: "bolt.fill"
                        )
                    }
                    .padding(.horizontal)

                    VStack(spacing: 4) {
                        Text("Runtime: \(formattedRuntimeHours) hrs")
                            .foregroundStyle(.secondary)
                        Text(lastExercisedShort)
                            .foregroundStyle(lastExercisedDaysAgo > 7 ? .red : .secondary)
                        Text(lastOutageShort)
                            .foregroundStyle(.secondary)
                        Text(nextServiceShort)
                            .foregroundStyle(serviceHoursColor)
                    }
                    .font(.title3)

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
                            showExerciseConfirmation = true
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

                    if monitor.status?.serviceCheckNeeded == true {
                        Button {
                            showServiceConfirmation = true
                        } label: {
                            Label("Generator service is due.", systemImage: "wrench.and.screwdriver")
                                .font(.caption)
                                .foregroundStyle(.white)
                                .padding(.horizontal)
                                .padding(.vertical)
                                .frame(maxWidth: .infinity)
                                .background(.blue.opacity(0.85), in: .rect(cornerRadius: 10))
                        }
                        .padding(.horizontal)
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
            }
            .animation(.default, value: monitor.errorMessage)
            .animation(.default, value: monitor.status?.exerciseScheduleCheckNeeded)
            .animation(.default, value: monitor.status?.serviceCheckNeeded)
            .alert("Dismiss Exercise Reminder?",
                   isPresented: $showExerciseConfirmation) {
                Button("Dismiss") {
                    Task { await monitor.dismissExerciseReminder() }
                }
                Button("Cancel", role: .cancel) { }
            } message: {
                Text("Confirm you have verified the weekly exercise schedule on the generator controller.")
            }
            .alert("Mark Service Complete?",
                   isPresented: $showServiceConfirmation) {
                Button("Complete Service") {
                    Task { await monitor.completeServiceReminder() }
                }
                Button("Cancel", role: .cancel) { }
            } message: {
                Text("This will record the current runtime (\(formattedRuntimeHours) hrs) as the last service point.")
            }
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

    private var lastExercisedShort: String {
        guard monitor.status?.lastExerciseAt != nil else { return "Last Exercised —" }
        let days = lastExercisedDaysAgo
        if days == 0 {
            return "Exercised Today"
        } else if days == 1 {
            return "Exercised 1 Day Ago"
        } else {
            return "Exercised \(days) Days Ago"
        }
    }

    private var lastOutageShort: String {
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

    private var nextServiceShort: String {
        guard let remaining = monitor.status?.hoursUntilService else {
            return "Next Service \u{2014}"
        }
        if remaining <= 0 {
            return "Service Overdue"
        }
        let formatted = remaining.formatted(.number.precision(.fractionLength(0)))
        return "Next Service in \(formatted) hrs"
    }

    private var serviceHoursColor: Color {
        guard let remaining = monitor.status?.hoursUntilService else {
            return .secondary
        }
        return remaining <= 0 ? .red : .secondary
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
// MARK: - Helper Views

private struct VoltageCell: View {
    let label: String
    let voltage: Float?
    let systemImage: String

    var body: some View {
        VStack(spacing: 2) {
            Image(systemName: systemImage)
                .foregroundStyle(.secondary)
                .imageScale(.small)
            Text(formattedVoltage)
                .font(.title3)
                .fontWeight(.medium)
                .monospacedDigit()
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var formattedVoltage: String {
        guard let v = voltage else { return "— V" }
        return "\(Int(v)) V"
    }
}



