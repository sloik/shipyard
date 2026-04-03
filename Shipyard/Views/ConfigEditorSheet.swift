import SwiftUI
import AppKit

extension NSNotification.Name {
    static let shipyardConfigDidSave = NSNotification.Name("shipyardConfigDidSave")
}

struct ConfigEditorSheet: View {
    let serverName: String
    @State private var configContent: String = ""
    @State private var isLoading: Bool = true
    @State private var loadError: String? = nil
    @State private var isSaving: Bool = false
    @Binding var isPresented: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Title bar
            HStack {
                Text(L10n.string("configEditor.sheet.title"))
                    .font(.headline)
                Spacer()
                Button(action: { isPresented = false }) {
                    Image(systemName: "xmark")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Color(nsColor: .controlBackgroundColor))
            .overlay(Divider(), alignment: .bottom)

            // Content area
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error = loadError {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .font(.system(size: 48))
                        .foregroundStyle(.red)
                    Text(L10n.string("configEditor.sheet.loadFailedTitle"))
                        .font(.headline)
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button(L10n.string("common.action.dismiss")) {
                        isPresented = false
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding()
            } else {
                VStack(spacing: 0) {
                    let schema = try? JSONSerialization.data(withJSONObject: [:])
                    JSONEditorView(
                        jsonText: $configContent,
                        inputSchema: schema ?? Data()
                    )
                    .frame(maxHeight: .infinity)

                    // Validation and action bar
                    HStack(spacing: 12) {
                        let validationErrors = validateJSON()
                        if !validationErrors.isEmpty {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.red)
                            Text(validationErrors[0])
                                .font(.caption)
                                .foregroundStyle(.red)
                        } else {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(.green)
                            Text(L10n.string("configEditor.sheet.validJson"))
                                .font(.caption)
                                .foregroundStyle(.green)
                        }

                        Spacer()

                        Button(L10n.string("common.action.cancel")) {
                            isPresented = false
                        }
                        .keyboardShortcut(.cancelAction)

                        Button(L10n.string("common.action.save")) {
                            saveConfig()
                        }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!validationErrors.isEmpty || isSaving)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .background(Color(nsColor: .controlBackgroundColor))
                    .overlay(Divider(), alignment: .top)
                }
            }
        }
        .frame(minWidth: 600, minHeight: 500)
        .task {
            await loadConfig()
        }
    }

    private func loadConfig() async {
        isLoading = true
        loadError = nil

        do {
            let path = MCPConfig.defaultPath
            let fileManager = FileManager.default

            if fileManager.fileExists(atPath: path) {
                let data = try Data(contentsOf: URL(fileURLWithPath: path))
                if let jsonString = String(data: data, encoding: .utf8) {
                    // Parse raw JSON and re-serialize with clean options
                    do {
                        let jsonObject = try JSONSerialization.jsonObject(with: Data(jsonString.utf8))
                        let cleanData = try JSONSerialization.data(
                            withJSONObject: jsonObject,
                            options: JSONFormatter.displayOptions
                        )
                        if let cleanJsonString = String(data: cleanData, encoding: .utf8) {
                            configContent = JSONFormatter.decodeUnicodeEscapes(cleanJsonString)
                        } else {
                            // Fallback: use raw content if re-serialization fails
                            configContent = jsonString
                        }
                    } catch {
                        // If JSON parsing fails, show raw content so user can manually fix it
                        configContent = jsonString
                    }
                } else {
                    throw ConfigError.invalidJSON("Could not decode file contents")
                }
            } else {
                // File doesn't exist, start with empty config
                configContent = "{\n  \"mcpServers\": {}\n}"
            }
        } catch {
            loadError = error.localizedDescription
        }

        isLoading = false
    }

    private func validateJSON() -> [String] {
        let (isValid, errorMsg) = JSONSchemaValidator.isValidJSON(configContent)
        if !isValid, let msg = errorMsg {
            return [L10n.format("configEditor.sheet.invalidJsonError", msg)]
        }
        return []
    }

    private func saveConfig() {
        isSaving = true
        let validationErrors = validateJSON()

        if !validationErrors.isEmpty {
            // Should not reach here due to button being disabled
            isSaving = false
            return
        }

        do {
            let path = MCPConfig.defaultPath
            let fileURL = URL(fileURLWithPath: path)

            // Create directory if needed
            let dirURL = fileURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: dirURL, withIntermediateDirectories: true)

            // Parse editor text as JSON and re-serialize with clean options
            let jsonObject = try JSONSerialization.jsonObject(with: Data(configContent.utf8))
            let cleanData = try JSONSerialization.data(
                withJSONObject: jsonObject,
                options: JSONFormatter.displayOptions
            )
            
            // Convert to string, decode unicode escapes, and append trailing newline
            guard var cleanJsonString = String(data: cleanData, encoding: .utf8) else {
                throw ConfigError.invalidJSON("Could not encode JSON")
            }
            
            cleanJsonString = JSONFormatter.decodeUnicodeEscapes(cleanJsonString)
            
            // Append trailing newline if not present
            if !cleanJsonString.hasSuffix("\n") {
                cleanJsonString.append("\n")
            }

            // Write file
            try cleanJsonString.write(to: fileURL, atomically: true, encoding: .utf8)

            NotificationCenter.default.post(name: .shipyardConfigDidSave, object: nil)

            // Dismiss the sheet after successful save
            isPresented = false
        } catch {
            loadError = L10n.format("error.config.saveFailed", error.localizedDescription)
            isSaving = false
        }
    }
}

#Preview {
    @Previewable @State var isPresented = true
    
    ConfigEditorSheet(
        serverName: "test-server",
        isPresented: $isPresented
    )
}
