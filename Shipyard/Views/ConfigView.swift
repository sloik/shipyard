import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ConfigView")

/// Config generation view — shows generated mcpServers JSON with copy/diff functionality.
struct ConfigView: View {
    @Environment(MCPRegistry.self) private var registry
    let keychainManager: KeychainManager

    @State private var selectedTarget: ConfigGenerator.ConfigTarget = .claudeDesktop
    @State private var includeSecrets = false
    @State private var generatedConfig = ""
    @State private var showDiff = false
    @State private var configDiff: ConfigDiff?
    @State private var copied = false

    private var configGenerator: ConfigGenerator {
        ConfigGenerator(keychainManager: keychainManager)
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header with controls
            HStack(spacing: 12) {
                Text(L10n.string("config.header.title"))
                    .font(.headline)

                Spacer()

                Text(L10n.string("config.header.targetLabel"))
                    .font(.callout)
                    .foregroundStyle(.secondary)

                Picker("Target", selection: $selectedTarget) {
                    ForEach(ConfigGenerator.ConfigTarget.allCases) { target in
                        Text(target.rawValue).tag(target)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 280)

                Toggle(L10n.string("config.header.includeSecretsToggle"), isOn: $includeSecrets)
                    .help(L10n.string("config.header.includeSecretsHelp"))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Divider()

            // Toolbar
            HStack(spacing: 8) {
                Button(action: generateConfig) {
                    Label(L10n.string("common.action.generate"), systemImage: "arrow.clockwise")
                }
                .help(L10n.string("config.toolbar.generateHelp"))

                Button(action: copyToClipboard) {
                    Label(
                        L10n.string(copied ? "common.state.copied" : "common.action.copy"),
                        systemImage: copied ? "checkmark" : "doc.on.doc"
                    )
                }
                .help(L10n.string("config.toolbar.copyHelp"))
                .disabled(generatedConfig.isEmpty)

                Button(action: showConfigDiff) {
                    Label(L10n.string("common.action.diff"), systemImage: "arrow.left.arrow.right")
                }
                .help(L10n.string("config.toolbar.diffHelp"))

                Spacer()

                HStack(spacing: 8) {
                    Text(selectedTarget.configPath)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)

                    Button(action: revealInFinder) {
                        Label(L10n.string("common.action.revealInFinder"), systemImage: "folder")
                    }
                    .labelStyle(.iconOnly)
                    .help(L10n.string("config.toolbar.revealHelp"))

                    Button(action: openInTerminal) {
                        Label(L10n.string("common.action.openInTerminal"), systemImage: "terminal")
                    }
                    .labelStyle(.iconOnly)
                    .help(L10n.string("config.toolbar.openTerminalHelp"))
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)

            Divider()

            // Config output
            if showDiff, let diff = configDiff {
                // Diff view
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(diff.summary)
                            .font(.caption)
                            .foregroundStyle(diff.hasChanges ? .orange : .green)
                        Spacer()
                        Button(L10n.string("common.action.closeDiff")) { showDiff = false }
                            .buttonStyle(.plain)
                            .font(.caption)
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 8)

                    HSplitView {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(L10n.string("config.diff.currentTitle"))
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 12)
                            ScrollView {
                                Text(diff.current)
                                    .font(.body.monospaced())
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(12)
                                    .textSelection(.enabled)
                            }
                        }

                        VStack(alignment: .leading, spacing: 4) {
                            Text(L10n.string("config.diff.generatedTitle"))
                                .font(.caption.bold())
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 12)
                            ScrollView {
                                Text(diff.generated)
                                    .font(.body.monospaced())
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(12)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                }
            } else {
                // Generated config
                ScrollView {
                    if generatedConfig.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "doc.text")
                                .font(.system(size: 48))
                                .foregroundStyle(.secondary)
                            Text(L10n.string("config.empty.message"))
                                .font(.headline)
                                .foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .padding(.top, 80)
                    } else {
                        Text(generatedConfig)
                            .font(.body.monospaced())
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(16)
                            .textSelection(.enabled)
                    }
                }

                // Next steps hint
                if !generatedConfig.isEmpty && !showDiff {
                    Divider()
                    HStack(spacing: 8) {
                        Image(systemName: "info.circle")
                            .foregroundStyle(.secondary)
                        Text(L10n.format("config.footer.nextStepHint", selectedTarget.rawValue))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                }
            }
        }
        .onAppear {
            generateConfig()
        }
        .onChange(of: selectedTarget) { _, _ in
            generateConfig()
        }
        .onChange(of: includeSecrets) { _, _ in
            generateConfig()
        }
    }

    // MARK: - Actions

    private func generateConfig() {
        generatedConfig = configGenerator.generate(
            servers: registry.registeredServers,
            target: selectedTarget,
            includeSecrets: includeSecrets
        )
        copied = false
    }

    private func copyToClipboard() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(generatedConfig, forType: .string)
        copied = true
        log.info("Config copied to clipboard (target=\(selectedTarget.rawValue), secrets=\(includeSecrets))")

        // Reset copied state after 2 seconds
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            copied = false
        }
    }

    private func showConfigDiff() {
        configDiff = configGenerator.diffConfig(
            servers: registry.registeredServers,
            target: selectedTarget
        )
        if configDiff == nil {
            configDiff = ConfigDiff(
                hasChanges: false,
                summary: L10n.string("config.diff.matchesGenerated"),
                current: generatedConfig,
                generated: generatedConfig
            )
        }
        showDiff = true
    }

    private func revealInFinder() {
        let expandedPath = selectedTarget.configPathExpanded
        let parentDir = (expandedPath as NSString).deletingLastPathComponent

        // Check if file exists; if not, reveal the parent directory
        if FileManager.default.fileExists(atPath: expandedPath) {
            NSWorkspace.shared.selectFile(expandedPath, inFileViewerRootedAtPath: parentDir)
        } else {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: parentDir)
        }

        log.info("Revealed config path in Finder (path=\(expandedPath))")
    }

    private func openInTerminal() {
        let expandedPath = selectedTarget.configPathExpanded
        let parentDir = (expandedPath as NSString).deletingLastPathComponent

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "Terminal", parentDir]

        do {
            try process.run()
            log.info("Opened Terminal with directory (path=\(parentDir))")
        } catch {
            log.error("Failed to open Terminal: \(error.localizedDescription)")
        }
    }
}
