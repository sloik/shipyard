import Testing
import Foundation
@testable import Shipyard

@Suite("MCPNotificationParser")
struct NotificationParserTests {

    let parser = MCPNotificationParser()

    @Test("Parses valid notifications/message")
    @available(macOS 14.0, *)
    @MainActor
    func parsesValidNotification() {
        let json = """
        {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": {"message": "Model loaded"}}}
        """
        let entry = parser.parse(line: json)
        #expect(entry != nil)
        #expect(entry?.level == .info)
        #expect(entry?.message == "Model loaded")
        #expect(entry?.source == .mcp)
    }

    @Test("Returns nil for non-notification method")
    @available(macOS 14.0, *)
    @MainActor
    func returnsNilForNonNotification() {
        let json = """
        {"jsonrpc": "2.0", "method": "result", "params": {}}
        """
        #expect(parser.parse(line: json) == nil)
    }

    @Test("Returns nil for invalid JSON")
    @available(macOS 14.0, *)
    @MainActor
    func returnsNilForInvalidJSON() {
        #expect(parser.parse(line: "not json at all") == nil)
    }

    @Test("Returns nil when params missing")
    @available(macOS 14.0, *)
    @MainActor
    func returnsNilForMissingParams() {
        let json = """
        {"jsonrpc": "2.0", "method": "notifications/message"}
        """
        #expect(parser.parse(line: json) == nil)
    }

    @Test("Includes logger prefix in message")
    @available(macOS 14.0, *)
    @MainActor
    func includesLoggerPrefix() {
        let json = """
        {"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "logger": "myapp", "data": {"message": "started"}}}
        """
        let entry = parser.parse(line: json)
        #expect(entry?.message == "[myapp] started")
    }

    @Test("Maps MCP levels correctly")
    @available(macOS 14.0, *)
    @MainActor
    func mapsLevelsCorrectly() {
        #expect(parser.mapLevel("error") == .error)
        #expect(parser.mapLevel("warning") == .warning)
        #expect(parser.mapLevel("info") == .info)
        #expect(parser.mapLevel("debug") == .debug)
        #expect(parser.mapLevel("emergency") == .error)
        #expect(parser.mapLevel("notice") == .warning)
        #expect(parser.mapLevel(nil) == .info)
        #expect(parser.mapLevel("unknown") == .info)
    }
}
