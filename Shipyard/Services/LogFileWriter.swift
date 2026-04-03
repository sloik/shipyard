import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "LogFileWriter")

/// Writes log entries to disk with rotation.
///
/// Directory structure:
/// ```
/// <root>/logs/mcp/
/// ├── mac-runner/
/// │   ├── 2026-03-10.log
/// │   └── 2026-03-09.log
/// └── lmstudio/
///     ├── 2026-03-10.log
///     └── 2026-03-09.log
/// ```
///
/// Rotation policy: max 10 MB per file, max 7 days, max 7 files per MCP.
@MainActor final class LogFileWriter {

    // MARK: - Configuration

    static let maxFileSize: UInt64 = 10 * 1024 * 1024  // 10 MB
    static let maxAgeDays: Int = 7
    static let maxFilesPerMCP: Int = 7

    // MARK: - State

    /// Active file handles per MCP name
    private var fileHandles: [String: FileHandle] = [:]
    /// Current log file date per MCP name (for date-based rotation)
    private var currentDate: [String: String] = [:]

    private let baseDirectory: URL
    private let dateFormatter: DateFormatter
    private let timestampFormatter: DateFormatter

    // MARK: - Init

    init(paths: PathManager = .shared, baseDirectory: URL? = nil) {
        let logsDir = baseDirectory ?? paths.mcpLogsDirectory
        self.baseDirectory = logsDir

        self.dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"

        self.timestampFormatter = DateFormatter()
        timestampFormatter.dateFormat = "HH:mm:ss.SSS"

        log.info("LogFileWriter init — base: \(logsDir.path)")
    }

    // MARK: - Public API

    /// Writes a log entry for the given MCP server
    func write(_ entry: LogEntry, serverName: String) {
        let today = dateFormatter.string(from: Date())

        // Rotate if date changed
        if currentDate[serverName] != today {
            closeHandle(for: serverName)
            currentDate[serverName] = today
            rotateOldFiles(for: serverName)
        }

        // Get or create file handle
        let handle: FileHandle
        if let existing = fileHandles[serverName] {
            // Check size-based rotation
            let offset = existing.offsetInFile
            if offset > Self.maxFileSize {
                closeHandle(for: serverName)
                // Rename current file with suffix and start fresh
                let dir = serverDirectory(for: serverName)
                let currentFile = dir.appendingPathComponent("\(today).log")
                let overflowFile = dir.appendingPathComponent("\(today)-\(UUID().uuidString.prefix(8)).log")
                try? FileManager.default.moveItem(at: currentFile, to: overflowFile)
                handle = createHandle(for: serverName, date: today)
            } else {
                handle = existing
            }
        } else {
            handle = createHandle(for: serverName, date: today)
        }

        // Format and write
        let timestamp = timestampFormatter.string(from: entry.timestamp)
        let level = entry.level.rawValue.uppercased().padding(toLength: 7, withPad: " ", startingAt: 0)
        let source = entry.source.rawValue.padding(toLength: 7, withPad: " ", startingAt: 0)
        let line = "[\(timestamp)] [\(level)] [\(source)] \(entry.message)\n"

        if let data = line.data(using: .utf8) {
            handle.write(data)
        }
    }

    /// Flush and close all open handles (call on app termination)
    func closeAll() {
        for (name, handle) in fileHandles {
            try? handle.close()
            log.info("Closed log handle for '\(name)'")
        }
        fileHandles.removeAll()
        currentDate.removeAll()
    }

    /// Returns the log directory for a given MCP server
    func logDirectory(for serverName: String) -> URL {
        serverDirectory(for: serverName)
    }

    /// Lists available log files for a server, newest first
    func logFiles(for serverName: String) -> [URL] {
        let dir = serverDirectory(for: serverName)
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.creationDateKey],
            options: [.skipsHiddenFiles]
        ) else { return [] }

        return files
            .filter { $0.pathExtension == "log" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
    }

    /// Reads the contents of a specific log file
    func readLogFile(_ url: URL, tailLines: Int? = nil) -> String {
        guard let content = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        guard let tailLines = tailLines else { return content }

        let lines = content.components(separatedBy: "\n")
        let startIndex = max(0, lines.count - tailLines)
        return lines[startIndex...].joined(separator: "\n")
    }

    // MARK: - Private

    private func serverDirectory(for serverName: String) -> URL {
        baseDirectory.appendingPathComponent(serverName)
    }

    private func createHandle(for serverName: String, date: String) -> FileHandle {
        let dir = serverDirectory(for: serverName)
        let fm = FileManager.default

        // Ensure directory exists
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)

        let filePath = dir.appendingPathComponent("\(date).log")

        // Create file if it doesn't exist
        if !fm.fileExists(atPath: filePath.path) {
            fm.createFile(atPath: filePath.path, contents: nil)
        }

        // Open for appending
        do {
            let handle = try FileHandle(forWritingTo: filePath)
            handle.seekToEndOfFile()
            fileHandles[serverName] = handle
            log.info("Opened log file: \(filePath.path)")
            return handle
        } catch {
            log.error("Failed to open log file \(filePath.path): \(error.localizedDescription)")
            // Fallback: create fresh and try again
            fm.createFile(atPath: filePath.path, contents: nil)
            let handle = (try? FileHandle(forWritingTo: filePath)) ?? FileHandle.nullDevice
            fileHandles[serverName] = handle
            return handle
        }
    }

    private func closeHandle(for serverName: String) {
        if let handle = fileHandles[serverName] {
            try? handle.close()
            fileHandles.removeValue(forKey: serverName)
        }
    }

    /// Remove log files older than maxAgeDays or exceeding maxFilesPerMCP
    private func rotateOldFiles(for serverName: String) {
        let dir = serverDirectory(for: serverName)
        let fm = FileManager.default

        guard let files = try? fm.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.creationDateKey],
            options: [.skipsHiddenFiles]
        ) else { return }

        let logFiles = files
            .filter { $0.pathExtension == "log" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }

        let cutoffDate = Calendar.current.date(byAdding: .day, value: -Self.maxAgeDays, to: Date()) ?? Date()

        for (index, file) in logFiles.enumerated() {
            // Remove if over max file count
            if index >= Self.maxFilesPerMCP {
                try? fm.removeItem(at: file)
                log.info("Rotated (count): \(file.lastPathComponent)")
                continue
            }

            // Remove if older than max age
            if let values = try? file.resourceValues(forKeys: [.creationDateKey]),
               let created = values.creationDate,
               created < cutoffDate {
                try? fm.removeItem(at: file)
                log.info("Rotated (age): \(file.lastPathComponent)")
            }
        }
    }
}
