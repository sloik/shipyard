import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "HTTPBridge")

/// HTTP transport bridge for streamable HTTP MCP servers
/// NOT @MainActor — network calls run off main thread
/// State updates (sessionId, connection status) hop to MainActor when needed
final class HTTPBridge: BridgeProtocol, Sendable {
    let mcpName: String
    private let endpointURL: URL
    private let customHeaders: [String: String]
    private let timeoutInterval: TimeInterval
    private let maxRetries = 3
    private let retryBackoffSeconds: [UInt64] = [1, 2, 4]

    // Thread-safe state using OSAllocatedUnfairLock
    private let stateLock: OSAllocatedUnfairLock<HTTPBridgeState>

    struct HTTPBridgeState {
        var sessionId: String?
        var isInitialized: Bool = false
    }

    private let urlSession: URLSession

    init(
        mcpName: String,
        endpointURL: URL,
        customHeaders: [String: String] = [:],
        timeout: TimeInterval = 30,
        urlSession: URLSession? = nil
    ) {
        self.mcpName = mcpName
        self.endpointURL = endpointURL
        self.customHeaders = customHeaders
        self.stateLock = OSAllocatedUnfairLock(initialState: HTTPBridgeState())
        self.timeoutInterval = timeout

        if let urlSession {
            self.urlSession = urlSession
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = timeout
            config.timeoutIntervalForResource = timeout
            self.urlSession = URLSession(configuration: config)
        }

        log.info("[\\(mcpName)] HTTPBridge initialized with URL: \\(endpointURL.absoluteString)")
    }

    /// Initialize the HTTP session
    func initialize() async throws -> [String: Any] {
        log.info("[\\(mcpName)] Initializing HTTP session")

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

        let response = try await performRequestWithRetry(
            method: "POST",
            body: initRequest,
            includeSession: false,
            allowSessionRecovery: false
        )

        if let sessionId = response.httpResponse.value(forHTTPHeaderField: "MCP-Session-Id"),
           !sessionId.isEmpty {
            stateLock.withLock { state in
                state.sessionId = sessionId
                state.isInitialized = true
            }
            log.info("[\\(self.mcpName)] HTTP session initialized, sessionId: \\(sessionId)")
        } else {
            stateLock.withLock { state in
                state.isInitialized = true
            }
        }

        return response.jsonPayload
    }

    /// Call a tool via HTTP
    func callTool(name: String, arguments: [String: Any]) async throws -> [String: Any] {
        guard stateLock.withLock({ $0.isInitialized }) else {
            throw BridgeError.notInitialized(mcpName)
        }

        let toolCallRequest: [String: Any] = [
            "jsonrpc": "2.0",
            "id": Int.random(in: 1..<10000),
            "method": "tools/call",
            "params": [
                "name": name,
                "arguments": arguments
            ] as [String: Any]
        ]

        let response = try await performRequestWithRetry(
            method: "POST",
            body: toolCallRequest,
            includeSession: true,
            allowSessionRecovery: true
        )
        return response.jsonPayload
    }

    /// Discover tools via HTTP
    func discoverTools() async throws -> [[String: Any]] {
        guard stateLock.withLock({ $0.isInitialized }) else {
            throw BridgeError.notInitialized(mcpName)
        }

        let discoverRequest: [String: Any] = [
            "jsonrpc": "2.0",
            "id": Int.random(in: 1..<10000),
            "method": "tools/list"
        ]

        let response = try await performRequestWithRetry(
            method: "POST",
            body: discoverRequest,
            includeSession: true,
            allowSessionRecovery: true
        )

        if let tools = response.jsonPayload["tools"] as? [[String: Any]] {
            return tools
        }
        if let result = response.jsonPayload["result"] as? [String: Any],
           let tools = result["tools"] as? [[String: Any]] {
            return tools
        }
        return []
    }

    /// Disconnect the HTTP session
    func disconnect() async {
        log.info("[\\(mcpName)] Disconnecting HTTP session")

        let sessionId = stateLock.withLock { $0.sessionId }
        if let sessionId {
            do {
                var request = makeBaseRequest(method: "DELETE", includeSession: false)
                request.setValue(sessionId, forHTTPHeaderField: "MCP-Session-Id")
                _ = try await urlSession.data(for: request)
            } catch {
                log.warning("[\\(mcpName)] HTTP disconnect request failed: \\(error.localizedDescription)")
            }
        }

        clearSession()
    }

    private struct HTTPResponsePayload {
        let httpResponse: HTTPURLResponse
        let jsonPayload: [String: Any]
    }

    private func performRequestWithRetry(
        method: String,
        body: [String: Any]?,
        includeSession: Bool,
        allowSessionRecovery: Bool
    ) async throws -> HTTPResponsePayload {
        var hasReinitializedSession = false

        return try await withRetry { attempt in
            do {
                return try await self.performRequest(
                    method: method,
                    body: body,
                    includeSession: includeSession
                )
            } catch BridgeError.sessionExpired where allowSessionRecovery && !hasReinitializedSession {
                hasReinitializedSession = true
                log.info("[\\(mcpName)] Session expired; re-initializing and retrying request")
                _ = try await self.initialize()
                return try await self.performRequest(
                    method: method,
                    body: body,
                    includeSession: includeSession
                )
            } catch {
                if attempt >= self.maxRetries {
                    throw error
                }
                throw error
            }
        }
    }

    private func performRequest(
        method: String,
        body: [String: Any]?,
        includeSession: Bool
    ) async throws -> HTTPResponsePayload {
        var request = makeBaseRequest(method: method, includeSession: includeSession)

        if let body {
            do {
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            } catch {
                throw BridgeError.serializationFailed(error.localizedDescription)
            }
        }

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch let bridgeError as BridgeError {
            throw bridgeError
        } catch {
            throw mapNetworkError(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw BridgeError.connectionFailed(mcpName, L10n.string("error.httpBridge.invalidResponseType"))
        }

        if httpResponse.statusCode == 404 && includeSession {
            clearSession()
            throw BridgeError.sessionExpired(mcpName)
        }

        if isTransientHTTPStatus(httpResponse.statusCode) {
            throw BridgeError.httpError(
                mcpName,
                httpResponse.statusCode,
                L10n.string("error.httpBridge.transientHttpFailure")
            )
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw BridgeError.httpError(
                mcpName,
                httpResponse.statusCode,
                L10n.string("error.httpBridge.httpRequestFailed")
            )
        }

        guard isSupportedContentType(httpResponse) else {
            let contentType = httpResponse.value(forHTTPHeaderField: "Content-Type") ?? "unknown"
            throw BridgeError.httpError(
                mcpName,
                httpResponse.statusCode,
                L10n.format("error.httpBridge.unsupportedResponseContentType", contentType)
            )
        }

        if data.isEmpty {
            return HTTPResponsePayload(httpResponse: httpResponse, jsonPayload: [:])
        }

        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw BridgeError.serializationFailed(L10n.string("error.httpBridge.responseNotJsonObject"))
        }

        if let result = object["result"] as? [String: Any] {
            return HTTPResponsePayload(httpResponse: httpResponse, jsonPayload: result)
        }

        return HTTPResponsePayload(httpResponse: httpResponse, jsonPayload: object)
    }

    private func makeBaseRequest(method: String, includeSession: Bool) -> URLRequest {
        var request = URLRequest(url: endpointURL)
        request.httpMethod = method
        request.timeoutInterval = timeoutInterval
        request.setValue("2024-11-05", forHTTPHeaderField: "MCP-Protocol-Version")

        for (key, value) in customHeaders {
            request.setValue(value, forHTTPHeaderField: key)
        }

        if includeSession,
           let sessionId = stateLock.withLock({ $0.sessionId }),
           !sessionId.isEmpty {
            request.setValue(sessionId, forHTTPHeaderField: "MCP-Session-Id")
        }

        if shouldSendOriginHeader(),
           request.value(forHTTPHeaderField: "Origin") == nil {
            request.setValue("https://shipyard.local", forHTTPHeaderField: "Origin")
        }

        return request
    }

    private func withRetry<T>(_ operation: @escaping (_ attempt: Int) async throws -> T) async throws -> T {
        var attempt = 1
        while true {
            do {
                return try await operation(attempt)
            } catch let bridgeError as BridgeError {
                guard bridgeError.isTransient, attempt < maxRetries else {
                    throw bridgeError
                }

                let delay = retryBackoffSeconds[min(attempt - 1, retryBackoffSeconds.count - 1)]
                log.warning("[\\(mcpName)] transient error on attempt \\(attempt), retrying in \\(delay)s: \\(bridgeError.localizedDescription)")
                try await Task.sleep(nanoseconds: delay * 1_000_000_000)
                attempt += 1
            } catch {
                throw error
            }
        }
    }

    private func mapNetworkError(_ error: Error) -> BridgeError {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .timedOut:
                return .timeout(mcpName, timeoutInterval)
            case .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed,
                 .networkConnectionLost, .notConnectedToInternet:
                return .connectionFailed(mcpName, urlError.localizedDescription)
            default:
                return .connectionFailed(mcpName, urlError.localizedDescription)
            }
        }

        return .connectionFailed(mcpName, error.localizedDescription)
    }

    private func isTransientHTTPStatus(_ statusCode: Int) -> Bool {
        if statusCode >= 500 && statusCode <= 599 {
            return true
        }
        return statusCode == 408 || statusCode == 429
    }

    private func isSupportedContentType(_ response: HTTPURLResponse) -> Bool {
        guard let contentType = response.value(forHTTPHeaderField: "Content-Type")?.lowercased() else {
            return true
        }

        if contentType.contains("text/event-stream") {
            return false
        }

        return contentType.contains("application/json")
    }

    private func shouldSendOriginHeader() -> Bool {
        guard let host = endpointURL.host?.lowercased() else {
            return false
        }
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }

    private func clearSession() {
        stateLock.withLock { state in
            state.sessionId = nil
            state.isInitialized = false
        }
    }
}

typealias SSEBridge = HTTPBridge
