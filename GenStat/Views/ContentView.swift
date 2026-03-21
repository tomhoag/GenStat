import SwiftUI

struct ContentView: View {
    @State private var monitor = GeneratorMonitor()
    @State private var showingLog = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if showingLog {
                EventLogView(monitor: monitor, showingLog: $showingLog)
            } else {
                StatusView(monitor: monitor, showingLog: $showingLog)
            }
        }
        .onChange(of: scenePhase, initial: true) { _, newPhase in
            if newPhase == .active {
                monitor.startPolling()
            } else {
                monitor.stopPolling()
            }
        }
    }
}

#Preview {
    ContentView()
}
