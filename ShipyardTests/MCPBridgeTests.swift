import Testing
import Foundation
@testable import Shipyard

@Suite("MCPBridge")
@MainActor
struct MCPBridgeTests {

    // MARK: - Helper Methods

    /// Creates a bridge and drains its stdin pipe so writes don't block during tests.
    /// The drain task runs in the background and should be cancelled when done.
    private func makeBridgeWithDrain() -> (bridge: MCPBridge, drainTask: Task<Void, Never>) {
        let pipe = Pipe()
        let bridge = MCPBridge(mcpName: "test-mcp", stdinPipe: pipe)

        // Drain the read end of stdin in background so writes don't block
        let drainTask = Task.detached {
            while !Task.isCancelled {
                let data = pipe.fileHandleForReading.availableData
                if data.isEmpty {
                    try? await Task.sleep(for: .milliseconds(10))
                    continue
                }
            }
        }

        return (bridge, drainTask)
    }

    // MARK: - routeStdoutLine Tests

    @Test("routeStdoutLine with valid response returns true")
    func routeStdoutLineValidResponse() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        // Start a call in background (creates pending request with id=1)
        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        // Give it a moment to register the pending request
        try await Task.sleep(for: .milliseconds(100))

        // Route a valid response with id=1
        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"status":"ok"}}
            """)

        #expect(consumed == true)

        // Verify the call task receives the result
        let result = try await callTask.value
        #expect(result["status"] as? String == "ok")
    }

    @Test("routeStdoutLine with error response throws MCPBridgeError.childError")
    func routeStdoutLineErrorResponse() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        // Start a call in background
        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        // Route an error response
        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"Something went wrong"}}
            """)

        #expect(consumed == true)

        // Verify the call task throws childError
        do {
            _ = try await callTask.value
            Issue.record("Should have thrown MCPBridgeError.childError")
        } catch let error as MCPBridgeError {
            if case .childError(let mcp, let msg) = error {
                #expect(mcp == "test-mcp")
                #expect(msg == "Something went wrong")
            } else {
                Issue.record("Should be .childError case, got \(error)")
            }
        }
    }

    @Test("routeStdoutLine with notification calls onNotification and returns true")
    func routeStdoutLineNotification() {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        var notificationReceived: String?
        bridge.onNotification = { line in
            notificationReceived = line
        }

        let notificationLine = """
            {"jsonrpc":"2.0","method":"notifications/message","params":{"text":"hello"}}
            """
        let consumed = bridge.routeStdoutLine(notificationLine)

        #expect(consumed == true)
        #expect(notificationReceived == notificationLine)
    }

    @Test("routeStdoutLine with invalid JSON returns false")
    func routeStdoutLineInvalidJSON() {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let consumed = bridge.routeStdoutLine("not valid json at all {{{")

        #expect(consumed == false)
    }

    @Test("routeStdoutLine with unknown format returns false")
    func routeStdoutLineUnknownFormat() {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        // Valid JSON but no id and no method
        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","someField":"someValue"}
            """)

        #expect(consumed == false)
    }

    @Test("routeStdoutLine with response without matching pending request returns false")
    func routeStdoutLineUnmatchedId() {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        // Response for id=999 when no request is pending
        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":999,"result":{"status":"ok"}}
            """)

        #expect(consumed == false)
    }

    // MARK: - cancelAll Tests

    @Test("cancelAll throws mcpStopped for all pending requests")
    func cancelAllThrowsMCPStopped() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        // Start multiple calls in background
        let call1 = Task {
            try await bridge.call(method: "method1", timeout: 30)
        }
        let call2 = Task {
            try await bridge.call(method: "method2", timeout: 30)
        }

        try await Task.sleep(for: .milliseconds(100))

        // Cancel all pending requests
        bridge.cancelAll()

        // Both calls should throw mcpStopped
        do {
            _ = try await call1.value
            Issue.record("call1 should have thrown")
        } catch let error as MCPBridgeError {
            if case .mcpStopped(let mcp) = error {
                #expect(mcp == "test-mcp")
            } else {
                Issue.record("Should be .mcpStopped case, got \(error)")
            }
        }

        do {
            _ = try await call2.value
            Issue.record("call2 should have thrown")
        } catch let error as MCPBridgeError {
            if case .mcpStopped(let mcp) = error {
                #expect(mcp == "test-mcp")
            } else {
                Issue.record("Should be .mcpStopped case, got \(error)")
            }
        }
    }

    // MARK: - MCPBridgeError errorDescription Tests

    @Test("MCPBridgeError.serializationFailed has non-empty description")
    func errorDescriptionSerializationFailed() {
        let error = MCPBridgeError.serializationFailed
        let desc = error.errorDescription

        #expect(desc != nil)
        #expect(desc != "")
        #expect((desc ?? "").contains("JSON-RPC") || (desc ?? "").contains("serial"))
    }

    @Test("MCPBridgeError.timeout has non-empty description")
    func errorDescriptionTimeout() {
        let error = MCPBridgeError.timeout("my-mcp", "my_method", 10.5)
        let desc = error.errorDescription

        #expect(desc != nil)
        #expect(desc != "")
        #expect((desc ?? "").contains("my-mcp"))
        #expect((desc ?? "").contains("my_method"))
        #expect((desc ?? "").contains("10"))
    }

    @Test("MCPBridgeError.childError has non-empty description")
    func errorDescriptionChildError() {
        let error = MCPBridgeError.childError("test-mcp", "Something failed in child")
        let desc = error.errorDescription

        #expect(desc != nil)
        #expect(desc != "")
        #expect((desc ?? "").contains("test-mcp"))
        #expect((desc ?? "").contains("Something failed"))
    }

    @Test("MCPBridgeError.mcpStopped has non-empty description")
    func errorDescriptionMCPStopped() {
        let error = MCPBridgeError.mcpStopped("stopped-mcp")
        let desc = error.errorDescription

        #expect(desc != nil)
        #expect(desc != "")
        #expect((desc ?? "").contains("stopped-mcp"))
        #expect((desc ?? "").contains("stopped") || (desc ?? "").contains("Stopped"))
    }

    @Test("MCPBridgeError.notRunning has non-empty description")
    func errorDescriptionNotRunning() {
        let error = MCPBridgeError.notRunning("idle-mcp")
        let desc = error.errorDescription

        #expect(desc != nil)
        #expect(desc != "")
        #expect((desc ?? "").contains("idle-mcp"))
        #expect((desc ?? "").contains("not running") || (desc ?? "").contains("running"))
    }

    // MARK: - Non-Dict Result Tests (BUG-011)

    @Test("routeStdoutLine with string result wraps it in _raw_result")
    func routeStdoutLineStringResult() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":"hello world"}
            """)

        #expect(consumed == true)

        let result = try await callTask.value
        // Verify the string is wrapped in _raw_result
        #expect(result["_raw_result"] as? String == "hello world")
    }

    @Test("routeStdoutLine with array result wraps it in _raw_result")
    func routeStdoutLineArrayResult() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":[1,2,3,"four"]}
            """)

        #expect(consumed == true)

        let result = try await callTask.value
        // Verify the array is wrapped in _raw_result
        let rawArray = result["_raw_result"] as? [Any]
        #expect(rawArray != nil)
        #expect((rawArray?[0] as? NSNumber)?.intValue == 1)
        #expect((rawArray?[3] as? String) == "four")
    }

    @Test("routeStdoutLine with null result wraps it in _raw_result")
    func routeStdoutLineNullResult() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":null}
            """)

        #expect(consumed == true)

        let result = try await callTask.value
        // Verify null is wrapped in _raw_result
        #expect(result["_raw_result"] is NSNull)
    }

    @Test("routeStdoutLine with number result wraps it in _raw_result")
    func routeStdoutLineNumberResult() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":42}
            """)

        #expect(consumed == true)

        let result = try await callTask.value
        // Verify number is wrapped in _raw_result
        #expect((result["_raw_result"] as? NSNumber)?.intValue == 42)
    }

    @Test("routeStdoutLine with dict result does NOT wrap it (normal behavior)")
    func routeStdoutLineDictResultNoWrap() async throws {
        let (bridge, drainTask) = makeBridgeWithDrain()
        defer { drainTask.cancel() }

        let callTask = Task {
            try await bridge.call(method: "test_method", timeout: 5)
        }

        try await Task.sleep(for: .milliseconds(100))

        let consumed = bridge.routeStdoutLine("""
            {"jsonrpc":"2.0","id":1,"result":{"status":"ok","value":123}}
            """)

        #expect(consumed == true)

        let result = try await callTask.value
        // Dict results should NOT be wrapped — _raw_result key should not exist
        #expect(result["_raw_result"] == nil)
        // Instead, the dict contents should be directly accessible
        #expect(result["status"] as? String == "ok")
        #expect((result["value"] as? NSNumber)?.intValue == 123)
    }
}
