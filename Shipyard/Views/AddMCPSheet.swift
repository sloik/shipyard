import SwiftUI
import Foundation
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "AddMCPSheet")

/// Sheet for adding a new MCP server entry to mcps.json
struct AddMCPSheet: View {
    @Environment(MCPRegistry.self) var registry
    @Environment(\.dismiss) var dismiss
    
    // Form fields
    @State private var name: String = ""
    @State private var transport: String = "stdio"
    
    // Stdio fields
    @State private var command: String = ""
    @State private var arguments: String = ""
    @State private var workingDirectory: String = ""
    @State private var environmentVariables: String = ""
    
    // HTTP fields
    @State private var url: String = ""
    @State private var headers: String = ""
    
    // Common fields
    @State private var disabled: Bool = false
    @State private var overrideEnabled: Bool = false
    @State private var timeoutSeconds: String = ""
    
    // Validation
    @State private var validationError: String?
    
    private let transports = ["stdio", "streamable-http"]
    
    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Add MCP Server")
                    .font(.headline)
                Spacer()
                Button(action: { dismiss() }) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding()
            .background(Color(nsColor: .controlBackgroundColor))
            .border(.separator, width: 1)
            
            // Form content
            Form {
                Section(header: Text("Basic Information")) {
                    TextField("Server Name", text: $name)
                        .help("Unique identifier for this MCP server (required)")
                    
                    Picker("Transport", selection: $transport) {
                        ForEach(transports, id: \.self) { t in
                            Text(t.prefix(1).uppercased() + t.dropFirst()).tag(t)
                        }
                    }
                    .onChange(of: transport) {
                        validationError = nil
                    }
                }
                
                if transport == "stdio" {
                    Section(header: Text("Stdio Configuration")) {
                        TextField("Command", text: $command)
                            .help("Executable name or path (e.g., python3, /usr/bin/python3)")
                        
                        TextField("Arguments", text: $arguments)
                            .help("Space-separated arguments (e.g., server.py --debug)")
                            .lineLimit(1)
                        
                        TextField("Working Directory", text: $workingDirectory)
                            .help("Optional: working directory for the process")
                        
                        TextField("Environment Variables", text: $environmentVariables, axis: .vertical)
                            .lineLimit(3...5)
                            .help("Optional: one per line in KEY=VALUE format")
                    }
                } else {
                    Section(header: Text("HTTP Configuration")) {
                        TextField("URL", text: $url)
                            .help("HTTP endpoint URL (e.g., http://localhost:3000/mcp)")
                        
                        TextField("Headers", text: $headers, axis: .vertical)
                            .lineLimit(3...5)
                            .help("Optional: one per line in KEY: VALUE format")
                    }
                }
                
                Section(header: Text("Options")) {
                    Toggle("Disabled", isOn: $disabled)
                        .help("Register but don't start automatically")
                    
                    Toggle("Override", isOn: $overrideEnabled)
                        .help("Take priority over manifest with same name")
                    
                    TextField("Timeout (seconds)", text: $timeoutSeconds)
                        .help("Optional: request timeout in seconds (default: 30)")
                }
                
                if let error = validationError {
                    Section {
                        HStack {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundStyle(.red)
                            Text(error)
                                .foregroundStyle(.red)
                        }
                    }
                }
            }
            .formStyle(.grouped)
            
            // Footer buttons
            HStack(spacing: 12) {
                Spacer()
                Button(action: { dismiss() }) {
                    Text("Cancel")
                        .frame(minWidth: 80)
                }
                .keyboardShortcut(.cancelAction)
                
                Button(action: addMCP) {
                    Text("Add")
                        .frame(minWidth: 80)
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
            }
            .padding()
            .background(Color(nsColor: .controlBackgroundColor))
            .border(.separator, width: 1)
        }
        .frame(width: 500, height: 600)
    }
    
    // MARK: - Actions
    
    private func addMCP() {
        // Validate inputs
        if name.trimmingCharacters(in: .whitespaces).isEmpty {
            validationError = "Server name is required"
            return
        }
        
        if transport == "stdio" {
            if command.trimmingCharacters(in: .whitespaces).isEmpty {
                validationError = "Command is required for stdio transport"
                return
            }
        } else {
            if url.trimmingCharacters(in: .whitespaces).isEmpty {
                validationError = "URL is required for HTTP transport"
                return
            }
        }
        
        do {
            // Load existing config
            let configPath = MCPConfig.defaultPath
            let config = try MCPConfig.loadOrCreateDefault(at: configPath)
            
            // Build the new entry
            let timeout = parseTimeout(timeoutSeconds)
            let entry = MCPConfig.ServerEntry(
                transport: transport == "stdio" ? "stdio" : "streamable-http",
                command: command.isEmpty ? nil : command,
                args: parseArguments(arguments),
                cwd: workingDirectory.isEmpty ? nil : workingDirectory,
                env: parseEnvironmentVariables(environmentVariables),
                envSecretKeys: nil,
                url: url.isEmpty ? nil : url,
                headers: parseHeaders(headers),
                headersSecretKeys: nil,
                disabled: disabled ? true : nil,
                override: overrideEnabled ? true : nil,
                timeout: timeout,
                healthCheck: nil  // Health check config not yet exposed in UI
            )
            
            // Merge into existing config
            var mcpServers = config.mcpServers
            mcpServers[name] = entry
            
            let updatedConfig = MCPConfig(mcpServers: mcpServers)
            
            // Write back to disk
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(updatedConfig)
            
            try data.write(to: URL(fileURLWithPath: configPath))
            
            log.info("Added MCP server '\(name)' to mcps.json")
            
            // Reload config in registry
            Task {
                await registry.reloadConfig()
                log.info("Config reloaded after adding '\(name)'")
            }
            
            dismiss()
        } catch {
            validationError = "Failed to save config: \(error.localizedDescription)"
            log.error("Error adding MCP: \(error.localizedDescription)")
        }
    }
    
    // MARK: - Parsing Helpers
    
    private func parseArguments(_ input: String) -> [String]? {
        let trimmed = input.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        return trimmed.split(separator: " ").map(String.init)
    }
    
    private func parseEnvironmentVariables(_ input: String) -> [String: String]? {
        let lines = input.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
        let pairs = lines.filter { !$0.isEmpty }.compactMap { line -> (String, String)? in
            let parts = line.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { return nil }
            return (String(parts[0]), String(parts[1]))
        }
        return pairs.isEmpty ? nil : Dictionary(uniqueKeysWithValues: pairs)
    }
    
    private func parseHeaders(_ input: String) -> [String: String]? {
        let lines = input.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
        let pairs = lines.filter { !$0.isEmpty }.compactMap { line -> (String, String)? in
            let parts = line.split(separator: ":", maxSplits: 1)
            guard parts.count == 2 else { return nil }
            return (String(parts[0]), String(parts[1]).trimmingCharacters(in: .whitespaces))
        }
        return pairs.isEmpty ? nil : Dictionary(uniqueKeysWithValues: pairs)
    }
    
    private func parseTimeout(_ input: String) -> Int? {
        let trimmed = input.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        return Int(trimmed)
    }
}

// MARK: - Preview

#Preview {
    @Previewable @State var registry = MCPRegistry()
    
    return AddMCPSheet()
        .environment(registry)
}
