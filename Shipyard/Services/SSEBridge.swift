import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "SSEBridge")

/// Legacy HTTP+SSE transport bridge for backward-compatible MCP servers.
/// NOT @MainActor — network calls execute off main thread.
/// Maintains a persistent SSE (Server-Sent Events) connection for incoming messages
/// and uses HTTP POST for outgoing messages.
final class SSEBridge: BridgeProtocol, Sendable {
    nonisolated let mcpName: String
    nonisolated let endpointURL: URL
    nonisolated let customHeaders: [String: String]
    nonisolated let timeout: TimeInterval

    /// Thread-safe bridge state
    private let state: OSAllocatedUnfairLock<SSEBridgeState>

    struct SSEBridgeState: Sendable {
        var isInitialized: Bool = false
        var messageID: Int = 1  // Incrementing request ID for correlation
        /// Pending responses awaiting SSE stream delivery, keyed by JSON-RPC id
        /// Stored as JSON Data for Sendable conformance
        var pendingResponses: [Int: Data] = [:]
    }

    /// URLSession for HTTP communication
    nonisolated private let urlSession: URLSession

    /// Task tracking the persistent SSE stream read
    private let sseStreamTask: OSAllocatedUnfairLock<Task<Void, Never>?>

    init(
        mcpName: String,
        endpointURL: URL,
        customHeaders: [String: String] = [:],
        timeout: TimeInterval = 30
    ) {
        self.mcpName = mcpName
        self.endpointURL = endpointURL
        self.customHeaders = customHeaders
        self.timeout = timeout
        self.state = OSAllocatedUnfairLock(initialState: SSEBridgeState())
        self.sseStreamTask = OSAllocatedUnfairLock(initialState: nil)

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        config.waitsForConnectivity = false
        self.urlSession = URLSession(configuration: config)
    }

    /// Initialize the MCP connection.
    /// Establishes persistent SSE stream and sends InitializeRequest.
    nonisolated func initialize() async throws -> [String: Any] {
        log.debug("[\(self.mcpName)] Initializing SSE bridge...")

        // Start persistent SSE stream in background
        startSSEStream()

        // Send initialization request
        let initRequest: [String: Any] = [
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": [
                "protocolVersion": "2024-11-05",
                "capabilities": [:] as [String: Any],
                "clientInfo": [
                    "name": "Shipyard",
                    "version": "1.0"
                ] as [String: Any]
            ] as [String: Any]
        ]

        let response = try await sendMessage(jsonObject: initRequest, requestId: 1)
        state.withLock { $0.isInitialized = true }
        log.info("[\(self.mcpName)] Initialized SSE connection")
        return response
    }

    /// Call a tool by name with arguments.
    nonisolated func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any] {
        let isInit = state.withLock { $0.isInitialized }
        guard isInit else {
            throw BridgeError.notInitialized(mcpName)
        }

        let requestId = state.withLock { state -> Int in
            let id = state.messageID
            state.messageID += 1
            return id
        }

        let toolRequest: [String: Any] = [
            "jsonrpc": "2.0",
            "id": requestId,
            "method": "tools/call",
            "params": [
                "name": name,
                "arguments": arguments
            ] as [String: Any]
        ]

        return try await sendMessage(jsonObject: toolRequest, requestId: requestId)
    }

    /// Discover available tools.
    nonisolated func discoverTools() async throws -> [[String: Any]] {
        let isInit = state.withLock { $0.isInitialized }
        guard isInit else {
            throw BridgeError.notInitialized(mcpName)
        }

        let requestId = state.withLock { state -> Int in
            let id = state.messageID
            state.messageID += 1
            return id
        }

        let discoverRequest: [String: Any] = [
            "jsonrpc": "2.0",
            "id": requestId,
            "method": "tools/list",
            "params": [:] as [String: Any]
        ]

        let response = try await sendMessage(jsonObject: discoverRequest, requestId: requestId)

        if let tools = response["tools"] as? [[String: Any]] {
            return tools
        }

        log.warning("[\(self.mcpName)] tools/list response missing 'tools' field")
        return []
    }

    /// Disconnect the bridge.
    /// Closes the SSE stream.
    nonisolated func disconnect() async {
        log.debug("[\(self.mcpName)] Disconnecting SSE bridge")
        stopSSEStream()
        state.withLock { $0.isInitialized = false }
    }

    // MARK: - Private Helpers

    /// Send a JSON-RPC message via HTTP POST and wait for response via SSE stream.
    private nonisolated func sendMessage(
        jsonObject: [String: Any],
        requestId: Int
    ) async throws -> [String: Any] {
        // Register pending response (empty initially, will be filled by SSE stream)
        state.withLock { state in
            state.pendingResponses[requestId] = Data()
        }

        defer {
            state.withLock { state in
                state.pendingResponses.removeValue(forKey: requestId)
            }
        }

        // Send message via POST
        let jsonData = try JSONSerialization.data(withJSONObject: jsonObject)
        var request = URLRequest(url: endpointURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = timeout
        addHeaders(to: &request)

        do {
            request.httpBody = jsonData
            let (responseData, httpResponse) = try await urlSession.data(for: request)

            guard let httpResponse = httpResponse as? HTTPURLResponse else {
                throw BridgeError.connectionFailed(mcpName, "Invalid response type")
            }

            if httpResponse.statusCode >= 400 {
                let errorMsg = String(data: responseData, encoding: .utf8) ?? "Unknown error"
                throw BridgeError.httpError(mcpName, httpResponse.statusCode, errorMsg)
            }

            // Legacy SSE: messages come back via SSE stream, not in POST response
            // Wait for response on SSE stream (with timeout)
            let jsonResponse = try await waitForResponse(requestId: requestId)
            return jsonResponse

        } catch let error as BridgeError {
            throw error
        } catch {
            throw BridgeError.connectionFailed(mcpName, error.localizedDescription)
        }
    }

    /// Wait for a response with matching request ID on the SSE stream.
    private nonisolated func waitForResponse(
        requestId: Int,
        timeout: TimeInterval = 30
    ) async throws -> [String: Any] {
        let startTime = Date()

        while true {
            // Check if response has arrived
            let responseData = state.withLock { state -> Data? in
                guard let data = state.pendingResponses[requestId], !data.isEmpty else {
                    return nil
                }
                return data
            }

            if let responseData = responseData {
                guard let json = try JSONSerialization.jsonObject(with: responseData) as? [String: Any] else {
                    throw BridgeError.serializationFailed("Failed to deserialize SSE response")
                }
                return json
            }

            // Check timeout
            if Date().timeIntervalSince(startTime) > timeout {
                throw BridgeError.timeout(mcpName, timeout)
            }

            // Small sleep to avoid busy-waiting
            try await Task.sleep(nanoseconds: 100_000_000)  // 100ms
        }
    }

    /// Start the persistent SSE stream (GET request that returns text/event-stream).
    private nonisolated func startSSEStream() {
        // Already running?
        let existing = sseStreamTask.withLock { $0 }
        if existing != nil {
            return
        }

        let task = Task {
            await self.readSSEStream()
        }

        sseStreamTask.withLock { $0 = task }
    }

    /// Stop the persistent SSE stream.
    private nonisolated func stopSSEStream() {
        let streamTask = sseStreamTask.withLock { task in
            let current = task
            return current
        }
        streamTask?.cancel()
    }

    /// Read and parse SSE stream continuously.
    /// Uses URLSession.bytes(for:) to stream the response.
    private nonisolated func readSSEStream() async {
        var request = URLRequest(url: endpointURL)
        request.httpMethod = "GET"
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = timeout
        addHeaders(to: &request)

        do {
            let (bytes, response) = try await urlSession.bytes(for: request)

            guard let httpResponse = response as? HTTPURLResponse else {
                log.warning("[\(self.mcpName)] SSE stream: invalid response type")
                return
            }

            if httpResponse.statusCode >= 400 {
                log.warning("[\(self.mcpName)] SSE stream: HTTP \(httpResponse.statusCode)")
                return
            }

            var buffer = ""

            for try await line in bytes.lines {
                buffer.append(line)
                buffer.append("\n")

                // Process complete events (separated by blank lines)
                if line.isEmpty && !buffer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    await parseSSEEvent(buffer)
                    buffer = ""
                }
            }

            // Process any remaining event
            if !buffer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                await parseSSEEvent(buffer)
            }

            log.debug("[\(self.mcpName)] SSE stream ended normally")

        } catch is CancellationError {
            log.debug("[\(self.mcpName)] SSE stream cancelled")
        } catch {
            log.warning("[\(self.mcpName)] SSE stream error: \(error.localizedDescription)")
        }
    }

    /// Parse an SSE event and extract JSON-RPC response.
    private nonisolated func parseSSEEvent(_ eventText: String) async {
        let events = SSEParser.parseEvents(from: eventText)
        guard let event = events.first, let dataString = event.data else {
            return
        }

        do {
            guard let jsonData = dataString.data(using: .utf8) else {
                throw BridgeError.serializationFailed("Failed to encode SSE data as UTF-8")
            }

            // Verify it's valid JSON before storing
            guard let jsonObject = try JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
                throw BridgeError.serializationFailed("SSE data field is not valid JSON")
            }

            // Extract request ID from response to correlate with pending request
            if let requestId = jsonObject["id"] as? Int {
                state.withLock { state in
                    // Store the JSON data for later deserialization
                    state.pendingResponses[requestId] = jsonData
                }
                log.debug("[\(self.mcpName)] SSE received response for request \(requestId)")
            }
        } catch {
            log.warning("[\(self.mcpName)] SSE parse error: \(error.localizedDescription)")
        }
    }

    /// Add required headers to the request.
    private nonisolated func addHeaders(to request: inout URLRequest) {
        request.setValue("2024-11-05", forHTTPHeaderField: "MCP-Protocol-Version")

        // Add custom headers (e.g., Authorization)
        for (key, value) in customHeaders {
            request.setValue(value, forHTTPHeaderField: key)
        }
    }
}
