import SwiftUI

struct PowerFlowView: View {
    let state: GeneratorState

    private var displayStatus: DisplayStatus {
        state.displayStatus
    }

    var body: some View {
        VStack {
            GeneratorImageView(displayStatus: displayStatus)
                .frame(maxWidth: .infinity)
                .aspectRatio(200.0 / 160.0, contentMode: .fit)

            Text(displayStatus.label)
                .font(.largeTitle)
                .bold()
                .foregroundStyle(displayStatus.color)
                .animation(.easeInOut, value: state)
        }
    }
}

private struct GeneratorImageView: View {
    let displayStatus: DisplayStatus

    var body: some View {
        Group {
            if UIImage(named: "generator_placeholder") != nil {
                Image("generator_placeholder")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(.primary)
                    .overlay {
                        Image("generator_bolt")
                            .resizable()
                            .scaledToFit()
                            .foregroundStyle(displayStatus.color)
                    }
            } else {
                Image(systemName: "bolt.fill")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(displayStatus.color)
                    .padding()
            }
        }
        .saturation(displayStatus == .unknown ? 0.3 : 1.0)
        .clipShape(.rect(cornerRadius: 20))
    }
}

#Preview("Ready") {
    PowerFlowView(state: .normal)
        .padding()
}

#Preview("Exercising") {
    PowerFlowView(state: .weeklyTest)
        .padding()
}

#Preview("Running") {
    PowerFlowView(state: .outage)
        .padding()
}

#Preview("Critical") {
    PowerFlowView(state: .critical)
        .padding()
}

#Preview("Unknown") {
    PowerFlowView(state: .unknown)
        .padding()
}
