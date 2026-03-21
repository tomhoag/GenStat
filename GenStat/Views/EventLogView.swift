import SwiftUI

struct EventLogView: View {
    var monitor: GeneratorMonitor
    @Binding var showingLog: Bool

    var body: some View {
        NavigationStack {
            Group {
                if monitor.events.isEmpty && !monitor.isLoading {
                    ContentUnavailableView(
                        "No Events",
                        systemImage: "list.bullet.rectangle",
                        description: Text("No events recorded yet")
                    )
                } else {
                    List {
                        ForEach(monitor.events) { event in
                            EventRow(event: event)
                                .onAppear {
                                    if event.id == monitor.events.last?.id {
                                        Task { await monitor.loadMoreEvents() }
                                    }
                                }
                        }
                        if monitor.isLoadingMore {
                            HStack {
                                Spacer()
                                ProgressView()
                                Spacer()
                            }
                            .listRowSeparator(.hidden)
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .overlay {
                if monitor.isLoading {
                    ProgressView()
                        .controlSize(.large)
                }
            }
            .navigationTitle("Event Log")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Status", systemImage: "chevron.left") {
                        showingLog = false
                    }
                }
            }
        }
    }
}

#Preview {
    EventLogView(monitor: GeneratorMonitor(), showingLog: .constant(true))
}
