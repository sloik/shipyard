import Testing
import Foundation
@testable import ShipyardBridgeLib

// MARK: - Mock Socket

final class MockShipyardSocket: ShipyardSocketProtocol, @unchecked Sendable {
    var responseToReturn: [String: Any]? = nil
    var lastMethod: String? = nil
    var lastParams: [String: Any]? = nil

    func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]? {
        lastMethod = method
        lastParams = params
        return responseToReturn
    }
}

// MARK: - handleShipyardStatus Tests

@Suite("handleShipyardStatus Tests")
struct HandleShipyardStatusTests {
    @Test("Success with server list")
    func successWithServerList() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "mcp_one",
                    "version": "1.0.0",
                    "state": "running",
                    "health": "healthy",
                    "pid": 1234,
                    "cpu_percent": 12.5,
                    "memory_mb": 256.0,
                    "last_health_check": "2024-03-12T10:30:00Z",
                    "auto_restart": true,
                    "dependencies_ok": true
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(mock.lastMethod == "status")
        #expect(result.contains("mcp_one"))
        #expect(result.contains("1.0.0"))
        #expect(result.contains("running"))
        #expect(result.contains("1234"))
        #expect(result.contains("12.5%"))
        #expect(result.contains("256"))
        #expect(result.contains("healthy"))
        #expect(result.contains("on"))
        #expect(result.contains("ok"))
    }

    @Test("Socket connection failure")
    func socketConnectionFailure() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(result.contains("Error:"))
        #expect(result.contains("Failed to connect"))
    }

    @Test("Error response from socket")
    func errorResponseFromSocket() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Socket error occurred"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(result.contains("Error:"))
        #expect(result.contains("Socket error occurred"))
    }

    @Test("Invalid response format")
    func invalidResponseFormat() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": "not an array"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(result.contains("Error:"))
        #expect(result.contains("Invalid response format"))
    }

    @Test("Server with missing fields uses defaults")
    func serverWithMissingFieldsUsesDefaults() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "minimal_server"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(result.contains("minimal_server"))
        #expect(result.contains("unknown"))
    }

    @Test("Multiple servers formatting")
    func multipleServersFormatting() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "server_a",
                    "version": "1.0.0",
                    "state": "running",
                    "health": "healthy",
                    "auto_restart": false,
                    "dependencies_ok": false
                ],
                [
                    "name": "server_b",
                    "version": "2.0.0",
                    "state": "stopped",
                    "health": "unhealthy",
                    "auto_restart": true,
                    "dependencies_ok": true
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardStatus()

        #expect(result.contains("server_a"))
        #expect(result.contains("server_b"))
        #expect(result.contains("1.0.0"))
        #expect(result.contains("2.0.0"))
        #expect(result.contains("off"))
        #expect(result.contains("issues detected"))
    }
}

// MARK: - handleShipyardHealth Tests

@Suite("handleShipyardHealth Tests")
struct HandleShipyardHealthTests {
    @Test("Success with healthy servers")
    func successWithHealthyServers() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "mcp_one",
                    "healthy": true,
                    "message": "all good"
                ],
                [
                    "name": "mcp_two",
                    "healthy": false,
                    "message": "connection refused"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardHealth()

        #expect(mock.lastMethod == "health")
        #expect(result.contains("Health Status:"))
        #expect(result.contains("mcp_one"))
        #expect(result.contains("✓ healthy"))
        #expect(result.contains("mcp_two"))
        #expect(result.contains("✗ unhealthy"))
        #expect(result.contains("connection refused"))
    }

    @Test("Socket connection failure")
    func socketConnectionFailure() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardHealth()

        #expect(result.contains("Error:"))
        #expect(result.contains("Failed to connect"))
    }

    @Test("Error response from socket")
    func errorResponseFromSocket() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Health check failed"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardHealth()

        #expect(result.contains("Error:"))
        #expect(result.contains("Health check failed"))
    }

    @Test("Server with missing fields uses defaults")
    func serverWithMissingFieldsUsesDefaults() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "server_minimal"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardHealth()

        #expect(result.contains("server_minimal"))
        #expect(result.contains("✗ unhealthy"))
        #expect(result.contains("ok"))
    }

    @Test("Healthy server does not show message")
    func healthyServerDoesNotShowMessage() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "name": "healthy_server",
                    "healthy": true,
                    "message": "some message"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardHealth()

        #expect(result.contains("✓ healthy"))
        #expect(!result.contains("some message"))
    }
}

// MARK: - handleShipyardLogs Tests

@Suite("handleShipyardLogs Tests")
struct HandleShipyardLogsTests {
    @Test("Success with log entries")
    func successWithLogEntries() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "timestamp": "2024-03-12T10:30:00Z",
                    "level": "INFO",
                    "message": "Server started"
                ],
                [
                    "timestamp": "2024-03-12T10:30:01Z",
                    "level": "ERROR",
                    "message": "Connection failed"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardLogs(mcpName: "test_mcp")

        #expect(mock.lastMethod == "logs")
        #expect(result.contains("Logs for test_mcp:"))
        #expect(result.contains("[2024-03-12T10:30:00Z]"))
        #expect(result.contains("INFO: Server started"))
        #expect(result.contains("[2024-03-12T10:30:01Z]"))
        #expect(result.contains("ERROR: Connection failed"))
    }

    @Test("Socket connection failure")
    func socketConnectionFailure() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardLogs(mcpName: "test_mcp")

        #expect(result.contains("Error:"))
        #expect(result.contains("Failed to connect"))
    }

    @Test("With level filter")
    func withLevelFilter() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": []
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        _ = handleShipyardLogs(mcpName: "test_mcp", lines: 100, level: "ERROR")

        #expect(mock.lastParams != nil)
        #expect(mock.lastParams?["name"] as? String == "test_mcp")
        #expect(mock.lastParams?["lines"] as? Int == 100)
        #expect(mock.lastParams?["level"] as? String == "ERROR")
    }

    @Test("With custom line count")
    func withCustomLineCount() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": []
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        _ = handleShipyardLogs(mcpName: "test_mcp", lines: 200)

        #expect(mock.lastParams?["lines"] as? Int == 200)
    }

    @Test("Default parameters")
    func defaultParameters() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": []
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        _ = handleShipyardLogs(mcpName: "test_mcp")

        #expect(mock.lastParams?["lines"] as? Int == 50)
        #expect(mock.lastParams?["level"] == nil)
    }

    @Test("Entry with missing fields uses defaults")
    func entryWithMissingFieldsUsesDefaults() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                [
                    "timestamp": "2024-03-12T10:30:00Z"
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardLogs(mcpName: "test_mcp")

        #expect(result.contains("[2024-03-12T10:30:00Z]"))
        #expect(result.contains("INFO:"))
    }
}

// MARK: - handleShipyardRestart Tests

@Suite("handleShipyardRestart Tests")
struct HandleShipyardRestartTests {
    @Test("Success restart")
    func successRestart() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardRestart(mcpName: "test_mcp")

        #expect(mock.lastMethod == "restart")
        #expect(mock.lastParams?["name"] as? String == "test_mcp")
        #expect(result == "Restart request sent for test_mcp")
    }

    @Test("Socket connection failure")
    func socketConnectionFailure() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardRestart(mcpName: "test_mcp")

        #expect(result.contains("Error:"))
        #expect(result.contains("Failed to connect"))
    }

    @Test("Error response from socket")
    func errorResponseFromSocket() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Server not found"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardRestart(mcpName: "nonexistent")

        #expect(result.contains("Error:"))
        #expect(result.contains("Server not found"))
    }
}

// MARK: - handleShipyardGatewaySetEnabled Tests

@Suite("handleShipyardGatewaySetEnabled Tests")
struct HandleShipyardGatewaySetEnabledTests {
    @Test("Enable MCP")
    func enableMcp() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(mcpName: "test_mcp", enabled: true)

        #expect(mock.lastMethod == "gateway_set_enabled")
        #expect(mock.lastParams?["mcp"] as? String == "test_mcp")
        #expect(mock.lastParams?["enabled"] as? Bool == true)
        #expect(result == "test_mcp is now enabled")
    }

    @Test("Disable MCP")
    func disableMcp() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(mcpName: "test_mcp", enabled: false)

        #expect(mock.lastParams?["enabled"] as? Bool == false)
        #expect(result == "test_mcp is now disabled")
    }

    @Test("Enable tool")
    func enableTool() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(toolName: "test_tool", enabled: true)

        #expect(mock.lastParams?["tool"] as? String == "test_tool")
        #expect(mock.lastParams?["enabled"] as? Bool == true)
        #expect(result == "test_tool is now enabled")
    }

    @Test("Disable tool")
    func disableTool() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(toolName: "test_tool", enabled: false)

        #expect(result == "test_tool is now disabled")
    }

    @Test("Both MCP and tool names provided uses MCP")
    func bothMcpAndToolNamesProvidesUsesMcp() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(mcpName: "mcp_name", toolName: "tool_name", enabled: true)

        #expect(result == "mcp_name is now enabled")
    }

    @Test("Neither MCP nor tool name provided")
    func neitherMcpNorToolNameProvided() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(enabled: true)

        #expect(result == "unknown is now enabled")
    }

    @Test("Socket connection failure")
    func socketConnectionFailure() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(mcpName: "test_mcp", enabled: true)

        #expect(result.contains("Error:"))
        #expect(result.contains("Failed to connect"))
    }

    @Test("Error response from socket")
    func errorResponseFromSocket() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Cannot enable unknown MCP"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let result = handleShipyardGatewaySetEnabled(mcpName: "unknown_mcp", enabled: true)

        #expect(result.contains("Error:"))
        #expect(result.contains("Cannot enable unknown MCP"))
    }
}

// MARK: - handleShipyardGatewayDiscover Tests

@Suite("handleShipyardGatewayDiscover Tests")
struct HandleShipyardGatewayDiscoverTests {
    @Test("Success returns result and nil error")
    func successReturnsResultAndNilError() {
        let mock = MockShipyardSocket()
        let toolData: [String: Any] = [
            "tools": [
                [
                    "mcp": "test_mcp",
                    "name": "test_tool",
                    "description": "A test tool",
                    "enabled": true
                ]
            ]
        ]
        mock.responseToReturn = [
            "result": toolData
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayDiscover()

        #expect(mock.lastMethod == "gateway_discover")
        #expect(result != nil)
        #expect(error == nil)
        #expect(result?["tools"] != nil)
    }

    @Test("Socket failure returns nil result and error message")
    func socketFailureReturnsNilResultAndErrorMessage() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayDiscover()

        #expect(result == nil)
        #expect(error != nil)
        #expect(error?.contains("Failed to connect") == true)
    }

    @Test("Error response returns nil result and error message")
    func errorResponseReturnsNilResultAndErrorMessage() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Gateway not available"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayDiscover()

        #expect(result == nil)
        #expect(error == "Gateway not available")
    }

    @Test("Invalid response format returns error")
    func invalidResponseFormatReturnsError() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": "not a dictionary"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayDiscover()

        #expect(result == nil)
        #expect(error == "Invalid response format")
    }

    @Test("Custom timeout is passed to socket")
    func customTimeoutIsPassedToSocket() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = ["result": [:]]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        _ = handleShipyardGatewayDiscover(timeout: 30.0)

        #expect(mock.lastMethod == "gateway_discover")
    }
}

// MARK: - handleShipyardGatewayCall Tests

@Suite("handleShipyardGatewayCall Tests")
struct HandleShipyardGatewayCallTests {
    @Test("Success returns JSON string and nil error")
    func successReturnsJsonStringAndNilError() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                "status": "ok",
                "data": ["value": 123]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(mock.lastMethod == "gateway_call")
        #expect(mock.lastParams?["tool"] as? String == "test_tool")
        #expect(result != nil)
        #expect(error == nil)
        #expect(result?.contains("status") == true)
        #expect(result?.contains("ok") == true)
    }

    @Test("Socket failure returns nil result and error message")
    func socketFailureReturnsNilResultAndErrorMessage() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = nil

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result == nil)
        #expect(error != nil)
        #expect(error?.contains("Failed to connect") == true)
    }

    @Test("Error response returns nil result and error message")
    func errorResponseReturnsNilResultAndErrorMessage() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": "Tool execution failed"
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result == nil)
        #expect(error == "Tool execution failed")
    }

    @Test("Null result (not wrapped) is serialized as 'null'")
    func nullResultNotWrappedIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": NSNull()
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result == "null")
        #expect(error == nil)
    }

    @Test("Tool name and arguments are passed correctly")
    func toolNameAndArgumentsArePassedCorrectly() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [:]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let args: [String: Any] = ["param1": "value1", "param2": 42]
        _ = handleShipyardGatewayCall(toolName: "my_tool", arguments: args)

        #expect(mock.lastParams?["tool"] as? String == "my_tool")
        #expect(mock.lastParams?["arguments"] is [String: Any])
    }

    @Test("Result with complex nested structure is serialized")
    func resultWithComplexStructureIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                "data": [
                    "nested": [
                        "deep": "value"
                    ],
                    "array": [1, 2, 3]
                ]
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result?.contains("nested") == true)
        #expect(result?.contains("deep") == true)
    }

    @Test("String result is serialized as JSON string")
    func stringResultIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": ["_raw_result": "hello world"]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result == "\"hello world\"")
    }

    @Test("Array result is serialized as JSON array")
    func arrayResultIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": ["_raw_result": [1, 2, 3, "four"]]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result?.contains("1") == true)
        #expect(result?.contains("2") == true)
        #expect(result?.contains("four") == true)
    }

    @Test("Numeric result is serialized as number")
    func numericResultIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": ["_raw_result": NSNumber(value: 42)]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result == "42")
    }

    @Test("Null result is serialized as 'null'")
    func nullResultIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": ["_raw_result": NSNull()]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result == "null")
    }

    @Test("Dict error format is handled correctly")
    func dictErrorFormatIsHandled() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "error": [
                "code": NSNumber(value: -32000),
                "message": "Server error"
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result == nil)
        #expect(error == "Server error")
    }

    @Test("No result field returns invalid response format error")
    func noResultFieldReturnsError() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [:]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result == nil)
        #expect(error == "Invalid response format")
    }

    @Test("Dict result without _raw_result wrapping is serialized normally")
    func dictResultWithoutWrappingIsSerialized() {
        let mock = MockShipyardSocket()
        mock.responseToReturn = [
            "result": [
                "status": "ok",
                "value": 123
            ]
        ]

        let savedSocket = shipyardSocket
        defer { shipyardSocket = savedSocket }
        shipyardSocket = mock

        let (result, error) = handleShipyardGatewayCall(toolName: "test_tool", arguments: [:])

        #expect(result != nil)
        #expect(error == nil)
        #expect(result?.contains("status") == true)
        #expect(result?.contains("ok") == true)
    }
}
