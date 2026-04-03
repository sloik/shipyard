import Testing
@testable import Shipyard

@Suite("SPEC-025 — Builtin lifecycle controls", .timeLimit(.minutes(1)))
struct SPEC025BuiltinControlsTests {
    @Test("Shipyard builtin shows restart only in running state")
    @available(macOS 14.0, *)
    @MainActor
    func builtinShowsRestartOnly() {
        let visibility = MCPRowLifecycleControlVisibility.resolve(
            isDisabled: false,
            source: .synthetic,
            isBuiltin: true,
            isRunning: true,
            hasStart: true,
            hasStop: true,
            hasRestart: true
        )

        #expect(visibility.showSection)
        #expect(!visibility.showStart)
        #expect(!visibility.showStop)
        #expect(visibility.showRestart)
    }

    @Test("Non-builtin running server shows stop and restart")
    @available(macOS 14.0, *)
    @MainActor
    func regularRunningShowsStopAndRestart() {
        let visibility = MCPRowLifecycleControlVisibility.resolve(
            isDisabled: false,
            source: .config,
            isBuiltin: false,
            isRunning: true,
            hasStart: true,
            hasStop: true,
            hasRestart: true
        )

        #expect(visibility.showSection)
        #expect(!visibility.showStart)
        #expect(visibility.showStop)
        #expect(visibility.showRestart)
    }

    @Test("Builtin idle state still hides start")
    @available(macOS 14.0, *)
    @MainActor
    func builtinIdleHidesStart() {
        let visibility = MCPRowLifecycleControlVisibility.resolve(
            isDisabled: false,
            source: .synthetic,
            isBuiltin: true,
            isRunning: false,
            hasStart: true,
            hasStop: true,
            hasRestart: true
        )

        #expect(visibility.showSection)
        #expect(!visibility.showStart)
        #expect(!visibility.showStop)
        #expect(!visibility.showRestart)
    }
}
