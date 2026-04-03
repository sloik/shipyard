import Testing
import Foundation
@testable import Shipyard

@Suite("ConfigEditorSheet", .timeLimit(.minutes(1)))
struct ConfigEditorSheetTests {

    @Test("loadConfig: unescapes forward slashes on load")
    func loadConfigUnescapesSlashes() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-unescape-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        // Write a config with escaped slashes
        let escapedJSON = """
        {
          "mcpServers": {
            "python": {
              "command": "\\/opt\\/homebrew\\/bin\\/python3"
            }
          }
        }
        """

        try escapedJSON.data(using: .utf8)!.write(to: URL(fileURLWithPath: configPath))
        let loaded = try loadAndFormatConfig(from: configPath)

        #expect(loaded.contains("/opt/homebrew/bin/python3"))
        #expect(!loaded.contains("\\/opt"))
    }

    @Test("loadConfig: preserves already-clean JSON")
    func loadConfigPreservesCleanJSON() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-clean-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let cleanJSON = """
        {
          "mcpServers": {
            "server": {
              "command": "/usr/bin/python3"
            }
          }
        }
        """

        try cleanJSON.data(using: .utf8)!.write(to: URL(fileURLWithPath: configPath))
        let loaded = try loadAndFormatConfig(from: configPath)

        #expect(loaded.contains("/usr/bin/python3"))
    }

    @Test("loadConfig: falls back to raw content on malformed JSON")
    func loadConfigFallsBackOnMalformedJSON() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-malformed-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let malformedJSON = "{ broken json"
        try malformedJSON.data(using: .utf8)!.write(to: URL(fileURLWithPath: configPath))
        let loaded = try loadAndFormatConfig(from: configPath)

        #expect(loaded == malformedJSON)
    }

    @Test("saveConfig: writes clean JSON without escaped slashes")
    func saveConfigWritesCleanJSON() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-save-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let dict: [String: Any] = [
            "mcpServers": [
                "python": [
                    "command": "/opt/homebrew/bin/python3"
                ]
            ]
        ]

        try saveConfigFormatted(dict, to: configPath)
        let content = try String(contentsOfFile: configPath, encoding: .utf8)

        #expect(content.contains("/opt/homebrew/bin/python3"))
        #expect(!content.contains("\\/opt"))
    }

    @Test("saveConfig: adds trailing newline")
    func saveConfigAddTrailingNewline() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-newline-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let dict: [String: Any] = ["mcpServers": [:]]
        try saveConfigFormatted(dict, to: configPath)
        let content = try String(contentsOfFile: configPath, encoding: .utf8)

        #expect(content.hasSuffix("\n"))
    }

    @Test("saveConfig: uses sortedKeys for deterministic output")
    func saveConfigUsesSortedKeys() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-sorted-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let dict: [String: Any] = [
            "mcpServers": [
                "zebra": ["command": "z"],
                "alpha": ["command": "a"],
                "mike": ["command": "m"]
            ]
        ]

        try saveConfigFormatted(dict, to: configPath)
        let content = try String(contentsOfFile: configPath, encoding: .utf8)

        let alphaPos = content.range(of: "alpha")?.lowerBound
        let mikePos = content.range(of: "mike")?.lowerBound
        let zebraPos = content.range(of: "zebra")?.lowerBound

        #expect(alphaPos != nil && mikePos != nil && zebraPos != nil)
        if let alpha = alphaPos, let mike = mikePos, let zebra = zebraPos {
            #expect(alpha < mike && mike < zebra)
        }
    }

    @Test("roundTrip: idempotent formatting")
    func roundTripIdempotent() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-roundtrip-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let initial = """
        {
          "mcpServers": {
            "python": {
              "command": "\\/usr\\/bin\\/python3"
            }
          }
        }
        """

        try initial.data(using: .utf8)!.write(to: URL(fileURLWithPath: configPath))
        let loaded = try loadAndFormatConfig(from: configPath)

        let jsonData = loaded.data(using: .utf8)!
        let parsed = try JSONSerialization.jsonObject(with: jsonData) as? [String: Any]
        try saveConfigFormatted(parsed ?? [:], to: configPath)

        let reloaded = try loadAndFormatConfig(from: configPath)

        #expect(loaded == reloaded)
    }

    @Test("error: missing file throws")
    func loadConfigMissingFileThrows() throws {
        let nonExistentPath = "/tmp/nonexistent-\(UUID().uuidString).json"

        #expect(throws: Error.self) {
            let _ = try loadAndFormatConfig(from: nonExistentPath)
        }
    }

    @Test("saveConfig: produces valid JSON")
    func saveConfigProducesValidJSON() throws {
        let tempDir = FileManager.default.temporaryDirectory
        let configPath = tempDir.appendingPathComponent("test-valid-\(UUID().uuidString).json").path

        defer {
            try? FileManager.default.removeItem(atPath: configPath)
        }

        let dict: [String: Any] = [
            "mcpServers": [
                "test": [
                    "command": "/usr/bin/python3",
                    "args": ["server.py"]
                ]
            ]
        ]

        try saveConfigFormatted(dict, to: configPath)
        let content = try String(contentsOfFile: configPath, encoding: .utf8)
        let reparsed = try JSONSerialization.jsonObject(with: content.data(using: .utf8)!)

        #expect(reparsed is [String: Any])
    }

    private func loadAndFormatConfig(from path: String) throws -> String {
        let data = try Data(contentsOf: URL(fileURLWithPath: path))
        let content = try String(contentsOfFile: path, encoding: .utf8)

        if let jsonObject = try? JSONSerialization.jsonObject(with: data) {
            if let formatted = try? JSONSerialization.data(
                withJSONObject: jsonObject,
                options: [.prettyPrinted, .withoutEscapingSlashes, .sortedKeys]
            ) {
                return String(data: formatted, encoding: .utf8) ?? content
            }
        }

        return content
    }

    private func saveConfigFormatted(_ dict: [String: Any], to path: String) throws {
        let jsonData = try JSONSerialization.data(
            withJSONObject: dict,
            options: [.prettyPrinted, .withoutEscapingSlashes, .sortedKeys]
        )

        var jsonString = String(data: jsonData, encoding: .utf8) ?? ""
        if !jsonString.hasSuffix("\n") {
            jsonString.append("\n")
        }

        try jsonString.write(toFile: path, atomically: true, encoding: .utf8)
    }
}
