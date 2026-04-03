import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct LogViewer: View {
    let server: MCPServer
    var onNavigateToLogs: (() -> Void)? = nil
    @State private var scrollToBottom = true
    @State private var searchText = ""
    @State private var filterLevel: LogLevel? = nil
    @State private var filterSource: LogSource? = nil

    /// Filtered log entries based on search, level, and source filters
    private var filteredEntries: [(offset: Int, element: LogEntry)] {
        Array(server.stderrBuffer.enumerated()).filter { _, entry in
            if let level = filterLevel, entry.level != level {
                return false
            }
            if let source = filterSource, entry.source != source {
                return false
            }
            if !searchText.isEmpty {
                return entry.message.localizedCaseInsensitiveContains(searchText)
            }
            return true
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Server Detail Header
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 10, height: 10)
                        .accessibilityLabel(L10n.format("logs.viewer.serverStatusAccessibility", statusLabel))

                    VStack(alignment: .leading, spacing: 2) {
                        Text(server.manifest.name)
                            .font(.headline)
                            .foregroundStyle(.primary)

                        HStack(spacing: 12) {
                            Text(L10n.format("logs.viewer.versionValue", server.manifest.version))
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            Text(statusLabel)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(statusColor.opacity(0.15))
                                .clipShape(RoundedRectangle(cornerRadius: 4))

                            Text(L10n.format("logs.viewer.lineCount", server.stderrBuffer.count))
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            // Process stats display (Phase 4.3)
                            if let stats = server.processStats {
                                Divider()
                                    .frame(height: 12)

                                HStack(spacing: 8) {
                                    Text(L10n.format("logs.viewer.pidValue", stats.pid))
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)

                                    Text(L10n.format("logs.viewer.cpuValue", String(format: "%.1f", stats.cpuPercent)))
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)

                                    Text(L10n.format("logs.viewer.memoryValue", String(format: "%.1f", stats.memoryMB)))
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }

                    Spacer()
                }

                if !server.manifest.description.isEmpty {
                    Text(verbatim: server.manifest.description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                // Log context hint
                HStack(spacing: 4) {
                    Image(systemName: "info.circle")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(L10n.string("logs.viewer.stderrHint"))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                    
                    Spacer()
                    
                    if let onNavigateToLogs {
                        Button(action: onNavigateToLogs) {
                            HStack(spacing: 2) {
                                Text(L10n.string("logs.tab.title"))
                                    .font(.caption2)
                                Image(systemName: "arrow.right")
                                    .font(.caption2)
                            }
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(Color.accentColor)
                        .help(L10n.string("logs.viewer.systemLogsHelp"))
                    }
                }

                // Dependency warnings (Phase 4.4)
                let unsatisfiedDeps = server.dependencyResults.filter { !$0.satisfied }
                if !unsatisfiedDeps.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(unsatisfiedDeps, id: \.name) { dep in
                            Label(dep.message, systemImage: "exclamationmark.triangle.fill")
                                .font(.caption)
                                .foregroundStyle(ShipyardColors.warning)
                                .contextMenu {
                                    Button(L10n.string("logs.viewer.copyThisIssueButton")) {
                                        let text = formatSingleDep(dep)
                                        NSPasteboard.general.clearContents()
                                        NSPasteboard.general.setString(text, forType: .string)
                                    }
                                    Button(L10n.string("servers.row.copyDependencyReportButton")) {
                                        let text = formatDependencyReport()
                                        NSPasteboard.general.clearContents()
                                        NSPasteboard.general.setString(text, forType: .string)
                                    }
                                }
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Divider()

            // Filter bar
            HStack(spacing: 8) {
                HStack(spacing: 4) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField(L10n.string("logs.search.placeholder"), text: $searchText)
                        .textFieldStyle(.plain)
                    if !searchText.isEmpty {
                        Button(action: { searchText = "" }) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(.thickMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 6))

                Picker("Level", selection: $filterLevel) {
                    Text(L10n.string("logs.filter.all")).tag(LogLevel?.none)
                    ForEach([LogLevel.error, .warning, .info, .debug], id: \.self) { level in
                        HStack {
                            Circle()
                                .fill(levelColor(level))
                                .frame(width: 6, height: 6)
                            Text(level.rawValue.capitalized)
                        }
                        .tag(LogLevel?.some(level))
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: 120)
                .accessibilityLabel(L10n.string("logs.filter.levelAccessibility"))

                Picker("Source", selection: $filterSource) {
                    Text(L10n.string("logs.filter.all")).tag(LogSource?.none)
                    ForEach([LogSource.stderr, .mcp, .manager], id: \.self) { source in
                        HStack {
                            Image(systemName: sourceIcon(source))
                                .font(.caption2)
                            Text(sourceLabel(source))
                        }
                        .tag(LogSource?.some(source))
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: 120)
                .accessibilityLabel(L10n.string("logs.filter.sourceAccessibility"))

                Spacer()

                if !filteredEntries.isEmpty && filteredEntries.count != server.stderrBuffer.count {
                    Text("\(filteredEntries.count)/\(server.stderrBuffer.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 6)

            Divider()

            // Log content
            ZStack(alignment: .bottomTrailing) {
                if server.stderrBuffer.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "doc.text")
                                .font(.system(size: 48))
                                .foregroundStyle(.secondary)
                        Text(L10n.string("logs.viewer.emptyTitle"))
                            .font(.headline)
                            .foregroundStyle(.secondary)
                        Text(L10n.string("logs.viewer.emptyMessage"))
                            .font(.body)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if filteredEntries.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 48))
                            .foregroundStyle(.secondary)
                        Text(L10n.string("logs.empty.noMatchesTitle"))
                            .font(.headline)
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollViewReader { proxy in
                        ScrollView(.vertical, showsIndicators: true) {
                            VStack(alignment: .leading, spacing: 0) {
                                ForEach(filteredEntries, id: \.offset) { index, entry in
                                    HStack(alignment: .top, spacing: 8) {
                                        Circle()
                                            .fill(levelColor(entry.level))
                                            .frame(width: 6, height: 6)
                                            .padding(.top, 6)

                                        Text(formatTimestamp(entry.timestamp))
                                            .font(.caption.monospaced())
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)

                                        Text(sourceLabel(entry.source))
                                            .font(.caption2.monospaced())
                                            .foregroundStyle(sourceColor(entry.source))
                                            .padding(.horizontal, 4)
                                            .padding(.vertical, 1)
                                            .background(sourceColor(entry.source).opacity(0.1))
                                            .clipShape(RoundedRectangle(cornerRadius: 3))

                                        Text(entry.message)
                                            .font(.body.monospaced())
                                            .foregroundStyle(.primary)
                                            .lineLimit(nil)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .topLeading)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 3)
                                    .id("log-\(index)")
                                    .accessibilityLabel("\(formatTimestamp(entry.timestamp)) [\(entry.level.rawValue)] [\(sourceLabel(entry.source))] \(entry.message)")
                                }
                            }
                            .padding(.vertical, 8)
                            .frame(maxWidth: .infinity, alignment: .topLeading)
                            .onChange(of: server.stderrBuffer.count) { oldCount, newCount in
                                if scrollToBottom && newCount > oldCount {
                                    if let lastIndex = filteredEntries.last?.offset {
                                        withAnimation {
                                            proxy.scrollTo("log-\(lastIndex)", anchor: .bottom)
                                        }
                                    }
                                }
                            }
                            .onAppear {
                                if let lastIndex = filteredEntries.last?.offset {
                                    proxy.scrollTo("log-\(lastIndex)", anchor: .bottom)
                                }
                            }
                        }
                    }
                }

                VStack(spacing: 8) {
                    Toggle(L10n.string("logs.viewer.autoScrollToggle"), isOn: $scrollToBottom)
                        .help(L10n.string("logs.viewer.autoScrollHelp"))
                        .labelStyle(.iconOnly)
                        .padding(8)
                        .background(.thickMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                }
                .padding(12)
            }
        }
        .toolbar {
            ToolbarItem(placement: .secondaryAction) {
                Menu {
                    Button(action: { exportJSON() }) {
                        Label(L10n.string("logs.viewer.exportJsonButton"), systemImage: "doc.text")
                    }
                    Button(action: { exportPlainText() }) {
                        Label(L10n.string("logs.viewer.exportTextButton"), systemImage: "doc.plaintext")
                    }
                } label: {
                    Label(L10n.string("common.action.export"), systemImage: "square.and.arrow.up")
                }
                .help(L10n.string("logs.viewer.exportHelp"))
                .accessibilityLabel(L10n.string("logs.viewer.exportAccessibility"))
                .disabled(server.stderrBuffer.isEmpty)
            }
            ToolbarItem(placement: .secondaryAction) {
                Button(action: { server.stderrBuffer.removeAll() }) {
                    Label(L10n.string("common.action.clear"), systemImage: "trash")
                }
                .help(L10n.string("logs.viewer.clearHelp"))
                .disabled(server.stderrBuffer.isEmpty)
            }
            ToolbarItem(placement: .secondaryAction) {
                Button(action: { revealLogInFinder() }) {
                    Label(L10n.string("common.action.revealLogInFinder"), systemImage: "doc.text.magnifyingglass")
                }
                .help(L10n.string("logs.viewer.revealHelp"))
            }
            ToolbarItem(placement: .secondaryAction) {
                Button(action: { openLogsFolder() }) {
                    Label(L10n.string("common.action.openLogsFolder"), systemImage: "folder")
                }
                .help(L10n.string("logs.viewer.openLogsFolderHelp"))
            }
        }
    }

    // MARK: - Helpers

    private func levelColor(_ level: LogLevel) -> Color {
        switch level {
        case .error: return Color(nsColor: .systemRed)
        case .warning: return Color(nsColor: .systemOrange)
        case .info: return .accentColor
        case .debug: return .secondary
        }
    }

    private var statusColor: Color {
        switch server.state {
        case .running: return ShipyardColors.running
        case .idle: return ShipyardColors.idle
        case .error: return ShipyardColors.error
        case .starting, .stopping: return ShipyardColors.transition
        }
    }

    private var statusLabel: String {
        switch server.state {
        case .running: return L10n.string("common.state.running")
        case .idle: return L10n.string("common.state.idle")
        case .error: return L10n.string("common.state.error")
        case .starting: return L10n.string("common.state.starting")
        case .stopping: return L10n.string("common.state.stopping")
        }
    }

    private func formatTimestamp(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: date)
    }

    private func sourceIcon(_ source: LogSource) -> String {
        switch source {
        case .stderr: return "terminal"
        case .mcp: return "arrow.left.arrow.right"
        case .manager: return "gear"
        }
    }

    private func sourceLabel(_ source: LogSource) -> String {
        switch source {
        case .stderr: return L10n.string("logs.source.stderr")
        case .mcp: return L10n.string("logs.source.mcp")
        case .manager: return L10n.string("logs.source.app")
        }
    }

    private func sourceColor(_ source: LogSource) -> Color {
        switch source {
        case .stderr: return .secondary
        case .mcp: return .purple
        case .manager: return .teal
        }
    }

    // MARK: - Dependency Report

    private func formatSingleDep(_ dep: DependencyCheckResult) -> String {
        let status = dep.satisfied ? "✅" : "❌"
        var line = "\(status) \(dep.name): \(dep.message)"
        if let found = dep.found {
            line += " (found: \(found))"
        }
        line += " (required: \(dep.required))"
        return line
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
            lines.append("  \(formatSingleDep(dep))")
        }
        return lines.joined(separator: "\n")
    }

    // MARK: - Log File Access

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

    // MARK: - Export

    private func exportJSON() {
        let entries = filteredEntries.map { $0.element }
        let exportData = entries.map { entry -> [String: String] in
            [
                "timestamp": ISO8601DateFormatter().string(from: entry.timestamp),
                "level": entry.level.rawValue,
                "source": entry.source.rawValue,
                "message": entry.message
            ]
        }

        guard let jsonData = try? JSONSerialization.data(withJSONObject: exportData, options: [.prettyPrinted, .sortedKeys]) else { return }

        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        let dateStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd-HHmmss"; return f.string(from: Date()) }()
        panel.nameFieldStringValue = "\(server.manifest.name)-logs-\(dateStr).json"
        panel.canCreateDirectories = true

        if panel.runModal() == .OK, let url = panel.url {
            try? jsonData.write(to: url)
            NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: url.deletingLastPathComponent().path)
        }
    }

    private func exportPlainText() {
        let entries = filteredEntries.map { $0.element }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss.SSS"

        let text = entries.map { entry in
            let ts = formatter.string(from: entry.timestamp)
            let level = entry.level.rawValue.uppercased().padding(toLength: 7, withPad: " ", startingAt: 0)
            let source = entry.source.rawValue.padding(toLength: 7, withPad: " ", startingAt: 0)
            return "[\(ts)] [\(level)] [\(source)] \(entry.message)"
        }.joined(separator: "\n")

        let panel = NSSavePanel()
        panel.allowedContentTypes = [.plainText]
        let dateStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd-HHmmss"; return f.string(from: Date()) }()
        panel.nameFieldStringValue = "\(server.manifest.name)-logs-\(dateStr).txt"
        panel.canCreateDirectories = true

        if panel.runModal() == .OK, let url = panel.url {
            try? text.write(to: url, atomically: true, encoding: .utf8)
            NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: url.deletingLastPathComponent().path)
        }
    }
}
