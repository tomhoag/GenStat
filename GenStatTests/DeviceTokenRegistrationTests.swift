import Foundation
import Testing
@testable import GenStat

@Suite("Device Token Registration")
struct DeviceTokenRegistrationTests {

    @Test("Hex encodes token data correctly")
    func hexEncodesTokenData() {
        let tokenData = Data([0xAB, 0xCD, 0xEF, 0x01, 0x23, 0x45, 0x67, 0x89])
        let hex = tokenData.map { String(format: "%02x", $0) }.joined()
        #expect(hex == "abcdef0123456789")
    }

    @Test("Hex encoding produces lowercase characters")
    func hexEncodingIsLowercase() {
        let tokenData = Data([0xFF, 0x00, 0xAA, 0x55])
        let hex = tokenData.map { String(format: "%02x", $0) }.joined()
        #expect(hex == "ff00aa55")
        #expect(hex == hex.lowercased())
    }

    @Test("Empty token data produces empty string")
    func emptyTokenData() {
        let tokenData = Data()
        let hex = tokenData.map { String(format: "%02x", $0) }.joined()
        #expect(hex.isEmpty)
    }

    @Test("Typical 32-byte token produces 64 hex characters")
    func typicalTokenLength() {
        let tokenData = Data(repeating: 0xAB, count: 32)
        let hex = tokenData.map { String(format: "%02x", $0) }.joined()
        #expect(hex.count == 64)
    }
}
