import SwiftUI

struct EventRow: View {
    let event: GeneratorEvent

    var body: some View {
        HStack {
            // Date + state transition
            VStack(alignment: .leading) {
                Text(event.createdAt.formatted(.dateTime.month(.abbreviated).day().hour().minute()))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                HStack {
                    Text(event.previousState.displayName)
                        .foregroundStyle(event.previousState.color)
                    Image(systemName: "arrow.right")
                        .foregroundStyle(.secondary)
                        .imageScale(.small)
                    Text(event.newState.displayName)
                        .foregroundStyle(event.newState.color)
                }
                .font(.subheadline)
                .bold()
            }

            Spacer()

            // Duration
            if let duration = event.durationSeconds, duration > 0 {
                Text(formattedDuration(duration))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text("—")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // Voltages
            VStack(alignment: .trailing) {
                Text("Util: \(formattedVoltage(event.utilityVoltage))")
                Text("Gen: \(formattedVoltage(event.generatorVoltage))")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical)
    }

    private func formattedVoltage(_ voltage: Float?) -> String {
        guard let voltage else { return "0V" }
        return voltage.formatted(.number.precision(.fractionLength(0))) + "V"
    }

}
