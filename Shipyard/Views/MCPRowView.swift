import AppKit
import SwiftUI

// MARK: - Shipyard Color Palette

/// Semantic colors that adapt to light/dark mode using system NSColor variants.
enum ShipyardColors {
    /// Server states
    static let running = Color(nsColor: .systemGreen)
    static let idle = Color(nsColor: .systemGray)
    static let error = Color(nsColor: .systemRed)
    static let transition = Color(nsColor: .systemYellow)

    /// Semantic accents
    static let warning = Color(nsColor: .systemOrange)
    static let info = Color(nsColor: .systemBlue)
}

struct MCPRowLifecycleControlVisibility {
    let showSection: Bool
    let showStart: Bool
    let showStop: Bool
    let showRestart: Bool

    static func resolve(
        isDisabled: Bool,
        source: MCPSource,
        isBuiltin: Bool,
        isRunning: Bool,
        hasStart: Bool,
        hasStop: Bool,
        hasRestart: Bool
    ) -> MCPRowLifecycleControlVisibility {
        let showSection = !isDisabled && (source != .synthetic || isBuiltin)
        guard showSection else {
            return .init(showSection: false, showStart: false, showStop: false, showRestart: false)
        }

        if isRunning {
            return .init(
                showSection: true,
                showStart: false,
                showStop: !isBuiltin && hasStop,
                showRestart: hasRestart
            )
        }

        return .init(
            showSection: true,
            showStart: !isBuiltin && hasStart,
            showStop: false,
            showRestart: false
        )
    }
}

struct MCPRowView: View {
    let server: MCPServer
    var onStart: (() -> Void)? = nil
    var onStop: (() -> Void)? = nil
    var onRestart: (() -> Void)? = nil
    @State private var showConfigEditor = false

    var body: some View {
        let lifecycleControls = MCPRowLifecycleControlVisibility.resolve(
            isDisabled: server.disabled,
            source: server.source,
            isBuiltin: server.isBuiltin,
            isRunning: server.state == .running,
            hasStart: onStart != nil,
            hasStop: onStop != nil,
            hasRestart: onRestart != nil
        )

        HStack(spacing: 10) {
            // Status indicator
            if server.state == .starting || server.state == .stopping {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 8, height: 8)
            } else {
                Circle()
                    .fill(statusColor)
                    .frame(width: 8, height: 8)
                    .accessibilityLabel("Status indicator")
                    .accessibilityValue(stateLabel)
            }

            // Server info
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(server.manifest.name)
                        .font(.body)
                        .fontWeight(.medium)

                    // Source badge (config vs manifest) — only for config-sourced MCPs
                    if server.source == .config {
                        Text("JSON")
                            .font(.system(size: 9, weight: .medium))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 2)
                            .background(ShipyardColors.info.opacity(0.12))
                            .foregroundStyle(ShipyardColors.info)
                            .cornerRadius(3)
                            .fixedSize()
                    }

                    if server.isLegacyMigrated {
                        Text("LEGACY")
                            .font(.system(size: 9, weight: .medium))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 2)
                            .background(ShipyardColors.warning.opacity(0.14))
                            .foregroundStyle(ShipyardColors.warning)
                            .cornerRadius(3)
                            .fixedSize()
                    }

                    if server.isPendingConfigRemoval {
                        Text("REMOVED")
                            .font(.system(size: 9, weight: .medium))
                            .padding(.horizontal, 4)
                            .padding(.vertical, 2)
                            .background(ShipyardColors.warning.opacity(0.14))
                            .foregroundStyle(ShipyardColors.warning)
                            .cornerRadius(3)
                            .fixedSize()
                    }

                    // Disabled badge
                    if server.disabled {
                        Label("Disabled", systemImage: "xmark.circle.fill")
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.gray.opacity(0.1))
                            .foregroundStyle(.secondary)
                            .cornerRadius(4)
                    }
                }
                
                Text(server.manifest.description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)

                if let migratedFrom = server.migratedFrom {
                    Label("Legacy manifest backup: \(migratedFrom)/manifest.json", systemImage: "archivebox")
                        .font(.caption2)
                        .foregroundStyle(ShipyardColors.warning)
                        .lineLimit(2)
                }

                // Error message display
                if case .error(let message) = server.state {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(ShipyardColors.error)
                        .lineLimit(2)
                }

                if server.isPendingConfigRemoval {
                    Label("Removed from mcps.json. Stop to finish removal.", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .foregroundStyle(ShipyardColors.warning)
                        .lineLimit(2)
                }

                // Process stats and indicators (only when running)
                if server.state == .running {
                    HStack(spacing: 8) {
                        // HTTP indicator or process stats
                        if server.isHTTP {
                            Label("HTTP", systemImage: "network")
                                .font(.caption2)
                                .foregroundStyle(ShipyardColors.info)
                        } else if let stats = server.processStats {
                            Text("PID: \(stats.pid)")
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)

                            Text("\(String(format: "%.1f", stats.memoryMB)) MB")
                                .font(.caption2.monospaced())
                                .foregroundStyle(.secondary)
                        }

                        // Health status indicator (Phase 3)
                        if case .unhealthy(let reason) = server.healthStatus {
                            Label(reason, systemImage: "exclamationmark.circle.fill")
                                .font(.caption2)
                                .foregroundStyle(ShipyardColors.warning)
                                .lineLimit(2)
                                .help("Health check failed: \(reason)")
                        }

                        // Restart count indicator (Phase 3)
                        if server.restartCount > 0 {
                            Label("\(server.restartCount) restart\(server.restartCount == 1 ? "" : "s")", systemImage: "arrow.clockwise")
                                .font(.caption2)
                                .foregroundStyle(ShipyardColors.info)
                        }
                    }
                }

                // Dependency warnings (shown regardless of state)
                let unsatisfiedCount = server.dependencyResults.filter { !$0.satisfied }.count
                if unsatisfiedCount > 0 {
                    Label("\(unsatisfiedCount) dep issue\(unsatisfiedCount == 1 ? "" : "s")", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption2)
                        .foregroundStyle(ShipyardColors.warning)
                        .help(server.dependencyResults.filter { !$0.satisfied }.map(\.name).joined(separator: ", "))
                        .contextMenu {
                            Button("Copy Dependency Report") {
                                let text = formatDependencyReport()
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(text, forType: .string)
                            }
                        }
                }
            }

            Spacer()
            
            // State label
            Text(stateLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.trailing, 4)
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Double-click to view server details and logs")
        .contextMenu {
            if lifecycleControls.showSection {
                if lifecycleControls.showStop, let onStop {
                    Button(action: onStop) {
                        Label("Stop", systemImage: "stop.fill")
                    }
                }
                if lifecycleControls.showRestart, let onRestart {
                    Button(action: onRestart) {
                        Label("Restart", systemImage: "arrow.clockwise")
                    }
                    .disabled(server.isPendingConfigRemoval)
                }
                if lifecycleControls.showStart, let onStart {
                    Button(action: onStart) {
                        Label("Start", systemImage: "play.fill")
                    }
                }
                Divider()
            }

            // Config-sourced actions
            if server.source == .config {
                Button {
                    showConfigEditor = true
                } label: {
                    Label("Edit in Config…", systemImage: "square.and.pencil")
                }

                Button(action: { revealConfigInFinder() }) {
                    Label("Reveal Config in Finder", systemImage: "doc.text.magnifyingglass")
                }

                Divider()
            }

            Button(action: { revealLogInFinder() }) {
                Label("Reveal Log in Finder", systemImage: "doc.text.magnifyingglass")
            }
            Button(action: { openLogsFolder() }) {
                Label("Open Logs Folder", systemImage: "folder")
            }
        }
        .sheet(isPresented: $showConfigEditor) {
            ConfigEditorSheet(
                serverName: server.manifest.name,
                isPresented: $showConfigEditor
            )
        }
    }
    
    // MARK: - Computed Properties
    
    private var statusColor: Color {
        switch server.state {
        case .running:
            return ShipyardColors.running
        case .idle:
            return ShipyardColors.idle
        case .error:
            return ShipyardColors.error
        case .starting, .stopping:
            return ShipyardColors.transition
        }
    }
    
    private func formatDependencyReport() -> String {
        var lines: [String] = []
        lines.append("Shipyard Dependency Report: \(server.manifest.name)")
        lines.append("Command: \(server.manifest.command) \(server.manifest.args.joined(separator: " "))")
        if let runtime = server.manifest.dependencies?.runtime {
            lines.append("Runtime: \(runtime)")
        }
        lines.append("")
        for dep in server.dependencyResults {
            let status = dep.satisfied ? "✅" : "❌"
            var line = "  \(status) \(dep.name): \(dep.message)"
            if let found = dep.found {
                line += " (found: \(found))"
            }
            line += " (required: \(dep.required))"
            lines.append(line)
        }
        return lines.joined(separator: "\n")
    }

    private func revealLogInFinder() {
        let logDir = PathManager.shared.mcpLogDirectory(for: server.manifest.name)
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"
        let todayFile = logDir.appendingPathComponent("\(dateFormatter.string(from: Date())).log")
        if FileManager.default.fileExists(atPath: todayFile.path) {
            NSWorkspace.shared.activateFileViewerSelecting([todayFile])
        } else {
            NSWorkspace.shared.open(logDir)
        }
    }

    private func openLogsFolder() {
        NSWorkspace.shared.open(PathManager.shared.logsDirectory)
    }

    private func revealConfigInFinder() {
        let url = URL(fileURLWithPath: MCPConfig.defaultPath)
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    private var stateLabel: String {
        switch server.state {
        case .running:
            return "Running"
        case .idle:
            return "Idle"
        case .error:
            return "Error"
        case .starting:
            return "Starting"
        case .stopping:
            return "Stopping"
        }
    }
}

// Preview disabled due to compiler limitations with @Observable in macOS-only builds
// To test, run the app and check the server list in the main window
