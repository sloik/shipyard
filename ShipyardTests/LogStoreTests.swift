import Testing
import Foundation
@testable import Shipyard

@Suite("LogStore")
@MainActor
struct LogStoreTests {
    // MARK: - Test Helpers

    private func createTempLogFile(content: String) -> String {
        let tempDir = NSTemporaryDirectory()
        let fileName = "test-bridge-\(UUID().uuidString).jsonl"
        let filePath = (tempDir as NSString).appendingPathComponent(fileName)
        try? content.write(toFile: filePath, atomically: true, encoding: .utf8)
        return filePath
    }

    private func cleanupTempFile(_ path: String) {
        try? FileManager.default.removeItem(atPath: path)
    }

    // MARK: - Tests

    @Test
    func testLoadValidJSONL() {
        let content = """
        {"ts":"2024-01-15T10:30:45.123Z","level":"info","cat":"socket","src":"bridge","msg":"Server started"}
        {"ts":"2024-01-15T10:30:46.456Z","level":"warn","cat":"auth","src":"bridge","msg":"Auth failed"}
        """
        let filePath = createTempLogFile(content: content)
        defer { cleanupTempFile(filePath) }

        let store = LogStore(logFilePath: filePath)
        store.loadFromDisk()

        #expect(store.entries.count == 2)
        #expect(store.entries[0].msg == "Server started")
        #expect(store.entries[0].level == "info")
        #expect(store.entries[1].msg == "Auth failed")
        #expect(store.entries[1].level == "warn")
    }

    @Test
    func testFilterByLevel() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "debug", cat: "test", src: "bridge", msg: "Debug message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "info", cat: "test", src: "bridge", msg: "Info message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "warn", cat: "test", src: "bridge", msg: "Warn message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:48.123Z", level: "error", cat: "test", src: "bridge", msg: "Error message")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        // Filter for warning level and above
        store.levelFilter = .warn
        #expect(store.filteredEntries.count == 2)
        #expect(store.filteredEntries[0].level == "warn")
        #expect(store.filteredEntries[1].level == "error")

        // Clear filter
        store.levelFilter = nil
        #expect(store.filteredEntries.count == 4)
    }

    @Test
    func testFilterByCategory() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "info", cat: "socket", src: "bridge", msg: "Socket message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "info", cat: "auth", src: "bridge", msg: "Auth message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "info", cat: "socket", src: "bridge", msg: "Socket message 2")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        store.categoryFilter = ["socket"]
        #expect(store.filteredEntries.count == 2)
        #expect(store.filteredEntries.allSatisfy { $0.cat == "socket" })

        store.categoryFilter = ["socket", "auth"]
        #expect(store.filteredEntries.count == 3)

        store.categoryFilter = []
        #expect(store.filteredEntries.count == 3)
    }

    @Test
    func testFilterBySource() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "info", cat: "test", src: "bridge", msg: "Bridge log"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "info", cat: "test", src: "app", msg: "App log"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "info", cat: "test", src: "bridge", msg: "Bridge log 2")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        store.sourceFilter = "bridge"
        #expect(store.filteredEntries.count == 2)
        #expect(store.filteredEntries.allSatisfy { $0.src == "bridge" })

        store.sourceFilter = "app"
        #expect(store.filteredEntries.count == 1)
        #expect(store.filteredEntries[0].msg == "App log")

        store.sourceFilter = nil
        #expect(store.filteredEntries.count == 3)
    }

    @Test
    func testFilterBySearchText() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "info", cat: "test", src: "bridge", msg: "Connection established"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "info", cat: "test", src: "bridge", msg: "User login successful"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "error", cat: "test", src: "bridge", msg: "Connection timeout")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        store.searchText = "connection"
        #expect(store.filteredEntries.count == 2)

        store.searchText = "login"
        #expect(store.filteredEntries.count == 1)
        #expect(store.filteredEntries[0].msg == "User login successful")

        store.searchText = "CONNECTION"  // Case insensitive
        #expect(store.filteredEntries.count == 2)

        store.searchText = ""
        #expect(store.filteredEntries.count == 3)
    }

    @Test
    func testMalformedLinesSkipped() {
        let content = """
        {"ts":"2024-01-15T10:30:45.123Z","level":"info","cat":"socket","src":"bridge","msg":"Valid entry"}
        This is not JSON
        {"ts":"2024-01-15T10:30:46.123Z","level":"info","cat":"socket"
        {"ts":"2024-01-15T10:30:47.123Z","level":"info","cat":"socket","src":"bridge","msg":"Another valid entry"}
        """
        let filePath = createTempLogFile(content: content)
        defer { cleanupTempFile(filePath) }

        let store = LogStore(logFilePath: filePath)
        store.loadFromDisk()

        // Only valid entries should be loaded
        #expect(store.entries.count == 2)
        #expect(store.entries[0].msg == "Valid entry")
        #expect(store.entries[1].msg == "Another valid entry")
    }

    @Test
    func testEmptyFile() {
        let store = LogStore(logFilePath: "/tmp/nonexistent-shipyard-\(UUID().uuidString).jsonl")
        store.loadFromDisk()

        #expect(store.entries.isEmpty)
    }

    @Test
    func testAvailableCategories() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "info", cat: "socket", src: "bridge", msg: "Message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "info", cat: "auth", src: "bridge", msg: "Message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "info", cat: "socket", src: "bridge", msg: "Message"),
            BridgeLogEntry(ts: "2024-01-15T10:30:48.123Z", level: "info", cat: "rpc", src: "bridge", msg: "Message")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        let categories = store.availableCategories
        #expect(categories == ["auth", "rpc", "socket"])  // Sorted unique
    }

    @Test
    func testCombinedFilters() {
        let entries = [
            BridgeLogEntry(ts: "2024-01-15T10:30:45.123Z", level: "info", cat: "socket", src: "bridge", msg: "Socket connection"),
            BridgeLogEntry(ts: "2024-01-15T10:30:46.123Z", level: "warn", cat: "auth", src: "bridge", msg: "Auth timeout"),
            BridgeLogEntry(ts: "2024-01-15T10:30:47.123Z", level: "info", cat: "socket", src: "app", msg: "Socket disconnect"),
            BridgeLogEntry(ts: "2024-01-15T10:30:48.123Z", level: "error", cat: "socket", src: "bridge", msg: "Socket error occurred"),
            BridgeLogEntry(ts: "2024-01-15T10:30:49.123Z", level: "warn", cat: "socket", src: "bridge", msg: "Socket warning")
        ]

        let store = LogStore(logFilePath: "/tmp/nonexistent.jsonl")
        store.entries = entries

        // Filter: warn+ level, socket category, bridge source
        store.levelFilter = .warn
        store.categoryFilter = ["socket"]
        store.sourceFilter = "bridge"

        #expect(store.filteredEntries.count == 2)
        #expect(store.filteredEntries[0].msg == "Socket error occurred")
        #expect(store.filteredEntries[1].msg == "Socket warning")

        // Add search text
        store.searchText = "warning"
        #expect(store.filteredEntries.count == 1)
        #expect(store.filteredEntries[0].msg == "Socket warning")
    }

    @Test
    func testLastTwoThousandLines() {
        var lines: [String] = []
        for i in 0..<3000 {
            let entry = [
                "ts": "2024-01-15T10:30:00.000Z",
                "level": "info",
                "cat": "test",
                "src": "bridge",
                "msg": "Entry \(i)"
            ] as [String: Any]
            if let data = try? JSONSerialization.data(withJSONObject: entry),
               let line = String(data: data, encoding: .utf8) {
                lines.append(line)
            }
        }
        let content = lines.joined(separator: "\n")
        let filePath = createTempLogFile(content: content)
        defer { cleanupTempFile(filePath) }

        let store = LogStore(logFilePath: filePath)
        store.loadFromDisk()

        // Should load only the last 2000 entries
        #expect(store.entries.count == 2000)
        // Verify it's the last 2000 (starting from index 1000)
        #expect(store.entries.first?.msg == "Entry 1000")
        #expect(store.entries.last?.msg == "Entry 2999")
    }

    @Test
    func testLoadMultipleFiles() {
        let bridgeContent = """
        {"ts":"2024-01-15T10:30:45.000Z","level":"info","cat":"socket","src":"bridge","msg":"Bridge log 1"}
        {"ts":"2024-01-15T10:30:47.000Z","level":"info","cat":"socket","src":"bridge","msg":"Bridge log 2"}
        """
        let appContent = """
        {"ts":"2024-01-15T10:30:46.000Z","level":"info","cat":"lifecycle","src":"app","msg":"App log 1"}
        {"ts":"2024-01-15T10:30:48.000Z","level":"info","cat":"lifecycle","src":"app","msg":"App log 2"}
        """

        let bridgePath = createTempLogFile(content: bridgeContent)
        let appPath = createTempLogFile(content: appContent)
        defer {
            cleanupTempFile(bridgePath)
            cleanupTempFile(appPath)
        }

        let store = LogStore(logFilePaths: [bridgePath, appPath])
        store.loadFromDisk()

        // Should have 4 entries total, sorted by timestamp
        #expect(store.entries.count == 4)
        #expect(store.entries[0].msg == "Bridge log 1")
        #expect(store.entries[0].src == "bridge")
        #expect(store.entries[1].msg == "App log 1")
        #expect(store.entries[1].src == "app")
        #expect(store.entries[2].msg == "Bridge log 2")
        #expect(store.entries[3].msg == "App log 2")
    }
}
