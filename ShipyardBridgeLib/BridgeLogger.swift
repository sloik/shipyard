import Foundation

public enum BridgeLogLevel: String, Codable, Comparable {
    case debug, info, warn, error

    public static func < (lhs: BridgeLogLevel, rhs: BridgeLogLevel) -> Bool {
        let order: [BridgeLogLevel] = [.debug, .info, .warn, .error]
        return order.firstIndex(of: lhs)! < order.firstIndex(of: rhs)!
    }
}

// MARK: - BridgeLogging Protocol

/// Protocol for injectable logging. Allows tests to capture and verify log calls.
public protocol BridgeLogging: Sendable {
    func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]?)
}

// MARK: - BridgeLogger Implementation

public final class BridgeLogger: BridgeLogging, @unchecked Sendable {
    public static let shared = BridgeLogger()
    private var fileHandle: FileHandle?
    private let dateFormatter: ISO8601DateFormatter
    private let logPath: String
    private var writeCount: Int = 0

    /// Prevents recursive log→send→log loop
    private var isForwarding: Bool = false

    /// Rotation config
    private let maxFileSize: UInt64 = 10 * 1024 * 1024  // 10 MB
    private let maxRotations: Int = 3

    private init() {
        let logsDir = "\(NSHomeDirectory())/.shipyard/logs"
        try? FileManager.default.createDirectory(atPath: logsDir, withIntermediateDirectories: true)

        self.logPath = "\(logsDir)/bridge.jsonl"
        if !FileManager.default.fileExists(atPath: logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil)
        }
        self.fileHandle = FileHandle(forWritingAtPath: logPath)
        self.fileHandle?.seekToEndOfFile()

        self.dateFormatter = ISO8601DateFormatter()
        self.dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    }

    public func log(_ level: BridgeLogLevel, cat: String, msg: String, meta: [String: Any]? = nil) {
        let ts = dateFormatter.string(from: Date())

        var dict: [String: Any] = [
            "ts": ts,
            "level": level.rawValue,
            "cat": cat,
            "src": "bridge",
            "msg": msg
        ]
        if let meta = meta {
            dict["meta"] = meta
        }

        // Check rotation every 100 writes
        writeCount += 1
        if writeCount % 100 == 0 {
            rotateIfNeeded()
        }

        if let data = try? JSONSerialization.data(withJSONObject: dict),
           var line = String(data: data, encoding: .utf8) {
            line += "\n"
            if let lineData = line.data(using: .utf8) {
                try? fileHandle?.write(contentsOf: lineData)
            }
        }

        // Dual-write to stderr (mandatory — visible in app's System Logs tab + fallback when app is not running)
        let stderrMsg = "[\(cat)] \(msg)\n"
        if let stderrData = stderrMsg.data(using: .utf8) {
            try? FileHandle.standardError.write(contentsOf: stderrData)
        }

        // Forward to Shipyard app (info+ only, fire-and-forget)
        // Guard against recursive log→send→log loop: send() logs internally,
        // which would re-enter here and fire another send(), ad infinitum.
        if level >= .info, !isForwarding {
            isForwarding = true
            let forwardDict = dict
            let logger = self
            DispatchQueue.global(qos: .utility).async {
                _ = shipyardSocket.send(method: "log_event", params: forwardDict, timeout: 2.0)
                logger.isForwarding = false
            }
        }
    }

    // MARK: - Log Rotation

    private func rotateIfNeeded() {
        let fm = FileManager.default
        guard let attrs = try? fm.attributesOfItem(atPath: logPath),
              let fileSize = attrs[.size] as? UInt64,
              fileSize >= maxFileSize else {
            return
        }

        // Close current file handle
        fileHandle?.closeFile()
        fileHandle = nil

        // Rotate: .3→delete, .2→.3, .1→.2, current→.1
        let basePath = (logPath as NSString).deletingPathExtension
        let ext = (logPath as NSString).pathExtension

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
                if fm.fileExists(atPath: logPath) {
                    try? fm.moveItem(atPath: logPath, toPath: rotatedPath)
                }
            }
        }

        // Create new file and open handle
        fm.createFile(atPath: logPath, contents: nil)
        fileHandle = FileHandle(forWritingAtPath: logPath)
        fileHandle?.seekToEndOfFile()
    }

    deinit {
        fileHandle?.closeFile()
    }
}

// MARK: - Global Injectable Logger

/// The active logger instance. Defaults to BridgeLogger.shared.
/// Override in tests with a mock.
public nonisolated(unsafe) var bridgeLog: any BridgeLogging = BridgeLogger.shared

// MARK: - BridgeLogging Default Implementation

public extension BridgeLogging {
    func log(_ level: BridgeLogLevel, cat: String, msg: String) {
        log(level, cat: cat, msg: msg, meta: nil)
    }
}
