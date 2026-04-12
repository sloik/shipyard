---
id: SPEC-BUG-016
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-014, SPEC-BUG-015]
violates: [SPEC-004, SPEC-017, UX-002]
prior_attempts:
  - knowledge/attempts/SPEC-BUG-014-stale-server-count-source-of-truth.md
  - knowledge/attempts/SPEC-BUG-015-same-route-refresh-hook-disproved-by-live-wails.md
created: 2026-04-12
---

# Live Wails desktop app still shows `0 servers` and empty state while `/api/servers` is non-empty

## Problem

The packaged Wails desktop app still renders `0 servers` and the first-run
Servers empty state even after earlier backend and route-refresh fixes. This is
confirmed in the real desktop runtime, not just inferred from code.

**Live evidence from 2026-04-12:**
- Built current Wails app via `make wails-build`
- Launched: `cmd/shipyard/build/bin/shipyard.app/Contents/MacOS/shipyard --config /Users/ed/servers.json`
- `GET /api/servers` returned `[{\"name\":\"lmstudio\",\"status\":\"online\",...}]`
- macOS accessibility dump of the Shipyard window still exposed:
  - `static text 0 servers`
  - `static text No servers configured`
- Clicking the real `Servers` tab in the live app still left the empty-state UI visible

This means the desktop runtime is not consuming or rendering the API state that
the backend is already serving.

**Violated specs:**
- `SPEC-004` — Phase 3: Multi-Server Management
- `SPEC-017` — Standalone Desktop App via Wails
- `UX-002` — Dashboard Design

**Violated criteria:**
- `SPEC-004 AC-2` — dashboard shows all servers with status indicators
- `SPEC-017 R3` — existing functionality works identically in the native window
- `SPEC-017 AC 1` — native window loads the dashboard with working server state
- `UX-002` server-management contract — configured servers render as cards/list, not empty onboarding

## Reproduction

1. Build the desktop app: `make wails-build`
2. Launch `cmd/shipyard/build/bin/shipyard.app/Contents/MacOS/shipyard --config /Users/ed/servers.json`
3. Confirm `curl http://localhost:9417/api/servers` returns at least one server
4. Click the `Servers` tab in the live Wails window
5. **Actual:** the window still shows `0 servers` and `No servers configured`
6. **Expected:** the window shows the configured server cards/status from `/api/servers`

## Root Cause

The packaged Wails window was able to bootstrap the desktop config endpoint and
open its live WebSocket, but the HTTP fetch path for `/api/*` still failed to
hydrate UI state. The remaining blocker was the localhost HTTP server: it did
not return CORS headers or handle preflight requests, so desktop-origin fetches
to `http://127.0.0.1:9417/api/...` could not populate `#server-count`,
`#servers-empty`, or `#servers-grid` even though the backend data was correct.

## Requirements

- [x] R1: Instrument or otherwise prove whether the live Wails UI is issuing `/api/servers` requests when the Servers view is shown.
- [x] R2: If the request is issued, prove why the returned data is not reaching the DOM state that drives `#server-count`, `#servers-empty`, and `#servers-grid`.
- [x] R3: The fix must be validated against the packaged desktop app, not only browser or unit-test behavior.
- [x] R4: The final implementation must leave a regression guard that covers the discovered runtime-specific cause as closely as practical.

## Acceptance Criteria

- [x] AC 1: In the packaged Wails desktop app, with `/api/servers` non-empty, the live window no longer exposes `0 servers` or `No servers configured`.
- [x] AC 2: Clicking `Servers` in the live desktop app shows configured server cards instead of the empty-state onboarding.
- [x] AC 3: The runtime investigation notes explicitly describe the true cause that kept API state from reaching the live desktop DOM.
- [x] AC 4: Regression tests are added or adjusted for the discovered cause.
- [x] AC 5: `go test ./...` passes.
- [x] AC 6: `go vet ./...` passes.
- [x] AC 7: `go build ./...` passes.

## Context

- Relevant files:
  - `cmd/shipyard/desktop.go`
  - `internal/web/server.go`
  - `internal/web/ui/index.html`
  - `internal/web/ui_layout_test.go`
- Relevant failed attempts:
  - `knowledge/attempts/SPEC-BUG-014-stale-server-count-source-of-truth.md`
  - `knowledge/attempts/SPEC-BUG-015-same-route-refresh-hook-disproved-by-live-wails.md`
- Packaged app path:
  - `cmd/shipyard/build/bin/shipyard.app/Contents/MacOS/shipyard`

## Out of Scope

- Redesigning the Servers UI
- Changing config format
- Auto-import improvements unrelated to the bug

## Research Hints

- Start with live request tracing or visible runtime instrumentation instead of more route speculation.
- Verify whether `/api/servers` is called from the live Wails page at all.
- If it is called, verify whether JSON parsing or DOM updates fail silently in the desktop runtime.
- Treat browser-mode success as insufficient evidence.

## Gap Protocol

- Research-acceptable gaps: request tracing, DOM-state instrumentation, runtime-specific event behavior
- Stop-immediately gaps: any fix that only passes tests but is not re-verified in the packaged Wails app
- Max research subagents before stopping: 0
