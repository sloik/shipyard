import Testing
import Foundation
@testable import Shipyard

@Suite("LogMetadataHelper Tests")
struct LogMetadataHelperTests {
    
    // MARK: - UserDefaults Toggle Persistence
    
    @Test("Toggle persists to UserDefaults")
    func testTogglePersistence() {
        // Clear any existing value
        UserDefaults.standard.removeObject(forKey: LogMetadataHelper.showFullArgumentsKey)
        
        // Verify initial state (defaults to false)
        #expect(LogMetadataHelper.shouldShowFullArguments == false)
        
        // Toggle on
        LogMetadataHelper.toggleShowFullArguments()
        #expect(LogMetadataHelper.shouldShowFullArguments == true)
        
        // Toggle off
        LogMetadataHelper.toggleShowFullArguments()
        #expect(LogMetadataHelper.shouldShowFullArguments == false)
        
        // Verify persistence: create a new helper instance (in real code, it would be from a different session)
        let storedValue = UserDefaults.standard.bool(forKey: LogMetadataHelper.showFullArgumentsKey)
        #expect(storedValue == false)
    }
    
    // MARK: - Argument Metadata Extraction
    
    @Test("Argument metadata extraction (keys-only mode)")
    func testArgumentMetadataKeysOnly() {
        // Ensure keys-only mode
        UserDefaults.standard.set(false, forKey: LogMetadataHelper.showFullArgumentsKey)
        
        let arguments: [String: Any] = [
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 1000
        ]
        
        let metadata = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "openai",
            toolName: "invoke_model",
            arguments: arguments
        )
        
        // Verify keys are present
        #expect(metadata["argument_keys"] != nil)
        if case .string(let keysStr) = metadata["argument_keys"]! {
            #expect(keysStr.contains("max_tokens"))
            #expect(keysStr.contains("model"))
            #expect(keysStr.contains("temperature"))
        }
        
        // Verify arguments_redacted is true
        #expect(metadata["arguments_redacted"] == .bool(true))
        
        // Verify full arguments are NOT present
        #expect(metadata["arguments"] == nil)
    }
    
    @Test("Argument metadata extraction (full arguments mode)")
    func testArgumentMetadataFullArguments() {
        let arguments: [String: Any] = [
            "model": "gpt-4",
            "temperature": 0.7
        ]
        
        let metadata = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "openai",
            toolName: "invoke_model",
            arguments: arguments,
            showFullArguments: true
        )
        
        // Verify arguments_redacted is false
        #expect(metadata["arguments_redacted"] == .bool(false))
        
        // Verify full arguments are present as JSON string
        #expect(metadata["arguments"] != nil)
        if case .string(let argsStr) = metadata["arguments"] {
            #expect(argsStr.contains("gpt-4"))
            #expect(argsStr.contains("temperature"))
        } else {
            Issue.record("Expected .string value for arguments metadata")
        }
    }
    
    // MARK: - Gateway Call Metadata
    
    @Test("Gateway call metadata includes all required fields")
    func testGatewayCallMetadata() {
        let arguments = ["input": "test"]
        
        let metadata = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "local-mcp",
            toolName: "process__run_command",
            originalToolName: "run_command",
            requestSize: 256,
            responseSize: 512,
            duration: 1250,
            arguments: arguments,
            errorCode: nil
        )
        
        // Verify all required fields
        #expect(metadata["mcp_name"] == .string("local-mcp"))
        #expect(metadata["tool_name"] == .string("process__run_command"))
        #expect(metadata["original_tool_name"] == .string("run_command"))
        #expect(metadata["request_size_bytes"] == .int(256))
        #expect(metadata["response_size_bytes"] == .int(512))
        #expect(metadata["duration_ms"] == .int(1250))
        #expect(metadata["argument_keys"] != nil)
    }
    
    // MARK: - Process Lifecycle Metadata
    
    @Test("Process start metadata")
    func testProcessStartMetadata() {
        let metadata = LogMetadataHelper.processStartMetadata(
            mcpName: "lmstudio",
            command: "python3",
            arguments: ["server.py", "--port", "8000"],
            pid: 12345,
            version: "1.2.3",
            stateTransition: "idle → starting"
        )
        
        #expect(metadata["mcp_name"] == .string("lmstudio"))
        #expect(metadata["command"] == .string("python3"))
        #expect(metadata["pid"] == .int(12345))
        #expect(metadata["version"] == .string("1.2.3"))
        #expect(metadata["state_transition"] == .string("idle → starting"))
        
        // Verify arguments are joined
        if case .string(let argsStr) = metadata["arguments"]! {
            #expect(argsStr.contains("server.py"))
            #expect(argsStr.contains("8000"))
        }
    }
    
    @Test("Process stop metadata")
    func testProcessStopMetadata() {
        let metadata = LogMetadataHelper.processStopMetadata(
            mcpName: "lmstudio",
            pid: 12345,
            exitCode: 0,
            signal: nil,
            durationMs: 30000,
            stateTransition: "running → idle"
        )
        
        #expect(metadata["mcp_name"] == .string("lmstudio"))
        #expect(metadata["pid"] == .int(12345))
        #expect(metadata["exit_code"] == .int(0))
        #expect(metadata["duration_since_start_ms"] == .int(30000))
        #expect(metadata["state_transition"] == .string("running → idle"))
        #expect(metadata["signal"] == nil)  // Not provided
    }
    
    // MARK: - Gateway Discovery Metadata
    
    @Test("Discovery metadata includes all fields")
    func testDiscoveryMetadata() {
        let mcpNames = ["openai", "lmstudio", "anthropic"]
        
        let metadata = LogMetadataHelper.discoveryMetadata(
            mcpCount: 3,
            toolCount: 42,
            duration: 285,
            mcpNames: mcpNames
        )
        
        #expect(metadata["mcp_count"] == .int(3))
        #expect(metadata["tool_count"] == .int(42))
        #expect(metadata["duration_ms"] == .int(285))
        
        if case .string(let namesStr) = metadata["mcp_names"]! {
            #expect(namesStr.contains("openai"))
            #expect(namesStr.contains("lmstudio"))
            #expect(namesStr.contains("anthropic"))
        }
    }
    
    // MARK: - Socket Operation Metadata
    
    @Test("Socket operation metadata")
    func testSocketOperationMetadata() {
        let metadata = LogMetadataHelper.socketOperationMetadata(
            method: "gateway_call",
            bytesSent: 256,
            bytesReceived: 512,
            duration: 150,
            clientCount: 3,
            errorCode: nil
        )
        
        #expect(metadata["method"] == .string("gateway_call"))
        #expect(metadata["bytes_sent"] == .int(256))
        #expect(metadata["bytes_received"] == .int(512))
        #expect(metadata["duration_ms"] == .int(150))
        #expect(metadata["client_count"] == .int(3))
        #expect(metadata["error_code"] == nil)
    }
    
    // MARK: - Tool State Change Metadata
    
    @Test("Tool enable/disable metadata")
    func testToolStateChangeMetadata() {
        let metadata = LogMetadataHelper.toolStateChangeMetadata(
            operation: "set_enabled",
            scope: "tool",
            targetName: "openai__invoke_model",
            previousState: "enabled",
            newState: "disabled",
            affectedToolCount: 1
        )
        
        #expect(metadata["operation"] == .string("set_enabled"))
        #expect(metadata["scope"] == .string("tool"))
        #expect(metadata["target_name"] == .string("openai__invoke_model"))
        #expect(metadata["previous_state"] == .string("enabled"))
        #expect(metadata["new_state"] == .string("disabled"))
        #expect(metadata["affected_tool_count"] == .int(1))
    }
    
    // MARK: - Backward Compatibility
    
    @Test("Nil metadata handled gracefully in UI")
    func testNilMetadataBackwardCompatibility() {
        // Old entries with meta: nil should not cause crashes
        let entry = BridgeLogEntry(
            ts: "2026-03-26T10:00:00.000Z",
            level: "info",
            cat: "mcp",
            src: "app",
            msg: "Test message",
            meta: nil  // Old entries have no metadata
        )
        
        // Verify entry is created without error
        #expect(entry.meta == nil)
        #expect(entry.msg == "Test message")
    }
    
    // MARK: - Metadata Serialization
    
    @Test("Metadata serializes to JSON correctly")
    func testMetadataJSONSerialization() {
        let metadata = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "test-mcp",
            toolName: "test_tool",
            duration: 100,
            arguments: ["key": "value"]
        )
        
        // Create an entry with metadata
        var metaDict: [String: AnyCodableValue] = metadata
        
        // Verify each value can be encoded
        let encoder = JSONEncoder()
        do {
            let jsonData = try encoder.encode(metaDict)
            let jsonString = String(data: jsonData, encoding: .utf8)
            #expect(jsonString != nil)
            #expect(jsonString?.contains("test-mcp") ?? false)
        } catch {
            #expect(Bool(false), "Metadata should serialize to JSON")
        }
    }
}
