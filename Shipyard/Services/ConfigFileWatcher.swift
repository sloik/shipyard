import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ConfigFileWatcher")

/// Watches the centralized config directory for changes to mcps.json
/// Debounces rapid changes within a 1-second window before calling the callback
/// NOTE: Watches the parent directory, not the file itself — external editors often
/// replace files with new inodes, so watching the parent directory catches all edit patterns
@MainActor final class ConfigFileWatcher {
    private let configDir: String
    private let configFile: String
    private var directoryHandle: FileHandle?
    private var dispatchSource: DispatchSourceFileSystemObject?
    private var debounceTimer: Timer?
    private var isWatching: Bool = false
    private var lastModificationDate: Date?

    /// Callback invoked when config file changes are detected (debounced)
    var onConfigChanged: @Sendable @MainActor () async -> Void = { }

    /// App logger — injected from ShipyardApp
    var appLogger: AppLogger?

    init(paths: PathManager = .shared) {
        self.configDir = paths.configDirectory.path
        self.configFile = paths.mcpsConfigFile.lastPathComponent
        log.info("ConfigFileWatcher initialized for: \(self.configDir)/\(self.configFile)")
    }

    /// Starts watching the config directory for changes
    /// Creates the config directory and default empty file if they don't exist
    func start() {
        guard !isWatching else {
            log.warning("ConfigFileWatcher already running")
            return
        }

        log.info("Starting ConfigFileWatcher for \(self.configDir)")

        let fileManager = FileManager.default

        // Ensure config directory exists
        do {
            try fileManager.createDirectory(atPath: configDir, withIntermediateDirectories: true, attributes: nil)
            log.info("Config directory exists or created: \(self.configDir)")
        } catch {
            log.error("Failed to create config directory: \(error.localizedDescription)")
            appLogger?.log(.error, cat: "watcher", msg: "Failed to create config directory")
            return
        }

        // Ensure default empty config file exists
        let configPath = configDir + "/" + configFile
        if !fileManager.fileExists(atPath: configPath) {
            do {
                _ = try MCPConfig.loadOrCreateDefault(at: configPath)
                log.info("Created default config file: \(configPath)")
                appLogger?.log(.info, cat: "watcher", msg: "Created default config file")
            } catch {
                log.error("Failed to create default config file: \(error.localizedDescription)")
                appLogger?.log(.error, cat: "watcher", msg: "Failed to create default config file")
                return
            }
        }

        // Get initial modification date
        do {
            let attributes = try fileManager.attributesOfItem(atPath: configPath)
            lastModificationDate = attributes[.modificationDate] as? Date
        } catch {
            log.warning("Failed to get initial modification date: \(error.localizedDescription)")
        }

        // Open the directory for watching
        guard let handle = FileHandle(forReadingAtPath: configDir) else {
            log.error("Failed to open directory for watching: \(self.configDir)")
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
                await self?.handleConfigDirChange()
            }
        }

        source.setCancelHandler { [weak self] in
            self?.directoryHandle?.closeFile()
            self?.directoryHandle = nil
            log.info("ConfigFileWatcher dispatch source cancelled")
        }

        source.resume()
        self.dispatchSource = source
        self.isWatching = true

        log.info("ConfigFileWatcher started successfully")
        appLogger?.log(.info, cat: "watcher", msg: "ConfigFileWatcher started")
    }

    /// Stops watching the config directory
    func stop() {
        guard isWatching else {
            log.warning("ConfigFileWatcher not running")
            return
        }

        log.info("Stopping ConfigFileWatcher")

        // Cancel debounce timer
        debounceTimer?.invalidate()
        debounceTimer = nil

        // Cancel dispatch source
        dispatchSource?.cancel()
        dispatchSource = nil

        self.isWatching = false

        log.info("ConfigFileWatcher stopped")
        appLogger?.log(.info, cat: "watcher", msg: "ConfigFileWatcher stopped")
    }

    /// Handles a directory change with debouncing
    /// Only triggers if mcps.json content actually changed (compare modification date)
    /// Rapid changes within 1 second are coalesced into a single callback
    private func handleConfigDirChange() async {
        log.debug("ConfigFileWatcher: filesystem change detected")

        // Check if mcps.json exists and has changed
        let fileManager = FileManager.default
        let configPath = configDir + "/" + configFile

        guard fileManager.fileExists(atPath: configPath) else {
            log.warning("Config file no longer exists: \(configPath)")
            appLogger?.log(.warn, cat: "watcher", msg: "Config file deleted")
            return
        }

        // Get current modification date
        do {
            let attributes = try fileManager.attributesOfItem(atPath: configPath)
            let currentModDate = attributes[.modificationDate] as? Date

            // Only trigger callback if modification date actually changed
            if let lastMod = lastModificationDate, let currentMod = currentModDate {
                if lastMod == currentMod {
                    log.debug("ConfigFileWatcher: modification date unchanged, ignoring event")
                    return
                }
            }

            lastModificationDate = currentModDate
        } catch {
            log.warning("Failed to get modification date: \(error.localizedDescription)")
            // Continue anyway to be safe
        }

        // Cancel existing debounce timer and reset
        debounceTimer?.invalidate()

        // Schedule a callback after 1 second of no changes
        debounceTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: false) { [weak self] _ in
            Task { @MainActor in
                log.debug("ConfigFileWatcher: debounce window expired, invoking callback")
                await self?.invokeCallback()
            }
        }
    }

    /// Invokes the registered callback
    private func invokeCallback() async {
        log.info("ConfigFileWatcher: invoking onConfigChanged callback")
        appLogger?.log(.debug, cat: "watcher", msg: "Triggering config reload due to file change")
        await onConfigChanged()
    }

    // No deinit — caller must call stop() before releasing.
    // @MainActor properties can't be accessed from nonisolated deinit in Swift 6.
}
