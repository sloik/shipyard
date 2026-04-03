import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ExecutionQueueManager")

// MARK: - ExecutionQueueManager

/// Manages tool execution queue, history, and recent call persistence
@Observable @MainActor final class ExecutionQueueManager {
    var activeExecutions: [ToolExecution] = []
    var history: [ToolExecution] = []

    /// UserDefaults for persistence
    private let defaults: UserDefaults
    private let recentCallsPrefix = "execution.recent"
    private let historyKey = "execution.history"

    /// Reference to SocketServer for dispatching tool calls
    private weak var socketServer: SocketServer?

    /// Maximum history size (oldest entries evicted when exceeding)
    private let maxHistorySize = 20

    /// Maximum recent calls per tool
    private let maxRecentCalls = 5

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        loadHistory()
    }
    
    /// Set the socket server reference for dispatching calls
    func setSocketServer(_ server: SocketServer) {
        self.socketServer = server
    }
    
    // MARK: - Execution Flow
    
    /// Execute a tool asynchronously without blocking
    /// Returns the execution object immediately; status updates fire as the task progresses
    func executeToolAsync(
        toolName: String,
        arguments: [String: Any]
    ) -> ToolExecution {
        let request = ToolExecutionRequest(toolName: toolName, arguments: arguments)
        let execution = ToolExecution(toolName: toolName, request: request)
        
        // Add to active executions
        activeExecutions.append(execution)
        
        log.debug("Execution started: \(toolName) (id=\(execution.id.uuidString))")
        
        // Spawn async task
        let task = Task {
            await executeInternal(execution)
        }
        
        execution.setTask(task)
        
        return execution
    }
    
    /// Execute a tool with user confirmation (non-blocking)
    /// Called after user confirms in sheet
    func confirmAndExecute(execution: ToolExecution) {
        // Move to active if not already there
        if !activeExecutions.contains(where: { $0.id == execution.id }) {
            activeExecutions.append(execution)
        }
        
        // Spawn async task
        let task = Task {
            await executeInternal(execution)
        }
        
        execution.setTask(task)
    }
    
    /// Internal execution logic — runs in background task
    private func executeInternal(_ execution: ToolExecution) async {
        guard let socketServer = socketServer else {
            execution.markFailure(error: "Socket server not available")
            moveToHistory(execution)
            return
        }
        
        execution.markExecuting()
        
        do {
            // Call tool via socket server
            let responseJSON = try await socketServer.callTool(
                name: execution.toolName,
                arguments: execution.request.arguments
            )
            
            // Log response details
            log.debug("callTool response for \(execution.toolName): \(responseJSON.count) chars")
            if responseJSON.count <= 500 {
                log.debug("callTool response content: \(responseJSON)")
            } else {
                log.debug("callTool response preview: \(String(responseJSON.prefix(200)))...")
            }
            
            // Parse and mark success
            let response = ToolExecutionResponse(responseJSON: responseJSON)
            execution.markSuccess(response: response)
            
            // Save recent call
            saveRecentCall(execution)
            
            log.debug("Execution succeeded: \(execution.toolName) (id=\(execution.id.uuidString))")
        } catch {
            execution.markFailure(error: error.localizedDescription)
            log.warning("Execution failed: \(execution.toolName): \(error.localizedDescription)")
        }
        
        // Move to history
        moveToHistory(execution)
    }
    
    // MARK: - History Management

    /// Move execution from active to history, maintaining cap at maxHistorySize
    private func moveToHistory(_ execution: ToolExecution) {
        // Remove from active
        activeExecutions.removeAll { $0.id == execution.id }

        // Add to history
        history.insert(execution, at: 0)  // Newest first

        // Enforce cap
        if history.count > maxHistorySize {
            history.removeLast(history.count - maxHistorySize)
        }

        // Persist to UserDefaults
        persistHistory()
    }
    
    // MARK: - Retry
    
    /// Retry a previous execution with the same request
    func retryExecution(_ execution: ToolExecution) -> ToolExecution {
        return executeToolAsync(
            toolName: execution.toolName,
            arguments: execution.request.arguments
        )
    }
    
    // MARK: - Cancellation
    
    /// Cancel an active execution
    func cancelExecution(_ execution: ToolExecution) {
        execution.cancel()
        // Still move to history after cancellation
        moveToHistory(execution)
    }
    
    // MARK: - Recent Calls Persistence
    
    /// Save a tool call to recent calls (persisted to UserDefaults)
    private func saveRecentCall(_ execution: ToolExecution) {
        let key = "\(recentCallsPrefix).\(execution.toolName)"

        // Save arguments dict directly via JSONSerialization (not Codable — avoids base64 encoding of Data)
        let callDict: [String: Any] = [
            "toolName": execution.request.toolName,
            "arguments": execution.request.arguments
        ]

        var recentCalls: [[String: Any]] = defaults.array(forKey: key) as? [[String: Any]] ?? []
        recentCalls.insert(callDict, at: 0)

        if recentCalls.count > maxRecentCalls {
            recentCalls = Array(recentCalls.prefix(maxRecentCalls))
        }

        defaults.set(recentCalls, forKey: key)
        log.debug("Saved recent call for \(execution.toolName)")
    }
    
    /// Get recent calls for a tool (max 5)
    func getRecentCalls(for toolName: String) -> [ToolExecutionRequest] {
        let key = "\(recentCallsPrefix).\(toolName)"

        guard let recentDicts = defaults.array(forKey: key) as? [[String: Any]] else {
            return []
        }

        var requests: [ToolExecutionRequest] = []

        for dict in recentDicts {
            if let toolName = dict["toolName"] as? String,
               let args = dict["arguments"] as? [String: Any] {
                requests.append(ToolExecutionRequest(toolName: toolName, arguments: args))
            }
        }

        return requests
    }

    // MARK: - History Persistence

    /// Persist history array to UserDefaults (only completed/failed/cancelled entries)
    private func persistHistory() {
        let serialized: [[String: Any]] = history.compactMap { serializeExecution($0) }
        defaults.set(serialized, forKey: historyKey)
        log.debug("Persisted \(serialized.count) history entries")
    }

    /// Load history from UserDefaults on app startup
    private func loadHistory() {
        guard let dicts = defaults.array(forKey: historyKey) as? [[String: Any]] else {
            return
        }

        var loaded: [ToolExecution] = []
        for dict in dicts {
            if let execution = deserializeExecution(dict) {
                loaded.append(execution)
            }
        }

        history = loaded
        log.debug("Loaded \(loaded.count) history entries from UserDefaults")
    }

    /// Serialize a ToolExecution to [String: Any] for UserDefaults storage
    private func serializeExecution(_ execution: ToolExecution) -> [String: Any]? {
        // Only serialize completed/failed/cancelled entries (skip pending/executing)
        guard [.success, .failure, .cancelled].contains(execution.status) else {
            return nil
        }

        var dict: [String: Any] = [
            "id": execution.id.uuidString,
            "toolName": execution.toolName,
            "status": execution.status.rawValue,
        ]

        // Serialize request
        var requestDict: [String: Any] = [
            "toolName": execution.request.toolName,
            "arguments": execution.request.arguments,
        ]

        // Validate arguments are plist-compatible
        if !JSONSerialization.isValidJSONObject(execution.request.arguments) {
            // If arguments contain non-plist types, serialize to JSON string
            if let data = try? JSONSerialization.data(withJSONObject: execution.request.arguments),
               let jsonString = String(data: data, encoding: .utf8) {
                requestDict["arguments"] = jsonString
                requestDict["arguments_is_json_string"] = true
            }
        }

        dict["request"] = requestDict

        // Serialize timestamps
        if let startedAt = execution.startedAt {
            dict["startedAt"] = startedAt.timeIntervalSince1970
        }
        if let completedAt = execution.completedAt {
            dict["completedAt"] = completedAt.timeIntervalSince1970
        }

        // Serialize response (if success)
        if let response = execution.response {
            dict["response"] = [
                "responseJSON": response.responseJSON,
                "contentLength": response.contentLength,
            ]
        }

        // Serialize error (if failure)
        if let error = execution.error {
            dict["error"] = error
        }

        return dict
    }

    /// Deserialize [String: Any] from UserDefaults back to ToolExecution
    private func deserializeExecution(_ dict: [String: Any]) -> ToolExecution? {
        guard let idString = dict["id"] as? String,
              let id = UUID(uuidString: idString),
              let toolName = dict["toolName"] as? String,
              let statusRawValue = dict["status"] as? String,
              let status = ExecutionStatus(rawValue: statusRawValue),
              let requestDict = dict["request"] as? [String: Any],
              let requestToolName = requestDict["toolName"] as? String else {
            log.warning("Failed to deserialize execution: missing required fields")
            return nil
        }

        // Deserialize arguments
        var arguments: [String: Any] = [:]
        if let isJsonString = requestDict["arguments_is_json_string"] as? Bool, isJsonString,
           let jsonString = requestDict["arguments"] as? String,
           let data = jsonString.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            arguments = json
        } else if let args = requestDict["arguments"] as? [String: Any] {
            arguments = args
        }

        let request = ToolExecutionRequest(toolName: requestToolName, arguments: arguments)
        let execution = ToolExecution(id: id, toolName: toolName, request: request)

        // Restore status and timing
        execution.status = status

        if let startedAtInterval = dict["startedAt"] as? TimeInterval {
            execution.startedAt = Date(timeIntervalSince1970: startedAtInterval)
        }

        if let completedAtInterval = dict["completedAt"] as? TimeInterval {
            execution.completedAt = Date(timeIntervalSince1970: completedAtInterval)
        }

        // Restore response (if present)
        if let responseDict = dict["response"] as? [String: Any],
           let responseJSON = responseDict["responseJSON"] as? String {
            execution.response = ToolExecutionResponse(responseJSON: responseJSON)
        }

        // Restore error (if present)
        if let error = dict["error"] as? String {
            execution.error = error
        }

        return execution
    }
}

// MARK: - SocketServer Extension

extension SocketServer {
    /// Async method to call a tool via the existing gateway_call pathway
    /// Returns raw JSON response string
    func callTool(name: String, arguments: [String: Any]) async throws -> String {
        log.debug("callTool: dispatching gateway_call for tool \(name)")
        return try await withCheckedThrowingContinuation { continuation in
            // Dispatch on main actor to ensure we can call dispatchRequest
            Task { @MainActor in
                let params: [String: Any] = ["tool": name, "arguments": arguments]
                let requestDict: [String: Any] = ["method": "gateway_call", "params": params]
                
                guard let requestData = try? JSONSerialization.data(withJSONObject: requestDict),
                      let requestLine = String(data: requestData, encoding: .utf8) else {
                    log.error("callTool: failed to encode request for \(name)")
                    continuation.resume(throwing: NSError(domain: "ToolExecution", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to encode request"]))
                    return
                }
                
                log.debug("callTool: sending request to dispatchRequest")
                let responseLine = await self.dispatchRequest(requestLine)
                log.debug("callTool: received response for \(name) (\(responseLine.count) chars)")
                continuation.resume(returning: responseLine)
            }
        }
    }
}
