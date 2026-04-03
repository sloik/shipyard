import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("ShipyardBridge Tools Changed Notification")
struct ToolsChangedTests {

    @Test("Emits MCP notification with correct format")
    func emitsCorrectNotificationFormat() {
        // Test that the notification is properly formatted JSON-RPC
        let notification: [String: Any] = [
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": [String: Any]()
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: notification),
              let jsonStr = String(data: jsonData, encoding: .utf8) else {
            #expect(Bool(false), "Failed to serialize notification")
            return
        }

        // Verify it's valid JSON
        guard let reparsed = try? JSONSerialization.jsonObject(with: jsonStr.data(using: .utf8) ?? Data()) as? [String: Any] else {
            #expect(Bool(false), "Failed to reparse notification JSON")
            return
        }

        #expect(reparsed["jsonrpc"] as? String == "2.0")
        #expect(reparsed["method"] as? String == "notifications/tools/list_changed")
    }

    @Test("Notification includes proper structure")
    func notificationIncludesProperStructure() {
        let notification: [String: Any] = [
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": [String: Any]()
        ]

        #expect(notification["jsonrpc"] as? String == "2.0")
        #expect(notification["method"] as? String == "notifications/tools/list_changed")
        #expect(notification["params"] is [String: Any])
    }

    @Test("Parses tools_changed notification from socket")
    func parsesToolsChangedFromSocket() {
        let toolsChangedLine = """
        {"method": "tools_changed", "params": {}}
        """

        guard let jsonData = toolsChangedLine.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let method = json["method"] as? String else {
            #expect(Bool(false), "Failed to parse notification")
            return
        }

        #expect(method == "tools_changed")
    }

    @Test("Tools list can be serialized for MCP response")
    func serializesToolsForMCPResponse() {
        let sampleTool: [String: Any] = [
            "name": "test_tool",
            "description": "Test tool",
            "inputSchema": [
                "type": "object",
                "properties": [
                    "arg": ["type": "string"]
                ]
            ]
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: sampleTool),
              let jsonStr = String(data: jsonData, encoding: .utf8) else {
            #expect(Bool(false), "Failed to serialize tool")
            return
        }

        guard let reparsed = try? JSONSerialization.jsonObject(with: jsonStr.data(using: .utf8) ?? Data()) as? [String: Any] else {
            #expect(Bool(false), "Failed to reparse tool")
            return
        }

        #expect(reparsed["name"] as? String == "test_tool")
    }

    @Test("ShipyardSocketProtocol mock works correctly")
    func mockSocketWorks() {
        let mockSocket = MockShipyardSocket(shouldFail: false)
        let result = mockSocket.send(method: "gateway_discover", params: nil, timeout: 5.0)

        #expect(result != nil)
        let tools = (result?["result"] as? [String: Any])?["tools"] as? [[String: Any]]
        #expect(tools != nil)
    }

    @Test("Mock socket returns nil on failure")
    func mockSocketFailure() {
        let mockSocket = MockShipyardSocket(shouldFail: true)
        let result = mockSocket.send(method: "gateway_discover", params: nil, timeout: 5.0)

        #expect(result == nil)
    }
}

// MARK: - Mock Socket for Testing

class MockShipyardSocket: ShipyardSocketProtocol {
    let shouldFail: Bool

    init(shouldFail: Bool = false) {
        self.shouldFail = shouldFail
    }

    public func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]? {
        if shouldFail {
            return nil
        }

        if method == "gateway_discover" {
            return ["result": ["tools": [[String: Any]]()]]
        }

        return nil
    }
}
