import Testing
import Foundation
@testable import Shipyard

@Suite("MCPServer")
struct MCPServerTests {

    private func makeTestManifest() -> MCPManifest {
        let json = """
        {
            "name": "test",
            "version": "1.0.0",
            "description": "Test",
            "transport": "stdio",
            "command": "python3",
            "args": ["server.py"]
        }
        """.data(using: .utf8)!
        return try! JSONDecoder().decode(MCPManifest.self, from: json)
    }

    @Test("appendLog adds entry to buffer")
    @available(macOS 14.0, *)
    @MainActor
    func appendLogAddsEntry() {
        let server = MCPServer(manifest: makeTestManifest())
        let entry = LogEntry(timestamp: Date(), message: "test")
        server.appendLog(entry)
        #expect(server.stderrBuffer.count == 1)
        #expect(server.stderrBuffer.first?.message == "test")
    }

    @Test("appendLog trims buffer at 1000 entries")
    @available(macOS 14.0, *)
    @MainActor
    func appendLogTrimsBuffer() {
        let server = MCPServer(manifest: makeTestManifest())
        for i in 0..<1050 {
            server.appendLog(LogEntry(timestamp: Date(), message: "log \(i)"))
        }
        #expect(server.stderrBuffer.count == 1000)
        // First entry should be "log 50" (first 50 trimmed)
        #expect(server.stderrBuffer.first?.message == "log 50")
    }

    @Test("clearLogs empties buffer")
    @available(macOS 14.0, *)
    @MainActor
    func clearLogsEmptiesBuffer() {
        let server = MCPServer(manifest: makeTestManifest())
        server.appendLog(LogEntry(timestamp: Date(), message: "test"))
        server.clearLogs()
        #expect(server.stderrBuffer.isEmpty)
    }

    @Test("ServerState.isRunning")
    func serverStateIsRunning() {
        #expect(ServerState.running.isRunning == true)
        #expect(ServerState.idle.isRunning == false)
        #expect(ServerState.starting.isRunning == false)
        #expect(ServerState.stopping.isRunning == false)
        #expect(ServerState.error("fail").isRunning == false)
    }
}
