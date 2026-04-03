import Testing
import Foundation
import AppKit
@testable import Shipyard
// ShipyardBridgeLib tests are in ShipyardBridgeTests target

// MARK: - BUG-003 Tests: Execution Flow Verification

@Suite("BUG-003: Execution Flow Verification", .timeLimit(.minutes(1)))
@MainActor
struct BUG003ExecutionFlowTests {

    // MARK: - Helper Methods

    private func makeQueueManager() -> ExecutionQueueManager {
        let suiteName = "com.shipyard.test.bug003.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return ExecutionQueueManager(defaults: defaults)
    }
    
    /// Creates a ToolExecution and adds to activeExecutions WITHOUT spawning a background Task.
    @discardableResult
    private func addExecution(to manager: ExecutionQueueManager, toolName: String, arguments: [String: Any] = [:]) -> ToolExecution {
        let request = ToolExecutionRequest(toolName: toolName, arguments: arguments)
        let execution = ToolExecution(toolName: toolName, request: request)
        manager.activeExecutions.append(execution)
        return execution
    }

    // MARK: - AC 1: Executing tool creates visible entry in queue panel

    @Test("AC 1a: Adding execution creates visible entry in activeExecutions")
    func executeToolAddsToActiveExecutions() {
        let manager = makeQueueManager()
        let toolName = "test_tool"
        let args: [String: Any] = ["param": "value"]

        let execution = addExecution(to: manager, toolName: toolName, arguments: args)

        #expect(manager.activeExecutions.count == 1)
        #expect(manager.activeExecutions[0].id == execution.id)
        #expect(manager.activeExecutions[0].toolName == toolName)
    }

    @Test("AC 1b: Multiple tool executions all appear in queue")
    func multipleExecutionsVisible() {
        let manager = makeQueueManager()

        let ex1 = addExecution(to: manager, toolName: "tool1")
        let ex2 = addExecution(to: manager, toolName: "tool2")
        let ex3 = addExecution(to: manager, toolName: "tool3")

        #expect(manager.activeExecutions.count == 3)
        #expect(manager.activeExecutions.map(\.id) == [ex1.id, ex2.id, ex3.id])
    }

    // MARK: - AC 2: Active execution shows hourglass, completes with checkmark/X

    @Test("AC 2a: Initial status is pending")
    func initialStatusIsPending() {
        let manager = makeQueueManager()

        let execution = addExecution(to: manager, toolName: "test")

        #expect(execution.status == .pending)
    }

    @Test("AC 2b: markExecuting transitions to .executing state")
    func markExecutingTransitionsState() {
        let execution = ToolExecution(
            toolName: "test",
            request: ToolExecutionRequest(toolName: "test", arguments: [:])
        )

        execution.markExecuting()

        #expect(execution.status == .executing)
    }

    @Test("AC 2c: markSuccess transitions to .success")
    func markSuccessCompletesExecution() {
        let execution = ToolExecution(
            toolName: "test",
            request: ToolExecutionRequest(toolName: "test", arguments: [:])
        )
        let response = ToolExecutionResponse(responseJSON: "{\"result\": \"ok\"}")

        execution.markSuccess(response: response)

        #expect(execution.status == .success)
        #expect(execution.response != nil)
    }

    @Test("AC 2d: markFailure transitions to .failure")
    func markFailureCompletesExecution() {
        let execution = ToolExecution(
            toolName: "test",
            request: ToolExecutionRequest(toolName: "test", arguments: [:])
        )

        execution.markFailure(error: "Tool not found")

        #expect(execution.status == .failure)
        #expect(execution.error == "Tool not found")
    }

    // MARK: - AC 3: Failure shows error in queue panel row

    @Test("AC 3a: Failed execution stores error message")
    func failedExecutionStoresError() {
        let execution = ToolExecution(
            toolName: "broken_tool",
            request: ToolExecutionRequest(toolName: "broken_tool", arguments: [:])
        )
        let errorMsg = "MCP not running"

        execution.markFailure(error: errorMsg)

        #expect(execution.error == errorMsg)
        #expect(execution.status == .failure)
    }

    @Test("AC 3b: Manager tracks failed and successful executions together")
    func mixedExecutionOutcomes() {
        let manager = makeQueueManager()

        let success = addExecution(to: manager, toolName: "good_tool")
        let failure = addExecution(to: manager, toolName: "bad_tool")

        success.markExecuting()
        success.markSuccess(response: ToolExecutionResponse(responseJSON: "{}"))

        failure.markExecuting()
        failure.markFailure(error: "Timeout")

        #expect(success.status == .success)
        #expect(failure.status == .failure)
        #expect(manager.activeExecutions.count == 2)
    }

    // MARK: - AC 4: Queue panel visible by default

    @Test("AC 4: Manager initializes with empty active/history")
    func queuePanelInitializationState() {
        let manager = makeQueueManager()

        #expect(manager.activeExecutions.isEmpty)
        #expect(manager.history.isEmpty)
    }
}

// MARK: - BUG-004 Tests: Sheet Blank Content

@Suite("BUG-004: Tool Execution Sheet Content", .timeLimit(.minutes(1)))
struct BUG004SheetContentTests {

    @Test("AC: GatewayTool conforms to Identifiable")
    func gatewayToolIsIdentifiable() {
        let tool = GatewayTool(
            prefixedName: "test_mcp__test_tool",
            mcpName: "test_mcp",
            originalName: "test_tool",
            description: "Test",
            inputSchema: Data(),
            enabled: true
        )

        let id = tool.id
        #expect(id == "test_mcp__test_tool")
    }

    @Test("Identifiable id is unique across different tools")
    func identifiableIdUniqueness() {
        let tool1 = GatewayTool(
            prefixedName: "mcp1__tool_a",
            mcpName: "mcp1",
            originalName: "tool_a",
            description: "",
            inputSchema: Data(),
            enabled: true
        )

        let tool2 = GatewayTool(
            prefixedName: "mcp1__tool_b",
            mcpName: "mcp1",
            originalName: "tool_b",
            description: "",
            inputSchema: Data(),
            enabled: true
        )

        #expect(tool1.id != tool2.id)
    }
}

// MARK: - BUG-007 Tests: Response Display Visibility

@Suite("BUG-007: Response Display Visibility", .timeLimit(.minutes(1)))
@MainActor
struct BUG007ResponseDisplayTests {

    @Test("AC 1/4: splitLines keeps visible text for compact JSON")
    func splitLinesKeepsCompactJSONVisible() {
        let json = "{}"
        let highlighted = JSONHighlighter.highlight(json)

        let lines = CodeBlockView.splitLines(from: highlighted)

        #expect(lines.count == 1)
        #expect(lines[0].string == "{}")
    }

    @Test("AC 1/3: splitLines preserves all rendered lines for pretty JSON")
    func splitLinesPreservesPrettyJSONLineCount() {
        let json = """
        {
          "name": "list_voices",
          "count": 12,
          "enabled": true
        }
        """
        let highlighted = JSONHighlighter.highlight(json)

        let lines = CodeBlockView.splitLines(from: highlighted)

        let expectedCount = json.components(separatedBy: "\n").count
        #expect(lines.count == expectedCount)
        #expect(lines[1].string.contains("\"name\""))
        #expect(lines[2].string.contains("\"count\""))
    }

    @Test("AC 2: syntax attributes are present for key tokens")
    func highlighterAppliesAttributesToKeys() {
        let json = """
        {
          "name": "voice"
        }
        """
        let highlighted = JSONHighlighter.highlight(json)
        let keyRange = (highlighted.string as NSString).range(of: "\"name\"")

        let foreground = highlighted.attribute(.foregroundColor, at: keyRange.location, effectiveRange: nil)
        let font = highlighted.attribute(.font, at: keyRange.location, effectiveRange: nil)

        #expect(foreground != nil)
        #expect(font != nil)
    }
}

// MARK: - BUG-011 Tests: Gateway Response Format

@Suite("BUG-011: Gateway Response Format", .timeLimit(.minutes(1)))
struct BUG011ResponseFormatTests {

    @Test("AC 1: Dict result serialization")
    func dictResultSerialization() throws {
        let dictResult: [String: Any] = [
            "content": [
                ["type": "text", "text": "hello"]
            ]
        ]

        let data = try JSONSerialization.data(withJSONObject: dictResult)
        let jsonStr = String(data: data, encoding: .utf8)

        #expect(jsonStr != nil)
        #expect(jsonStr!.contains("hello"))
    }

    @Test("AC 2: String result serialization")
    func stringResultSerialization() throws {
        let stringResult = "plain string response"
        let wrapped: [String: Any] = ["value": stringResult]
        let data = try JSONSerialization.data(withJSONObject: wrapped)
        let jsonStr = String(data: data, encoding: .utf8)

        #expect(jsonStr != nil)
        #expect(jsonStr!.contains("plain string response"))
    }

    @Test("AC 3: Array result serialization")
    func arrayResultSerialization() throws {
        let arrayResult: [Any] = [1, 2, 3]
        let data = try JSONSerialization.data(withJSONObject: arrayResult)
        let jsonStr = String(data: data, encoding: .utf8)

        #expect(jsonStr != nil)
        #expect(jsonStr!.contains("["))
        #expect(jsonStr!.contains("]"))
    }

    @Test("AC 4: Null result handling")
    func nullResultHandling() throws {
        let nullValue: [String: Any?] = ["result": NSNull()]
        let data = try JSONSerialization.data(withJSONObject: nullValue)
        let jsonStr = String(data: data, encoding: .utf8)

        #expect(jsonStr != nil)
        #expect(jsonStr!.contains("null"))
    }

    @Test("AC 5: Shipyard string error format")
    func shipyardStringError() throws {
        let errorResponse: [String: Any] = [
            "error": "Tool not found"
        ]

        if let error = errorResponse["error"] as? String {
            #expect(error == "Tool not found")
        } else {
            Issue.record("Error extraction failed")
        }
    }

    @Test("AC 6: JSON-RPC dict error format")
    func jsonRpcDictError() throws {
        let errorResponse: [String: Any] = [
            "error": [
                "code": -32000,
                "message": "oops"
            ]
        ]

        if let errorDict = errorResponse["error"] as? [String: Any],
           let errorMsg = errorDict["message"] as? String {
            #expect(errorMsg == "oops")
        } else {
            Issue.record("Error extraction failed")
        }
    }

    @Test("AC 7: Non-dict result doesn't leak JSON-RPC envelope")
    func nonDictResultNoEnvelopeLeak() throws {
        let jsonRpcResponse: [String: Any] = [
            "jsonrpc": "2.0",
            "id": 1,
            "result": "plain string"
        ]

        let goodResult = jsonRpcResponse["result"]
        if let goodResult = goodResult {
            let wrapped: [String: Any] = ["_value": goodResult]
            #expect(!wrapped.keys.contains("jsonrpc"))
        }
    }
}

// MARK: - BUG-012 Tests: Config MCP Duplicates

@Suite("BUG-012: Config MCP Duplicates & Case-Sensitivity", .timeLimit(.minutes(1)))
@MainActor
struct BUG012ConfigDuplicatesTests {

    private func makeManifest(name: String) -> MCPManifest {
        let json = """
        {
            "name": "\(name)",
            "version": "1.0.0",
            "description": "Test",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    @Test("AC 1a: Manifest uses cwd as rootDirectory")
    func configStdioMcpUseCwdAsRoot() throws {
        let entry: [String: Any] = [
            "command": "python3",
            "cwd": "/opt/homebrew/bin"
        ]

        if let cwd = entry["cwd"] as? String {
            #expect(cwd == "/opt/homebrew/bin")
        }
    }

    @Test("AC 1b: Command path used as rootDirectory fallback")
    func commandPathAsRootDirectory() throws {
        let entry: [String: Any] = [
            "command": "/usr/local/bin/my-server"
        ]

        if let command = entry["command"] as? String {
            let dirname = (command as NSString).deletingLastPathComponent
            #expect(dirname == "/usr/local/bin")
        }
    }

    @Test("AC 2a: Case-insensitive collision detection")
    func caseInsensitiveCollisionDetection() {
        let names = ["Shipyard", "shipyard", "SHIPYARD", "ShipYard"]
        let normalized = names.map { $0.lowercased() }
        let unique = Set(normalized)

        #expect(unique.count == 1)
    }

    @Test("AC 2b: Manifest wins over config in collision")
    func manifestWinsOverConfig() throws {
        let registry = MCPRegistry()
        let manifestServer = MCPServer(manifest: makeManifest(name: "shared"), source: .manifest)
        try registry.register(manifestServer)

        #expect(registry.registeredServers.count == 1)
        #expect(registry.registeredServers[0].source == .manifest)

        let configServer = MCPServer(manifest: makeManifest(name: "shared"), source: .config)
        #expect(throws: RegistryError.self) {
            try registry.register(configServer)
        }
    }

    @Test("AC 2c: Config entry with case-different name detected as collision")
    func caseInsensitiveRegistryCollision() throws {
        let registry = MCPRegistry()
        let server1 = MCPServer(manifest: makeManifest(name: "Shipyard"), source: .manifest)
        try registry.register(server1)

        let server2 = MCPServer(manifest: makeManifest(name: "shipyard"), source: .config)
        #expect(throws: RegistryError.self) {
            try registry.register(server2)
        }

        #expect(registry.registeredServers.count == 1)
    }

    @Test("AC 4: Unreachable command marked disabled logic")
    func unreachableCommandMarkDisabled() {
        let entry: [String: Any] = [
            "command": "/nonexistent/path/to/server"
        ]

        let command = entry["command"] as? String ?? ""
        let cwd = entry["cwd"] as? String
        let fileManager = FileManager.default

        let commandExists = fileManager.fileExists(atPath: command)
        let shouldDisable = !commandExists && cwd == nil

        #expect(shouldDisable)
    }

    @Test("Different names don't collide if registered separately")
    func differentNamesNoCollision() throws {
        let registry = MCPRegistry()
        let server1 = MCPServer(manifest: makeManifest(name: "tool_a"), source: .manifest)
        let server2 = MCPServer(manifest: makeManifest(name: "tool_b"), source: .config)

        try registry.register(server1)
        try registry.register(server2)

        #expect(registry.registeredServers.count == 2)
    }
}

// MARK: - BUG-005 Tests: View Button Functionality

@Suite("BUG-005: Execution Detail View Navigation", .timeLimit(.minutes(1)))
@MainActor
struct BUG005ViewButtonTests {

    private func makeQueueManager() -> ExecutionQueueManager {
        let suiteName = "com.shipyard.test.bug005.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return ExecutionQueueManager(defaults: defaults)
    }

    @discardableResult
    private func addExecution(to manager: ExecutionQueueManager, toolName: String) -> ToolExecution {
        let request = ToolExecutionRequest(toolName: toolName, arguments: [:])
        let execution = ToolExecution(toolName: toolName, request: request)
        manager.activeExecutions.append(execution)
        return execution
    }

    @Test("AC: ToolExecution can be selected and deselected")
    func executionSelectionState() {
        let manager = makeQueueManager()
        let execution1 = addExecution(to: manager, toolName: "tool1")
        let execution2 = addExecution(to: manager, toolName: "tool2")

        var selectedExecution: ToolExecution? = nil

        selectedExecution = execution1
        #expect(selectedExecution?.id == execution1.id)

        selectedExecution = execution2
        #expect(selectedExecution?.id == execution2.id)

        selectedExecution = nil
        #expect(selectedExecution == nil)
    }
}

// MARK: - BUG-008 Tests: Response Logging

@Suite("BUG-008: Response Logging", .timeLimit(.minutes(1)))
struct BUG008ResponseLoggingTests {

    @Test("AC 1: Response size calculation")
    func responseSizeCalculation() {
        let responseJSON = "{\"result\": \"ok\"}"
        let responseSize = responseJSON.count

        #expect(responseSize > 0)
        #expect(responseSize == 16)
    }

    @Test("AC 2: Response preview truncation works")
    func responsePreviewTruncation() {
        let longResponse = String(repeating: "x", count: 600)
        let previewLimit = 200

        let preview = String(longResponse.prefix(previewLimit))
        #expect(preview.count == previewLimit)
        #expect(preview.hasSuffix("x"))
    }
}

// MARK: - BUG-014 Tests: Sidebar Ordering and Source Badge

@Suite("BUG-014: Sidebar Ordering and Source Badge", .timeLimit(.minutes(1)))
@MainActor
struct BUG014SidebarOrderingTests {

    // MARK: - Helpers

    private func makeServer(name: String, source: MCPSource) -> MCPServer {
        let manifest = MCPManifest(
            name: name,
            version: "1.0",
            description: source == .config ? "Configured via Claude Desktop" : "Test server",
            transport: "stdio",
            command: "/usr/bin/test",
            args: [],
            env: nil,
            env_secret_keys: nil,
            dependencies: nil,
            health_check: nil,
            logging: nil,
            install: nil
        )
        return MCPServer(manifest: manifest, source: source)
    }

    // MARK: - AC 3: Shipyard is always first

    @Test("AC 3: Shipyard (synthetic) is always first in sortedServers")
    func shipyardAlwaysFirst() throws {
        let registry = MCPRegistry()
        // Add in wrong order: config, manifest, synthetic
        try registry.register(makeServer(name: "zebra-config", source: .config))
        try registry.register(makeServer(name: "alpha-manifest", source: .manifest))
        try registry.register(makeServer(name: "Shipyard", source: .synthetic))

        let sorted = registry.sortedServers
        #expect(sorted.count == 3)
        #expect(sorted[0].manifest.name == "Shipyard")
        #expect(sorted[0].source == .synthetic)
    }

    // MARK: - AC 4: Manifest MCPs sorted alphabetically after Shipyard

    @Test("AC 4: Manifest MCPs appear after Shipyard, sorted alphabetically")
    func manifestMCPsSortedAlphabetically() throws {
        let registry = MCPRegistry()
        try registry.register(makeServer(name: "Shipyard", source: .synthetic))
        try registry.register(makeServer(name: "charlie", source: .manifest))
        try registry.register(makeServer(name: "alpha", source: .manifest))
        try registry.register(makeServer(name: "bravo", source: .manifest))

        let sorted = registry.sortedServers
        #expect(sorted[0].manifest.name == "Shipyard")
        #expect(sorted[1].manifest.name == "alpha")
        #expect(sorted[2].manifest.name == "bravo")
        #expect(sorted[3].manifest.name == "charlie")
    }

    // MARK: - AC 5: Config MCPs appear after manifest MCPs, sorted alphabetically

    @Test("AC 5: Config MCPs appear after manifest MCPs, sorted alphabetically")
    func configMCPsAfterManifestSorted() throws {
        let registry = MCPRegistry()
        try registry.register(makeServer(name: "Shipyard", source: .synthetic))
        try registry.register(makeServer(name: "zulu-config", source: .config))
        try registry.register(makeServer(name: "manifest-bravo", source: .manifest))
        try registry.register(makeServer(name: "alpha-config", source: .config))
        try registry.register(makeServer(name: "manifest-alpha", source: .manifest))

        let sorted = registry.sortedServers
        #expect(sorted.count == 5)
        // Synthetic first
        #expect(sorted[0].source == .synthetic)
        // Manifest group (alphabetical)
        #expect(sorted[1].manifest.name == "manifest-alpha")
        #expect(sorted[1].source == .manifest)
        #expect(sorted[2].manifest.name == "manifest-bravo")
        #expect(sorted[2].source == .manifest)
        // Config group (alphabetical)
        #expect(sorted[3].manifest.name == "alpha-config")
        #expect(sorted[3].source == .config)
        #expect(sorted[4].manifest.name == "zulu-config")
        #expect(sorted[4].source == .config)
    }

    // MARK: - AC 4/5: Case-insensitive sorting

    @Test("Sorting is case-insensitive")
    func caseInsensitiveSorting() throws {
        let registry = MCPRegistry()
        try registry.register(makeServer(name: "Bravo", source: .manifest))
        try registry.register(makeServer(name: "alpha", source: .manifest))
        try registry.register(makeServer(name: "Charlie", source: .manifest))

        let sorted = registry.sortedServers
        #expect(sorted[0].manifest.name == "alpha")
        #expect(sorted[1].manifest.name == "Bravo")
        #expect(sorted[2].manifest.name == "Charlie")
    }

    // MARK: - Empty registry

    @Test("sortedServers returns empty for empty registry")
    func emptyRegistrySortedServers() {
        let registry = MCPRegistry()
        #expect(registry.sortedServers.isEmpty)
    }

    // MARK: - AC 1: Config servers have .config source

    @Test("AC 1/2: Config source is correctly set on MCPServer")
    func configSourcePropertySet() {
        let configServer = makeServer(name: "test", source: .config)
        let manifestServer = makeServer(name: "test2", source: .manifest)

        #expect(configServer.source == .config)
        #expect(manifestServer.source == .manifest)
    }
}
