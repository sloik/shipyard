import Testing
import Foundation
@testable import ShipyardBridgeLib

// MARK: - Mock Socket for Forwarding Tests

final class ForwardingMockSocket: ShipyardSocketProtocol, @unchecked Sendable {
    private let lock = NSLock()
    private var _calls: [(method: String, params: [String: Any]?)] = []

    var calls: [(method: String, params: [String: Any]?)] {
        lock.lock()
        defer { lock.unlock() }
        return _calls
    }

    func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]? {
        lock.lock()
        _calls.append((method: method, params: params))
        lock.unlock()
        return ["result": ["ok": true]]
    }
}

// MARK: - Tests

@Suite("BridgeLogger Forwarding")
struct BridgeLoggerForwardingTests {

    @Test("info level logs are forwarded via log_event")
    func infoForwarded() async throws {
        let mockSocket = ForwardingMockSocket()
        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mockSocket

        BridgeLogger.shared.log(.info, cat: "test-fwd", msg: "info forwarding test")

        // Give background dispatch time to execute
        try await Task.sleep(for: .milliseconds(300))

        let logEventCalls = mockSocket.calls.filter { $0.method == "log_event" }
        let matching = logEventCalls.filter { ($0.params?["msg"] as? String) == "info forwarding test" }
        #expect(!matching.isEmpty, "info log should be forwarded as log_event")

        if let call = matching.first {
            #expect(call.params?["level"] as? String == "info")
            #expect(call.params?["cat"] as? String == "test-fwd")
            #expect(call.params?["src"] as? String == "bridge")
            #expect(call.params?["ts"] != nil)
        }
    }

    @Test("debug level logs are NOT forwarded")
    func debugNotForwarded() async throws {
        let mockSocket = ForwardingMockSocket()
        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mockSocket

        BridgeLogger.shared.log(.debug, cat: "test-fwd", msg: "debug should not forward")

        try await Task.sleep(for: .milliseconds(300))

        let logEventCalls = mockSocket.calls.filter { $0.method == "log_event" }
        let matching = logEventCalls.filter { ($0.params?["msg"] as? String) == "debug should not forward" }
        #expect(matching.isEmpty, "debug log should NOT be forwarded")
    }

    @Test("warn and error levels are forwarded")
    func warnAndErrorForwarded() async throws {
        let mockSocket = ForwardingMockSocket()
        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mockSocket

        BridgeLogger.shared.log(.warn, cat: "test-fwd", msg: "warn forwarding test")
        BridgeLogger.shared.log(.error, cat: "test-fwd", msg: "error forwarding test")

        try await Task.sleep(for: .milliseconds(300))

        let logEventCalls = mockSocket.calls.filter { $0.method == "log_event" }
        let warnCalls = logEventCalls.filter { ($0.params?["msg"] as? String) == "warn forwarding test" }
        let errorCalls = logEventCalls.filter { ($0.params?["msg"] as? String) == "error forwarding test" }

        #expect(!warnCalls.isEmpty, "warn should be forwarded")
        #expect(!errorCalls.isEmpty, "error should be forwarded")
    }

    @Test("meta dictionary is included in forwarded entry")
    func metaIncluded() async throws {
        let mockSocket = ForwardingMockSocket()
        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mockSocket

        BridgeLogger.shared.log(.info, cat: "test-fwd", msg: "meta forwarding test", meta: ["key": "value", "count": 42])

        try await Task.sleep(for: .milliseconds(300))

        let logEventCalls = mockSocket.calls.filter { $0.method == "log_event" }
        let matching = logEventCalls.filter { ($0.params?["msg"] as? String) == "meta forwarding test" }
        let call = try #require(matching.first, "Should have forwarded meta test entry")

        let meta = try #require(call.params?["meta"] as? [String: Any])
        #expect(meta["key"] as? String == "value")
        #expect(meta["count"] as? Int == 42)
    }
}
