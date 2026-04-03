---
id: SPEC-021
priority: 1
layer: 0
type: feature
status: done
after: [SPEC-022]
prior_attempts: []
nfrs: [NFR-001, NFR-002]
created: 2026-03-30
---

# Startup Performance Profiling & Instrumentation

## Problem

Shipyard has a ~10s startup hang that makes the app feel broken on launch. Prior trace analysis (see `SPEC_REDOWORK_ORDER.md` and UX-005 block reason) identified multiple suspects — MenuBarExtra scene rebuilds, `loadConfig()`, auto-start process spawning, cross-scene invalidation cascades — but no systematic measurement exists. We need structured instrumentation that:

1. Measures every startup phase with wall-clock timestamps
2. Covers both the app side (SwiftUI scenes, registry mutations, environment wiring) and the child MCP side (process spawn → stdio ready → tools discovered)
3. Produces a machine-readable startup report so we can track regressions across builds
4. Runs automatically on every launch (not just under Instruments)

Without this, any fix is a guess. With it, we can identify the exact phase(s) consuming >1s and fix them surgically.

## Requirements

- [ ] R1: Add a `StartupProfiler` singleton that records timestamped phases with labels (e.g., `"registry.init"`, `"loadConfig"`, `"autoStart.begin"`, `"autoStart.complete"`, `"discovery.begin"`, `"discovery.complete"`, `"firstSceneRender"`)
- [ ] R2: Each phase records `CFAbsoluteTimeGetCurrent()` start and end, with computed duration in milliseconds
- [ ] R3: Instrument `ShipyardApp.init`, `.task {}` block, `MCPRegistry.discover()`, `MCPRegistry.loadConfig()`, `AutoStartManager.autoStart()`, `ProcessManager.startServer()` (per server), and the first `MainWindow.body` evaluation
- [ ] R4: Instrument child MCP startup: measure time from `Process.launch()` to first successful stdio response (the `initialize` handshake). Log per-server: name, spawn time, handshake time, total ready time
- [ ] R5: Instrument `GatewayRegistry.discoverTools(for:)` — measure per-server tool discovery time
- [ ] R6: On startup completion (all servers started, tools discovered), log the full startup report to the app's log system (L3 level) as structured JSON
- [ ] R7: Write the startup report to `~/.config/shipyard/startup-profile.json` (overwritten each launch) for external analysis
- [ ] R8: Add a "Startup Profile" section in the About tab showing last startup time breakdown (total time, top 3 slowest phases)
- [ ] R9: If total startup time exceeds 4s, log a L2 warning with the top 3 slowest phases

## Acceptance Criteria

- [ ] AC 1: Launching Shipyard produces `startup-profile.json` at `~/.config/shipyard/` with phase-level timing data
- [ ] AC 2: JSON contains at minimum: `total_ms`, `phases[]` (each with `label`, `start_ms`, `end_ms`, `duration_ms`), `servers[]` (each with `name`, `spawn_ms`, `handshake_ms`, `tools_discovered`, `total_ms`)
- [ ] AC 3: About tab shows "Last startup: Xs" with expandable breakdown of phases >500ms
- [ ] AC 4: Console log (L3) emits the full startup report as one structured JSON line
- [ ] AC 5: If startup >4s, an L2 warning appears in logs with the top 3 bottleneck phases
- [ ] AC 6: Profiling overhead is <50ms (the profiler itself must not contribute to the hang)
- [ ] AC 7: Build succeeds with zero errors; all existing tests pass
- [ ] AC 8: No SwiftUI faults introduced (NFR-001)

## Context

### Prior analysis (DO NOT re-derive — use these findings):

From `SPEC_REDOWORK_ORDER.md` — ranked hang suspects:
1. **SPEC-019 `loadConfig()`** — adds servers during startup → registry mutations → scene invalidation cascade
2. **SPEC-005 auto-start** — spawns child processes during startup → each process state change triggers registry updates
3. **Settings scene** — `@Environment(MCPRegistry.self)` means every registry change rebuilds Settings even when hidden
4. **MenuBarExtra computed icon** — `menuBarIconName`/`menuBarIconColor` read `registry.registeredServers` in label closure → every change triggers `NSStatusBarButton.setImage`
5. **SPEC-011 execution queue panel** — always-visible, observes ExecutionQueueManager

From UX-005 trace evidence:
- 725 samples in `AppDelegate.makeMainMenu(updateImmediately:)`
- 542 samples in `AppKitMainMenuItem.updateMainMenu(...)`
- 386 samples in `MenuBarExtraController.updateButton(_:)`
- 241 samples in `NSStatusBarButton.setImage`
- Synchronous `SMAppService.status` call from `MenuBarView.body`

### Key files:
- `Shipyard/App/ShipyardApp.swift` — startup wiring, scene declarations
- `Shipyard/Services/MCPRegistry.swift` — `discover()`, `loadConfig()`, server state
- `Shipyard/Services/ProcessManager.swift` — `startServer()`, child process lifecycle
- `Shipyard/Services/GatewayRegistry.swift` — `discoverTools(for:)`
- `Shipyard/Services/AutoStartManager.swift` — auto-start logic
- `Shipyard/Services/SocketServer.swift` — stdio MCP communication

### Note on SPEC-022:
SPEC-022 removes MenuBarExtra entirely. This eliminates suspect #4 (computed icon triggering setImage on every registry change) before profiling begins. Profile results should reflect the post-MenuBarExtra-removal state.

## Alternatives Considered

- **Instruments-only approach (rejected):** Instruments gives deep traces but requires manual setup, can't run automatically, and produces non-machine-readable output. We need automatic, per-launch profiling that detects regressions.
- **os_signpost only (rejected):** Good for Instruments integration but doesn't produce a standalone report. Could be added later as a complement.
- **Startup timer only (rejected):** A single "startup took Xs" number doesn't tell us which phase is slow. Phase-level breakdown is essential.

## Scenarios

1. Developer launches Shipyard after a code change → app starts → `startup-profile.json` is written → developer opens it and sees that `autoStart` took 6.2s (3 servers × ~2s each) → targets async autostart as the fix
2. User opens About tab → sees "Last startup: 3.1s" with breakdown: `discovery: 0.8s, loadConfig: 0.3s, autoStart: 1.5s, firstRender: 0.5s` → knows the app is healthy
3. A regression is introduced → startup goes from 3s to 12s → L2 warning fires: "Startup exceeded 4s (12.1s). Top bottlenecks: loadConfig (8.3s), autoStart (2.1s), discovery (1.2s)" → developer catches it immediately in logs

## Out of Scope

- Actually fixing the hang (that comes after profiling identifies the bottleneck)
- Instruments/os_signpost integration (future enhancement)
- Continuous performance monitoring in production (future)
- Profiling runtime performance (this spec is startup-only)

## Notes for the Agent

- **Read `DevKB/swift.md`** before writing code
- Use `CFAbsoluteTimeGetCurrent()` for timing — it's monotonic enough for ms-level startup measurement and has no framework dependency
- The `StartupProfiler` should be a simple class with `func begin(_ label: String)` / `func end(_ label: String)` / `func report() -> StartupReport` — don't over-engineer it
- For per-server timing, `ProcessManager.startServer()` is the entry point. The handshake completion is when `MCPBridge.initialize()` returns successfully
- Write `startup-profile.json` atomically (`Data.write(to:options:.atomic)`)
- The About tab section should be read-only, minimal UI — just a `DisclosureGroup` with timing data
- Do NOT use `os_log` or `Logger` for the profiler itself — use `print` or direct file writes to avoid any framework overhead during measurement
- Build after every change — use `mcp__xcode__BuildProject`
