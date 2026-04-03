import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "ToolExecutionSheet")

/// Tool Execution Sheet — parameter input, JSON/Form tabs, confirmation
struct ToolExecutionSheet: View {
    let tool: GatewayTool
    var initialArguments: [String: Any]?
    var onExecutionStarted: ((ToolExecution) -> Void)?

    @Environment(ExecutionQueueManager.self) private var queueManager
    @Environment(\.dismiss) private var dismiss

    @State private var payload: [String: Any] = [:]
    @State private var selectedTab: ExecutionTab = .json
    @State private var jsonText: String = "{}"
    @State private var showConfirmation = false
    @State private var recentCalls: [ToolExecutionRequest] = []
    
    enum ExecutionTab {
        case json
        case form
    }
    
    var toolDisplayName: String {
        tool.originalName
    }
    
    var hasParameters: Bool {
        guard let schema = parseInputSchema() else { return false }
        let properties = schema["properties"] as? [String: Any] ?? [:]
        return !properties.isEmpty
    }
    
    var body: some View {
        VStack(spacing: 0) {
            // Header with Recent dropdown
            HStack(spacing: 12) {
                Text(toolDisplayName)
                    .font(.title3)
                    .fontWeight(.semibold)
                
                Spacer()
                
                // Recent calls dropdown
                if !recentCalls.isEmpty {
                    Menu {
                        ForEach(recentCalls.indices, id: \.self) { index in
                            let req = recentCalls[index]
                            Button(action: { selectRecentCall(req) }) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(L10n.format("execution.sheet.recentCallLabel", recentCalls.count - index))
                                        .font(.caption)
                                    if let argStr = serializeArguments(req.arguments) {
                                        Text(argStr)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                    }
                                }
                            }
                        }
                    } label: {
                        Label(L10n.string("execution.sheet.recentMenuLabel"), systemImage: "clock")
                            .font(.caption)
                    }
                    .menuStyle(.borderlessButton)
                }
                
                Button(action: { dismiss() }) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help(L10n.string("common.action.closeSheetHelp"))
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            
            Divider()
            
            // Tab selector
            if hasParameters {
                Picker("", selection: $selectedTab) {
                    Text(L10n.string("execution.sheet.jsonTab")).tag(ExecutionTab.json)
                    Text(L10n.string("execution.sheet.formTab")).tag(ExecutionTab.form)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                
                Divider()
            }
            
            // Content area
            if hasParameters {
                Group {
                    if selectedTab == .json {
                        jsonTabView
                    } else {
                        formTabView
                    }
                }
            } else {
                // No parameters required
                VStack(spacing: 16) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 40))
                        .foregroundStyle(.green)
                    Text(L10n.string("execution.sheet.noParametersTitle"))
                        .font(.callout)
                        .fontWeight(.medium)
                    Text(L10n.string("execution.sheet.noParametersMessage"))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(16)
            }
            
            Divider()
            
            // Action buttons
            HStack(spacing: 12) {
                Button(action: { dismiss() }) {
                    Text(L10n.string("common.action.cancel"))
                }
                .keyboardShortcut(.cancelAction)
                
                Button(action: resetPayload) {
                    Image(systemName: "arrow.counterclockwise")
                }
                .buttonStyle(.bordered)
                .help(L10n.string("execution.sheet.resetHelp"))
                
                Spacer()
                
                Button(action: { showConfirmation = true }) {
                    Text(L10n.string("common.action.execute"))
                        .fontWeight(.semibold)
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .frame(minWidth: 500, minHeight: 400)
        .task {
            // Load recent calls on appear
            recentCalls = queueManager.getRecentCalls(for: tool.prefixedName)

            // Pre-fill from initialArguments if provided (e.g., from Retry)
            if let initialArgs = initialArguments {
                payload = initialArgs
                updateJsonText()
            } else if let firstRecent = recentCalls.first {
                // Otherwise, pre-fill from most recent call if available
                payload = firstRecent.arguments
                updateJsonText()
            } else {
                // No history — build defaults from schema for required fields
                payload = buildDefaultPayload()
                updateJsonText()
            }
        }
        .onChange(of: selectedTab) { _, newTab in
            if newTab == .json {
                updateJsonText()
            } else {
                // Sync payload from JSON when switching to form
                if let jsonData = jsonText.data(using: .utf8),
                   let parsed = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] {
                    payload = parsed
                }
            }
        }
        .alert(L10n.string("execution.sheet.confirmTitle"), isPresented: $showConfirmation) {
            Button(L10n.string("common.action.cancel"), role: .cancel) {}
            Button(L10n.string("common.action.execute"), action: executeConfirmed)
        } message: {
            Text(L10n.format("execution.sheet.confirmMessage", toolDisplayName))
        }
    }
    
    // MARK: - JSON Tab
    
    @ViewBuilder
    private var jsonTabView: some View {
        VStack(spacing: 0) {
            JSONEditorView(jsonText: $jsonText, inputSchema: tool.inputSchema)
                .onChange(of: jsonText) { _, newText in
                    // Update payload from JSON when user types
                    if let jsonData = newText.data(using: .utf8),
                       let parsed = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] {
                        payload = parsed
                    }
                }
        }
    }
    
    // MARK: - Form Tab
    
    @ViewBuilder
    private var formTabView: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let schema = parseInputSchema() {
                    // Binding wrapper that syncs JSON when form values change
                    DynamicFormView(
                        schema: schema,
                        payload: Binding(
                            get: { payload },
                            set: { newValue in
                                payload = newValue
                                updateJsonText()
                            }
                        )
                    )
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "exclamationmark.circle.fill")
                            .font(.system(size: 32))
                            .foregroundStyle(.orange)
                        Text(L10n.string("execution.sheet.invalidSchemaTitle"))
                            .font(.callout)
                            .fontWeight(.medium)
                        Text(L10n.string("execution.sheet.invalidSchemaMessage"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                }
            }
            .padding(16)
        }
    }
    
    // MARK: - Helpers
    
    private func parseInputSchema() -> [String: Any]? {
        guard !tool.inputSchema.isEmpty else { return [:] }
        return try? JSONSerialization.jsonObject(with: tool.inputSchema) as? [String: Any]
    }
    
    private func updateJsonText() {
        if let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            jsonText = jsonString
        }
    }
    
    private func selectRecentCall(_ request: ToolExecutionRequest) {
        payload = request.arguments
        updateJsonText()
    }
    
    private func serializeArguments(_ args: [String: Any]) -> String? {
        guard let data = try? JSONSerialization.data(withJSONObject: args, options: [.sortedKeys]),
              let str = String(data: data, encoding: .utf8) else {
            return nil
        }
        return String(str.prefix(50)) + (str.count > 50 ? "…" : "")
    }
    
    private func resetPayload() {
        payload = buildDefaultPayload()
        updateJsonText()
    }
    
    private func executeConfirmed() {
        let execution = queueManager.executeToolAsync(
            toolName: tool.prefixedName,
            arguments: payload
        )
        log.debug("Execution started: \(tool.prefixedName)")
        onExecutionStarted?(execution)
        dismiss()
    }

    private func buildDefaultPayload() -> [String: Any] {
        guard let schema = parseInputSchema(),
              let properties = schema["properties"] as? [String: Any],
              let required = schema["required"] as? [String] else {
            return [:]
        }

        var defaults: [String: Any] = [:]
        for fieldName in required {
            guard let fieldSchema = properties[fieldName] as? [String: Any],
                  let fieldType = fieldSchema["type"] as? String else { continue }

            switch fieldType {
            case "string": defaults[fieldName] = ""
            case "number", "integer": defaults[fieldName] = 0
            case "boolean": defaults[fieldName] = false
            case "array": defaults[fieldName] = [Any]()
            case "object": defaults[fieldName] = [String: Any]()
            default: break
            }
        }
        return defaults
    }
}

#Preview {
    @Previewable @State var queueManager = ExecutionQueueManager()

    let tool = GatewayTool(
        prefixedName: "echo__echo_message",
        mcpName: "echo",
        originalName: "echo_message",
        description: "Echo back the input message — a starter MCP for testing",
        inputSchema: try! JSONSerialization.data(withJSONObject: [
            "type": "object",
            "properties": [
                "message": ["type": "string", "description": "Message to echo back"],
                "uppercase": ["type": "boolean", "description": "Return in uppercase"]
            ],
            "required": ["message"]
        ]),
        enabled: true
    )

    ToolExecutionSheet(tool: tool, onExecutionStarted: nil)
        .environment(queueManager)
}
