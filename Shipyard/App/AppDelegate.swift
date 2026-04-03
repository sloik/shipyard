import AppKit
import Darwin
import os

private let log = Logger(subsystem: "com.shipyard.app", category: "AppDelegate")

/// AppDelegate ensures the app activates and shows its window
/// when launched from Xcode (SPM executables don't auto-activate like .app bundles).
/// Also handles app lifecycle for SPEC-005 auto-start.
final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Shared reference to save running servers on quit (set by ShipyardApp)
    var autoStartManager: AutoStartManager?
    var registry: MCPRegistry?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Ignore SIGPIPE to prevent crash when client disconnects from Unix socket.
        // Without this, write() to a closed socket sends SIGPIPE which terminates the process.
        // With signal(SIGPIPE, SIG_IGN), write() returns -1 with errno=EPIPE instead,
        // allowing us to handle the error gracefully.
        signal(SIGPIPE, SIG_IGN)

        // Force the app to the foreground — necessary for SPM executables
        // launched from Xcode which don't have a proper .app bundle
        NSApp.activate(ignoringOtherApps: true)

        // Ensure the main window is visible
        if let window = NSApp.windows.first {
            window.makeKeyAndOrderFront(nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ application: NSApplication) -> Bool {
        // Keep running in menu bar when window is closed (Phase 3)
        false
    }

    func applicationShouldTerminateLocallyAfterLastWindowClosed(_ application: NSApplication) -> Bool {
        // Keep running in menu bar when window is closed
        false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // Save running servers before quit
        if let autoStartManager = autoStartManager, let registry = registry {
            let runningServers = registry.registeredServers.filter { $0.state.isRunning }
            autoStartManager.saveRunningServers(runningServers)
            log.info("Saved \(runningServers.count) running servers before quit")
        }
        return .terminateNow
    }
}
