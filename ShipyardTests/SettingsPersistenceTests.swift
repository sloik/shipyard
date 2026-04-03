import Testing
import Foundation
import SwiftUI
@testable import Shipyard

@Suite("Settings Persistence")
struct SettingsPersistenceTests {

    @MainActor
    private func makeManager() -> AutoStartManager {
        AutoStartManager()
    }

    // MARK: - Settings Persistence Tests

    @Test("Settings saved to UserDefaults are restored on next load")
    @available(macOS 14.0, *)
    @MainActor
    func settingsPersistenceAcrossLoads() {
        // Clean up
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        // Create manager and save settings
        let manager1 = makeManager()
        manager1.setRestoreServersEnabled(false)
        manager1.setAutoStartDelay(5)

        // Create new manager — should load saved settings
        let manager2 = makeManager()
        #expect(manager2.settings.restoreServersEnabled == false)
        #expect(manager2.settings.autoStartDelay == 5)
    }

    @Test("Toggle OFF → no auto-start triggered")
    @available(macOS 14.0, *)
    @MainActor
    func toggleOffDisablesAutoStart() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = makeManager()
        manager.setRestoreServersEnabled(false)

        #expect(manager.settings.restoreServersEnabled == false)
    }

    @Test("Toggle ON after OFF → auto-start resumes")
    @available(macOS 14.0, *)
    @MainActor
    func toggleOnAfterOff() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = makeManager()
        manager.setRestoreServersEnabled(false)
        #expect(manager.settings.restoreServersEnabled == false)

        manager.setRestoreServersEnabled(true)
        #expect(manager.settings.restoreServersEnabled == true)
    }

    @Test("Delay setting persists across app restarts")
    @available(macOS 14.0, *)
    @MainActor
    func delaySetting() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager1 = makeManager()
        manager1.setAutoStartDelay(7)

        // Simulate app restart
        let manager2 = makeManager()
        #expect(manager2.settings.autoStartDelay == 7)
    }

    @Test("Invalid delay values are clamped")
    @available(macOS 14.0, *)
    @MainActor
    func invalidDelayClamped() {
        let manager = makeManager()

        // Try to set invalid values
        manager.setAutoStartDelay(-10)
        #expect(manager.settings.autoStartDelay >= 1)

        manager.setAutoStartDelay(50)
        #expect(manager.settings.autoStartDelay <= 10)
    }

    @Test("Default settings on first launch")
    @available(macOS 14.0, *)
    @MainActor
    func defaultSettingsFirstLaunch() {
        UserDefaults.standard.removeObject(forKey: AutoStartManager.autoStartSettingsKey)

        let manager = makeManager()
        #expect(manager.settings.restoreServersEnabled == true)
        #expect(manager.settings.autoStartDelay == 2)
    }
}
