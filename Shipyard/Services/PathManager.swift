import Foundation

struct PathManager: Sendable {
    enum Profile: String, Sendable {
        case development
        case installed
        case homebrew
    }

    struct Overrides: Sendable {
        var profile: Profile?
        var homeDirectory: URL?
        var projectRootDirectory: URL?
        var developmentRootDirectory: URL?
        var stableRootDirectory: URL?
        var bridgeSourceBinary: URL?
        var homebrewPrefix: URL?

        init(
            profile: Profile? = nil,
            homeDirectory: URL? = nil,
            projectRootDirectory: URL? = nil,
            developmentRootDirectory: URL? = nil,
            stableRootDirectory: URL? = nil,
            bridgeSourceBinary: URL? = nil,
            homebrewPrefix: URL? = nil
        ) {
            self.profile = profile
            self.homeDirectory = homeDirectory
            self.projectRootDirectory = projectRootDirectory
            self.developmentRootDirectory = developmentRootDirectory
            self.stableRootDirectory = stableRootDirectory
            self.bridgeSourceBinary = bridgeSourceBinary
            self.homebrewPrefix = homebrewPrefix
        }
    }

    struct SetupResult: Sendable {
        let createdDirectories: [URL]
        let copiedBridgeBinary: Bool
        let bridgeSourceBinary: URL?
        let bridgeInstalledBinary: URL
    }

    enum SetupError: LocalizedError {
        case bridgeSourceMissing(target: String)

        var errorDescription: String? {
            switch self {
            case .bridgeSourceMissing(let target):
                return "ShipyardBridge source binary not found for installation target \(target)"
            }
        }
    }

    static var shared: PathManager {
        PathManager()
    }

    private let environment: [String: String]
    private let overrides: Overrides
    private let bundleURL: URL?

    init(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        overrides: Overrides = Overrides(),
        bundleURL: URL? = Bundle.main.bundleURL
    ) {
        self.environment = environment
        self.overrides = overrides
        self.bundleURL = bundleURL
    }

    var profile: Profile {
        if let override = overrides.profile {
            return override
        }

        if let raw = sanitizedPathValue(environment["SHIPYARD_PATH_PROFILE"]),
           let profile = Profile(rawValue: raw.lowercased()) {
            return profile
        }

        #if DEBUG
        return .development
        #else
        return inferredReleaseProfile
        #endif
    }

    var homeDirectory: URL {
        if let override = overrides.homeDirectory {
            return override
        }

        if let override = sanitizedPathValue(environment["SHIPYARD_HOME"]) {
            return URL(fileURLWithPath: override, isDirectory: true)
        }

        return FileManager.default.homeDirectoryForCurrentUser
    }

    var projectRootDirectory: URL {
        if let override = overrides.projectRootDirectory {
            return override
        }

        if let override = sanitizedPathValue(environment["SHIPYARD_PROJECT_ROOT"]) {
            return URL(fileURLWithPath: override, isDirectory: true)
        }

        return URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    var rootDirectory: URL {
        switch profile {
        case .development:
            if let override = overrides.developmentRootDirectory {
                return override
            }
            if let override = sanitizedPathValue(environment["SHIPYARD_DEV_ROOT"]) {
                return URL(fileURLWithPath: override, isDirectory: true)
            }
            return projectRootDirectory.appendingPathComponent(".shipyard-dev", isDirectory: true)

        case .installed, .homebrew:
            if let override = overrides.stableRootDirectory {
                return override
            }
            if let override = sanitizedPathValue(environment["SHIPYARD_ROOT_DIR"]) {
                return URL(fileURLWithPath: override, isDirectory: true)
            }
            return homeDirectory.appendingPathComponent(".shipyard", isDirectory: true)
        }
    }

    var binDirectory: URL {
        rootDirectory.appendingPathComponent("bin", isDirectory: true)
    }

    var configDirectory: URL {
        rootDirectory.appendingPathComponent("config", isDirectory: true)
    }

    var logsDirectory: URL {
        rootDirectory.appendingPathComponent("logs", isDirectory: true)
    }

    var dataDirectory: URL {
        rootDirectory.appendingPathComponent("data", isDirectory: true)
    }

    var mcpLogsDirectory: URL {
        logsDirectory.appendingPathComponent("mcp", isDirectory: true)
    }

    var socketFile: URL {
        dataDirectory.appendingPathComponent("shipyard.sock")
    }

    var appLogFile: URL {
        logsDirectory.appendingPathComponent("app.jsonl")
    }

    var bridgeLogFile: URL {
        logsDirectory.appendingPathComponent("bridge.jsonl")
    }

    var startupProfileFile: URL {
        dataDirectory.appendingPathComponent("startup-profile.json")
    }

    var manifestImportMarkerFile: URL {
        dataDirectory.appendingPathComponent("manifest-imported.json")
    }

    var manifestMigrationLogFile: URL {
        dataDirectory.appendingPathComponent("manifest-migration-log.json")
    }

    var mcpsConfigFile: URL {
        configDirectory.appendingPathComponent("mcps.json")
    }

    var bridgeBinary: URL {
        binDirectory.appendingPathComponent("ShipyardBridge")
    }

    var mcpDiscoveryRoot: URL {
        switch profile {
        case .development:
            return projectRootDirectory.deletingLastPathComponent()
        case .installed, .homebrew:
            return rootDirectory.appendingPathComponent("mcp", isDirectory: true)
        }
    }

    var shipyardMCPScript: URL {
        switch profile {
        case .development:
            return mcpDiscoveryRoot
                .appendingPathComponent("shipyard-mcp", isDirectory: true)
                .appendingPathComponent("server.py")
        case .installed, .homebrew:
            return rootDirectory
                .appendingPathComponent("shipyard-mcp", isDirectory: true)
                .appendingPathComponent("server.py")
        }
    }

    func mcpLogDirectory(for serverName: String) -> URL {
        mcpLogsDirectory.appendingPathComponent(serverName, isDirectory: true)
    }

    func bridgeSourceBinary(fileManager: FileManager = .default) -> URL? {
        if let override = overrides.bridgeSourceBinary {
            return override
        }

        if let override = sanitizedPathValue(environment["SHIPYARD_BRIDGE_SOURCE"]) {
            return URL(fileURLWithPath: override)
        }

        let candidates: [URL] = {
            switch profile {
            case .development:
                return developmentBridgeCandidates
            case .installed:
                return installedBridgeCandidates
            case .homebrew:
                return homebrewBridgeCandidates
            }
        }()

        return candidates.first(where: { fileManager.fileExists(atPath: $0.path) && $0.path != bridgeBinary.path })
    }

    @discardableResult
    func prepareRuntimeLayout(fileManager: FileManager = .default) throws -> SetupResult {
        let directories = [rootDirectory, binDirectory, configDirectory, logsDirectory, mcpLogsDirectory, dataDirectory]
        var createdDirectories: [URL] = []

        for directory in directories {
            if !fileManager.fileExists(atPath: directory.path) {
                try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
                createdDirectories.append(directory)
            }
        }

        var copiedBridgeBinary = false
        let targetBinary = bridgeBinary
        let sourceBinary = bridgeSourceBinary(fileManager: fileManager)

        if let sourceBinary {
            let needsCopy = !fileManager.fileExists(atPath: targetBinary.path)
                || !fileManager.contentsEqual(atPath: sourceBinary.path, andPath: targetBinary.path)

            if needsCopy {
                if fileManager.fileExists(atPath: targetBinary.path) {
                    try fileManager.removeItem(at: targetBinary)
                }
                try fileManager.copyItem(at: sourceBinary, to: targetBinary)
                copiedBridgeBinary = true
            }

            try fileManager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: targetBinary.path)
        } else if !fileManager.fileExists(atPath: targetBinary.path) {
            throw SetupError.bridgeSourceMissing(target: targetBinary.path)
        }

        return SetupResult(
            createdDirectories: createdDirectories,
            copiedBridgeBinary: copiedBridgeBinary,
            bridgeSourceBinary: sourceBinary,
            bridgeInstalledBinary: targetBinary
        )
    }

    private var inferredReleaseProfile: Profile {
        if let bundlePath = bundleURL?.path,
           bundlePath.contains("/Cellar/") || bundlePath.contains("/Homebrew/") {
            return .homebrew
        }
        return .installed
    }

    private var developmentBridgeCandidates: [URL] {
        var candidates: [URL] = []

        if let bundleURL {
            candidates.append(bundleURL.deletingLastPathComponent().appendingPathComponent("ShipyardBridge"))
            candidates.append(bundleURL.appendingPathComponent("Contents/Helpers/ShipyardBridge"))
            candidates.append(bundleURL.appendingPathComponent("Contents/Resources/ShipyardBridge"))
        }

        candidates.append(projectRootDirectory.appendingPathComponent(".build/debug/ShipyardBridge"))
        candidates.append(homeDirectory.appendingPathComponent(".shipyard/bin/ShipyardBridge"))
        return candidates
    }

    private var installedBridgeCandidates: [URL] {
        var candidates: [URL] = []

        if let bundleURL {
            candidates.append(bundleURL.appendingPathComponent("Contents/Helpers/ShipyardBridge"))
            candidates.append(bundleURL.appendingPathComponent("Contents/Resources/ShipyardBridge"))
            candidates.append(bundleURL.appendingPathComponent("Contents/MacOS/ShipyardBridge"))
        }

        candidates.append(homeDirectory.appendingPathComponent(".shipyard/bin/ShipyardBridge"))
        return candidates
    }

    private var homebrewBridgeCandidates: [URL] {
        let prefix = overrides.homebrewPrefix
            ?? sanitizedPathValue(environment["HOMEBREW_PREFIX"]).map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? URL(fileURLWithPath: "/opt/homebrew", isDirectory: true)

        return [
            prefix.appendingPathComponent("opt/shipyard/bin/ShipyardBridge"),
            URL(fileURLWithPath: "/opt/homebrew/opt/shipyard/bin/ShipyardBridge"),
            URL(fileURLWithPath: "/usr/local/opt/shipyard/bin/ShipyardBridge")
        ]
    }

    private func sanitizedPathValue(_ rawValue: String?) -> String? {
        guard let rawValue else { return nil }
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return NSString(string: trimmed).expandingTildeInPath
    }
}
