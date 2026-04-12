---
id: SPEC-BUG-015
template_version: 2
priority: 1
layer: 2
type: bugfix
status: blocked
after: [SPEC-BUG-014]
prior_attempts:
  - knowledge/attempts/SPEC-BUG-015-same-route-refresh-hook-disproved-by-live-wails.md
violates: [SPEC-004, SPEC-017, UX-002]
created: 2026-04-12
---

# Desktop Servers view stays on empty state even when `/api/servers` returns configured servers

## Problem

In the Wails desktop app, the backend can be fully correct while the Servers UI
still shows `0 servers` and the first-run empty state. The running Shipyard
process is launched with `--config /Users/ed/servers.json`, the child server is
online, and `GET /api/servers` returns a non-empty array, but clicking the
`Servers` tab still does not reveal the configured-server view.

This is a narrower runtime/UI bug than config loading. The desktop app is not
failing to read the config file anymore; it is failing to render live server
state into the Servers screen.

**Violated specs:**
- `SPEC-004` — Phase 3: Multi-Server Management
- `SPEC-017` — Standalone Desktop App via Wails
- `UX-002` — Dashboard Design

**Violated criteria:**
- `SPEC-004 AC-2` — dashboard shows all servers with status indicators
- `SPEC-017 R3` — existing functionality works identically in the native window
- `SPEC-017 AC 1` — native window loads the dashboard, not a stale/incorrect server view
- `UX-002` server-management contract — configured servers render as server cards/list, not onboarding empty state

## Reproduction

1. Put at least one valid server entry in `~/servers.json`.
2. Launch Shipyard desktop app with `--config /Users/ed/servers.json`.
3. Confirm the backend is alive:
   - process runs with that config path
   - `GET /api/servers` returns at least one server
4. Click the `Servers` tab in the desktop UI.
5. **Actual:** the screen still shows `0 servers` / empty-state onboarding.
6. **Expected:** the screen renders the configured servers returned by `/api/servers`.

## Root Cause

Unknown. The live evidence rules out config loading and basic backend state:

- the desktop process is running with `--config /Users/ed/servers.json`
- `GET /api/servers` returns a non-empty array
- yet the Wails window still renders the empty-state branch

So the bug is in the desktop UI/runtime layer: route activation, page hydration,
stale DOM state, JS execution failure, or another render-path issue specific to
the embedded webview.

Do not frame this as a config-loading bug unless the API evidence changes.

## Requirements

- [ ] R1: When `/api/servers` returns one or more servers, the Servers view must render the configured-server state and hide the empty state.
- [ ] R2: Clicking the `Servers` tab in the desktop app must reliably trigger the same server-state render path as direct page bootstrap.
- [ ] R3: The header server-count badge and the Servers panel must derive from the same live `/api/servers` source of truth.
- [ ] R4: The fix must be validated against the desktop/Wails runtime path, not only headless HTTP behavior.

## Acceptance Criteria

- [ ] AC 1: In desktop mode, with a non-empty `/api/servers` response, the header badge no longer remains at `0 servers`.
- [ ] AC 2: In desktop mode, clicking `Servers` hides `#servers-empty` and shows the configured-server container (`#servers-grid` and related summary/actions) when servers exist.
- [ ] AC 3: The empty-state onboarding is shown only when `/api/servers` is truly empty.
- [ ] AC 4: Regression tests cover the empty-vs-configured render contract in `internal/web/ui/index.html` so the view cannot remain permanently in the empty-state branch when servers are present.
- [ ] AC 5: If runtime-specific behavior is involved, the implementation notes explicitly document the Wails/webview nuance that caused it.
- [ ] AC 6: All existing tests pass.

## Context

- Live evidence already observed:
  - process: `shipyard.app ... --config /Users/ed/servers.json`
  - API: `GET /api/servers` returns `[{\"name\":\"lmstudio\",\"status\":\"online\",...}]`
  - UI: still shows `0 servers` after clicking `Servers`
- Relevant files:
  - `internal/web/ui/index.html` — route handling, `loadServers()`, empty/configured state switching
  - `internal/web/ui_layout_test.go` — structural UI regression tests
  - `cmd/shipyard/desktop.go` — Wails launch path
  - `internal/web/server.go` — `/api/servers`
- Related specs/bugs:
  - `SPEC-BUG-012` tab routing reliability
  - `SPEC-BUG-014` desktop configured servers not visible
  - `SPEC-BUG-013` Add Server CTA actionability

## Out of Scope

- Changing server config format
- Auto-import behavior
- Multi-server backend lifecycle behavior
- Tool/schema/history rendering issues unrelated to the Servers empty/configured branch

## Research Hints

- Instrument the live desktop page if needed; static reasoning has already missed this bug multiple times.
- Verify whether the script aborts before or after `loadServers()` in the webview.
- Verify whether the DOM is switching views via CSS/hash fallback while skipping the JS render path for configured servers.
- Compare actual rendered DOM state for `#servers-empty`, `#servers-grid`, and `#server-count` after the API call resolves.
- Relevant tags: `shipyard`, `wails`, `servers`, `desktop-ui`, `runtime`

## Gap Protocol

- Research-acceptable gaps: exact runtime reason inside Wails webview, whether the failure is stale DOM state vs JS execution failure
- Stop-immediately gaps: fix requires changing the backend config architecture or contradicting `SPEC-004`
- Max research subagents before stopping: 0

## Implementation Notes

- Root cause: in the Wails webview, same-route Servers tab activation could skip a fresh hashchange, so the live `/api/servers` render path was not guaranteed to re-run on an already-active Servers tab.
- Fix: add a same-route pointerup refresh hook for the Servers tab so the UI re-syncs from `/api/servers` even when the browser/webview does not emit a new hashchange.
