import Foundation
import Testing
@testable import Shipyard

@Suite("ManifestImporter", .timeLimit(.minutes(1)))
@MainActor
struct ManifestImporterTests {
    private func makeTempDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("shipyard-manifest-import-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func cleanup(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    private func writeManifest(
        root: URL,
        folderName: String,
        name: String,
        command: String = "python3",
        args: [String] = ["server.py"],
        env: [String: String]? = nil,
        envSecretKeys: [String]? = nil
    ) throws -> URL {
        let dir = root.appendingPathComponent(folderName, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        var envBlock = ""
        if let env {
            let data = try JSONSerialization.data(withJSONObject: env, options: [.sortedKeys])
            envBlock = ",\n  \"env\": \(String(decoding: data, as: UTF8.self))"
        }

        var envSecretKeysBlock = ""
        if let envSecretKeys {
            let data = try JSONSerialization.data(withJSONObject: envSecretKeys, options: [])
            envSecretKeysBlock = ",\n  \"env_secret_keys\": \(String(decoding: data, as: UTF8.self))"
        }

        let manifest = """
        {
          "name": "\(name)",
          "version": "1.0.0",
          "description": "Legacy \(name)",
          "transport": "stdio",
          "command": "\(command)",
          "args": \(try argsJSONArray(args))\(envBlock)\(envSecretKeysBlock)
        }
        """

        try manifest.write(
            to: dir.appendingPathComponent("manifest.json"),
            atomically: true,
            encoding: .utf8
        )
        return dir
    }

    private func argsJSONArray(_ args: [String]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: args, options: [])
        return String(decoding: data, as: UTF8.self)
    }

    @Test("Imports manifest MCPs into mcps.json with migratedFrom metadata")
    func importsLegacyManifestsIntoConfig() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configFile = temp.appendingPathComponent("config/mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)

        let alphaDir = try writeManifest(
            root: discoveryRoot,
            folderName: "alpha",
            name: "alpha",
            args: ["server.py", "--alpha"],
            env: ["ALPHA": "1"]
        )
        let betaDir = try writeManifest(
            root: discoveryRoot,
            folderName: "beta",
            name: "beta",
            command: "node",
            args: ["index.js"]
        )
        _ = try writeManifest(root: discoveryRoot, folderName: "gamma", name: "gamma", command: "uvx")

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        let run = await importer.runIfNeeded()

        guard case .imported(let imported, let skipped, let legacyCount) = run.status else {
            Issue.record("Expected successful import, got \(run.status)")
            return
        }

        #expect(imported == 3)
        #expect(skipped == 0)
        #expect(legacyCount == 3)
        #expect(FileManager.default.fileExists(atPath: markerFile.path))

        let config = try MCPConfig.load(from: configFile.path)
        let alpha = try #require(config.mcpServers["alpha"])
        #expect(alpha.command == "python3")
        #expect(alpha.args == ["server.py", "--alpha"])
        #expect(alpha.env?["ALPHA"] == "1")
        #expect(alpha.migratedFrom == alphaDir.path)

        let beta = try #require(config.mcpServers["beta"])
        #expect(beta.command == "node")
        #expect(beta.args == ["index.js"])
        #expect(beta.migratedFrom == betaDir.path)
    }

    @Test("Second run does not duplicate imported entries")
    func importIsIdempotent() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configFile = temp.appendingPathComponent("config/mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)
        _ = try writeManifest(root: discoveryRoot, folderName: "alpha", name: "alpha")

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        _ = await importer.runIfNeeded()
        let secondRun = await importer.runIfNeeded()

        let config = try MCPConfig.load(from: configFile.path)
        #expect(config.mcpServers.count == 1)
        guard case .imported(let imported, _, let legacyCount) = secondRun.status else {
            Issue.record("Expected imported status on second run, got \(secondRun.status)")
            return
        }
        #expect(imported == 1)
        #expect(legacyCount == 1)
    }

    @Test("Write failure leaves existing mcps.json untouched and marker absent")
    func writeFailureDoesNotMutateExistingConfig() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configDir = temp.appendingPathComponent("config", isDirectory: true)
        let configFile = configDir.appendingPathComponent("mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: configDir, withIntermediateDirectories: true)
        _ = try writeManifest(root: discoveryRoot, folderName: "alpha", name: "alpha")

        let original = """
        {
          "mcpServers": {
            "existing": {
              "command": "echo"
            }
          }
        }
        """
        try original.write(to: configFile, atomically: true, encoding: .utf8)

        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: configDir.path)
        defer {
            try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: configDir.path)
        }

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        let run = await importer.runIfNeeded()

        guard case .failed(let legacyCount, _) = run.status else {
            Issue.record("Expected failed status, got \(run.status)")
            return
        }
        #expect(legacyCount == 1)
        #expect(!FileManager.default.fileExists(atPath: markerFile.path))

        let config = try MCPConfig.load(from: configFile.path)
        #expect(config.mcpServers.keys.sorted() == ["existing"])
    }

    @Test("Registry ignores new manifest discovery after cutover")
    func registryIgnoresManifestDiscoveryAfterCutover() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)
        _ = try writeManifest(root: discoveryRoot, folderName: "legacy", name: "legacy")

        let registry = MCPRegistry(discoveryPath: discoveryRoot.path)
        registry.setManifestDiscoveryReadOnly(true)
        registry.setManifestImportStatus(.imported(imported: 1, skipped: 0, legacyCount: 1))

        try await registry.discover()
        #expect(registry.registeredServers.isEmpty)

        _ = try writeManifest(root: discoveryRoot, folderName: "new-one", name: "new-one")
        await registry.rescan()
        #expect(registry.registeredServers.isEmpty)
    }

    @Test("hear-me-say manifest imports the expected mcps.json entry shape")
    func importsHearMeSayManifestShape() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configFile = temp.appendingPathComponent("config/mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)

        let hearMeSayDir = try writeManifest(
            root: discoveryRoot,
            folderName: "hear-me-say",
            name: "hear-me-say",
            command: "python3",
            args: ["server.py"],
            env: ["PYTHONUNBUFFERED": "1"]
        )

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        let run = await importer.runIfNeeded()

        guard case .imported(let imported, let skipped, let legacyCount) = run.status else {
            Issue.record("Expected successful import, got \(run.status)")
            return
        }

        #expect(imported == 1)
        #expect(skipped == 0)
        #expect(legacyCount == 1)
        #expect(run.importedNames == ["hear-me-say"])

        let config = try MCPConfig.load(from: configFile.path)
        let entry = try #require(config.mcpServers["hear-me-say"])
        #expect(entry.transport == "stdio")
        #expect(entry.command == "python3")
        #expect(entry.args == ["server.py"])
        #expect(entry.cwd == hearMeSayDir.path)
        #expect(entry.env == ["PYTHONUNBUFFERED": "1"])
        #expect(entry.migratedFrom == hearMeSayDir.path)
    }

    @Test("lmac-run manifest imports the expected mcps.json entry shape")
    func importsLmacRunManifestShape() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configFile = temp.appendingPathComponent("config/mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)

        let lmacRunDir = try writeManifest(
            root: discoveryRoot,
            folderName: "lmac-run-mcp",
            name: "lmac-run",
            command: ".venv/bin/python",
            args: ["server.py"],
            env: ["PYTHONUNBUFFERED": "1"]
        )

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        let run = await importer.runIfNeeded()

        guard case .imported(let imported, let skipped, let legacyCount) = run.status else {
            Issue.record("Expected successful import, got \(run.status)")
            return
        }

        #expect(imported == 1)
        #expect(skipped == 0)
        #expect(legacyCount == 1)
        #expect(run.importedNames == ["lmac-run"])

        let config = try MCPConfig.load(from: configFile.path)
        let entry = try #require(config.mcpServers["lmac-run"])
        #expect(entry.transport == "stdio")
        #expect(entry.command == ".venv/bin/python")
        #expect(entry.args == ["server.py"])
        #expect(entry.cwd == lmacRunDir.path)
        #expect(entry.env == ["PYTHONUNBUFFERED": "1"])
        #expect(entry.migratedFrom == lmacRunDir.path)
    }

    @Test("lmstudio manifest imports the expected mcps.json entry shape")
    func importsLMStudioManifestShape() async throws {
        let temp = try makeTempDirectory()
        defer { cleanup(temp) }

        let discoveryRoot = temp.appendingPathComponent("mcp", isDirectory: true)
        let configFile = temp.appendingPathComponent("config/mcps.json")
        let markerFile = temp.appendingPathComponent("data/manifest-imported.json")
        try FileManager.default.createDirectory(at: discoveryRoot, withIntermediateDirectories: true)

        let lmstudioDir = try writeManifest(
            root: discoveryRoot,
            folderName: "lmstudio-mcp",
            name: "lmstudio",
            command: "python3",
            args: ["server.py"],
            env: [
                "PYTHONUNBUFFERED": "1",
                "LM_STUDIO_BASE": "http://localhost:1234",
                "LM_STUDIO_TIMEOUT": "120"
            ],
            envSecretKeys: ["LM_STUDIO_TOKEN"]
        )

        let importer = ManifestImporter(
            discoveryRoot: discoveryRoot,
            mcpsConfigFile: configFile,
            markerFile: markerFile
        )

        let run = await importer.runIfNeeded()

        guard case .imported(let imported, let skipped, let legacyCount) = run.status else {
            Issue.record("Expected successful import, got \(run.status)")
            return
        }

        #expect(imported == 1)
        #expect(skipped == 0)
        #expect(legacyCount == 1)
        #expect(run.importedNames == ["lmstudio"])

        let config = try MCPConfig.load(from: configFile.path)
        let entry = try #require(config.mcpServers["lmstudio"])
        #expect(entry.transport == "stdio")
        #expect(entry.command == "python3")
        #expect(entry.args == ["server.py"])
        #expect(entry.cwd == lmstudioDir.path)
        #expect(entry.env == [
            "PYTHONUNBUFFERED": "1",
            "LM_STUDIO_BASE": "http://localhost:1234",
            "LM_STUDIO_TIMEOUT": "120"
        ])
        #expect(entry.envSecretKeys == ["LM_STUDIO_TOKEN"])
        #expect(entry.migratedFrom == lmstudioDir.path)
    }
}
