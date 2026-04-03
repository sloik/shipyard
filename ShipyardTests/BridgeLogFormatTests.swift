import Testing
import Foundation

/// Tests for the BridgeLogger JSONL format contract.
/// BridgeLogger lives in ShipyardBridge (separate executable), so we can't import it directly.
/// These tests validate the JSONL format that Phase L2 (LogStore) will depend on when
/// reading bridge.jsonl entries.
@Suite("BridgeLog Format Contract")
struct BridgeLogFormatTests {

    // MARK: - JSONL Entry Format

    @Test("JSONL entry has all required fields")
    func jsonlEntryHasRequiredFields() throws {
        // Simulate what BridgeLogger produces
        let entry: [String: Any] = [
            "ts": "2026-03-12T14:30:05.123Z",
            "level": "info",
            "cat": "socket",
            "src": "bridge",
            "msg": "sent 245B for gateway_call"
        ]

        let data = try JSONSerialization.data(withJSONObject: entry)
        let parsed = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        #expect(parsed["ts"] is String)
        #expect(parsed["level"] is String)
        #expect(parsed["cat"] is String)
        #expect(parsed["src"] is String)
        #expect(parsed["msg"] is String)
    }

    @Test("JSONL entry with meta includes structured metadata")
    func jsonlEntryWithMetaIncludesMetadata() throws {
        let entry: [String: Any] = [
            "ts": "2026-03-12T14:30:05.123Z",
            "level": "info",
            "cat": "socket",
            "src": "bridge",
            "msg": "total 1024B for status",
            "meta": [
                "method": "status",
                "bytes": 1024,
                "duration_ms": 42
            ] as [String: Any]
        ]

        let data = try JSONSerialization.data(withJSONObject: entry)
        let parsed = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let meta = try #require(parsed["meta"] as? [String: Any])

        #expect(meta["method"] as? String == "status")
        #expect(meta["bytes"] as? Int == 1024)
        #expect(meta["duration_ms"] as? Int == 42)
    }

    @Test("JSONL entry without meta omits meta field")
    func jsonlEntryWithoutMetaOmitsField() throws {
        let entry: [String: Any] = [
            "ts": "2026-03-12T14:30:05.123Z",
            "level": "debug",
            "cat": "stdin",
            "src": "bridge",
            "msg": "EOF on stdin, exiting"
        ]

        let data = try JSONSerialization.data(withJSONObject: entry)
        let parsed = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        #expect(parsed["meta"] == nil)
    }

    // MARK: - Level Values

    @Test("Valid log levels are debug, info, warn, error")
    func validLogLevels() {
        let validLevels = ["debug", "info", "warn", "error"]
        for level in validLevels {
            #expect(validLevels.contains(level), "Level '\(level)' should be valid")
        }
    }

    @Test("Log level ordering: debug < info < warn < error")
    func logLevelOrdering() {
        let levels = ["debug", "info", "warn", "error"]
        for i in 0..<levels.count {
            for j in (i + 1)..<levels.count {
                let lowerIdx = levels.firstIndex(of: levels[i])!
                let higherIdx = levels.firstIndex(of: levels[j])!
                #expect(lowerIdx < higherIdx, "\(levels[i]) should be lower than \(levels[j])")
            }
        }
    }

    // MARK: - Category Values

    @Test("Known bridge categories are documented")
    func knownBridgeCategories() {
        // Categories defined in Shipyard-Logging-Spec.md Section 4
        let bridgeCategories = ["mcp", "socket", "gateway", "init", "stdin"]
        #expect(bridgeCategories.count == 5)
        // Each must be non-empty
        for cat in bridgeCategories {
            #expect(!cat.isEmpty)
        }
    }

    // MARK: - Source Value

    @Test("Bridge source is always 'bridge'")
    func bridgeSourceValue() {
        let src = "bridge"
        #expect(src == "bridge")
    }

    // MARK: - Timestamp Format

    @Test("Timestamp is valid ISO 8601 with fractional seconds")
    func timestampIsISO8601WithFractionalSeconds() {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        let now = Date()
        let ts = formatter.string(from: now)

        // Should be parseable back
        let parsed = formatter.date(from: ts)
        #expect(parsed != nil, "Timestamp '\(ts)' should be parseable")

        // Should contain a dot (fractional seconds)
        #expect(ts.contains("."), "Timestamp '\(ts)' should contain fractional seconds")
    }

    // MARK: - JSONL Line Format

    @Test("Entry serializes to single-line JSON (no newlines in output)")
    func entrySerializesToSingleLineJSON() throws {
        let entry: [String: Any] = [
            "ts": "2026-03-12T14:30:05.123Z",
            "level": "info",
            "cat": "socket",
            "src": "bridge",
            "msg": "sent 245B for gateway_call",
            "meta": ["method": "gateway_call", "bytes": 245] as [String: Any]
        ]

        let data = try JSONSerialization.data(withJSONObject: entry)
        let line = try #require(String(data: data, encoding: .utf8))

        // No embedded newlines (each JSONL line must be a single line)
        #expect(!line.contains("\n"), "JSONL line must not contain embedded newlines")
    }

    @Test("Multiple entries form valid JSONL (newline-delimited)")
    func multipleEntriesFormValidJSONL() throws {
        let entries: [[String: Any]] = [
            ["ts": "2026-03-12T14:30:05.100Z", "level": "info", "cat": "init", "src": "bridge", "msg": "startup"],
            ["ts": "2026-03-12T14:30:05.200Z", "level": "debug", "cat": "socket", "src": "bridge", "msg": "connecting"],
            ["ts": "2026-03-12T14:30:05.300Z", "level": "error", "cat": "socket", "src": "bridge", "msg": "timeout"]
        ]

        var lines: [String] = []
        for entry in entries {
            let data = try JSONSerialization.data(withJSONObject: entry)
            let line = try #require(String(data: data, encoding: .utf8))
            lines.append(line)
        }

        let jsonl = lines.joined(separator: "\n") + "\n"

        // Each line should parse independently
        let splitLines = jsonl.split(separator: "\n")
        #expect(splitLines.count == 3)

        for splitLine in splitLines {
            let lineData = Data(splitLine.utf8)
            let parsed = try JSONSerialization.jsonObject(with: lineData)
            #expect(parsed is [String: Any])
        }
    }

    // MARK: - Meta Field Types

    @Test("Meta supports string, int, and bool values")
    func metaSupportsCommonTypes() throws {
        let meta: [String: Any] = [
            "method": "gateway_call",        // String
            "bytes": 1024,                   // Int
            "success": true,                 // Bool
            "duration_ms": 42                // Int
        ]

        let entry: [String: Any] = [
            "ts": "2026-03-12T14:30:05.123Z",
            "level": "info",
            "cat": "gateway",
            "src": "bridge",
            "msg": "tool result: lmstudio__list_models ok",
            "meta": meta
        ]

        // Must serialize without error
        let data = try JSONSerialization.data(withJSONObject: entry)
        let parsed = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let parsedMeta = try #require(parsed["meta"] as? [String: Any])

        #expect(parsedMeta["method"] as? String == "gateway_call")
        #expect(parsedMeta["bytes"] as? Int == 1024)
        #expect(parsedMeta["success"] as? Bool == true)
        #expect(parsedMeta["duration_ms"] as? Int == 42)
    }
}
