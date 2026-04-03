import AppKit
import SwiftUI

/// Setup instructions view — step-by-step guide for configuring Claude Desktop or Claude Code.
struct InstructionsView: View {
    @Environment(MCPRegistry.self) private var registry
    let keychainManager: KeychainManager

    @State private var selectedTarget: ConfigGenerator.ConfigTarget = .claudeDesktop

    private var configGenerator: ConfigGenerator {
        ConfigGenerator(keychainManager: keychainManager)
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(L10n.string("instructions.header.title"))
                    .font(.headline)

                Spacer()

                Picker("Target", selection: $selectedTarget) {
                    ForEach(ConfigGenerator.ConfigTarget.allCases) { target in
                        Text(target.rawValue).tag(target)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 240)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Divider()

            // Steps
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    let steps = configGenerator.instructions(
                        for: selectedTarget,
                        servers: registry.registeredServers
                    )

                    ForEach(steps) { step in
                        StepRow(step: step)
                    }

                    // Secrets status section
                    secretsStatusSection
                }
                .padding(16)
            }
        }
    }

    // MARK: - Secrets Status

    private var serversWithSecrets: [MCPServer] {
        registry.registeredServers.filter {
            !($0.manifest.env_secret_keys ?? []).isEmpty
        }
    }

    @ViewBuilder
    private var secretsStatusSection: some View {
        if !serversWithSecrets.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Divider()
                    .padding(.vertical, 8)

                Text(L10n.string("instructions.secretsStatus.title"))
                    .font(.headline)

                ForEach(serversWithSecrets) { server in
                    SecretStatusRow(
                        server: server,
                        keychainManager: keychainManager
                    )
                }
            }
        }
    }
}

// MARK: - Secret Status Row

private struct SecretStatusRow: View {
    let server: MCPServer
    let keychainManager: KeychainManager

    var body: some View {
        let keys = server.manifest.env_secret_keys ?? []
        let allPresent = keychainManager.hasAllSecrets(for: server.manifest)

        HStack(spacing: 8) {
            Image(systemName: allPresent ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(allPresent ? .green : .orange)

            VStack(alignment: .leading, spacing: 2) {
                Text(server.manifest.name)
                    .font(.body.bold())

                Text(keys.joined(separator: ", "))
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Text(L10n.string(allPresent ? "instructions.secretsStatus.allStored" : "instructions.secretsStatus.missingSecrets"))
                .font(.caption)
                .foregroundColor(allPresent ? .secondary : .orange)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.3))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Step Row

private struct StepRow: View {
    let step: SetupStep

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // Step number badge
            Text("\(step.number)")
                .font(.caption.bold())
                .foregroundStyle(.white)
                .frame(width: 24, height: 24)
                .background(Circle().fill(.blue))

            VStack(alignment: .leading, spacing: 4) {
                Text(step.title)
                    .font(.body.bold())

                Text(step.detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let code = step.code {
                    HStack {
                        Text(code)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.primary)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)

                        Spacer()

                        Button(action: {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(code, forType: .string)
                        }) {
                            Image(systemName: "doc.on.doc")
                                .font(.caption)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                        .help(L10n.string("instructions.step.copyCommandHelp"))
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(Color(nsColor: .textBackgroundColor).opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .overlay(
                        RoundedRectangle(cornerRadius: 6)
                            .stroke(Color(nsColor: .separatorColor), lineWidth: 0.5)
                    )
                }
            }
        }
    }
}
