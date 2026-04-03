import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "DirectoryWatcher")

/// Watches a directory for filesystem changes using macOS FSEvents
/// Debounces rapid changes within a 1-second window before calling the callback
@MainActor final class DirectoryWatcher {
    private let watchPath: String
    private var directoryHandle: FileHandle?
    private var dispatchSource: DispatchSourceFileSystemObject?
    private var debounceTimer: Timer?
    private var isWatching: Bool = false

    /// Callback invoked when directory changes are detected (debounced)
    var onDirectoryChanged: @Sendable @MainActor () async -> Void = { }

    /// App logger — injected from ShipyardApp
    var appLogger: AppLogger?

    init(watchPath: String = PathManager.shared.mcpDiscoveryRoot.path) {
        self.watchPath = watchPath
        log.info("DirectoryWatcher initialized for: \(watchPath)")
    }

    /// Starts watching the directory for changes
    func start() {
        guard !isWatching else {
            log.warning("DirectoryWatcher already running")
            return
        }

        log.info("Starting DirectoryWatcher for \(self.watchPath)")

        // Open the directory for watching
        guard let handle = FileHandle(forReadingAtPath: watchPath) else {
            log.error("Failed to open directory for watching: \(self.watchPath)")
            appLogger?.log(.error, cat: "watcher", msg: "Failed to open directory for watching")
            return
        }

        self.directoryHandle = handle
        let fd = handle.fileDescriptor

        // Create a dispatch source for filesystem events
        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd,
            eventMask: [.write, .delete, .rename, .attrib],
            queue: .main
        )

        source.setEventHandler { [weak self] in
            Task { @MainActor in
                await self?.handleDirectoryChange()
            }
        }

        source.setCancelHandler { [weak self] in
            self?.directoryHandle?.closeFile()
            self?.directoryHandle = nil
            log.info("DirectoryWatcher dispatch source cancelled")
        }

        source.resume()
        self.dispatchSource = source
        self.isWatching = true

        log.info("DirectoryWatcher started successfully")
        appLogger?.log(.info, cat: "watcher", msg: "DirectoryWatcher started")
    }

    /// Stops watching the directory
    func stop() {
        guard isWatching else {
            log.warning("DirectoryWatcher not running")
            return
        }

        log.info("Stopping DirectoryWatcher")

        // Cancel debounce timer
        debounceTimer?.invalidate()
        debounceTimer = nil

        // Cancel dispatch source
        dispatchSource?.cancel()
        dispatchSource = nil

        self.isWatching = false

        log.info("DirectoryWatcher stopped")
        appLogger?.log(.info, cat: "watcher", msg: "DirectoryWatcher stopped")
    }

    /// Handles a directory change with debouncing
    /// Rapid changes within 1 second are coalesced into a single callback
    private func handleDirectoryChange() async {
        log.debug("DirectoryWatcher: filesystem change detected")

        // Cancel existing debounce timer and reset
        debounceTimer?.invalidate()

        // Schedule a callback after 1 second of no changes
        debounceTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: false) { [weak self] _ in
            Task { @MainActor in
                log.debug("DirectoryWatcher: debounce window expired, invoking callback")
                await self?.invokeCallback()
            }
        }
    }

    /// Invokes the registered callback
    private func invokeCallback() async {
        log.info("DirectoryWatcher: invoking onDirectoryChanged callback")
        appLogger?.log(.debug, cat: "watcher", msg: "Triggering rescan due to directory change")
        await onDirectoryChanged()
    }

    // No deinit — caller must call stop() before releasing.
    // @MainActor properties can't be accessed from nonisolated deinit in Swift 6.
}
