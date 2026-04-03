import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "MCPBridge")

/// Wrapper for JSON response to work around [String: Any] Sendable issues
struct JSONResponse: Sendable {
    nonisolated(unsafe) let dict: [String: Any]
    
    init(_ dict: [String: Any]) {
        self.dict = dict
    }
}

/// JSON-RPC 2.0 client for communicating with a child MCP process via stdio.
/// Sends requests to child stdin, correlates responses from child stdout by JSON-RPC `id`.
/// Conforms to BridgeProtocol for transport-agnostic interface.
@MainActor final class MCPBridge: BridgeProtocol {
    private let stdinHandle: FileHandle  // write end of child's stdin pipe
    nonisolated let mcpName: String
    nonisolated(unsafe) private var pendingRequests: [Int: CheckedContinuation<JSONResponse, any Error>] = [:]
    private var nextRequestId: Int = 1
    
    /// Callback for notification lines (lines with `method` but no `id`)
    var onNotification: ((String) -> Void)?
    
    /// Callback for operational log messages (bridge activity visible in UI)
    var onLog: ((String, LogLevel) -> Void)?
    
    init(mcpName: String, stdinPipe: Pipe) {
        self.mcpName = mcpName
        self.stdinHandle = stdinPipe.fileHandleForWriting
    }
    
    /// Send a JSON-RPC 2.0 request and await the response.
    /// Timeout after `timeout` seconds.
    func call(method: String, params: [String: Any]? = nil, timeout: TimeInterval = 30) async throws -> [String: Any] {
        let id = nextRequestId
        nextRequestId += 1
        
        var request: [String: Any] = [
            "jsonrpc": "2.0",
            "id": id,
            "method": method
        ]
        if let params = params {
            request["params"] = params
        }
        
        let jsonData = try JSONSerialization.data(withJSONObject: request)
        guard var lineData = String(data: jsonData, encoding: .utf8)?.data(using: .utf8) else {
            throw MCPBridgeError.serializationFailed
        }
        lineData.append(contentsOf: "\n".utf8)
        
        // Write to stdin (serialized — one write at a time)
        stdinHandle.write(lineData)
        log.debug("→ [\(self.mcpName)] id=\(id) method=\(method)")
        onLog?("→ [\(mcpName)] \(method)", .debug)
        
        // Await response with timeout.
        // Uses continuation + timeout task instead of task group to keep
        // pendingRequests access on MainActor (group.addTask escapes isolation).
        let mcpName = self.mcpName
        let timeoutTask = Task {
            try await Task.sleep(for: .seconds(timeout))
            await MainActor.run { [weak self] in
                if let continuation = self?.pendingRequests.removeValue(forKey: id) {
                    continuation.resume(throwing: MCPBridgeError.timeout(mcpName, method, timeout))
                }
            }
        }
        
        let response: JSONResponse
        do {
            response = try await withCheckedThrowingContinuation { continuation in
                self.pendingRequests[id] = continuation
            }
            timeoutTask.cancel()
        } catch {
            timeoutTask.cancel()
            pendingRequests.removeValue(forKey: id)
            throw error
        }
        
        pendingRequests.removeValue(forKey: id)
        return response.dict
    }

    /// Perform the MCP protocol initialization handshake.
    /// Must be called once after the child process starts, before any other calls.
    func initialize() async throws -> [String: Any] {
        let params: [String: Any] = [
            "protocolVersion": "2024-11-05",
            "capabilities": [:] as [String: Any],
            "clientInfo": [
                "name": "Shipyard",
                "version": "1.0"
            ] as [String: Any]
        ]

        let result = try await call(method: "initialize", params: params)
        let serverInfo = String(describing: result["serverInfo"] ?? "no serverInfo")
        log.info("MCP initialized for \(self.mcpName): \(serverInfo)")

        onLog?("[\(mcpName)] initialized: \(serverInfo)", .info)
        
        // Send initialized notification (no id, no response expected)
        try sendNotification(method: "notifications/initialized")
        
        return result
    }

    /// Send a JSON-RPC 2.0 notification (no id, no response).
    private func sendNotification(method: String, params: [String: Any]? = nil) throws {
        var notification: [String: Any] = [
            "jsonrpc": "2.0",
            "method": method
        ]
        if let params = params {
            notification["params"] = params
        }

        let jsonData = try JSONSerialization.data(withJSONObject: notification)
        guard var lineData = String(data: jsonData, encoding: .utf8)?.data(using: .utf8) else {
            throw MCPBridgeError.serializationFailed
        }
        lineData.append(contentsOf: "\n".utf8)
        stdinHandle.write(lineData)
        log.debug("→ [\(self.mcpName)] notification: \(method)")
    }

    /// Route a stdout JSON line. Called by ProcessManager's captureStdout.
    /// Returns true if the line was consumed (was a response), false if it's a notification.
    func routeStdoutLine(_ line: String) -> Bool {
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false  // not valid JSON — let caller handle
        }
        
        // Response: has "id" field (could be result or error)
        if let id = json["id"] as? Int, let continuation = pendingRequests.removeValue(forKey: id) {
            log.debug("← [\(self.mcpName)] id=\(id) response received")
            
            if let error = json["error"] as? [String: Any] {
                let errorMsg = error["message"] as? String ?? "unknown error"
                onLog?("← [\(mcpName)] id=\(id) error: \(errorMsg)", .error)
                continuation.resume(throwing: MCPBridgeError.childError(self.mcpName, errorMsg))
            } else if let result = json["result"] as? [String: Any] {
                onLog?("← [\(mcpName)] id=\(id) response", .debug)
                continuation.resume(returning: JSONResponse(result))
            } else if json["result"] != nil || json.keys.contains("result") {
                // Result might be an array or other type — wrap it in a dict with _raw_result
                onLog?("← [\(mcpName)] id=\(id) response", .debug)
                continuation.resume(returning: JSONResponse(["_raw_result": json["result"] ?? NSNull()]))
            } else {
                // No result or error field — wrap entire envelope
                onLog?("← [\(mcpName)] id=\(id) response", .debug)
                continuation.resume(returning: JSONResponse(json))
            }
            return true
        }
        
        // Notification: has "method" field but no "id" — route to callback
        if json["method"] != nil && json["id"] == nil {
            onNotification?(line)
            return true
        }
        
        return false  // unknown format
    }
    
    /// Discover tools from this child MCP by calling tools/list
    func discoverTools() async throws -> [[String: Any]] {
        onLog?("→ [\(mcpName)] tools/list", .debug)
        let response = try await call(method: "tools/list")
        // MCP tools/list returns {"tools": [...]}
        let tools = response["tools"] as? [[String: Any]] ?? []
        onLog?("← [\(mcpName)] tools/list → \(tools.count) tools", .info)
        return tools
    }
    
    /// Call a tool on this child MCP
    func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any] {
        onLog?("→ [\(mcpName)] tools/call: \(name)", .info)
        let result = try await call(method: "tools/call", params: ["name": name, "arguments": arguments])
        onLog?("← [\(mcpName)] tools/call: \(name) done", .info)
        return result
    }
    
    /// Cancel all pending requests (called when child MCP stops)
    func cancelAll() {
        onLog?("[\(mcpName)] cancelling \(pendingRequests.count) pending requests", .warning)
        for (id, continuation) in pendingRequests {
            continuation.resume(throwing: MCPBridgeError.mcpStopped(mcpName))
            log.debug("Cancelled pending request id=\(id) for \(self.mcpName)")
        }
        pendingRequests.removeAll()
    }

    /// BridgeProtocol conformance: disconnect (no-op for stdio - cleanup handled by ProcessManager)
    func disconnect() async {
        log.info("[\\(mcpName)] disconnect called (stdio bridge)")
        cancelAll()
    }
}

enum MCPBridgeError: LocalizedError, Sendable {
    case serializationFailed
    case timeout(String, String, TimeInterval)
    case childError(String, String)  // (mcpName, errorMessage)
    case mcpStopped(String)
    case notRunning(String)
    
    var errorDescription: String? {
        switch self {
        case .serializationFailed:
            return L10n.string("error.mcpBridge.serializationFailed")
        case .timeout(let mcp, let method, let secs):
            return L10n.format("error.mcpBridge.timeout", mcp, method, Int64(secs))
        case .childError(let mcp, let msg):
            return L10n.format("error.mcpBridge.childError", mcp, msg)
        case .mcpStopped(let mcp):
            return L10n.format("error.mcpBridge.stopped", mcp)
        case .notRunning(let mcp):
            return L10n.format("error.mcpBridge.notRunning", mcp)
        }
    }
}
