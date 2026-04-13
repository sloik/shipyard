---
id: SPEC-017
template_version: 2
priority: 1
layer: 2
type: feature
status: done
after: []
prior_attempts: []
created: 2026-04-06
---

# Standalone Desktop App via Wails

## Problem

Shipyard currently requires a two-step workflow: (1) run `shipyard --config servers.json` in a terminal, (2) manually open `http://localhost:9417` in a browser. This feels like a dev tool, not a product. Comparable tools (Postman, Insomnia, Tiny RDM) launch as standalone apps — double-click an icon, the UI appears.

The current architecture is already 90% there: single Go binary, embedded web UI, everything in one process. The missing piece is a native window wrapper so the user never opens a browser tab.

## Requirements

- [x] R1: Shipyard launches as a native desktop app (double-click `.app` on macOS, `.exe` on Windows)
- [x] R2: The dashboard UI appears in a native window, not a browser tab
- [x] R3: All existing functionality works identically (timeline, tools, history, servers, sessions, schema detection, profiling)
- [x] R4: Real-time updates (WebSocket) work inside the native window
- [x] R5: CLI/headless mode preserved via `--headless` flag (no window, HTTP server only — for CI, servers, scripting)
- [x] R6: The proxy HTTP API remains accessible on `localhost:<port>` for external MCP clients
- [x] R7: Build produces platform-native artifacts (`.app` bundle on macOS, `.exe` on Windows, ELF on Linux)
- [x] R8: Binary size stays under 25 MB (currently ~12 MB)

## Acceptance Criteria

- [x] AC 1: Running `shipyard --config servers.json` opens a native window with the dashboard loaded — no browser needed
- [x] AC 2: Running `shipyard --headless --config servers.json` starts the proxy + HTTP server with no window (current behavior preserved)
- [x] AC 3: Traffic timeline updates in real-time inside the native window (WebSocket or equivalent)
- [x] AC 4: Tool invocation from the native window works (call tool → see response)
- [x] AC 5: An external MCP client can connect to `localhost:9417` while the desktop app is running (proxy function unchanged)
- [x] AC 6: `wails build` (or equivalent) produces a macOS `.app` bundle that launches on double-click
- [x] AC 7: All existing tests pass (216+ tests, no regressions)
- [x] AC 8: Binary size is under 25 MB on macOS arm64
- [x] AC 9: Window title shows "Shipyard" and version; window is resizable with a minimum size of 900x600
- [x] AC 10: App quits cleanly — child MCP processes are terminated, SQLite DB flushed, no orphan processes

## Context

### Current Architecture

Shipyard v2 is a single Go binary (~12 MB) that:
- Manages child MCP server processes via stdio proxy (`internal/proxy/`)
- Captures all JSON-RPC traffic to SQLite (`internal/capture/`)
- Serves a web dashboard on `localhost:9417` via embedded static assets (`internal/web/`)
- Pushes real-time updates via WebSocket (`internal/web/hub.go`)
- Uses `go:embed` to bake `index.html`, `ds.css`, `ds.js` into the binary

Key files:
- `cmd/shipyard/main.go` — entry point, CLI flags, startup orchestration
- `internal/web/server.go` — HTTP server, 20+ REST endpoints, embedded UI serving
- `internal/web/hub.go` — WebSocket broadcast hub (66 LOC)
- `internal/web/ui/` — frontend assets (vanilla JS, custom CSS design system)
- `internal/proxy/manager.go` — multi-server lifecycle management
- `internal/capture/store.go` — SQLite + JSONL capture

### Migration Impact (from architecture analysis)

**No changes needed (~70% of code):**
- `internal/capture/store.go` — pure SQLite, zero HTTP coupling
- `internal/proxy/proxy.go` — pure subprocess management
- `internal/proxy/manager.go` business logic — request correlation, schema watching, response tracking
- Configuration loading — JSON parsing, validation

**Minor changes:**
- `internal/web/hub.go` — no structural change; WebSocket stays (frontend connects to localhost)
- `internal/web/server.go` — HTTP server stays; Wails window loads from it

**Major changes:**
- `cmd/shipyard/main.go` — conditional Wails vs headless startup
- Build system — Makefile, `.goreleaser.yml` adapted for Wails
- Frontend assets — moved to Wails `frontend/` directory

### Framework Choice: Wails v2

**Why Wails:**
- Go-native — no second language (vs Tauri/Rust)
- Single binary output — same distribution story as today
- Uses OS WebView (WebKit on macOS, WebView2 on Windows) — no bundled Chromium
- ~8-15 MB overhead — within our 25 MB budget
- Vanilla JS frontend supported (no forced React/Vue)
- Mature (v2.12.0, March 2025), actively maintained

**Why v2 over v3:**
- v3 is alpha (v3.0.0-alpha.74, Feb 2026) — no stable release date
- v2 is production-stable and sufficient for core requirements
- v3 features (system tray, server build mode, multi-window) are nice-to-have, not blockers
- Future v3 migration path is documented (`v3alpha.wails.io/migration/v2-to-v3/`)

**Key Wails v2 properties:**
- `//go:embed all:frontend/dist` for asset embedding (same mechanism we use today)
- `OnStartup` lifecycle hook for starting background goroutines
- `OnBeforeClose` hook for graceful shutdown
- `AssetServer.Handler` option for serving dynamic API endpoints
- `wails build` produces `.app` bundle on macOS, `.exe` on Windows
- CGO required on macOS/Linux (for WebKit bindings) — does NOT break wazero SQLite

### Architectural Approach: Localhost Coexistence

The simplest and lowest-risk approach: **keep the HTTP server running on localhost:9417, have the Wails window point at it.**

```
┌─────────────────────────────────┐
│         Wails Native Window     │
│  ┌───────────────────────────┐  │
│  │   WebView (OS WebKit)     │  │
│  │   loads localhost:9417    │  │
│  │   fetch() → REST API     │  │
│  │   WebSocket → ws://9417  │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
         │ HTTP / WS │
┌────────┴───────────┴────────────┐
│   Go Process (single binary)    │
│  ┌──────────┐ ┌──────────────┐  │
│  │ HTTP Srv │ │ Proxy Manager│  │
│  │ :9417    │ │ (child MCPs) │  │
│  └──────────┘ └──────────────┘  │
│  ┌──────────┐ ┌──────────────┐  │
│  │ SQLite   │ │ WS Hub       │  │
│  └──────────┘ └──────────────┘  │
└─────────────────────────────────┘
```

**Why localhost coexistence (not Wails bindings):**
1. Zero frontend changes — all `fetch()` and `WebSocket` calls stay identical
2. External MCP clients can still connect to `localhost:9417` (proxy function preserved)
3. Headless mode is trivial — just skip `wails.Run()`, keep HTTP server
4. WebSocket works reliably (real localhost, not Wails internal protocol)
5. Migration is reversible — if Wails doesn't work out, rip it out and we're back to CLI+browser

**Risk: WebSocket in Wails WebView — RESOLVED (2026-04-06)**
Research flagged that `ws://` connections inside Wails webview can fail due to the `wails://` custom protocol (issue #1293). Spike validated this works: `ws://localhost:9417/ws` connects instantly from Wails webview in both dev and production builds. **One workaround required:** `InsecureSkipVerify: true` on `websocket.AcceptOptions` because the Wails webview origin is `wails://wails` (not `http://localhost`). This is safe for localhost-only communication. REST `fetch()` also works with `Access-Control-Allow-Origin: *`. Binary size: 9.4 MB (.app bundle). Spike: `spike/wails-websocket/`.

## Alternatives Considered

- **Approach A (this spec): Wails v2 + localhost coexistence** — Wails adds native window, HTTP server stays on localhost:9417 unchanged. Minimal code changes, reversible. Chosen for lowest risk.
- **Approach B (deferred): Wails v2 + AssetServer.Handler** — Route all API calls through Wails' internal asset handler instead of localhost. Eliminates port binding. Rejected: higher coupling, breaks external MCP client access, more frontend changes.
- **Approach C (deferred): Wails v3** — Native system tray, server build mode, better events. Rejected: alpha stability risk. Revisit when v3 reaches beta/stable.
- **Approach D (rejected): Tauri** — Lighter binaries (~3 MB) but requires Rust toolchain alongside Go. Go backend runs as sidecar process. Rejected: two-language complexity, sidecar coordination overhead.
- **Approach E (rejected): webview library** — Minimal Go library to open a native window. Gives a window but no app packaging, no build tooling, no lifecycle management. Too bare-bones.
- **Approach F (rejected): PWA manifest** — Zero-code approach: browser "installs" the web app. Rejected: still requires CLI running separately, no real app experience.

## Scenarios

1. User double-clicks Shipyard.app → native window opens → dashboard shows "No servers configured" → user clicks "Import from Claude Code" → servers appear → traffic flows in real-time
2. User runs `shipyard --headless --config servers.json` on a Linux CI server → proxy starts → HTTP API available on port 9417 → no window opens → process runs until SIGTERM
3. User has Shipyard.app running with 3 MCP servers → Claude Code connects to proxy on :9417 → tool calls appear in Shipyard timeline → user replays a call from the UI → response matches
4. User closes the Shipyard window → child MCP processes get SIGTERM → SQLite WAL is checkpointed → app exits with code 0 → no orphan processes in Activity Monitor
5. User runs `shipyard --config servers.json --port 8080` → window opens → dashboard loads from localhost:8080 → custom port works

## Out of Scope

- System tray icon / minimize to tray (requires Wails v3 — future spec)
- Auto-update mechanism (future — consider Sparkle on macOS)
- macOS code signing and notarization (separate spec for distribution)
- Windows installer (NSIS) — v2 can generate this but it's a distribution concern
- Multi-window support (separate timeline + tools windows — Wails v3 feature)
- Touch Bar / menu bar integration
- DMG creation with background image
- Application icon design (use placeholder for now)

## Research Hints

- Files to study:
  - `cmd/shipyard/main.go` — current startup flow, understand all flags
  - `internal/web/server.go` — how embed + HTTP serving works today
  - `internal/web/ui/index.html` — frontend entry point, all fetch/WS URLs
  - `Makefile` — current build targets
  - `.goreleaser.yml` — current release config
- Patterns to look for:
  - All `fetch("/api/...)` calls in `index.html` — these stay unchanged (localhost)
  - `new WebSocket(...)` connection in `index.html` — must work in Wails webview
  - `//go:embed` directives — will move to Wails frontend dir
- Wails references:
  - Wails v2 vanilla template: `wails init -n shipyard -t vanilla`
  - Lifecycle hooks: `OnStartup`, `OnDomReady`, `OnBeforeClose`, `OnShutdown`
  - AssetServer docs: `wails.io/docs/guides/dynamic-assets/`
  - Window options: `wails.io/docs/reference/options/#window`
- DevKB: `DevKB/go.md`
- Cortex tags: shipyard, wails, desktop-app

## Gap Protocol

- Research-acceptable gaps: Wails project structure conventions, wails.json configuration options, platform-specific build flags
- Stop-immediately gaps: WebSocket doesn't work in Wails webview connecting to localhost (AC 3 blocker), CGO breaks wazero SQLite, binary size exceeds 25 MB
- Max research subagents before stopping: 3

---

## Implementation Guide

### Phase 1: Spike — COMPLETE (2026-04-06)

WebSocket spike validated successfully. See `spike/wails-websocket/`. Key findings:
- WebSocket connects instantly from Wails webview to localhost:9417
- REST fetch works with `Access-Control-Allow-Origin: *`
- Requires `InsecureSkipVerify: true` on WebSocket accept (origin is `wails://wails`)
- Binary size: 9.4 MB (.app bundle), build time: 12s (arm64)
- Graceful shutdown works (context cancellation → HTTP server stop → WaitGroup)

### Phase 2: Scaffold Wails Project

1. Install Wails CLI: `go install github.com/wailsapp/wails/v2/cmd/wails@latest`
2. Run `wails doctor` to verify environment
3. Initialize Wails in the existing repo: restructure to match Wails layout
4. Move `internal/web/ui/*` to `frontend/` (or `frontend/dist/` if skipping build step)
5. Create `app.go` with the application struct
6. Update `go.mod` to add `github.com/wailsapp/wails/v2`

### Phase 3: Adapt Entry Point

Modify `cmd/shipyard/main.go`:

```
if --headless flag:
    // Current behavior: start HTTP server, block until signal
    startHTTPServer(ctx)
    <-ctx.Done()
else:
    // New behavior: start HTTP server in goroutine, then Wails
    go startHTTPServer(ctx)
    wails.Run(&options.App{
        Title:     "Shipyard",
        Width:     1280,
        Height:    800,
        MinWidth:  900,
        MinHeight: 600,
        AssetServer: &assetserver.Options{
            Assets: assets,  // frontend embed.FS
        },
        OnStartup:     app.startup,
        OnBeforeClose: app.beforeClose,
        OnShutdown:    app.shutdown,
    })
```

The `startup` method starts proxies. The `beforeClose` method triggers graceful shutdown (kill children, flush SQLite). The `shutdown` method does final cleanup.

**Key decision: Window URL**

Two sub-options for what the Wails window loads:

**Option A — Wails serves embedded assets, JS fetches from localhost:**
Frontend is embedded via Wails' asset handler (`//go:embed all:frontend/dist`). The HTML/CSS/JS loads from the embedded FS. All `fetch()` and `WebSocket` calls go to `http://localhost:9417`. This means the window loads instantly (no network) but API calls hit localhost.

**Option B — Window navigates to localhost:9417 directly:**
Use `wails.Run()` with no embedded assets. Instead, after the HTTP server starts, open the window pointing at `http://localhost:9417`. Simpler but window shows a blank page until the server is ready.

**Recommend Option A** — faster perceived startup, embedded assets are already the pattern.

### Phase 4: Frontend Adjustments

Minimal changes expected:
- Ensure all `fetch()` URLs are absolute (`http://localhost:${port}/api/...`) or use `window.location` resolution
- Verify WebSocket URL construction works from Wails context
- Test all 4 views (timeline, tools, history, servers)

### Phase 5: Build System

- Add `wails.json` configuration
- Update `Makefile`: add `wails-build`, `wails-dev` targets
- Update `.goreleaser.yml` for Wails cross-platform builds (note: macOS and Linux require native runners due to CGO)
- Verify `wails build` output is under 25 MB

### Phase 6: Testing

- Run all 216+ existing tests (they test internal packages — should pass unchanged)
- Add integration test: start app in headless mode, hit API endpoints
- Manual test: launch .app, configure servers, verify all views work
- Test graceful shutdown: close window, verify no orphan processes

## Notes for the Agent

- The HTTP server MUST stay on localhost. It's how MCP clients connect to the proxy. Wails is purely for the window — don't try to replace the HTTP server with Wails bindings.
- Don't restructure `internal/` packages. The Wails integration should be confined to `cmd/shipyard/main.go`, a new `app.go`, and the frontend asset location.
- The frontend is vanilla JS — no npm build step needed. Wails' `frontend:build` can be empty or a simple copy.
- Current `go:embed` in `internal/web/server.go` needs to coexist with Wails' embed. In headless mode, the HTTP server embeds and serves assets directly (current behavior). In desktop mode, Wails embeds them. Consider a shared embed.FS or conditional logic.
- wazero-based SQLite (CGO-free) works fine even with `CGO_ENABLED=1` (required by Wails). No conflict.
- Test the WebSocket spike (Phase 1) FIRST before committing to the full migration.

### Design for v3 migration

SPEC-018 covers the future v3 migration. To minimize that effort, follow these patterns now:
- Keep service structs clean — one struct per logical service, public methods only. v3 binds services via `application.NewService(&svc)`.
- Minimize direct `runtime.X(ctx, ...)` calls — wrap them in a thin adapter layer so the migration is a single-file change.
- Keep frontend runtime imports centralized (one module/file that wraps all Wails JS calls). v3 changes `@wailsapp/runtime` to `@wailsio/runtime`.
- Use events sparingly and document their contracts — v3 changes event handler signatures from variadic `interface{}` to typed `*CustomEvent`.
- Consider adding **Dockview** (https://dockview.dev/) for IDE-like dockable panels within the single v2 window. Zero-dependency vanilla TS library. Provides drag, split, float, tab groups, layout save/restore. This gives 80% of the multi-window UX within v2's single-window constraint and prepares the UI for v3 detach-to-window.
