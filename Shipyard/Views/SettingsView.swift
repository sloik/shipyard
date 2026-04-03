import SwiftUI
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "SettingsView")

/// Settings window for Shipyard preferences
struct SettingsView: View {
    @Environment(AutoStartManager.self) var autoStartManager
    @AppStorage("jsonViewer.fontSize") private var jsonViewerFontSize: Double = 11

    /// Local state bindings for the form
    @State private var restoreServersEnabled: Bool = true
    @State private var autoStartDelay: Int = 2

    var body: some View {
        Form {
            Section(header: Text(L10n.string("settings.autoStart.title"))) {
                Toggle(L10n.string("settings.autoStart.toggleLabel"), isOn: $restoreServersEnabled)
                    .onChange(of: restoreServersEnabled) { _, newValue in
                        autoStartManager.setRestoreServersEnabled(newValue)
                        log.info("Auto-start restore enabled: \(newValue)")
                    }
                    .help(L10n.string("settings.autoStart.toggleHelp"))

                HStack {
                    Text(L10n.string("settings.autoStart.delayLabel"))
                    Spacer()
                    HStack(spacing: 8) {
                        Stepper(value: $autoStartDelay, in: 1...10) {
                            Text(L10n.format("settings.autoStart.delayValue", autoStartDelay))
                                .monospacedDigit()
                                .frame(minWidth: 30)
                        }
                        .onChange(of: autoStartDelay) { _, newValue in
                            autoStartManager.setAutoStartDelay(newValue)
                            log.info("Auto-start delay set to: \(newValue)s")
                        }
                    }
                }
                .help(L10n.string("settings.autoStart.delayHelp"))

                Text(L10n.string("settings.autoStart.delayHint"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section(header: Text(L10n.string("settings.jsonViewer.title"))) {
                HStack {
                    Text(L10n.string("settings.jsonViewer.fontSizeLabel"))
                    Spacer()
                    HStack(spacing: 8) {
                        Stepper(value: $jsonViewerFontSize, in: 9...18) {
                            Text(L10n.format("settings.jsonViewer.fontSizeValue", Int(jsonViewerFontSize)))
                                .monospacedDigit()
                                .frame(minWidth: 35)
                        }
                        .onChange(of: jsonViewerFontSize) { _, newSize in
                            log.info("JSON viewer font size set to: \(Int(newSize))pt")
                        }
                    }
                }
                .help(L10n.string("settings.jsonViewer.fontSizeHelp"))

                Text(L10n.string("settings.jsonViewer.fontSizeHint"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(minWidth: 400, minHeight: 280)
        .onAppear {
            restoreServersEnabled = autoStartManager.settings.restoreServersEnabled
            autoStartDelay = autoStartManager.settings.autoStartDelay
        }
    }
}

#Preview {
    @Previewable @State var autoStartManager = AutoStartManager()

    SettingsView()
        .environment(autoStartManager)
}
