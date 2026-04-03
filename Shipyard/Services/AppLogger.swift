import Foundation
import os

private let sysLog = Logger(subsystem: "com.shipyard.app", category: "AppLogger")

@Observable @MainActor
final class AppLogger {
    private var fileHandle: FileHandle?
    private let dateFormatter: ISO8601DateFormatter
    private let logFilePath: String
    private var writeCount: Int = 0

    /// Rotation config
    private let maxFileSize: UInt64
    private let maxRotations: Int

    /// Weak reference to LogStore — wired up in ShipyardApp.task
    weak var logStore: LogStore?

    init(paths: PathManager = .shared, logFilePath: String? = nil, maxFileSize: UInt64 = 10 * 1024 * 1024, maxRotations: Int = 3) {
        self.logFilePath = logFilePath ?? paths.appLogFile.path
        self.maxFileSize = maxFileSize
        self.maxRotations = maxRotations

        self.dateFormatter = ISO8601DateFormatter()
        self.dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        // Ensure directory exists and open file for appending
        let logsDir = (self.logFilePath as NSString).deletingLastPathComponent
        try? FileManager.default.createDirectory(atPath: logsDir, withIntermediateDirectories: true)

        if !FileManager.default.fileExists(atPath: self.logFilePath) {
            FileManager.default.createFile(atPath: self.logFilePath, contents: nil)
        }
        self.fileHandle = FileHandle(forWritingAtPath: self.logFilePath)
        self.fileHandle?.seekToEndOfFile()

        sysLog.info("AppLogger initialized, writing to \(self.logFilePath)")
    }

    /// Log a structured entry to app.jsonl and feed LogStore
    func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: AnyCodableValue]? = nil) {
        let ts = dateFormatter.string(from: Date())

        // Build JSON dict
        var dict: [String: Any] = [
            "ts": ts,
            "level": level.rawValue,
            "cat": cat,
            "src": "app",
            "msg": msg
        ]
        if let meta = meta {
            var metaDict: [String: Any] = [:]
            for (key, value) in meta {
                switch value {
                case .string(let s): metaDict[key] = s
                case .int(let i): metaDict[key] = i
                case .double(let d): metaDict[key] = d
                case .bool(let b): metaDict[key] = b
                }
            }
            dict["meta"] = metaDict
        }

        // Check rotation every 100 writes
        writeCount += 1
        if writeCount % 100 == 0 {
            rotateIfNeeded()
        }

        // Write to file
        if let data = try? JSONSerialization.data(withJSONObject: dict),
           var line = String(data: data, encoding: .utf8) {
            line += "\n"
            if let lineData = line.data(using: .utf8) {
                fileHandle?.write(lineData)
            }
        }

        // Feed into LogStore for UI
        let entry = BridgeLogEntry(ts: ts, level: level.rawValue, cat: cat, src: "app", msg: msg, meta: meta)
        logStore?.append(entry)
    }

    // MARK: - Log Rotation

    private func rotateIfNeeded() {
        let fm = FileManager.default
        guard let attrs = try? fm.attributesOfItem(atPath: logFilePath),
              let fileSize = attrs[.size] as? UInt64,
              fileSize >= maxFileSize else {
            return
        }

        sysLog.info("AppLogger: rotating log file (\(fileSize) bytes > \(self.maxFileSize) limit)")

        // Close current file handle
        fileHandle?.closeFile()
        fileHandle = nil

        // Rotate: .3→delete, .2→.3, .1→.2, current→.1
        let basePath = (logFilePath as NSString).deletingPathExtension
        let ext = (logFilePath as NSString).pathExtension

        for i in stride(from: maxRotations, through: 1, by: -1) {
            let rotatedPath = "\(basePath).\(i).\(ext)"
            if i == maxRotations {
                try? fm.removeItem(atPath: rotatedPath)
            }
            if i > 1 {
                let prevPath = "\(basePath).\(i - 1).\(ext)"
                if fm.fileExists(atPath: prevPath) {
                    try? fm.moveItem(atPath: prevPath, toPath: rotatedPath)
                }
            } else {
                // i == 1: move current → .1
                if fm.fileExists(atPath: logFilePath) {
                    try? fm.moveItem(atPath: logFilePath, toPath: rotatedPath)
                }
            }
        }

        // Create new file and open handle
        fm.createFile(atPath: logFilePath, contents: nil)
        fileHandle = FileHandle(forWritingAtPath: logFilePath)
        fileHandle?.seekToEndOfFile()

        sysLog.info("AppLogger: rotation complete")
    }

    // Note: FileHandle will be closed automatically when deallocated.
    // No explicit deinit needed — deinit is nonisolated and cannot access
    // @MainActor-isolated properties.
}
