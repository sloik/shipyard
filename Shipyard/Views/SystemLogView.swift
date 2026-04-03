import AppKit
import SwiftUI
import UniformTypeIdentifiers
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "SystemLogView")

struct SystemLogView: View {
    @Environment(LogStore.self) private var logStore
    @State private var scrollToBottom = true
    @State private var expandedEntries: Set<UUID> = []
    @State private var useRelativeTimestamp = true
    @State private var showClearConfirmation = false

    private var logsDirectory: String {
        PathManager.shared.logsDirectory.path
    }

    var body: some View {
        @Bindable var logStore = logStore
        VStack(spacing: 0) {
            // Filter bar
            filterBar
                .padding(.horizontal, 16)
                .padding(.vertical, 6)

            Divider()

            // Log content
            ZStack(alignment: .bottomTrailing) {
                if logStore.entries.isEmpty {
                    emptyStateView
                } else if logStore.filteredEntries.isEmpty {
                    noMatchesView
                } else {
                    logListView
                }

                // Auto-scroll toggle
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
        .navigationTitle(L10n.string("logs.navigation.title"))
        .toolbar {
            ToolbarItem(placement: .secondaryAction) {
                Button(action: {
                    useRelativeTimestamp.toggle()
                }) {
                    Label(
                        L10n.string(useRelativeTimestamp ? "logs.toolbar.absoluteTimeButton" : "logs.toolbar.relativeTimeButton"),
                        systemImage: useRelativeTimestamp ? "clock.arrow.circlepath" : "clock"
                    )
                }
                .help(L10n.string(useRelativeTimestamp ? "logs.toolbar.absoluteTimeHelp" : "logs.toolbar.relativeTimeHelp"))
            }

            ToolbarItem(placement: .secondaryAction) {
                Button(action: revealLogFiles) {
                    Label(L10n.string("common.action.revealInFinder"), systemImage: "folder")
                }
                .help(L10n.string("logs.toolbar.revealHelp"))
            }

            ToolbarItem(placement: .secondaryAction) {
                Button(action: openLogsInTerminal) {
                    Label(L10n.string("common.action.openInTerminal"), systemImage: "terminal")
                }
                .help(L10n.string("logs.toolbar.openTerminalHelp"))
            }

            ToolbarItem(placement: .secondaryAction) {
                Button(action: exportFiltered) {
                    Label(L10n.string("common.action.export"), systemImage: "square.and.arrow.up")
                }
                .help(L10n.string("logs.toolbar.exportHelp"))
                .disabled(logStore.filteredEntries.isEmpty)
            }

            ToolbarItem(placement: .secondaryAction) {
                Button(action: {
                    logStore.loadFromDisk()
                    log.debug("Refreshed log entries from disk")
                }) {
                    Label(L10n.string("common.action.refresh"), systemImage: "arrow.clockwise")
                }
                .help(L10n.string("logs.toolbar.refreshHelp"))
            }

            ToolbarItem(placement: .secondaryAction) {
                Button(action: {
                    showClearConfirmation = true
                }) {
                    Label(L10n.string("common.action.clear"), systemImage: "trash")
                }
                .help(L10n.string("logs.toolbar.clearHelp"))
                .disabled(logStore.entries.isEmpty)
            }
        }
        .confirmationDialog(L10n.string("logs.confirm.clearTitle"), isPresented: $showClearConfirmation) {
            Button(L10n.string("common.action.clear"), role: .destructive) {
                logStore.clear()
                log.debug("Cleared all log entries")
            }
            Button(L10n.string("common.action.cancel"), role: .cancel) {}
        } message: {
            Text(L10n.string("logs.confirm.clearMessage"))
        }
    }

    // MARK: - Subviews

    @ViewBuilder
    private var filterBar: some View {
        @Bindable var logStore = logStore
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                // Search
                HStack(spacing: 4) {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(.secondary)
                    TextField(L10n.string("logs.search.placeholder"), text: $logStore.searchText)
                        .textFieldStyle(.plain)
                    if !logStore.searchText.isEmpty {
                        Button(action: { logStore.searchText = "" }) {
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

                // Level filter
                Picker("Level", selection: $logStore.levelFilter) {
                    Text(L10n.string("logs.filter.allLevels")).tag(BridgeLogLevel?.none)
                    ForEach([BridgeLogLevel.error, .warn, .info, .debug], id: \.self) { level in
                        HStack {
                            Circle()
                                .fill(levelColor(level))
                                .frame(width: 6, height: 6)
                            Text(level.rawValue.capitalized)
                        }
                        .tag(BridgeLogLevel?.some(level))
                    }
                }
                .pickerStyle(.menu)
                .fixedSize()
                .accessibilityLabel(L10n.string("logs.filter.levelAccessibility"))

                // Source filter
                Picker("Source", selection: $logStore.sourceFilter) {
                    Text(L10n.string("logs.filter.allSources")).tag(String?.none)
                    HStack {
                        Circle()
                            .fill(Color.blue)
                            .frame(width: 6, height: 6)
                        Text(L10n.string("logs.filter.bridgeSource"))
                    }
                    .tag(String?.some("bridge"))
                    HStack {
                        Circle()
                            .fill(Color.purple)
                            .frame(width: 6, height: 6)
                        Text(L10n.string("logs.filter.appSource"))
                    }
                    .tag(String?.some("app"))
                }
                .pickerStyle(.menu)
                .fixedSize()
                .accessibilityLabel(L10n.string("logs.filter.sourceAccessibility"))

                Spacer()

                if !logStore.filteredEntries.isEmpty && logStore.filteredEntries.count != logStore.entries.count {
                    Text("\(logStore.filteredEntries.count)/\(logStore.entries.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            // Category chips
            if !logStore.availableCategories.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(logStore.availableCategories, id: \.self) { category in
                            Button(action: {
                                if logStore.categoryFilter.contains(category) {
                                    logStore.categoryFilter.remove(category)
                                } else {
                                    logStore.categoryFilter.insert(category)
                                }
                            }) {
                                Text(category)
                                    .font(.caption)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(
                                        logStore.categoryFilter.contains(category)
                                            ? Color.accentColor.opacity(0.3)
                                            : Color.gray.opacity(0.1)
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 4))
                            }
                            .buttonStyle(.plain)
                        }
                        Spacer()
                    }
                }
                .frame(height: 28)
            }
        }
    }

    private var emptyStateView: some View {
        VStack(spacing: 16) {
            Image(systemName: "doc.text")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text(L10n.string("logs.empty.noLogsTitle"))
                .font(.headline)
                .foregroundStyle(.secondary)
            Text(L10n.string("logs.empty.noLogsMessage"))
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var noMatchesView: some View {
        VStack(spacing: 16) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text(L10n.string("logs.empty.noMatchesTitle"))
                .font(.headline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var logListView: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical, showsIndicators: true) {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(logStore.filteredEntries) { entry in
                        let isExpanded = expandedEntries.contains(entry.id)
                        VStack(alignment: .leading, spacing: 0) {
                            HStack(alignment: .top, spacing: 8) {
                                // Disclosure indicator
                                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                    .frame(width: 10)
                                    .padding(.top, 6)

                                // Level indicator
                                Circle()
                                    .fill(levelColor(entry.logLevel))
                                    .frame(width: 6, height: 6)
                                    .padding(.top, 6)

                                // Timestamp
                                Text(formatTimestamp(entry.timestamp))
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)

                                // Category badge
                                Text(entry.cat)
                                    .font(.caption2.monospaced())
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 4)
                                    .padding(.vertical, 1)
                                    .background(categoryColor(entry.cat))
                                    .clipShape(RoundedRectangle(cornerRadius: 3))

                                // Message
                                Text(entry.msg)
                                    .font(.body.monospaced())
                                    .foregroundStyle(.primary)
                                    .lineLimit(nil)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            // Expanded meta section
                            if isExpanded {
                                metaView(for: entry)
                                    .padding(.leading, 26)
                                    .padding(.top, 4)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 3)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            withAnimation(.easeInOut(duration: 0.15)) {
                                if expandedEntries.contains(entry.id) {
                                    expandedEntries.remove(entry.id)
                                } else {
                                    expandedEntries.insert(entry.id)
                                }
                            }
                        }
                        .id("log-\(entry.id)")
                    }
                }
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .onChange(of: logStore.filteredEntries.count) { oldCount, newCount in
                    if scrollToBottom && newCount > oldCount {
                        if let lastEntry = logStore.filteredEntries.last {
                            withAnimation {
                                proxy.scrollTo("log-\(lastEntry.id)", anchor: .bottom)
                            }
                        }
                    }
                }
                .onAppear {
                    if let lastEntry = logStore.filteredEntries.last {
                        proxy.scrollTo("log-\(lastEntry.id)", anchor: .bottom)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func metaView(for entry: BridgeLogEntry) -> some View {
        if let meta = entry.meta, !meta.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                ForEach(meta.keys.sorted(), id: \.self) { key in
                    HStack(spacing: 4) {
                        Text(key + ":")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                        Text(formatMetaValue(meta[key]!))
                            .font(.caption.monospaced())
                            .foregroundStyle(.primary)
                    }
                }
            }
            .padding(6)
            .background(Color.gray.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 4))
        } else {
            Text(L10n.string("logs.meta.empty"))
                .font(.caption)
                .foregroundStyle(.tertiary)
                .padding(6)
        }
    }

    // MARK: - Helpers

    private func levelColor(_ level: BridgeLogLevel) -> Color {
        switch level {
        case .debug: return .secondary
        case .info: return .accentColor
        case .warn: return Color(nsColor: .systemOrange)
        case .error: return Color(nsColor: .systemRed)
        }
    }

    private func categoryColor(_ category: String) -> Color {
        // Deterministic hash-based coloring for categories
        let hash = category.hash
        let colors: [Color] = [
            .blue, .purple, .pink, .red, .orange, .yellow, .green, .cyan, .indigo, .teal
        ]
        let index = abs(hash) % colors.count
        return colors[index]
    }

    private func formatTimestamp(_ date: Date) -> String {
        if useRelativeTimestamp {
            return formatRelativeTime(date)
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: date)
    }

    private func formatRelativeTime(_ date: Date) -> String {
        let elapsed = -date.timeIntervalSinceNow
        if elapsed < 1 { return L10n.string("logs.relative.now") }
        if elapsed < 60 { return L10n.format("logs.relative.secondsAgo", Int(elapsed)) }
        if elapsed < 3600 { return L10n.format("logs.relative.minutesAgo", Int(elapsed / 60)) }
        if elapsed < 86400 { return L10n.format("logs.relative.hoursAgo", Int(elapsed / 3600)) }
        return L10n.format("logs.relative.daysAgo", Int(elapsed / 86400))
    }

    private func formatMetaValue(_ value: AnyCodableValue) -> String {
        switch value {
        case .string(let s): return s
        case .int(let i): return "\(i)"
        case .double(let d): return String(format: "%.2f", d)
        case .bool(let b): return b ? "true" : "false"
        }
    }

    private func revealLogFiles() {
        let dir = logsDirectory
        if FileManager.default.fileExists(atPath: dir) {
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: dir)
        } else {
            // Create directory if it doesn't exist, then reveal
            try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: dir)
        }
        log.info("Revealed logs directory in Finder")
    }

    private func openLogsInTerminal() {
        let dir = logsDirectory
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", "Terminal", dir]

        do {
            try process.run()
            log.info("Opened Terminal at logs directory")
        } catch {
            log.error("Failed to open Terminal: \(error.localizedDescription)")
        }
    }

    private func exportFiltered() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [UTType.jsonl]
        let dateStr = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd-HHmmss"; return f.string(from: Date()) }()
        panel.nameFieldStringValue = "shipyard-logs-\(dateStr).jsonl"
        panel.canCreateDirectories = true

        if panel.runModal() == .OK, let url = panel.url {
            do {
                try logStore.exportFiltered(to: url)
                NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: url.deletingLastPathComponent().path)
                log.debug("Exported logs to \(url.path, privacy: .public)")
            } catch {
                log.error("Export failed: \(error.localizedDescription, privacy: .public)")
            }
        }
    }
}

// MARK: - Extension for UTType

extension UTType {
    static let jsonl = UTType(filenameExtension: "jsonl") ?? .plainText
}
