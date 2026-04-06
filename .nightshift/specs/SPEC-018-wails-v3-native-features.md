---
id: SPEC-018
template_version: 2
priority: 3
layer: 3
type: feature
status: blocked
after: [SPEC-017]
prior_attempts: []
created: 2026-04-06
---

# Block Reason

Blocked on two conditions:
1. **SPEC-017** (Wails v2 desktop app) must be complete first — this spec builds on the v2 foundation.
2. **Wails v3 must reach beta or stable.** As of 2026-04-06, v3 is at alpha.74 with no announced release date. The maintainer says "nearly ready" but the API is not frozen and breaking changes still land. The migration guide doesn't exist yet (gated on beta). **Unblock signal:** Wails v3.0.0-beta.1 release on GitHub, or the official migration guide published at v3alpha.wails.io/migration/v2-to-v3/.

# Wails v3 Native Desktop Features

## Problem

SPEC-017 delivers a standalone desktop app via Wails v2, but v2 has significant limitations:
- **No system tray** — Shipyard can't run in the background with a tray icon. Users must keep the window open or the app exits.
- **Single window only** — users can't detach Timeline, Tool Browser, or History into separate windows for multi-monitor workflows.
- **No native headless mode** — the `--headless` flag in SPEC-017 is a conditional skip of `wails.Run()`, not a built-in server mode.

Wails v3 addresses all three with first-class features: system tray, multi-window, and server build mode.

## Requirements

- [ ] R1: Migrate from Wails v2 to v3 — all existing functionality preserved
- [ ] R2: System tray icon — Shipyard runs in background, dashboard opens on tray click
- [ ] R3: Multi-window support — detach any panel (Timeline, Tools, History, Servers) into a separate window
- [ ] R4: Windows sync in real-time — a tool call captured in one view updates all open windows
- [ ] R5: Server build mode — `wails3 task build:server` produces a headless binary (replaces `--headless` flag)
- [ ] R6: Window layout persistence — save/restore which panels are detached and their positions

## Acceptance Criteria

- [ ] AC 1: All 216+ existing tests pass after v3 migration (no regressions)
- [ ] AC 2: Shipyard icon appears in macOS menu bar tray; clicking it toggles the main window
- [ ] AC 3: Right-clicking tray icon shows menu: "Show Dashboard", "Quit"
- [ ] AC 4: Closing the main window hides to tray (app stays running); Quit from tray exits the app
- [ ] AC 5: User can right-click a panel tab → "Open in New Window" → panel detaches to a separate native window
- [ ] AC 6: A tool call appears simultaneously in Timeline window AND History window (if both open)
- [ ] AC 7: `wails3 task build:server` produces a binary that runs headless, serves the dashboard over HTTP
- [ ] AC 8: Window positions and detached state are saved to a config file and restored on next launch
- [ ] AC 9: Binary size stays under 30 MB on macOS arm64

## Context

### Wails v3 Architecture (from research)

**Multi-window:**
- `app.NewWebviewWindowWithOptions(...)` creates additional windows
- Each window can load a different route via `SetURL("/timeline")`
- All windows share the same Go process — services are shared, no IPC needed
- State sync via unified event system: `app.EmitEvent("name", data)` broadcasts to all windows
- Each window has its own IPC bridge to Go but talks to the same backend

**System tray (v3 native):**
- `app.SystemTray.New()` creates tray icon
- `systemTray.AttachWindow(window)` binds a window to the tray
- `HideOnFocusLost: true` for auto-hide behavior
- macOS: template icons for light/dark mode, `ActivationPolicyAccessory` for menu-bar-only mode
- Known alpha bugs: left-click crash on Windows flyout (#3270), Linux context menu hides app (#4494)

**Server build mode:**
- Build with `-tags server` — no native window, no GUI dependencies
- App runs as pure HTTP server; events use WebSocket to connected browsers
- Same codebase compiles to desktop OR server — zero conditional logic needed
- Configurable via `WAILS_SERVER_HOST` and `WAILS_SERVER_PORT` env vars

### Migration Effort (from research)

Estimated 4-7 working days for Shipyard-class app:
- **Go code:** ~60-70% of files touched (mostly mechanical import path changes + service/event API updates)
- **JS frontend:** ~20-30% of files touched (runtime import path + event handler signatures)
- **Highest-effort items:** runtime context removal (threading `ctx` is deeply embedded), entry point rewrite, event system migration, build system (`Taskfile.yml` replaces `wails build`)

### Key v2→v3 Breaking Changes

| Area | v2 | v3 |
|------|----|----|
| Entry point | `wails.Run(&options.App{...})` | `application.New(opts)` then `app.Run()` |
| Binding | `Bind: []interface{}{&app}` | `Services: []application.Service{application.NewService(&app)}` |
| Lifecycle | `OnStartup(ctx)` | `ServiceStartup(ctx, options) error` |
| Events (Go) | `runtime.EventsEmit(ctx, "name", data)` | `app.Events.Emit("name", data)` |
| Events (JS) | `runtime.EventsOn("name", (data) => {})` | `Events.On("name", (event) => { event.Data })` |
| Runtime JS | `@wailsapp/runtime` or generated `wailsjs/` | `@wailsio/runtime` (tree-shakeable) |
| Build | `wails build` | `wails3 task build` (Taskfile-based) |
| Window | Single window in options | `app.NewWebviewWindow()` (multiple) |

### Known v3 Alpha Issues (as of alpha.74)

- **macOS:** Generally stable. Most reported bugs fixed. Watch for AppKit main-thread issues.
- **Windows:** Build hangs with large node_modules (fixed alpha.72). DPI scaling edge cases.
- **Linux:** Least stable. GTK4 experimental. File dialog crashes (#3683). Systray issues on Wayland.
- **Cross-platform:** Notification service needs explicit `ServiceStartup` call (#4449).

## Alternatives Considered

- **Approach A (this spec): Full v3 migration** — system tray, multi-window, server mode. Chosen: these are the features that make Shipyard a "real app."
- **Approach B (rejected): v2 + third-party systray** — `github.com/getlantern/systray` can add tray to v2. Rejected: no multi-window, hack-ish integration, still need v3 eventually.
- **Approach C (rejected): Dockview-only in v2** — IDE-like dockable panels within single window. Not rejected entirely — SPEC-017 recommends Dockview as a v2 interim. But true multi-window requires v3.

## Scenarios

1. User launches Shipyard → main window opens with all panels → user drags Timeline tab to second monitor → Timeline opens in separate window → tool calls stream to both windows simultaneously
2. User closes main window → app minimizes to tray → tray icon visible in macOS menu bar → user clicks tray icon → main window reappears with layout preserved
3. User right-clicks tray → selects "Quit" → all windows close → child MCP processes terminated → app exits cleanly
4. CI pipeline runs `wails3 task build:server` → produces headless binary → binary starts on port 9417 → curl hits `/api/servers` successfully → no window, no GUI dependencies
5. User detaches Tools and History to separate windows → closes app → reopens → same 3 windows restore in same positions

## Out of Scope

- Auto-update / Sparkle integration (separate spec)
- macOS code signing and notarization (separate spec)
- Native file drag-and-drop into Shipyard
- Touch Bar integration
- Custom window chrome / frameless windows
- Multiple independent Shipyard instances

## Research Hints

- Files to study:
  - `cmd/shipyard/main.go` — entry point to rewrite for v3
  - `app.go` (created in SPEC-017) — service struct to convert to v3 pattern
  - `internal/web/ui/index.html` — all JS runtime calls to update
  - Wails v3 examples: `github.com/wailsapp/wails/v3/examples/systray-basic/`, `events/`, `window/`
- Patterns to look for:
  - All `runtime.X(ctx, ...)` calls in Go code → convert to `app.X.Method(...)`
  - All `@wailsapp/runtime` imports in JS → convert to `@wailsio/runtime`
  - Event emission/subscription patterns → update signatures
- DevKB: `DevKB/go.md`
- Cortex tags: shipyard, wails, wails-v3, desktop-app, migration

## Gap Protocol

- Research-acceptable gaps: Wails v3 API details (check latest alpha docs), Taskfile configuration
- Stop-immediately gaps: v3 API has changed since this spec was written (breaking changes between alphas), systray crashes on target platform
- Max research subagents before stopping: 3

---

## Implementation Guide

### Pre-Migration Checklist

Before starting, verify:
- [ ] Wails v3 has reached beta (or team has accepted alpha risk)
- [ ] SPEC-017 is complete and stable
- [ ] `wails3 doctor` passes on the development machine
- [ ] Go version meets v3 requirement (1.25+)

### Phase 1: Mechanical Migration (1-2 days)

1. Update `go.mod`: `github.com/wailsapp/wails/v2` → `github.com/wailsapp/wails/v3`
2. Update all Go import paths (grep + replace)
3. Rewrite `main.go` entry point to v3 `application.New()` + `app.Run()` pattern
4. Convert service struct: rename lifecycle methods (`OnStartup` → `ServiceStartup`)
5. Convert `Bind` to `Services` in app options
6. Run tests — internal packages (`capture`, `proxy`, `manager`) should pass unchanged

### Phase 2: Event System Migration (1 day)

1. Replace all `runtime.EventsEmit(ctx, ...)` with `app.Events.Emit(...)`
2. Update JS event handlers: `runtime.EventsOn("name", fn)` → `Events.On("name", (event) => { event.Data })`
3. Update `@wailsapp/runtime` imports to `@wailsio/runtime`
4. Test real-time updates work (traffic timeline, server status)

### Phase 3: System Tray (1 day)

1. Create system tray with icon: `app.SystemTray.New()`
2. Attach main window to tray
3. Implement hide-on-close behavior (`OnBeforeClose` → hide window instead of quit)
4. Add tray menu: "Show Dashboard", separator, "Quit"
5. macOS: use template icon for light/dark mode
6. Test: close window → tray visible → click tray → window reappears

### Phase 4: Multi-Window (2-3 days)

1. Refactor frontend routing — each panel needs to be loadable at a URL route:
   - `/` or `/timeline` — Traffic Timeline
   - `/tools` — Tool Browser
   - `/history` — History & Replay
   - `/servers` — Server Management
2. Add "Open in New Window" context menu on panel tabs
3. On detach: `app.NewWebviewWindowWithOptions({URL: "/tools", Title: "Tools - Shipyard"})`
4. State sync: Go backend emits events; all windows subscribe
5. Window tracking: maintain a `map[string]*WebviewWindow` in Go for cleanup
6. Layout persistence: save window state (position, size, which panels detached) to JSON config
7. On startup: restore saved layout

### Phase 5: Server Build Mode (0.5 day)

1. Add `Taskfile.yml` with `build:server` task
2. Verify headless binary works (no GUI dependencies)
3. Test: start server binary → hit API endpoints from browser → real-time events via WebSocket
4. Remove old `--headless` flag (server mode replaces it)

### Phase 6: Build System & Testing (1-2 days)

1. Create `Taskfile.yml` for all build targets (dev, build, build:server, package)
2. Update CI/CD for v3 build commands
3. Cross-platform test matrix: macOS (primary), Windows, Linux
4. Test system tray on each platform
5. Test multi-window on each platform
6. Verify binary size under 30 MB

## Notes for the Agent

- **Check v3 alpha version before starting** — API may have changed since this spec was written (alpha.74). Read the latest changelog at `v3alpha.wails.io/changelog/`.
- The localhost HTTP server pattern from SPEC-017 STAYS. v3 adds native features on top; it doesn't replace the proxy architecture.
- For multi-window: each window loads the same SPA bundle but different route. This means the frontend needs client-side routing (hash-based is simplest for vanilla JS: `#/timeline`, `#/tools`, etc.). The current tab-based navigation already uses hash routing — extend it.
- System tray bugs on Linux/Wayland are known. If Linux tray doesn't work, degrade gracefully (no tray icon, standard window behavior). Don't block the spec on Linux tray.
- Server build mode may require conditional compilation (`//go:build !server`). Study the Wails v3 server example at `v3/examples/server/`.
