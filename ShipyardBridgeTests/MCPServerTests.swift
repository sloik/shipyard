import Testing
import Foundation
@testable import ShipyardBridgeLib

// MARK: - Mock Classes for MCPServer Tests

final class MCPServerMockSocket: ShipyardSocketProtocol, @unchecked Sendable {
    var responseToReturn: [String: Any]? = nil
    var lastMethod: String? = nil
    var lastParams: [String: Any]? = nil
    var callCount = 0

    func send(method: String, params: [String: Any]?, timeout: TimeInterval) -> [String: Any]? {
        lastMethod = method
        lastParams = params
        callCount += 1
        return responseToReturn
    }
}

class MCPServerMockLogger: BridgeLogging {
    var logs: [(level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]?)] = []

    func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]? = nil) {
        logs.append((level: level, cat: cat, msg: msg, meta: meta))
    }
}

// MARK: - Helper Methods

private func makeServer(mockSocket: MCPServerMockSocket, gatewayTools: [[String: Any]]? = nil) -> MCPServer {
    if let tools = gatewayTools {
        mockSocket.responseToReturn = ["result": ["tools": tools]]
    } else {
        mockSocket.responseToReturn = ["result": ["tools": []] as [String: Any]]
    }
    return MCPServer()
}

private func parseResponse(_ json: String?) -> [String: Any]? {
    guard let json = json, let data = json.data(using: .utf8),
          let dict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return nil
    }
    return dict
}

// MARK: - Suite 1: MCPServer handleRequest Dispatch Tests

@Suite("MCPServer handleRequest Dispatch")
struct MCPServerDispatchTests {
    @Test("Notifications return nil (no response)")
    func notificationsReturnNil() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: nil, method: "notifications/progress", params: nil)
        let response = server.handleRequest(request)

        #expect(response == nil)
    }

    @Test("Initialize returns valid JSON-RPC response")
    func initializeReturnsValidResponse() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        #expect(parsed?["result"] != nil)
    }

    @Test("Tools/list returns valid JSON-RPC response")
    func toolsListReturnsValidResponse() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 2, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        #expect(parsed?["result"] != nil)
    }

    @Test("Tools/call with valid tool name dispatches correctly")
    func toolsCallValidToolName() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)

        // Set response for shipyard_status call
        mockSocket.responseToReturn = [
            "result": []
        ]

        let params: [String: AnyCodable] = ["name": .string("shipyard_status")]
        let request = MCPRequest(id: 3, method: "tools/call", params: params)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        #expect(parsed?["result"] != nil)
    }

    @Test("Unknown method returns error -32601")
    func unknownMethodReturnsError() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 4, method: "unknown/method", params: nil)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        let error = parsed?["error"] as? [String: Any]
        #expect(error != nil)
        let code = error?["code"] as? Int
        #expect(code == -32601)
    }

    @Test("Request with null id still works")
    func requestWithNullIdWorks() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: nil, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        #expect(parsed?["result"] != nil)
    }

    @Test("Notification with notifications/ prefix returns nil regardless of content")
    func notificationPrefixReturnsNil() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: nil, method: "notifications/something", params: nil)
        let response = server.handleRequest(request)

        #expect(response == nil)
    }

    @Test("Response is valid JSON string with jsonrpc 2.0")
    func responseIsValidJSON() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 5, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        #expect(response != nil)
        let parsed = parseResponse(response)
        #expect(parsed != nil)
        let jsonrpc = parsed?["jsonrpc"] as? String
        #expect(jsonrpc == "2.0")
    }
}

// MARK: - Suite 2: MCPServer handleInitialize Tests

@Suite("MCPServer handleInitialize")
struct MCPServerInitializeTests {
    @Test("Response contains protocolVersion 2025-11-25")
    func responseContainsProtocolVersion() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let protocolVersion = result?["protocolVersion"] as? String
        #expect(protocolVersion == "2025-11-25")
    }

    @Test("Response contains capabilities with tools.listChanged = true")
    func responseContainsCapabilities() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let capabilities = result?["capabilities"] as? [String: Any]
        let tools = capabilities?["tools"] as? [String: Any]
        let listChanged = tools?["listChanged"] as? Bool
        #expect(listChanged == true)
    }

    @Test("Response contains serverInfo.name = shipyard")
    func responseContainsServerName() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let serverInfo = result?["serverInfo"] as? [String: Any]
        let name = serverInfo?["name"] as? String
        #expect(name == "shipyard")
    }

    @Test("Response contains serverInfo.version = 1.0.0")
    func responseContainsServerVersion() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let serverInfo = result?["serverInfo"] as? [String: Any]
        let version = serverInfo?["version"] as? String
        #expect(version == "1.0.0")
    }

    @Test("Response has jsonrpc 2.0 and matching id")
    func responseHasJsonrpcAndId() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let testId = 42
        let request = MCPRequest(id: testId, method: "initialize", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let jsonrpc = parsed?["jsonrpc"] as? String
        let id = parsed?["id"] as? Int
        #expect(jsonrpc == "2.0")
        #expect(id == testId)
    }
}

// MARK: - Suite 3: MCPServer handleToolsList Tests

@Suite("MCPServer handleToolsList")
struct MCPServerToolsListTests {
    @Test("Returns 7 management tools when no gateway tools")
    func returnsSevenManagementTools() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]
        #expect(tools?.count == 7)
    }

    @Test("Each management tool has name, description, inputSchema")
    func managementToolsHaveRequiredFields() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]

        for tool in tools ?? [] {
            #expect(tool["name"] != nil)
            #expect(tool["description"] != nil)
            #expect(tool["inputSchema"] != nil)
        }
    }

    @Test("Management tool names are correct")
    func managementToolNamesAreCorrect() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]
        let toolNames = tools?.compactMap { $0["name"] as? String } ?? []

        let expectedNames = [
            "shipyard_status",
            "shipyard_health",
            "shipyard_logs",
            "shipyard_restart",
            "shipyard_gateway_discover",
            "shipyard_gateway_call",
            "shipyard_gateway_set_enabled"
        ]

        for expectedName in expectedNames {
            #expect(toolNames.contains(expectedName))
        }
    }

    @Test("Tools with required fields include required in schema")
    func toolsWithRequiredFieldsHaveRequired() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]

        // Find shipyard_logs tool
        let shipyardLogsTool = tools?.first { ($0["name"] as? String) == "shipyard_logs" }
        let schema = shipyardLogsTool?["inputSchema"] as? [String: Any]
        let required = schema?["required"] as? [String]

        #expect(required != nil)
        #expect(required?.contains("mcp_name") == true)
    }

    @Test("Tools with default values include default in properties")
    func toolsWithDefaultValuesHaveDefault() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let server = makeServer(mockSocket: mockSocket)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]

        // Find shipyard_logs tool
        let shipyardLogsTool = tools?.first { ($0["name"] as? String) == "shipyard_logs" }
        let schema = shipyardLogsTool?["inputSchema"] as? [String: Any]
        let properties = schema?["properties"] as? [String: Any]
        let linesProperty = properties?["lines"] as? [String: Any]
        let defaultValue = linesProperty?["default"]

        #expect(defaultValue != nil)
    }

    @Test("With gateway tools, total tool count increases")
    func gatewayToolsIncreaseCount() {
        let mockSocket = MCPServerMockSocket()
        let mockLogger = MCPServerMockLogger()

        let savedSocket = shipyardSocket
        let savedLogger = bridgeLog
        defer {
            shipyardSocket = savedSocket
            bridgeLog = savedLogger
        }
        shipyardSocket = mockSocket
        bridgeLog = mockLogger

        let gatewayToolsList: [[String: Any]] = [
            [
                "name": "external_tool_1",
                "description": "First external tool",
                "inputSchema": [
                    "type": "object",
                    "properties": [:]
                ]
            ],
            [
                "name": "external_tool_2",
                "description": "Second external tool",
                "inputSchema": [
                    "type": "object",
                    "properties": [:]
                ]
            ]
        ]

        let server = makeServer(mockSocket: mockSocket, gatewayTools: gatewayToolsList)
        let request = MCPRequest(id: 1, method: "tools/list", params: nil)
        let response = server.handleRequest(request)

        let parsed = parseResponse(response)
        let result = parsed?["result"] as? [String: Any]
        let tools = result?["tools"] as? [[String: Any]]

        // 7 management tools + 2 gateway tools = 9 total
        #expect(tools?.count == 9)
    }
}
