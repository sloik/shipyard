import Foundation
import Testing
@testable import Shipyard

@Suite("SPEC-023: Localization String Catalog", .timeLimit(.minutes(1)))
struct SPEC023Tests {

    @Test("Catalog exists at spec path and is wired into app resources")
    func catalogExistsAndIsRegistered() throws {
        let catalogURL = repoRoot()
            .appendingPathComponent("Shipyard/Resources/Localizable.xcstrings")
        #expect(FileManager.default.fileExists(atPath: catalogURL.path))

        let project = try String(
            contentsOf: repoRoot().appendingPathComponent("Shipyard.xcodeproj/project.pbxproj"),
            encoding: .utf8
        )
        #expect(project.contains("Localizable.xcstrings in Resources"))
    }

    @Test("Every catalog key matches the three-segment schema")
    func catalogKeysMatchSchema() throws {
        let pattern = #"^[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+\.[a-z][a-zA-Z]+$"#
        let regex = try NSRegularExpression(pattern: pattern)
        let keys = try catalogStrings().keys.sorted()

        #expect(!keys.isEmpty)
        for key in keys {
            let range = NSRange(location: 0, length: key.utf16.count)
            let match = regex.firstMatch(in: key, options: [], range: range)
            #expect(match?.range == range, "Key does not match schema: \(key)")
        }
    }

    @Test("Catalog excludes log-only autostart strings")
    func catalogExcludesAutostartLogStrings() throws {
        let catalogText = try String(
            contentsOf: repoRoot().appendingPathComponent("Shipyard/Resources/Localizable.xcstrings"),
            encoding: .utf8
        )
        #expect(catalogText.contains("autostart") == false)
    }

    @Test("Views do not keep hardcoded Start or Stop literals")
    func viewsDoNotContainHardcodedStartStopLiterals() throws {
        let viewsURL = repoRoot().appendingPathComponent("Shipyard/Views")
        let fileURLs = try FileManager.default.contentsOfDirectory(
            at: viewsURL,
            includingPropertiesForKeys: nil
        ).filter { $0.pathExtension == "swift" }

        for fileURL in fileURLs {
            let contents = try String(contentsOf: fileURL, encoding: .utf8)
            #expect(contents.contains("\"Start\"") == false, "Hardcoded Start found in \(fileURL.lastPathComponent)")
            #expect(contents.contains("\"Stop\"") == false, "Hardcoded Stop found in \(fileURL.lastPathComponent)")
        }
    }

    @Test("Representative localized error descriptions resolve through the catalog")
    func localizedErrorDescriptionsResolveThroughCatalog() {
        #expect(ProcessManagerError.startFailed("boom").errorDescription == "Failed to start process: boom")
        #expect(ProcessManagerError.stopFailed("boom").errorDescription == "Failed to stop process: boom")
        #expect(ConfigError.invalidJSON("Unexpected token").errorDescription == "Invalid JSON: Unexpected token")

        let bridgeError = BridgeError.httpError("testMCP", 500, "HTTP request failed")
        #expect(bridgeError.errorDescription == "testMCP: HTTP 500 - HTTP request failed")

        let timeoutError = MCPBridgeError.timeout("my-mcp", "my_method", 10.5)
        #expect(timeoutError.errorDescription == "my-mcp did not respond to 'my_method' within 10s")
    }

    @Test("Catalog contains representative common and error keys")
    func catalogContainsRepresentativeKeys() throws {
        let keys = try Set(catalogStrings().keys)
        let requiredKeys: Set<String> = [
            "common.action.start",
            "common.action.stop",
            "servers.row.removedBadge",
            "error.process.startFailed",
            "error.bridge.httpError",
            "error.httpBridge.unsupportedResponseContentType"
        ]

        #expect(requiredKeys.isSubset(of: keys))
    }

    private func repoRoot() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func catalogStrings() throws -> [String: Any] {
        let catalogURL = repoRoot().appendingPathComponent("Shipyard/Resources/Localizable.xcstrings")
        let data = try Data(contentsOf: catalogURL)
        let object = try JSONSerialization.jsonObject(with: data)
        guard
            let json = object as? [String: Any],
            let strings = json["strings"] as? [String: Any]
        else {
            Issue.record("Failed to decode string catalog JSON")
            return [:]
        }
        return strings
    }
}
