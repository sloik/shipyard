import Testing
import Foundation
@testable import Shipyard

@Suite("PathManager")
struct PathManagerTests {
    private func makeTempDirectory() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("shipyard-paths-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func cleanup(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    @Test("Installed profile centralizes config, logs, socket, and bridge paths under ~/.shipyard")
    func installedProfilePaths() throws {
        let home = try makeTempDirectory()
        defer { cleanup(home) }

        let paths = PathManager(
            environment: [:],
            overrides: .init(profile: .installed, homeDirectory: home)
        )

        #expect(paths.rootDirectory == home.appendingPathComponent(".shipyard", isDirectory: true))
        #expect(paths.configDirectory == home.appendingPathComponent(".shipyard/config", isDirectory: true))
        #expect(paths.logsDirectory == home.appendingPathComponent(".shipyard/logs", isDirectory: true))
        #expect(paths.dataDirectory == home.appendingPathComponent(".shipyard/data", isDirectory: true))
        #expect(paths.socketFile == home.appendingPathComponent(".shipyard/data/shipyard.sock"))
        #expect(paths.bridgeBinary == home.appendingPathComponent(".shipyard/bin/ShipyardBridge"))
        #expect(paths.mcpsConfigFile == home.appendingPathComponent(".shipyard/config/mcps.json"))
    }

    @Test("Development profile keeps user-facing paths in-tree and discovery at the sibling MCP root")
    func developmentProfilePaths() throws {
        let projectRoot = try makeTempDirectory()
        defer { cleanup(projectRoot) }

        let paths = PathManager(
            environment: [:],
            overrides: .init(profile: .development, projectRootDirectory: projectRoot)
        )

        #expect(paths.rootDirectory == projectRoot.appendingPathComponent(".shipyard-dev", isDirectory: true))
        #expect(paths.mcpDiscoveryRoot == projectRoot.deletingLastPathComponent())
        #expect(paths.shipyardMCPScript == projectRoot.deletingLastPathComponent().appendingPathComponent("shipyard-mcp/server.py"))
    }

    @Test("Environment profile override changes all derived paths consistently")
    func environmentProfileOverride() throws {
        let home = try makeTempDirectory()
        let projectRoot = try makeTempDirectory()
        defer {
            cleanup(home)
            cleanup(projectRoot)
        }

        let paths = PathManager(
            environment: ["SHIPYARD_PATH_PROFILE": "development"],
            overrides: .init(homeDirectory: home, projectRootDirectory: projectRoot)
        )

        #expect(paths.profile == .development)
        #expect(paths.rootDirectory == projectRoot.appendingPathComponent(".shipyard-dev", isDirectory: true))
        #expect(paths.mcpsConfigFile.path.contains(".shipyard-dev/config/mcps.json"))
        #expect(paths.socketFile.path.contains(".shipyard-dev/data/shipyard.sock"))
    }

    @Test("Custom overrides allow fully isolated test paths")
    func customOverrides() throws {
        let home = try makeTempDirectory()
        let projectRoot = try makeTempDirectory()
        let customRoot = try makeTempDirectory()
        let bridgeSource = customRoot.appendingPathComponent("ShipyardBridge-source")
        defer {
            cleanup(home)
            cleanup(projectRoot)
            cleanup(customRoot)
        }

        try "bridge".write(to: bridgeSource, atomically: true, encoding: .utf8)

        let paths = PathManager(
            environment: [:],
            overrides: .init(
                profile: .installed,
                homeDirectory: home,
                projectRootDirectory: projectRoot,
                stableRootDirectory: customRoot,
                bridgeSourceBinary: bridgeSource
            )
        )

        #expect(paths.rootDirectory == customRoot)
        #expect(paths.bridgeSourceBinary() == bridgeSource)
        #expect(paths.bridgeBinary == customRoot.appendingPathComponent("bin/ShipyardBridge"))
    }

    @Test("prepareRuntimeLayout creates the directory tree and copies the bridge binary once")
    func prepareRuntimeLayoutCopiesBinaryOnce() throws {
        let home = try makeTempDirectory()
        let projectRoot = try makeTempDirectory()
        let sourceRoot = try makeTempDirectory()
        let sourceBinary = sourceRoot.appendingPathComponent("ShipyardBridge")
        defer {
            cleanup(home)
            cleanup(projectRoot)
            cleanup(sourceRoot)
        }

        try "#!/bin/sh\necho bridge\n".write(to: sourceBinary, atomically: true, encoding: .utf8)

        let paths = PathManager(
            environment: [:],
            overrides: .init(
                profile: .installed,
                homeDirectory: home,
                projectRootDirectory: projectRoot,
                bridgeSourceBinary: sourceBinary
            )
        )

        let first = try paths.prepareRuntimeLayout()
        #expect(first.createdDirectories.count >= 5)
        #expect(first.copiedBridgeBinary == true)
        #expect(FileManager.default.fileExists(atPath: paths.bridgeBinary.path))
        #expect(FileManager.default.fileExists(atPath: paths.configDirectory.path))
        #expect(FileManager.default.fileExists(atPath: paths.logsDirectory.path))
        #expect(FileManager.default.fileExists(atPath: paths.dataDirectory.path))

        let attributes = try FileManager.default.attributesOfItem(atPath: paths.bridgeBinary.path)
        let permissions = try #require(attributes[.posixPermissions] as? NSNumber)
        #expect((permissions.intValue & 0o111) != 0)

        let second = try paths.prepareRuntimeLayout()
        #expect(second.copiedBridgeBinary == false)
    }
}
