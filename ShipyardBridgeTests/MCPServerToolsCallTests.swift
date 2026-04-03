import Testing
import Foundation
@testable import ShipyardBridgeLib

// MARK: - Mock Classes for handleToolsCall Tests

/// Mock socket that supports multiple sequential calls with different responses
final class ToolsCallMockSocket: ShipyardSocketProtocol, @unchecked Sendable {
    var responses: [[String: Any]?] = []
    var callIndex = 0
    var methods: [String] = []
    var allParams: [[String: Any]?] = []

    func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]? {
        methods.append(method)
        allParams.append(params)
        let response = callIndex < responses.count ? responses[callIndex] : nil
        callIndex += 1
        return response
    }
}

class ToolsCallMockLogger: BridgeLogging {
    var logs: [(level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]?)] = []

    func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]? = nil) {
        logs.append((level: level, cat: cat, msg: msg, meta: meta))
    }
}

// MARK: - Helper Functions

private func makeServerAndMock(gatewayResponse: [String: Any]? = nil) -> (MCPServer, ToolsCallMockSocket) {
    let mock = ToolsCallMockSocket()
    let gwResponse = gatewayResponse ?? ["result": ["tools": []] as [String: Any]]
    mock.responses.append(gwResponse)  // responses[0] = gateway_discover during init

    let savedSocket = shipyardSocket
    let savedLogger = bridgeLog
    shipyardSocket = mock
    bridgeLog = ToolsCallMockLogger()

    let server = MCPServer()
    // Reset to original before returning to allow defer in test
    shipyardSocket = savedSocket
    bridgeLog = savedLogger

    return (server, mock)
}

private func parseResponse(_ json: String?) -> [String: Any]? {
    guard let json = json, let data = json.data(using: .utf8),
          let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return nil
    }
    return dict
}

// MARK: - Test Suite: MCPServer handleToolsCall

@Suite("MCPServer handleToolsCall")
struct MCPServerToolsCallTests {

    // MARK: - Parameter Validation Tests

    @Test("Missing name parameter returns error -32602")
    func missingNameParameterReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        // Set up mock response for the test call (index 1, after gateway_discover at 0)
        mock.responses.append(nil)

        let request = MCPRequest(id: 1, method: "tools/call", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32602)
        #expect((error?["message"] as? String)?.contains("name") == true)
    }

    @Test("Missing name with empty params returns error -32602")
    func missingNameWithEmptyParamsReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let params: [String: AnyCodable] = ["arguments": .object(["key": .string("val")])]
        let request = MCPRequest(id: 2, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32602)
    }

    // MARK: - Management Tool Dispatch Tests

    @Test("shipyard_status calls socket with method status")
    func statusCallsSocket() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        // response[0] = gateway_discover (during init)
        // response[1] = status result
        mock.responses.append(["result": [] as [[String: Any]]])

        let params: [String: AnyCodable] = ["name": .string("shipyard_status")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "status")
    }

    @Test("shipyard_health calls socket with method health")
    func healthCallsSocket() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": [] as [[String: Any]]])

        let params: [String: AnyCodable] = ["name": .string("shipyard_health")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "health")
    }

    @Test("shipyard_logs with mcp_name calls socket with logs method")
    func logsCallsSocketWithMcpName() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": [] as [[String: Any]]])

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_logs"),
            "arguments": .object([
                "mcp_name": .string("test-mcp"),
                "lines": .int(100)
            ])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "logs")

        // Verify params were passed correctly
        let callParams = mock.allParams[1]
        #expect(callParams?["name"] as? String == "test-mcp")
        #expect(callParams?["lines"] as? Int == 100)
    }

    @Test("shipyard_logs without mcp_name returns error -32602")
    func logsWithoutMcpNameReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_logs"),
            "arguments": .object(["lines": .int(50)])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32602)
        #expect((error?["message"] as? String)?.contains("mcp_name") == true)
    }

    @Test("shipyard_restart with mcp_name calls socket with restart method")
    func restartCallsSocketWithMcpName() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": "success"])

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_restart"),
            "arguments": .object(["mcp_name": .string("my-mcp")])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "restart")

        let callParams = mock.allParams[1]
        #expect(callParams?["name"] as? String == "my-mcp")
    }

    @Test("shipyard_restart without mcp_name returns error -32602")
    func restartWithoutMcpNameReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let params: [String: AnyCodable] = ["name": .string("shipyard_restart")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32602)
        #expect((error?["message"] as? String)?.contains("mcp_name") == true)
    }

    @Test("shipyard_gateway_discover calls socket with gateway_discover method")
    func gatewayDiscoverCallsSocket() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": ["tools": []] as [String: Any]])

        let params: [String: AnyCodable] = ["name": .string("shipyard_gateway_discover")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "gateway_discover")
    }

    @Test("shipyard_gateway_call with tool name calls socket with gateway_call method")
    func gatewayCallWithToolName() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        let gwCallResult: [String: Any] = ["result": "success"]
        mock.responses.append(gwCallResult)

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_gateway_call"),
            "arguments": .object([
                "tool": .string("lmstudio__list_models"),
                "arguments": .object([:])
            ])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "gateway_call")

        let callParams = mock.allParams[1]
        #expect(callParams?["tool"] as? String == "lmstudio__list_models")
    }

    @Test("shipyard_gateway_call without tool parameter returns error -32602")
    func gatewayCallWithoutToolParameterReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_gateway_call"),
            "arguments": .object(["arguments": .object([:]) as [String: AnyCodable]])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32602)
        #expect((error?["message"] as? String)?.contains("tool") == true)
    }

    @Test("shipyard_gateway_set_enabled calls socket with gateway_set_enabled method")
    func gatewaySetEnabledCallsSocket() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": "success"])

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_gateway_set_enabled"),
            "arguments": .object([
                "mcp_name": .string("test"),
                "enabled": .bool(true)
            ])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        #expect(mock.methods[1] == "gateway_set_enabled")
    }

    @Test("Unknown management tool returns error message")
    func unknownManagementToolReturnsError() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let params: [String: AnyCodable] = ["name": .string("shipyard_unknown_tool")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] as? Int == -32603)
        #expect((error?["message"] as? String)?.contains("Unknown management tool") == true)
    }

    // MARK: - Gateway Tool Dispatch Tests

    @Test("Non-shipyard tool name calls handleShipyardGatewayCall")
    func nonShipyardToolCallsGatewayCall() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": "gateway result"])

        let params: [String: AnyCodable] = [
            "name": .string("lmstudio__list_models"),
            "arguments": .object(["param1": .string("value1")])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        #expect(mock.methods.count == 2)
        // Should call gateway_call for non-shipyard tools
        #expect(mock.methods[1] == "gateway_call")

        let callParams = mock.allParams[1]
        #expect(callParams?["tool"] as? String == "lmstudio__list_models")
    }

    // MARK: - Response Format Tests

    @Test("Successful tool call returns content block with type text")
    func successfulToolReturnsContentBlock() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": [] as [[String: Any]]])

        let params: [String: AnyCodable] = ["name": .string("shipyard_status")]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let content = result?["content"] as? [[String: Any]]
        #expect(content != nil)
        #expect((content?.first?["type"] as? String) == "text")
    }

    @Test("Error response has correct JSON-RPC error structure")
    func errorResponseHasCorrectStructure() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(nil)

        let request = MCPRequest(id: 1, method: "tools/call", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        #expect(parsed?["jsonrpc"] as? String == "2.0")
        let error = parsed?["error"] as? [String: Any]
        #expect(error?["code"] != nil)
        #expect(error?["message"] != nil)
    }

    @Test("Response preserves request id")
    func responsePreservesRequestId() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        mock.responses.append(["result": [] as [[String: Any]]])

        let testId = 42
        let params: [String: AnyCodable] = ["name": .string("shipyard_status")]
        let request = MCPRequest(id: testId, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        #expect(parsed?["id"] as? Int == testId)
    }

    @Test("Tool call with arguments passes them correctly to socket")
    func toolCallWithArgumentsPassesThemCorrectly() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        let gwCallResult: [String: Any] = ["result": "call succeeded"]
        mock.responses.append(gwCallResult)

        let params: [String: AnyCodable] = [
            "name": .string("shipyard_gateway_call"),
            "arguments": .object([
                "tool": .string("some__tool"),
                "arguments": .object([
                    "arg1": .string("value1"),
                    "arg2": .int(123),
                    "arg3": .bool(true)
                ])
            ])
        ]
        let request = MCPRequest(id: 1, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let callParams = mock.allParams[1]
        let passedArgs = callParams?["arguments"] as? [String: Any]
        #expect(passedArgs?["arg1"] as? String == "value1")
        #expect(passedArgs?["arg2"] as? Int == 123)
        #expect(passedArgs?["arg3"] as? Bool == true)
    }

    @Test("Multiple sequential tool calls work correctly")
    func multipleSequentialToolCallsWork() {
        let (server, mock) = makeServerAndMock()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mock
        bridgeLog = ToolsCallMockLogger()

        // Add responses for two tool calls
        mock.responses.append(["result": [] as [[String: Any]]])  // First call (status)
        mock.responses.append(["result": [] as [[String: Any]]])  // Second call (health)

        // First call: status
        let params1: [String: AnyCodable] = ["name": .string("shipyard_status")]
        let request1 = MCPRequest(id: 1, method: "tools/call", params: params1)
        let response1 = server.handleRequest(request1)
        #expect(response1 != nil)

        // Second call: health
        let params2: [String: AnyCodable] = ["name": .string("shipyard_health")]
        let request2 = MCPRequest(id: 2, method: "tools/call", params: params2)
        let response2 = server.handleRequest(request2)
        #expect(response2 != nil)

        // Verify both calls were made
        #expect(mock.methods.count == 3)  // gateway_discover + status + health
        #expect(mock.methods[1] == "status")
        #expect(mock.methods[2] == "health")
    }
}
