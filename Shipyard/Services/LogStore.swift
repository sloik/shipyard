import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "LogStore")

// MARK: - LogStore

@Observable @MainActor
final class LogStore {
    var entries: [BridgeLogEntry] = []

    // Filters
    var levelFilter: BridgeLogLevel? = nil
    var categoryFilter: Set<String> = []
    var sourceFilter: String? = nil
    var searchText: String = ""

    // Configuration
    private let logFilePaths: [String]

    init(paths: PathManager = .shared, logFilePaths: [String]? = nil) {
        self.logFilePaths = logFilePaths ?? [
            paths.bridgeLogFile.path,
            paths.appLogFile.path
        ]
    }

    /// Convenience init for single file path (used by tests)
    init(logFilePath: String) {
        self.logFilePaths = [logFilePath]
    }

    // MARK: - Computed Properties

    var filteredEntries: [BridgeLogEntry] {
        entries.filter { entry in
            // Filter by level
            if let levelFilter = levelFilter {
                if entry.logLevel < levelFilter {
                    return false
                }
            }

            // Filter by category
            if !categoryFilter.isEmpty {
                if !categoryFilter.contains(entry.cat) {
                    return false
                }
            }

            // Filter by source
            if let sourceFilter = sourceFilter {
                if entry.src != sourceFilter {
                    return false
                }
            }

            // Filter by search text
            if !searchText.isEmpty {
                if !entry.msg.localizedCaseInsensitiveContains(searchText) {
                    return false
                }
            }

            return true
        }
    }

    var availableCategories: [String] {
        Array(Set(entries.map { $0.cat })).sorted()
    }

    // MARK: - Operations

    func loadFromDisk() {
        entries.removeAll()

        var allEntries: [BridgeLogEntry] = []

        for filePath in logFilePaths {
            guard FileManager.default.fileExists(atPath: filePath) else {
                log.debug("LogStore: file not found at \(filePath, privacy: .public)")
                continue
            }

            do {
                let content = try String(contentsOfFile: filePath, encoding: .utf8)
                let lines = content.split(separator: "\n", omittingEmptySubsequences: true)

                for line in lines {
                    guard let jsonData = line.data(using: .utf8) else { continue }

                    do {
                        guard let jsonDict = try JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else {
                            continue
                        }

                        if let entry = BridgeLogEntry.fromJSON(jsonDict) {
                            allEntries.append(entry)
                        }
                    } catch {
                        continue
                    }
                }
                log.debug("LogStore: loaded entries from \(filePath, privacy: .public)")
            } catch {
                log.error("LogStore: error reading \(filePath, privacy: .public): \(error.localizedDescription, privacy: .public)")
            }
        }

        // Sort all entries by timestamp, keep last 2000
        allEntries.sort { $0.timestamp < $1.timestamp }
        if allEntries.count > 2000 {
            allEntries = Array(allEntries.suffix(2000))
        }
        entries = allEntries

        log.debug("LogStore: loaded \(self.entries.count, privacy: .public) total entries from \(self.logFilePaths.count, privacy: .public) files")
    }

    func append(_ entry: BridgeLogEntry) {
        entries.append(entry)
        // Enforce max cap (same as loadFromDisk)
        if entries.count > 2000 {
            entries.removeFirst(entries.count - 2000)
        }
    }

    func exportFiltered(to url: URL) throws {
        let entries = filteredEntries

        let jsonArray = entries.map { entry -> [String: Any] in
            var dict: [String: Any] = [
                "ts": entry.ts,
                "level": entry.level,
                "cat": entry.cat,
                "src": entry.src,
                "msg": entry.msg
            ]
            if let meta = entry.meta {
                var metaDict: [String: Any] = [:]
                for (key, value) in meta {
                    switch value {
                    case .string(let s):
                        metaDict[key] = s
                    case .int(let i):
                        metaDict[key] = i
                    case .double(let d):
                        metaDict[key] = d
                    case .bool(let b):
                        metaDict[key] = b
                    }
                }
                dict["meta"] = metaDict
            }
            return dict
        }

        let lines = jsonArray.map { dict in
            guard let lineData = try? JSONSerialization.data(withJSONObject: dict),
                  let line = String(data: lineData, encoding: .utf8) else {
                return ""
            }
            return line
        }
        let jsonl = lines.joined(separator: "\n") + "\n"

        guard let jsonlData = jsonl.data(using: .utf8) else {
            throw NSError(domain: "LogStore", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to encode JSONL"])
        }

        try jsonlData.write(to: url)
        log.debug("LogStore: exported \(entries.count, privacy: .public) entries to \(url.path, privacy: .public)")
    }

    func clear() {
        entries.removeAll()
    }
}
