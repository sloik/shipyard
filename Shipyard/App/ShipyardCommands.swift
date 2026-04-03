import SwiftUI
import os
import AppKit
import UniformTypeIdentifiers

private let log = Logger(subsystem: "com.shipyard.app", category: "ShipyardCommands")

/// FocusedValue for the currently selected tab in the main window
struct SelectedTabKey: FocusedValueKey {
    typealias Value = Binding<NavigationTab>
}

extension FocusedValues {
    var selectedTab: Binding<NavigationTab>? {
        get { self[SelectedTabKey.self] }
        set { self[SelectedTabKey.self] = newValue }
    }
}

/// Commands for the main window — View, File, and Server menus
struct ShipyardCommands: Commands {
    @FocusedValue(\.selectedTab) var selectedTab
    let registry: MCPRegistry
    let processManager: ProcessManager
    let logStore: LogStore

    var body: some Commands {
        // MARK: - View Menu
        CommandMenu(L10n.string("commands.view.title")) {
            ForEach(NavigationTab.allCases) { tab in
                Button(action: { selectedTab?.wrappedValue = tab }) {
                    Text(L10n.string(tab.titleKey))
                }
                .keyboardShortcut(tab.shortcutKey, modifiers: .command)
                .disabled(selectedTab == nil)
            }

            Divider()

            Button(action: refreshServers) {
                Text(L10n.string("common.action.refresh"))
            }
            .keyboardShortcut("r", modifiers: .command)
        }

        // MARK: - File Menu
        CommandMenu(L10n.string("commands.file.title")) {
            Button(action: revealConfigInFinder) {
                Text(L10n.string("common.action.revealConfigInFinder"))
            }
            .keyboardShortcut("c", modifiers: [.command, .shift])

            Button(action: revealLogsInFinder) {
                Text(L10n.string("common.action.revealLogsInFinder"))
            }
            .keyboardShortcut("l", modifiers: [.command, .shift])

            Divider()

            Button(action: exportLogs) {
                Text(L10n.string("common.action.exportLogs"))
            }
            .keyboardShortcut("e", modifiers: .command)
        }

        // MARK: - Server Menu
        CommandMenu(L10n.string("commands.server.title")) {
            Button(action: startAllServers) {
                Text(L10n.string("commands.server.startAllButton"))
            }
            .keyboardShortcut("s", modifiers: [.command, .shift])

            Button(action: stopAllServers) {
                Text(L10n.string("commands.server.stopAllButton"))
            }
            .keyboardShortcut("x", modifiers: [.command, .shift])

            Divider()

            Button(action: refreshServerStatus) {
                Text(L10n.string("commands.server.refreshStatusButton"))
            }
        }
    }

    // MARK: - View Menu Actions

    private func refreshServers() {
        Task {
            do {
                try await registry.discover()
                await processManager.syncServers(from: registry)
                log.info("Servers refreshed from View menu")
            } catch {
                log.error("Discovery failed: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - File Menu Actions

    private func revealConfigInFinder() {
        // Use default target (Claude Desktop)
        let configPath = "~/.config/claude_desktop_config.json"
        let expandedPath = (configPath as NSString).expandingTildeInPath
        let parentDir = (expandedPath as NSString).deletingLastPathComponent

        if FileManager.default.fileExists(atPath: expandedPath) {
            NSWorkspace.shared.selectFile(expandedPath, inFileViewerRootedAtPath: parentDir)
        } else {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: parentDir)
        }

        log.info("Revealed config in Finder")
    }

    private func revealLogsInFinder() {
        let logsDir = PathManager.shared.logsDirectory.path

        if FileManager.default.fileExists(atPath: logsDir) {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: logsDir)
        } else {
            try? FileManager.default.createDirectory(atPath: logsDir, withIntermediateDirectories: true)
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: logsDir)
        }

        log.info("Revealed logs in Finder")
    }

    private func exportLogs() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType.jsonl]
        let dateStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd-HHmmss"; return f.string(from: Date()) }()
        panel.nameFieldStringValue = "shipyard-logs-\(dateStr).jsonl"
        panel.canCreateDirectories = true

        if panel.runModal() == .OK, let url = panel.url {
            do {
                let jsonlData = logStore.filteredEntries
                    .map { entry in
                        [
                            "timestamp": entry.timestamp.timeIntervalSince1970,
                            "level": entry.logLevel.rawValue,
                            "cat": entry.cat,
                            "msg": entry.msg,
                            "src": entry.src,
                            "meta": entry.meta ?? [:]
                        ] as [String: Any]
                    }

                let jsonlLines = try jsonlData.map { entry -> String in
                    let jsonData = try JSONSerialization.data(withJSONObject: entry)
                    return String(data: jsonData, encoding: .utf8) ?? ""
                }

                let content = jsonlLines.joined(separator: "\n")
                try content.write(to: url, atomically: true, encoding: .utf8)

                // Reveal in Finder
                let parentDir = (url.path as NSString).deletingLastPathComponent
                NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: parentDir)

                log.info("Exported logs to \(url.path)")
            } catch {
                log.error("Failed to export logs: \(error.localizedDescription)")
            }
        }
    }

    // MARK: - Server Menu Actions

    private func startAllServers() {
        Task {
            for server in registry.registeredServers where server.state != .running && server.state != .starting {
                do {
                    try await processManager.start(server)
                } catch {
                    server.state = .error(error.localizedDescription)
                    log.error("Failed to start '\(server.manifest.name)': \(error.localizedDescription)")
                }
            }
            log.info("Started all servers from Server menu")
        }
    }

    private func stopAllServers() {
        Task {
            for server in registry.registeredServers where server.state == .running {
                await processManager.stop(server)
            }
            log.info("Stopped all servers from Server menu")
        }
    }

    private func refreshServerStatus() {
        Task {
            do {
                try await registry.discover()
                await processManager.syncServers(from: registry)
                log.info("Server status refreshed from Server menu")
            } catch {
                log.error("Server status refresh failed: \(error.localizedDescription)")
            }
        }
    }
}
