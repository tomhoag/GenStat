import SwiftUI

/// A modal overlay showing the breakdown of generator runtime hours
/// into total, outage, and exercise categories.
struct RuntimeBreakdownOverlay: View {
    let totalHours: Float?
    let exerciseHours: Float?
    let outageHours: Float?
    @Binding var isPresented: Bool

    var body: some View {
        ZStack {
            Color.black.opacity(0.3)
                .ignoresSafeArea()
                .onTapGesture {
                    isPresented = false
                }

            VStack(spacing: 12) {
                Text("Runtime Breakdown")
                    .font(.headline)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Divider()

                RuntimeBreakdownRow(
                    label: String(localized: "Total"),
                    hours: totalHours,
                    systemImage: "clock.fill"
                )
                RuntimeBreakdownRow(
                    label: String(localized: "Outage"),
                    hours: outageHours,
                    systemImage: "bolt.slash.fill"
                )
                RuntimeBreakdownRow(
                    label: String(localized: "Exercise"),
                    hours: exerciseHours,
                    systemImage: "arrow.triangle.2.circlepath"
                )
            }
            .padding()
            .glassEffect(in: .rect(cornerRadius: 16))
            .padding(.horizontal, 40)
        }
    }
}

/// A single row in the runtime breakdown overlay.
private struct RuntimeBreakdownRow: View {
    let label: String
    let hours: Float?
    let systemImage: String

    var body: some View {
        HStack {
            Label(label, systemImage: systemImage)
                .foregroundStyle(.primary)
            Spacer()
            Text(formattedHours)
                .monospacedDigit()
                .foregroundStyle(.secondary)
        }
    }

    private var formattedHours: String {
        guard let hours else {
            return "\u{2014}"
        }
        let formatted = hours.formatted(.number.precision(.fractionLength(1)))
        return String(localized: "\(formatted) hrs")
    }
}

#Preview {
    RuntimeBreakdownOverlay(
        totalHours: 156.3,
        exerciseHours: 42.1,
        outageHours: 114.2,
        isPresented: .constant(true)
    )
}
