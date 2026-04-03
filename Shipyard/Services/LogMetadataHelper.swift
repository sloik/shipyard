import Foundation

// MARK: - Log Metadata Helper

/// Helper functions for constructing and managing log metadata
struct LogMetadataHelper {
    /// UserDefaults key for argument visibility toggle
    static let showFullArgumentsKey = "com.shipyard.logs.show_full_arguments"
    
    /// Check if full arguments should be logged (opt-in, defaults to false)
    static var shouldShowFullArguments: Bool {
        UserDefaults.standard.bool(forKey: showFullArgumentsKey)
    }
    
    /// Toggle full argument visibility
    static func toggleShowFullArguments() {
        UserDefaults.standard.set(
            !shouldShowFullArguments,
            forKey: showFullArgumentsKey
        )
    }
    
    // MARK: - Gateway Call Metadata
    
    /// Extract metadata for a gateway call operation
    /// - Parameters:
    ///   - mcpName: Name of the MCP being called
    ///   - toolName: Name of the tool
    ///   - originalToolName: Original tool name (if renamed)
    ///   - requestSize: Size of request in bytes
    ///   - responseSize: Size of response in bytes
    ///   - duration: Duration of call in milliseconds
    ///   - arguments: Arguments passed to the tool
    ///   - errorCode: Error code if operation failed
    /// - Returns: Dictionary of metadata for the log entry
    static func gatewayCallMetadata(
        mcpName: String,
        toolName: String,
        originalToolName: String? = nil,
        requestSize: Int? = nil,
        responseSize: Int? = nil,
        duration: Int? = nil,
        arguments: [String: Any]? = nil,
        errorCode: String? = nil,
        showFullArguments: Bool? = nil
    ) -> [String: AnyCodableValue] {
        let showFull = showFullArguments ?? shouldShowFullArguments
        var meta: [String: AnyCodableValue] = [
            "mcp_name": .string(mcpName),
            "tool_name": .string(toolName),
        ]
        
        if let orig = originalToolName {
            meta["original_tool_name"] = .string(orig)
        }
        
        if let size = requestSize {
            meta["request_size_bytes"] = .int(size)
        }
        
        if let size = responseSize {
            meta["response_size_bytes"] = .int(size)
        }
        
        if let dur = duration {
            meta["duration_ms"] = .int(dur)
        }
        
        // Extract argument keys or full arguments based on toggle
        if let args = arguments {
            let keys = Array(args.keys).sorted()
            meta["argument_keys"] = .string(keys.joined(separator: ", "))
            meta["arguments_redacted"] = .bool(!showFull)
            
            if showFull {
                // Convert argument values to JSON string for logging
                if let jsonData = try? JSONSerialization.data(withJSONObject: args),
                   let jsonString = String(data: jsonData, encoding: .utf8) {
                    meta["arguments"] = .string(jsonString)
                }
            }
        }
        
        if let code = errorCode {
            meta["error_code"] = .string(code)
        }
        
        return meta
    }
    
    // MARK: - Process Lifecycle Metadata
    
    /// Extract metadata for process start event
    static func processStartMetadata(
        mcpName: String,
        command: String,
        arguments: [String]? = nil,
        pid: Int? = nil,
        version: String? = nil,
        stateTransition: String? = nil
    ) -> [String: AnyCodableValue] {
        var meta: [String: AnyCodableValue] = [
            "mcp_name": .string(mcpName),
            "command": .string(command),
        ]
        
        if let args = arguments {
            meta["arguments"] = .string(args.joined(separator: " "))
        }
        
        if let p = pid {
            meta["pid"] = .int(p)
        }
        
        if let v = version {
            meta["version"] = .string(v)
        }
        
        if let transition = stateTransition {
            meta["state_transition"] = .string(transition)
        }
        
        return meta
    }
    
    /// Extract metadata for process stop event
    static func processStopMetadata(
        mcpName: String,
        pid: Int? = nil,
        exitCode: Int? = nil,
        signal: Int? = nil,
        durationMs: Int? = nil,
        stateTransition: String? = nil
    ) -> [String: AnyCodableValue] {
        var meta: [String: AnyCodableValue] = [
            "mcp_name": .string(mcpName),
        ]
        
        if let p = pid {
            meta["pid"] = .int(p)
        }
        
        if let code = exitCode {
            meta["exit_code"] = .int(code)
        }
        
        if let sig = signal {
            meta["signal"] = .int(sig)
        }
        
        if let dur = durationMs {
            meta["duration_since_start_ms"] = .int(dur)
        }
        
        if let transition = stateTransition {
            meta["state_transition"] = .string(transition)
        }
        
        return meta
    }
    
    // MARK: - Gateway Discovery Metadata
    
    /// Extract metadata for discovery operation
    static func discoveryMetadata(
        mcpCount: Int? = nil,
        toolCount: Int? = nil,
        duration: Int? = nil,
        mcpNames: [String]? = nil
    ) -> [String: AnyCodableValue] {
        var meta: [String: AnyCodableValue] = [:]
        
        if let count = mcpCount {
            meta["mcp_count"] = .int(count)
        }
        
        if let count = toolCount {
            meta["tool_count"] = .int(count)
        }
        
        if let dur = duration {
            meta["duration_ms"] = .int(dur)
        }
        
        if let names = mcpNames {
            meta["mcp_names"] = .string(names.joined(separator: ", "))
        }
        
        return meta
    }
    
    // MARK: - Socket Operation Metadata
    
    /// Extract metadata for socket operations
    static func socketOperationMetadata(
        method: String,
        bytesSent: Int? = nil,
        bytesReceived: Int? = nil,
        duration: Int? = nil,
        clientCount: Int? = nil,
        errorCode: String? = nil
    ) -> [String: AnyCodableValue] {
        var meta: [String: AnyCodableValue] = [
            "method": .string(method),
        ]
        
        if let sent = bytesSent {
            meta["bytes_sent"] = .int(sent)
        }
        
        if let recv = bytesReceived {
            meta["bytes_received"] = .int(recv)
        }
        
        if let dur = duration {
            meta["duration_ms"] = .int(dur)
        }
        
        if let count = clientCount {
            meta["client_count"] = .int(count)
        }
        
        if let code = errorCode {
            meta["error_code"] = .string(code)
        }
        
        return meta
    }
    
    // MARK: - Tool Enable/Disable Metadata
    
    /// Extract metadata for tool state change operations
    static func toolStateChangeMetadata(
        operation: String,
        scope: String,
        targetName: String,
        previousState: String,
        newState: String,
        affectedToolCount: Int? = nil
    ) -> [String: AnyCodableValue] {
        var meta: [String: AnyCodableValue] = [
            "operation": .string(operation),
            "scope": .string(scope),
            "target_name": .string(targetName),
            "previous_state": .string(previousState),
            "new_state": .string(newState),
        ]
        
        if let count = affectedToolCount {
            meta["affected_tool_count"] = .int(count)
        }
        
        return meta
    }
}
