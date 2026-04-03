import Foundation
import Testing
@testable import Shipyard

/// Test suite for BridgeProtocol conformance
@Suite("BridgeProtocol Tests")
struct BridgeProtocolTests {
    
    /// Mock bridge for testing protocol conformance
    final class MockBridge: BridgeProtocol, Sendable {
        nonisolated let mcpName: String
        
        nonisolated func initialize() async throws -> [String: Any] {
            return ["serverInfo": ["name": "MockMCP", "version": "1.0"]]
        }
        
        nonisolated func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any] {
            return ["result": "success", "tool": name]
        }
        
        nonisolated func discoverTools() async throws -> [[String: Any]] {
            return [
                ["name": "tool1", "description": "Test tool 1"],
                ["name": "tool2", "description": "Test tool 2"]
            ]
        }
        
        nonisolated func disconnect() async {
            // no-op for mock
        }
        
        init(name: String = "MockMCP") {
            self.mcpName = name
        }
    }
    
    @Test("Protocol exposes mcpName")
    func testMcpNameProperty() {
        let bridge = MockBridge(name: "TestMCP")
        #expect(bridge.mcpName == "TestMCP")
    }
    
    @Test("Protocol requires initialize")
    func testInitializeRequired() async throws {
        let bridge = MockBridge()
        let result = try await bridge.initialize()
        #expect(result["serverInfo"] != nil)
    }
    
    @Test("Protocol requires callTool")
    func testCallToolRequired() async throws {
        let bridge = MockBridge()
        let result = try await bridge.callTool(name: "myTool", arguments: ["arg1": "value1"])
        #expect(result["tool"] as? String == "myTool")
    }
    
    @Test("Protocol requires discoverTools")
    func testDiscoverToolsRequired() async throws {
        let bridge = MockBridge()
        let tools = try await bridge.discoverTools()
        #expect(tools.count == 2)
        #expect(tools[0]["name"] as? String == "tool1")
    }
    
    @Test("Protocol requires disconnect")
    func testDisconnectRequired() async throws {
        let bridge = MockBridge()
        // Should not throw
        await bridge.disconnect()
    }
}

/// Test suite for BridgeError
@Suite("BridgeError Tests")
struct BridgeErrorTests {
    
    @Test("Transient errors are classified correctly")
    func testTransientErrorClassification() {
        let timeoutError = BridgeError.timeout("test", 30)
        #expect(timeoutError.isTransient == true)
        
        let sessionExpiredError = BridgeError.sessionExpired("test")
        #expect(sessionExpiredError.isTransient == true)
        
        let connectionFailedError = BridgeError.connectionFailed("test", "reason")
        #expect(connectionFailedError.isTransient == true)
    }
    
    @Test("Permanent errors are classified correctly")
    func testPermanentErrorClassification() {
        let notInitError = BridgeError.notInitialized("test")
        #expect(notInitError.isTransient == false)
        
        let serializationError = BridgeError.serializationFailed("reason")
        #expect(serializationError.isTransient == false)
        
        let processNotRunningError = BridgeError.processNotRunning("test")
        #expect(processNotRunningError.isTransient == false)
    }
    
    @Test("Error descriptions are provided")
    func testErrorDescriptions() {
        let error = BridgeError.timeout("myMCP", 30)
        #expect(error.errorDescription != nil)
        #expect(error.errorDescription?.contains("myMCP") == true)
        #expect(error.errorDescription?.contains("30") == true)
    }
    
    @Test("HTTP error provides status code and message")
    func testHttpError() {
        let error = BridgeError.httpError("myMCP", 500, "Internal Server Error")
        #expect(error.errorDescription?.contains("500") == true)
        #expect(error.errorDescription?.contains("Internal Server Error") == true)
    }
}
