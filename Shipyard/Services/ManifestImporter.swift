import Foundation
import os

private let manifestImportLog = Logger(subsystem: "com.shipyard.app", category: "ManifestImporter")

enum ManifestImportStatus: Sendable, Equatable {
    case pending(legacyCount: Int)
    case imported(imported: Int, skipped: Int, legacyCount: Int)
    case noLegacyFound
    case failed(legacyCount: Int, message: String)
}

struct ManifestImportRun: Sendable, Equatable {
    let status: ManifestImportStatus
    let importedNames: [String]
    let allowedLegacyPaths: Set<String>

    var manifestDiscoveryIsReadOnly: Bool {
        switch status {
        case .imported, .noLegacyFound:
            return true
        case .pending, .failed:
            return false
        }
    }
}

final class ManifestImporter {
    private struct Marker: Codable, Sendable {
        let importedAt: Date
        let imported: Int
        let skipped: Int
        let legacyCount: Int
    }

    private struct LegacyManifestRecord: Sendable {
        let manifest: MCPManifest
        let directory: URL

        var manifestFile: URL {
            directory.appendingPathComponent("manifest.json")
        }
    }

    private let discoveryRoot: URL
    private let mcpsConfigFile: URL
    private let markerFile: URL
    private let fileManager: FileManager

    init(
        discoveryRoot: URL = PathManager.shared.mcpDiscoveryRoot,
        mcpsConfigFile: URL = PathManager.shared.mcpsConfigFile,
        markerFile: URL = PathManager.shared.manifestImportMarkerFile,
        fileManager: FileManager = .default
    ) {
        self.discoveryRoot = discoveryRoot
        self.mcpsConfigFile = mcpsConfigFile
        self.markerFile = markerFile
        self.fileManager = fileManager
    }

    func runIfNeeded() async -> ManifestImportRun {
        let importedConfig = (try? MCPConfig.loadOrCreateDefault(at: mcpsConfigFile.path)) ?? MCPConfig(mcpServers: [:])
        let allowedLegacyPaths = Set(importedConfig.mcpServers.values.compactMap(\.migratedFrom))

        if fileManager.fileExists(atPath: markerFile.path) {
            let importedCount = importedConfig.mcpServers.values.filter { $0.migratedFrom != nil }.count
            if importedCount == 0 {
                return ManifestImportRun(
                    status: .noLegacyFound,
                    importedNames: [],
                    allowedLegacyPaths: allowedLegacyPaths
                )
            }

            return ManifestImportRun(
                status: .imported(imported: importedCount, skipped: 0, legacyCount: importedCount),
                importedNames: Array(importedConfig.mcpServers.keys).sorted(),
                allowedLegacyPaths: allowedLegacyPaths
            )
        }

        let manifests: [LegacyManifestRecord]
        do {
            manifests = try discoverLegacyManifests()
        } catch {
            return ManifestImportRun(
                status: .failed(legacyCount: 0, message: error.localizedDescription),
                importedNames: [],
                allowedLegacyPaths: allowedLegacyPaths
            )
        }

        if manifests.isEmpty {
            do {
                try writeMarker(imported: 0, skipped: 0, legacyCount: 0)
                return ManifestImportRun(status: .noLegacyFound, importedNames: [], allowedLegacyPaths: [])
            } catch {
                return ManifestImportRun(
                    status: .failed(legacyCount: 0, message: error.localizedDescription),
                    importedNames: [],
                    allowedLegacyPaths: []
                )
            }
        }

        do {
            let result = try importLegacyManifests(manifests, into: importedConfig)
            return ManifestImportRun(
                status: .imported(
                    imported: result.importedNames.count,
                    skipped: result.skippedCount,
                    legacyCount: manifests.count
                ),
                importedNames: result.importedNames,
                allowedLegacyPaths: result.allowedLegacyPaths
            )
        } catch {
            manifestImportLog.error("Manifest import failed: \(error.localizedDescription)")
            return ManifestImportRun(
                status: .failed(legacyCount: manifests.count, message: error.localizedDescription),
                importedNames: [],
                allowedLegacyPaths: allowedLegacyPaths
            )
        }
    }

    private func discoverLegacyManifests() throws -> [LegacyManifestRecord] {
        guard fileManager.fileExists(atPath: discoveryRoot.path) else {
            return []
        }

        let contents = try fileManager.contentsOfDirectory(
            at: discoveryRoot,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )

        var manifests: [LegacyManifestRecord] = []
        for item in contents {
            let values = try item.resourceValues(forKeys: [.isDirectoryKey])
            guard values.isDirectory == true else { continue }

            let manifestURL = item.appendingPathComponent("manifest.json")
            guard fileManager.fileExists(atPath: manifestURL.path) else { continue }

            do {
                let manifest = try MCPManifest.load(from: item)
                manifests.append(LegacyManifestRecord(manifest: manifest, directory: item))
            } catch {
                let path = manifestURL.path
                manifestImportLog.error("[Import] Failed unknown from \(path): \(error.localizedDescription)")
                throw error
            }
        }

        return manifests.sorted {
            $0.manifest.name.localizedCaseInsensitiveCompare($1.manifest.name) == .orderedAscending
        }
    }

    private func importLegacyManifests(
        _ manifests: [LegacyManifestRecord],
        into existingConfig: MCPConfig
    ) throws -> (importedNames: [String], skippedCount: Int, allowedLegacyPaths: Set<String>) {
        var mergedServers = existingConfig.mcpServers
        var existingNames = Set(mergedServers.keys.map { $0.lowercased() })
        var importedNames: [String] = []
        var skippedCount = 0

        for record in manifests {
            let name = record.manifest.name
            let manifestPath = record.manifestFile.path

            if existingNames.contains(name.lowercased()) {
                skippedCount += 1
                manifestImportLog.info("[Import] Skipped \(name) from \(manifestPath): already in mcps.json")
                continue
            }

            mergedServers[name] = MCPConfig.ServerEntry(manifest: record.manifest, directory: record.directory)
            existingNames.insert(name.lowercased())
            importedNames.append(name)
            manifestImportLog.info("[Import] Migrated \(name) from \(manifestPath)")
        }

        let mergedConfig = MCPConfig(mcpServers: mergedServers)
        try writeConfigAtomically(mergedConfig)
        try writeMarker(imported: importedNames.count, skipped: skippedCount, legacyCount: manifests.count)

        let allowedLegacyPaths = Set(mergedConfig.mcpServers.values.compactMap(\.migratedFrom))
        return (importedNames.sorted(), skippedCount, allowedLegacyPaths)
    }

    private func writeConfigAtomically(_ config: MCPConfig) throws {
        try fileManager.createDirectory(
            at: mcpsConfigFile.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        let tempURL = mcpsConfigFile
            .deletingLastPathComponent()
            .appendingPathComponent(".mcps-\(UUID().uuidString).tmp")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(config)

        do {
            try data.write(to: tempURL, options: .atomic)
            if fileManager.fileExists(atPath: mcpsConfigFile.path) {
                _ = try fileManager.replaceItemAt(mcpsConfigFile, withItemAt: tempURL)
            } else {
                try fileManager.moveItem(at: tempURL, to: mcpsConfigFile)
            }
        } catch {
            try? fileManager.removeItem(at: tempURL)
            throw error
        }
    }

    private func writeMarker(imported: Int, skipped: Int, legacyCount: Int) throws {
        try fileManager.createDirectory(
            at: markerFile.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )

        let marker = Marker(
            importedAt: Date(),
            imported: imported,
            skipped: skipped,
            legacyCount: legacyCount
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(marker)
        try data.write(to: markerFile, options: .atomic)
    }
}
