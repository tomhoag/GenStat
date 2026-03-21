import SwiftUI

struct ErrorBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        Button {
            onDismiss()
        } label: {
            Text(message)
                .font(.caption)
                .foregroundStyle(.white)
                .padding(.horizontal)
                .padding(.vertical)
                .frame(maxWidth: .infinity)
                .background(.red.opacity(0.85), in: .rect(cornerRadius: 10))
        }
        .padding(.horizontal)
    }
}
