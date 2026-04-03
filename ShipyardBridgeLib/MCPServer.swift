import Foundation
import Darwin

// MARK: - MCP Server

public class MCPServer {
    private var managementTools: [ToolDef] = []
    private var gatewayTools: [ToolDef] = []
    private var allTools: [ToolDef] = []
    private var notificationListener: Thread?
    private var isListening = false
    private let listenerStateLock = NSLock()
    private var clientInitialized = false

    public init() {
        self.managementTools = buildManagementTools()
        self.allTools = self.managementTools
        // Discover gateway tools once at startup (5s timeout)
        refreshGatewayTools()

        if gatewayTools.isEmpty {
            bridgeLog.log(.warn, cat: "init", msg: "gateway refresh: no tools found, proceeding with management-only")
        } else {
            bridgeLog.log(.info, cat: "init", msg: "gateway refresh: \(gatewayTools.count) tools discovered", meta: ["tool_count": gatewayTools.count])
        }

    }

    deinit {
        stopNotificationListener()
    }

    private func refreshGatewayTools() {
        let (gatewayData, _) = handleShipyardGatewayCatalog()
        guard let gatewayData = gatewayData,
              let tools = gatewayData["tools"] as? [[String: Any]] else {
            self.gatewayTools = []
            return
        }

        var newTools: [ToolDef] = []
        for toolDict in tools {
            guard let name = toolDict["name"] as? String,
                  let description = toolDict["description"] as? String,
                  let schemaDict = toolDict["inputSchema"] as? [String: Any] else {
                continue
            }

            // Parse inputSchema into ToolInputSchema
            let properties = schemaDict["properties"] as? [String: Any] ?? [:]
            let required = schemaDict["required"] as? [String] ?? []

            var propDefs: [String: ToolInputSchema.PropertyDef] = [:]
            for (key, propDict) in properties {
                if let prop = propDict as? [String: Any] {
                    let type = prop["type"] as? String ?? "string"
                    let desc = prop["description"] as? String
                    let defaultVal = prop["default"]

                    var defaultCodable: AnyCodable? = nil
                    if let defaultVal = defaultVal {
                        if let b = defaultVal as? Bool {
                            defaultCodable = .bool(b)
                        } else if let i = defaultVal as? Int {
                            defaultCodable = .int(i)
                        } else if let d = defaultVal as? Double {
                            defaultCodable = .double(d)
                        } else if let s = defaultVal as? String {
                            defaultCodable = .string(s)
                        }
                    }

                    propDefs[key] = ToolInputSchema.PropertyDef(type: type, description: desc, default: defaultCodable)
                }
            }

            let schema = ToolInputSchema(type: "object", properties: propDefs, required: required)
            newTools.append(ToolDef(name: name, description: description, inputSchema: schema))
        }

        self.gatewayTools = newTools
        self.allTools = self.managementTools + self.gatewayTools
    }

    // MARK: - Notification Listener (Spec 004)

    /// Starts a background thread that listens for tools_changed notifications from Shipyard
    private func startNotificationListener() {
        guard !isListening else { return }

        isListening = true
        let listener = Thread { [weak self] in
            self?.notificationListenerLoop()
        }
        listener.name = "ShipyardNotificationListener"
        listener.start()
        notificationListener = listener

        bridgeLog.log(.info, cat: "notif", msg: "Notification listener thread started")
    }

    /// Stops the notification listener thread
    private func stopNotificationListener() {
        isListening = false
        notificationListener?.cancel()
        notificationListener = nil

        bridgeLog.log(.info, cat: "notif", msg: "Notification listener thread stopped")
    }

    /// Background loop that listens for notifications on the Shipyard socket
    /// Connects to the socket and reads notifications, processing tools_changed
    private func notificationListenerLoop() {
        let SOCKET_PATH = NSHomeDirectory() + "/Library/Application Support/Shipyard/shipyard.sock"

        while isListening {
            // Open connection to Shipyard socket
            let socketFD = socket(AF_UNIX, SOCK_STREAM, 0)
            guard socketFD >= 0 else {
                Thread.sleep(forTimeInterval: 2.0)
                continue
            }

            defer { close(socketFD) }

            // Connect to socket
            var addr = sockaddr_un()
            addr.sun_family = sa_family_t(AF_UNIX)
            let pathBytes = SOCKET_PATH.utf8CString

            guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
                Thread.sleep(forTimeInterval: 2.0)
                continue
            }

            pathBytes.withUnsafeBufferPointer { srcBuffer in
                withUnsafeMutableBytes(of: &addr.sun_path) { dstBuffer in
                    dstBuffer.copyMemory(from: UnsafeRawBufferPointer(srcBuffer))
                }
            }

            var addrCopy = addr
            let addrLen = MemoryLayout<sockaddr_un>.size

            let connectResult = withUnsafePointer(to: &addrCopy) { ptr in
                connect(
                    socketFD,
                    UnsafeRawPointer(ptr).assumingMemoryBound(to: sockaddr.self),
                    socklen_t(addrLen)
                )
            }

            guard connectResult == 0 else {
                Thread.sleep(forTimeInterval: 2.0)
                continue
            }

            bridgeLog.log(.debug, cat: "notif", msg: "Connected to Shipyard for notification listening")

            // Set a long read timeout
            var tv = timeval()
            tv.tv_sec = 300  // 5 minutes
            tv.tv_usec = 0
            setsockopt(socketFD, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))

            // Read notifications from the socket
            var buffer = [UInt8](repeating: 0, count: 4096)
            var partialData = ""

            while isListening {
                let bytesRead = Darwin.read(socketFD, &buffer, 4096)

                if bytesRead <= 0 {
                    // Connection closed or timeout
                    break
                }

                if let str = String(bytes: Array(buffer.prefix(bytesRead)), encoding: .utf8) {
                    partialData.append(str)

                    // Parse complete lines (notifications are JSON-RPC)
                    while let newlineIdx = partialData.firstIndex(of: "\n") {
                        let line = String(partialData[..<newlineIdx]).trimmingCharacters(in: .whitespacesAndNewlines)
                        partialData.removeFirst(partialData.distance(from: partialData.startIndex, to: partialData.index(after: newlineIdx)))

                        if !line.isEmpty,
                           let jsonData = line.data(using: .utf8),
                           let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
                           let method = json["method"] as? String {

                            if method == "tools_changed" {
                                bridgeLog.log(.info, cat: "notif", msg: "Received tools_changed notification")
                                // Refresh gateway tools immediately
                                refreshGatewayTools()
                                // Emit the MCP protocol notification to Claude
                                emitToolsListChangedNotification()
                            }
                        }
                    }
                }
            }

            bridgeLog.log(.debug, cat: "notif", msg: "Disconnected from Shipyard, reconnecting...")

            // Reconnect after delay
            if isListening {
                Thread.sleep(forTimeInterval: 2.0)
            }
        }
    }

    /// Emits the MCP 2.0 notifications/tools/list_changed notification to Claude via stdout
    private func emitToolsListChangedNotification() {
        guard isClientInitialized() else {
            bridgeLog.log(.debug, cat: "notif", msg: "suppress tools/list_changed before client initialization")
            return
        }

        let notification: [String: Any] = [
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": [:]
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: notification),
              let jsonStr = String(data: jsonData, encoding: .utf8) else {
            bridgeLog.log(.error, cat: "notif", msg: "Failed to serialize tools/list_changed notification")
            return
        }

        let outputLine = jsonStr + "\n"
        FileHandle.standardOutput.write(outputLine.data(using: .utf8) ?? Data())

        bridgeLog.log(.info, cat: "notif", msg: "Emitted notifications/tools/list_changed to Claude")
    }

    private func markClientInitialized() {
        listenerStateLock.lock()
        clientInitialized = true
        listenerStateLock.unlock()
    }

    private func isClientInitialized() -> Bool {
        listenerStateLock.lock()
        let value = clientInitialized
        listenerStateLock.unlock()
        return value
    }

    public func handleRequest(_ request: MCPRequest) -> String? {
        let startTime = CFAbsoluteTimeGetCurrent()

        // Check if this is a notification (notifications never get responses)
        if request.method.hasPrefix("notifications/") {
            if request.method == "notifications/initialized" {
                markClientInitialized()
                startNotificationListener()
                bridgeLog.log(.info, cat: "mcp", msg: "client initialized; notification listener started")
            }
            bridgeLog.log(.debug, cat: "mcp", msg: "notification consumed: \(request.method)")
            return nil
        }

        let idStr = request.id.map { String($0) } ?? "null"
        bridgeLog.log(.info, cat: "mcp", msg: "request: \(request.method) id=\(idStr)")

        let response: String?
        switch request.method {
        case "initialize":
            response = handleInitialize(id: request.id)

        case "tools/list":
            response = handleToolsList(id: request.id)

        case "tools/call":
            response = handleToolsCall(id: request.id, params: request.params)

        default:
            response = encodeError(id: request.id, code: -32601, message: "Method not found: \(request.method)")
        }

        let durationMs = Int((CFAbsoluteTimeGetCurrent() - startTime) * 1000)
        bridgeLog.log(.info, cat: "mcp", msg: "response: \(request.method) \(durationMs)ms")

        return response
    }

    private func handleInitialize(id: Int?) -> String? {
        let capabilities = [
            "tools": [
                "listChanged": true
            ]
        ] as [String: Any]

        let serverInfo = [
            "name": "shipyard",
            "version": "1.0.0"
        ] as [String: Any]

        let result: [String: Any] = [
            "protocolVersion": "2025-11-25",
            "capabilities": capabilities,
            "serverInfo": serverInfo
        ]

        return encodeResponse(id: id, result: result)
    }

    private func handleToolsList(id: Int?) -> String? {
        // Gateway tools cached from init(); no socket call here
        let toolsArray = allTools.map { tool -> [String: Any] in
            var schemaDict: [String: Any] = [
                "type": tool.inputSchema.type,
                "properties": [:]
            ]

            var propertiesDict: [String: Any] = [:]
            for (key, prop) in tool.inputSchema.properties {
                var propDict: [String: Any] = ["type": prop.type]
                if let desc = prop.description {
                    propDict["description"] = desc
                }
                if let def = prop.default {
                    propDict["default"] = def.toAny()
                }
                propertiesDict[key] = propDict
            }
            schemaDict["properties"] = propertiesDict

            if !tool.inputSchema.required.isEmpty {
                schemaDict["required"] = tool.inputSchema.required
            }

            return [
                "name": tool.name,
                "description": tool.description,
                "inputSchema": schemaDict
            ]
        }

        let result = ["tools": toolsArray]
        return encodeResponse(id: id, result: result)
    }

    private func handleToolsCall(id: Int?, params: [String: AnyCodable]?) -> String? {
        guard let params = params,
              let nameAnyCodable = params["name"],
              case .string(let toolName) = nameAnyCodable else {
            return encodeError(id: id, code: -32602, message: "Missing required parameter: name")
        }

        let argsAnyCodable: [String: AnyCodable]?
        if let argValue = params["arguments"], case .object(let obj) = argValue {
            argsAnyCodable = obj
        } else {
            argsAnyCodable = nil
        }
        let arguments = extractParams(argsAnyCodable)

        let category = toolName.hasPrefix("shipyard_") ? "mcp" : "gateway"
        bridgeLog.log(.info, cat: category, msg: "tool call: \(toolName)", meta: ["tool": toolName])

        var resultText: String?
        var errorMsg: String?

        // Check if it's a management tool
        if toolName.hasPrefix("shipyard_") {
            switch toolName {
            case "shipyard_status":
                resultText = handleShipyardStatus()

            case "shipyard_health":
                resultText = handleShipyardHealth()

            case "shipyard_logs":
                guard let mcpName = arguments["mcp_name"] as? String else {
                    return encodeError(id: id, code: -32602, message: "Missing required parameter: mcp_name")
                }
                let lines = arguments["lines"] as? Int ?? 50
                let level = arguments["level"] as? String
                resultText = handleShipyardLogs(mcpName: mcpName, lines: lines, level: level)

            case "shipyard_restart":
                guard let mcpName = arguments["mcp_name"] as? String else {
                    return encodeError(id: id, code: -32602, message: "Missing required parameter: mcp_name")
                }
                resultText = handleShipyardRestart(mcpName: mcpName)

            case "shipyard_gateway_discover":
                let (discoverData, discoverError) = handleShipyardGatewayDiscover(timeout: EXTENDED_TIMEOUT)
                if let error = discoverError {
                    errorMsg = error
                } else {
                    resultText = formatGatewayDiscoverResult(discoverData)
                }

            case "shipyard_gateway_call":
                guard let toolToCall = arguments["tool"] as? String else {
                    return encodeError(id: id, code: -32602, message: "Missing required parameter: tool")
                }
                let callArgs = arguments["arguments"] as? [String: Any] ?? [:]
                let (callResult, callError) = handleShipyardGatewayCall(toolName: toolToCall, arguments: callArgs)
                resultText = callResult
                errorMsg = callError

            case "shipyard_gateway_set_enabled":
                let mcpName = arguments["mcp_name"] as? String
                let toolName = arguments["tool_name"] as? String
                let enabled = arguments["enabled"] as? Bool ?? true
                resultText = handleShipyardGatewaySetEnabled(mcpName: mcpName, toolName: toolName, enabled: enabled)

            default:
                errorMsg = "Unknown management tool: \(toolName)"
            }
        } else {
            // It's a gateway tool
            let (gwResult, gwError) = handleShipyardGatewayCall(toolName: toolName, arguments: arguments)
            resultText = gwResult
            errorMsg = gwError
        }

        let success = errorMsg == nil
        bridgeLog.log(.info, cat: category, msg: "tool result: \(toolName) \(success ? "ok" : "error")", meta: ["tool": toolName, "success": success])

        if let errorMsg = errorMsg {
            return encodeError(id: id, code: -32603, message: errorMsg)
        }

        if let resultText = resultText {
            let contentBlock = MCPContentBlock(type: "text", text: resultText)
            let toolResult = MCPToolResult(content: [contentBlock])

            if let data = try? JSONEncoder().encode(toolResult),
               let resultDict = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return encodeResponse(id: id, result: resultDict)
            }
        }

        return encodeError(id: id, code: -32603, message: "Failed to call tool")
    }

    public func run() {
        let input = FileHandle.standardInput
        let inputStream = FileInputStream(handle: input)

        while let line = inputStream.readLine() {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)

            if trimmed.isEmpty {
                continue
            }

            bridgeLog.log(.debug, cat: "stdin", msg: "line \(trimmed.count) chars")

            guard let request = parseJSONLine(trimmed) else {
                bridgeLog.log(.error, cat: "stdin", msg: "JSON parse error", meta: ["line_preview": String(trimmed.prefix(200))])
                let error = encodeError(id: nil, code: -32700, message: "Parse error")
                if let error = error {
                    FileHandle.standardOutput.write(error.data(using: .utf8) ?? Data())
                    FileHandle.standardOutput.write("\n".data(using: .utf8) ?? Data())
                }
                continue
            }

            if let response = handleRequest(request) {
                FileHandle.standardOutput.write(response.data(using: .utf8) ?? Data())
                FileHandle.standardOutput.write("\n".data(using: .utf8) ?? Data())
            }
        }

        // EOF on stdin — exit gracefully
        bridgeLog.log(.info, cat: "stdin", msg: "EOF on stdin, exiting")
        exit(0)
    }

    private func encodeResponse(id: Int?, result: Any) -> String? {
        guard let jsonData = try? JSONSerialization.data(withJSONObject: result),
              let resultDict = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
            return encodeError(id: id, code: -32603, message: "Internal serialization error")
        }

        var responseDict: [String: Any] = [
            "jsonrpc": "2.0"
        ]

        if let id = id {
            responseDict["id"] = id
        }

        responseDict["result"] = resultDict

        guard let data = try? JSONSerialization.data(withJSONObject: responseDict),
              let json = String(data: data, encoding: .utf8) else {
            return nil
        }

        return json
    }

    private func encodeError(id: Int?, code: Int, message: String) -> String? {
        var responseDict: [String: Any] = [
            "jsonrpc": "2.0",
            "error": [
                "code": code,
                "message": message
            ]
        ]

        if let id = id {
            responseDict["id"] = id
        }

        guard let data = try? JSONSerialization.data(withJSONObject: responseDict),
              let json = String(data: data, encoding: .utf8) else {
            return nil
        }

        return json
    }
}
