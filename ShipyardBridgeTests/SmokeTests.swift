import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("ShipyardBridgeLib Smoke Test")
struct SmokeTests {
    @Test("Library imports successfully")
    func libraryImports() {
        // If this compiles and runs, the library extraction is correct
        #expect(true)
    }
}

// MARK: - Mock Logger for Testing

class MockBridgeLogger: BridgeLogging {
    var logs: [(level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]?)] = []

    func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]? = nil) {
        logs.append((level: level, cat: cat, msg: msg, meta: meta))
    }
}

// MARK: - Injectable Logger Tests

@Suite("BridgeLogger Injection Tests")
struct InjectableLoggerTests {
    @Test("Logger protocol can be implemented")
    func mockLoggerConforms() {
        let mock = MockBridgeLogger()
        #expect(mock is BridgeLogging)
    }

    @Test("Mock logger captures log calls")
    func mockLoggerCaptures() {
        let mock = MockBridgeLogger()
        let savedLogger = bridgeLog
        bridgeLog = mock

        defer { bridgeLog = savedLogger }

        bridgeLog.log(.info, cat: "test", msg: "test message", meta: ["key": "value"])

        #expect(mock.logs.count == 1)
        #expect(mock.logs[0].level == .info)
        #expect(mock.logs[0].cat == "test")
        #expect(mock.logs[0].msg == "test message")
        #expect(mock.logs[0].meta?["key"] as? String == "value")
    }

    @Test("Mock logger works with default parameter")
    func mockLoggerDefaultParameter() {
        let mock = MockBridgeLogger()
        let savedLogger = bridgeLog
        bridgeLog = mock

        defer { bridgeLog = savedLogger }

        bridgeLog.log(.debug, cat: "test", msg: "test message")

        #expect(mock.logs.count == 1)
        #expect(mock.logs[0].level == .debug)
        #expect(mock.logs[0].meta == nil)
    }

    @Test("BridgeLogger.shared still works as default")
    func sharedLoggerIsDefault() {
        #expect(bridgeLog is BridgeLogger)
    }
}
