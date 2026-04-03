import AppKit
import SwiftUI

struct AboutView: View {
    @State private var startupReport: StartupProfileReport?
    @State private var startupBreakdownExpanded = false

    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
    }

    private var buildNumber: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
    }

    var body: some View {
        VStack(spacing: 20) {
            // App icon
            Image(systemName: "ferry.fill")
                .font(.system(size: 64))
                .foregroundStyle(.tint)
                .accessibilityLabel(L10n.string("about.icon.accessibilityLabel"))

            // App name and version
            VStack(spacing: 4) {
                Text(verbatim: "Shipyard")
                    .font(.title)
                    .fontWeight(.bold)

                Text(L10n.format("about.version.value", appVersion, buildNumber))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            // Tagline
            Text(L10n.string("about.tagline.message"))
                .font(.body)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Divider()
                .frame(maxWidth: 200)

            // Description
            VStack(spacing: 8) {
                Text(L10n.string("about.description.message"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 300)
            }

            if let startupReport {
                Divider()
                    .frame(maxWidth: 300)

                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.string("about.startupProfile.title"))
                        .font(.headline)

                    Text(L10n.format("about.startupProfile.lastStartup", formatSeconds(startupReport.totalMs)))
                        .font(.subheadline)
                        .monospacedDigit()

                    let topThree = startupReport.phases
                        .sorted { $0.durationMs > $1.durationMs }
                        .prefix(3)
                        .map { phase in
                            "\(phase.label) (\(formatMilliseconds(phase.durationMs))ms)"
                        }
                        .joined(separator: ", ")

                    if !topThree.isEmpty {
                        Text(L10n.format("about.startupProfile.topThree", topThree))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    DisclosureGroup(L10n.string("about.startupProfile.slowPhasesTitle"), isExpanded: $startupBreakdownExpanded) {
                        let slowPhases = startupReport.phases
                            .filter { $0.durationMs > 500 }
                            .sorted { $0.durationMs > $1.durationMs }

                        if slowPhases.isEmpty {
                            Text(L10n.string("common.state.none"))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        } else {
                            ForEach(slowPhases, id: \.stableID) { phase in
                                HStack {
                                    Text(phase.label)
                                    Spacer()
                                    Text("\(formatMilliseconds(phase.durationMs))ms")
                                        .monospacedDigit()
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .font(.caption)
                }
                .frame(maxWidth: 320, alignment: .leading)
            }

            // Quick links
            VStack(spacing: 8) {
                Button(action: { openURL("https://modelcontextprotocol.io/docs") }) {
                    Label(L10n.string("about.action.documentationButton"), systemImage: "book")
                }
                .buttonStyle(.link)

                Button(action: { openLogsFolder() }) {
                    Label(L10n.string("common.action.openLogsFolder"), systemImage: "folder")
                }
                .buttonStyle(.link)

                Button(action: { openConfigFolder() }) {
                    Label(L10n.string("about.action.openConfigFolderButton"), systemImage: "gearshape")
                }
                .buttonStyle(.link)
            }

            Spacer()

            Text("© 2026 Inwestomat")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear {
            startupReport = StartupProfiler.shared.lastReport ?? StartupProfiler.shared.loadReportFromDisk()
        }
    }

    private func openURL(_ urlString: String) {
        if let url = URL(string: urlString) {
            NSWorkspace.shared.open(url)
        }
    }

    private func openLogsFolder() {
        NSWorkspace.shared.open(PathManager.shared.logsDirectory)
    }

    private func openConfigFolder() {
        NSWorkspace.shared.open(PathManager.shared.rootDirectory)
    }

    private func formatMilliseconds(_ value: Double) -> String {
        String(format: "%.0f", value)
    }

    private func formatSeconds(_ milliseconds: Double) -> String {
        String(format: "%.2f", milliseconds / 1000)
    }
}
