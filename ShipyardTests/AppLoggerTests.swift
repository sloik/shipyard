import Testing
import Foundation
@testable import Shipyard

@Suite("AppLogger")
@MainActor
struct AppLoggerTests {
    private func createTempLogPath() -> String {
        let tempDir = NSTemporaryDirectory()
        return (tempDir as NSString).appendingPathComponent("test-app-\(UUID().uuidString).jsonl")
    }

    private func cleanupTempFile(_ path: String) {
        try? FileManager.default.removeItem(atPath: path)
    }

    @Test
    func testWritesJSONLToFile() {
        let path = createTempLogPath()
        defer { cleanupTempFile(path) }

        let logger = AppLogger(logFilePath: path)
        logger.log(.info, cat: "test", msg: "Hello world")

        let content = try! String(contentsOfFile: path, encoding: .utf8)
        let lines = content.split(separator: "\n")
        #expect(lines.count == 1)

        let json = try! JSONSerialization.jsonObject(with: lines[0].data(using: .utf8)!) as! [String: Any]
        #expect(json["level"] as? String == "info")
        #expect(json["cat"] as? String == "test")
        #expect(json["src"] as? String == "app")
        #expect(json["msg"] as? String == "Hello world")
        #expect(json["ts"] != nil)
    }

    @Test
    func testFeedsLogStore() {
        let path = createTempLogPath()
        defer { cleanupTempFile(path) }

        let store = LogStore(logFilePath: "/tmp/nonexistent-\(UUID().uuidString).jsonl")
        let logger = AppLogger(logFilePath: path)
        logger.logStore = store

        logger.log(.warn, cat: "process", msg: "Test warning")

        #expect(store.entries.count == 1)
        #expect(store.entries[0].src == "app")
        #expect(store.entries[0].level == "warn")
        #expect(store.entries[0].cat == "process")
        #expect(store.entries[0].msg == "Test warning")
    }

    @Test
    func testMetaIncluded() {
        let path = createTempLogPath()
        defer { cleanupTempFile(path) }

        let logger = AppLogger(logFilePath: path)
        logger.log(.info, cat: "process", msg: "Started server", meta: ["pid": .int(12345), "name": .string("test-mcp")])

        let content = try! String(contentsOfFile: path, encoding: .utf8)
        let json = try! JSONSerialization.jsonObject(with: content.trimmingCharacters(in: .whitespacesAndNewlines).data(using: .utf8)!) as! [String: Any]
        let meta = json["meta"] as! [String: Any]
        #expect(meta["pid"] as? Int == 12345)
        #expect(meta["name"] as? String == "test-mcp")
    }

    @Test
    func testWithoutLogStore() {
        let path = createTempLogPath()
        defer { cleanupTempFile(path) }

        // No logStore wired — should still write to file without crashing
        let logger = AppLogger(logFilePath: path)
        logger.log(.error, cat: "test", msg: "No store")

        let content = try! String(contentsOfFile: path, encoding: .utf8)
        #expect(!content.isEmpty)
    }

    @Test
    func testRotatesWhenFileTooLarge() {
        let tempDir = NSTemporaryDirectory()
        let baseName = "test-rotate-\(UUID().uuidString)"
        let path = (tempDir as NSString).appendingPathComponent("\(baseName).jsonl")
        defer {
            // Clean up all rotation files
            let fm = FileManager.default
            try? fm.removeItem(atPath: path)
            try? fm.removeItem(atPath: (tempDir as NSString).appendingPathComponent("\(baseName).1.jsonl"))
            try? fm.removeItem(atPath: (tempDir as NSString).appendingPathComponent("\(baseName).2.jsonl"))
            try? fm.removeItem(atPath: (tempDir as NSString).appendingPathComponent("\(baseName).3.jsonl"))
        }

        // Use tiny threshold (1 KB) to trigger rotation quickly
        let logger = AppLogger(logFilePath: path, maxFileSize: 1024, maxRotations: 3)

        // Write enough to exceed 1 KB — each JSON line is ~100-150 bytes
        // Need 100+ writes to trigger the check (writeCount % 100 == 0)
        for i in 0..<110 {
            logger.log(.info, cat: "test", msg: "Entry \(i) with padding to increase size of each line written to the log")
        }

        // After 110 writes with 1KB limit, rotation should have happened at write 100
        let fm = FileManager.default
        let rotatedPath = (tempDir as NSString).appendingPathComponent("\(baseName).1.jsonl")

        // The rotated file should exist
        #expect(fm.fileExists(atPath: rotatedPath), "Rotated .1.jsonl should exist after exceeding size limit")

        // Current file should also exist (new file after rotation)
        #expect(fm.fileExists(atPath: path), "Current log file should exist after rotation")

        // Current file should be smaller than the rotated one (it has only ~10 entries)
        let currentSize = (try? fm.attributesOfItem(atPath: path))?[.size] as? UInt64 ?? 0
        let rotatedSize = (try? fm.attributesOfItem(atPath: rotatedPath))?[.size] as? UInt64 ?? 0
        #expect(currentSize < rotatedSize, "Current file (\(currentSize)B) should be smaller than rotated file (\(rotatedSize)B)")
    }

    @Test
    func testRotationPreservesWriting() {
        let tempDir = NSTemporaryDirectory()
        let baseName = "test-rotate-write-\(UUID().uuidString)"
        let path = (tempDir as NSString).appendingPathComponent("\(baseName).jsonl")
        defer {
            let fm = FileManager.default
            try? fm.removeItem(atPath: path)
            try? fm.removeItem(atPath: (tempDir as NSString).appendingPathComponent("\(baseName).1.jsonl"))
        }

        let logger = AppLogger(logFilePath: path, maxFileSize: 1024, maxRotations: 3)

        // Write 105 entries to trigger rotation at 100, then write 5 more
        for i in 0..<105 {
            logger.log(.info, cat: "test", msg: "Entry \(i) with enough padding for size")
        }

        // Verify the current file has the post-rotation entries
        let content = try! String(contentsOfFile: path, encoding: .utf8)
        let lines = content.split(separator: "\n")
        #expect(lines.count > 0, "Post-rotation file should have entries")
        #expect(lines.count < 105, "Post-rotation file should have fewer entries than total written")
    }
}
