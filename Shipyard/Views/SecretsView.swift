import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "SecretsView")

/// Manages Keychain secrets for MCP servers — view/add/delete secret values.
struct SecretsView: View {
    @Environment(MCPRegistry.self) private var registry
    let keychainManager: KeychainManager

    @State private var editingSecret: SecretEntry?
    @State private var newValue = ""
    @State private var showSavedAlert = false

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(L10n.string("secrets.header.title"))
                    .font(.headline)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Divider()

            // Secrets list
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    let serversWithSecrets = registry.registeredServers.filter {
                        !($0.manifest.env_secret_keys ?? []).isEmpty
                    }

                    if serversWithSecrets.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "key")
                                .font(.system(size: 48))
                                .foregroundStyle(.secondary)
                            Text(L10n.string("secrets.empty.title"))
                                .font(.headline)
                                .foregroundStyle(.secondary)
                            Text(L10n.string("secrets.empty.message"))
                                .font(.body)
                                .foregroundStyle(.secondary)
                                .multilineTextAlignment(.center)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.top, 80)
                    } else {
                        ForEach(serversWithSecrets) { server in
                            serverSecretsSection(server)
                        }
                    }
                }
                .padding(16)
            }

            // Footer help text
            Divider()
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                Text(L10n.string("secrets.footer.warning"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
        }
        .alert(L10n.string("secrets.alert.savedTitle"), isPresented: $showSavedAlert) {
            Button(L10n.string("common.action.ok")) {}
        } message: {
            Text(L10n.string("secrets.alert.savedMessage"))
        }
    }

    // MARK: - Server Section

    @ViewBuilder
    private func serverSecretsSection(_ server: MCPServer) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(server.manifest.name)
                .font(.body.bold())

            let keys = server.manifest.env_secret_keys ?? []
            ForEach(keys, id: \.self) { key in
                secretRow(serverName: server.manifest.name, key: key)
            }
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.3))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    @ViewBuilder
    private func secretRow(serverName: String, key: String) -> some View {
        let hasValue = keychainManager.load(serverName: serverName, key: key) != nil
        let isEditing = editingSecret?.serverName == serverName && editingSecret?.key == key

        HStack(spacing: 8) {
            Image(systemName: hasValue ? "key.fill" : "key")
                .foregroundStyle(hasValue ? .green : .orange)
                .frame(width: 20)

            Text(key)
                .font(.body.monospaced())

            Spacer()

            if isEditing {
                SecureField(L10n.string("secrets.form.enterValuePlaceholder"), text: $newValue)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 300)

                Button(L10n.string("common.action.save")) {
                    saveSecret(serverName: serverName, key: key)
                }
                .disabled(newValue.isEmpty)

                Button(L10n.string("common.action.cancel")) {
                    editingSecret = nil
                    newValue = ""
                }
                .buttonStyle(.plain)
            } else {
                if hasValue {
                    Text(L10n.string("common.state.stored"))
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Button(action: {
                        editingSecret = SecretEntry(serverName: serverName, key: key)
                        newValue = ""
                    }) {
                        Label(L10n.string("common.action.edit"), systemImage: "pencil")
                            .labelStyle(.iconOnly)
                    }
                    .buttonStyle(.plain)
                    .help(L10n.string("secrets.action.changeSecretHelp"))

                    Button(action: {
                        deleteSecret(serverName: serverName, key: key)
                    }) {
                        Label(L10n.string("common.action.delete"), systemImage: "trash")
                            .labelStyle(.iconOnly)
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(.red)
                    .help(L10n.string("secrets.action.removeSecretHelp"))
                } else {
                    Text(L10n.string("common.state.notSet"))
                        .font(.caption)
                        .foregroundStyle(.orange)

                    Button(L10n.string("common.action.set")) {
                        editingSecret = SecretEntry(serverName: serverName, key: key)
                        newValue = ""
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Actions

    private func saveSecret(serverName: String, key: String) {
        do {
            try keychainManager.save(value: newValue, serverName: serverName, key: key)
            log.info("Saved secret \(serverName)/\(key)")
            editingSecret = nil
            newValue = ""
            showSavedAlert = true
        } catch {
            log.error("Failed to save secret: \(error.localizedDescription)")
        }
    }

    private func deleteSecret(serverName: String, key: String) {
        do {
            try keychainManager.delete(serverName: serverName, key: key)
            log.info("Deleted secret \(serverName)/\(key)")
        } catch {
            log.error("Failed to delete secret: \(error.localizedDescription)")
        }
    }
}

// MARK: - Supporting Types

private struct SecretEntry: Equatable {
    let serverName: String
    let key: String
}
