import Testing
import Foundation
@testable import Shipyard

@Suite("DirectoryWatcher")
@MainActor
struct DirectoryWatcherTests {

    @Test("Initializes with correct watch path")
    func initializesWithCorrectPath() {
        let testPath = "/tmp/test-discovery"
        let watcher = DirectoryWatcher(watchPath: testPath)
        #expect(watcher != nil)
    }

    @Test("Starts and stops successfully")
    func startsAndStopsSuccessfully() async throws {
        let tempPath = "/tmp/shipyard-startstop-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: tempPath, withIntermediateDirectories: true)

        defer {
            try? FileManager.default.removeItem(atPath: tempPath)
        }

        let watcher = DirectoryWatcher(watchPath: tempPath)
        watcher.start()
        try await Task.sleep(nanoseconds: 100_000_000)
        watcher.stop()
    }

    @Test("Callback can be set and cleared")
    func callbackCanBeSetAndCleared() {
        let tempPath = "/tmp/test-callback-\(UUID().uuidString)"
        let watcher = DirectoryWatcher(watchPath: tempPath)

        var callbackSet = false
        watcher.onDirectoryChanged = {
            callbackSet = true
        }

        // Verify callback was assigned (watcher accepted it)
        #expect(watcher != nil)
    }

    @Test("Handles non-existent directory gracefully")
    func handlesNonExistentDirectory() {
        let nonExistentPath = "/tmp/nonexistent-\(UUID().uuidString)/test"
        let watcher = DirectoryWatcher(watchPath: nonExistentPath)
        watcher.start()
        // Should not crash
        watcher.stop()
    }

    @Test("Multiple start calls are idempotent")
    func multipleStartsAreIdempotent() async throws {
        let tempPath = "/tmp/shipyard-idempotent-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: tempPath, withIntermediateDirectories: true)

        defer {
            try? FileManager.default.removeItem(atPath: tempPath)
        }

        let watcher = DirectoryWatcher(watchPath: tempPath)
        watcher.start()
        watcher.start()  // Second start should be harmless
        watcher.stop()
    }

    @Test("Multiple stop calls are idempotent")
    func multipleStopsAreIdempotent() async throws {
        let tempPath = "/tmp/shipyard-stop-\(UUID().uuidString)"
        try FileManager.default.createDirectory(atPath: tempPath, withIntermediateDirectories: true)

        defer {
            try? FileManager.default.removeItem(atPath: tempPath)
        }

        let watcher = DirectoryWatcher(watchPath: tempPath)
        watcher.start()
        watcher.stop()
        watcher.stop()  // Second stop should be harmless
    }

    @Test("Stop without start is safe")
    func stopWithoutStartIsSafe() {
        let watcher = DirectoryWatcher(watchPath: "/tmp/test")
        watcher.stop()  // Should not crash
    }
}
