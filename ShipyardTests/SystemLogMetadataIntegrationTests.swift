import Testing
import Foundation
@testable import Shipyard

@Suite("System Log Metadata Integration Tests")
struct SystemLogMetadataIntegrationTests {

    @Test("Toggle on/off changes argument visibility in subsequent logs")
    func testToggleAffectsArgumentVisibility() async {
        let arguments = ["model": "gpt-4", "temperature": 0.7] as [String: Any]

        // Create log entry with arguments (keys-only mode via explicit param)
        let meta1 = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "openai",
            toolName: "invoke",
            arguments: arguments,
            showFullArguments: false
        )

        // Verify keys-only
        #expect(meta1["arguments_redacted"] == .bool(true))
        #expect(meta1["argument_keys"] != nil)
        #expect(meta1["arguments"] == nil)

        // Create log entry with arguments (full arguments mode via explicit param)
        let meta2 = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "openai",
            toolName: "invoke",
            arguments: arguments,
            showFullArguments: true
        )

        // Verify full arguments
        #expect(meta2["arguments_redacted"] == .bool(false))
        #expect(meta2["arguments"] != nil)
        if case .string(let argsStr) = meta2["arguments"] {
            #expect(argsStr.contains("gpt-4"))
        } else {
            Issue.record("Expected .string value for arguments metadata")
        }
    }

    @Test("Gateway call metadata covers all 6 required fields")
    func testGatewayCallMetadataComplete() {
        let arguments = ["input": "test command"]
        let metadata = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "process",
            toolName: "process__run",
            originalToolName: "run_command",
            requestSize: 128,
            responseSize: 256,
            duration: 500,
            arguments: arguments
        )

        // Verify all 6 categories present:
        // 1. mcp_name
        #expect(metadata["mcp_name"] == .string("process"))

        // 2. tool_name
        #expect(metadata["tool_name"] == .string("process__run"))

        // 3. duration
        #expect(metadata["duration_ms"] == .int(500))

        // 4. request/response size
        #expect(metadata["request_size_bytes"] == .int(128))
        #expect(metadata["response_size_bytes"] == .int(256))

        // 5. argument_keys or arguments
        #expect(metadata["argument_keys"] != nil)

        // 6. error_code (optional, but test it when present)
        let metaWithError = LogMetadataHelper.gatewayCallMetadata(
            mcpName: "process",
            toolName: "process__run",
            arguments: arguments,
            errorCode: "execution_failed"
        )
        #expect(metaWithError["error_code"] == .string("execution_failed"))
    }

    @Test("Process lifecycle metadata includes all state transitions")
    func testProcessLifecycleMetadata() {
        // Start
        let startMeta = LogMetadataHelper.processStartMetadata(
            mcpName: "lmstudio",
            command: "python3",
            arguments: ["server.py"],
            pid: 9999,
            version: "2.0.0",
            stateTransition: "idle → starting"
        )
        #expect(startMeta["state_transition"] == .string("idle → starting"))

        // Running (implicit, no separate log)

        // Stop
        let stopMeta = LogMetadataHelper.processStopMetadata(
            mcpName: "lmstudio",
            pid: 9999,
            exitCode: 0,
            durationMs: 60000,
            stateTransition: "running → idle"
        )
        #expect(stopMeta["state_transition"] == .string("running → idle"))
    }

    @Test("Socket operations log all network metrics")
    func testSocketOperationMetadata() {
        let metadata = LogMetadataHelper.socketOperationMetadata(
            method: "gateway_call",
            bytesSent: 512,
            bytesReceived: 1024,
            duration: 250,
            clientCount: 2
        )

        #expect(metadata["method"] == .string("gateway_call"))
        #expect(metadata["bytes_sent"] == .int(512))
        #expect(metadata["bytes_received"] == .int(1024))
        #expect(metadata["duration_ms"] == .int(250))
        #expect(metadata["client_count"] == .int(2))
    }

    @Test("Tool enable/disable logs operation details")
    func testToolStateChangeMetadata() {
        // MCP-level disable
        let mcpMeta = LogMetadataHelper.toolStateChangeMetadata(
            operation: "set_enabled",
            scope: "mcp",
            targetName: "openai",
            previousState: "enabled",
            newState: "disabled",
            affectedToolCount: 5
        )
        #expect(mcpMeta["scope"] == .string("mcp"))
        #expect(mcpMeta["affected_tool_count"] == .int(5))

        // Tool-level disable
        let toolMeta = LogMetadataHelper.toolStateChangeMetadata(
            operation: "set_enabled",
            scope: "tool",
            targetName: "openai__invoke",
            previousState: "enabled",
            newState: "disabled"
        )
        #expect(toolMeta["scope"] == .string("tool"))
        #expect(toolMeta["target_name"] == .string("openai__invoke"))
    }

    @Test("Discovery metadata provides aggregated tool counts")
    func testDiscoveryMetadataAggregation() {
        let mcpNames = ["openai", "anthropic", "huggingface"]
        let metadata = LogMetadataHelper.discoveryMetadata(
            mcpCount: 3,
            toolCount: 47,
            duration: 300,
            mcpNames: mcpNames
        )

        // Verify aggregation fields
        #expect(metadata["mcp_count"] == .int(3))
        #expect(metadata["tool_count"] == .int(47))

        // Verify MCP list
        if case .string(let namesStr) = metadata["mcp_names"]! {
            #expect(namesStr.contains("openai"))
            #expect(namesStr.contains("anthropic"))
            #expect(namesStr.contains("huggingface"))
        }
    }

    @Test("Backward compatibility: nil metadata doesn't crash")
    func testBackwardCompatibilityNilMeta() {
        // Old JSONL entries might have no metadata field
        let entry = BridgeLogEntry(
            ts: "2026-01-01T00:00:00.000Z",
            level: "info",
            cat: "mcp",
            src: "app",
            msg: "Old entry without metadata",
            meta: nil
        )

        // Should not throw, should display gracefully
        #expect(entry.meta == nil)
        #expect(entry.msg == "Old entry without metadata")

        // SystemLogView would display "(no metadata)" for this
    }
}
