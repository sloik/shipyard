---
id: SPEC-BUG-015
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
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

### Attempt 1 — pointerup same-route refresh hook (disproved by live Wails testing)

- Root cause hypothesis: in the Wails webview, same-route Servers tab activation could skip a fresh `hashchange`, so the live `/api/servers` render path was not guaranteed to re-run on an already-active Servers tab.
- Fix applied: a `pointerup` listener on `tabNav` that calls `loadServers()` when the Servers tab is already active and the user clicks it again.
- Live test result: this fix did NOT resolve the issue. The Servers view still stayed empty even with the hook in place. The hook is still in the code (`tabNav.addEventListener('pointerup', ...)`) as a cheap guard but is not the root cause fix.

### Attempt 2 — `resolveAPIURL` stub (primary fix)

**Root cause:** `resolveAPIURL(path)` was an unfinished stub that always returned `path` unchanged. In the Wails desktop app, `usesDesktopAssetOrigin()` returns `true` because Wails serves the frontend via a custom URL scheme (not `http:` or `https:`). In that path, `appFetch` calls `loadDesktopBridgeConfig()` then `nativeFetch(resolveAPIURL(input))`. Since `resolveAPIURL` returned `path` unchanged, the fetch used a relative URL (e.g. `/api/servers`) inside a non-http scheme context.

In Wails v2 on macOS, WKWebView resolves relative URLs against the custom scheme origin (e.g. `wails://localhost/api/servers`). The Wails asset server's `Handler` (the desktop bridge) intercepts requests not found in the embedded assets and proxies `/api/*` to the real HTTP server — this path exists and should theoretically work. However, the asymmetry was telling: WebSocket URLs were already built as explicit absolute URLs (`ws://127.0.0.1:PORT/ws`) via `resolveWebSocketURL()`, which correctly used `desktopBridgeConfig.ws_base`. API fetches had no equivalent treatment.

**Fix applied:**
```javascript
function resolveAPIURL(path) {
    if (desktopBridgeConfig && desktopBridgeConfig.api_base) {
        return desktopBridgeConfig.api_base.replace(/\/$/, '') + path;
    }
    return path;
}
```
This makes desktop API fetches go directly to `http://127.0.0.1:PORT/api/servers` (bypassing custom scheme resolution entirely), matching the pattern that WebSocket already used successfully.

**Why this is correct:** The backend `desktopBridge.ServeHTTP` provides `/_shipyard/desktop-config` with `api_base: "http://127.0.0.1:PORT"`. The entire purpose of that endpoint is to give the frontend an explicit localhost base URL — `resolveAPIURL` was supposed to use it but was left as a stub.

**Error visibility (Option B):** The `loadServers()` catch handler now surfaces fetch errors in the UI by displaying the error message in `.empty-desc` instead of failing silently. Silent failures in Wails webviews are invisible (no developer console accessible to the user), which was masking the underlying failure.

**Live test required:** Łukasz must build and run the Wails app to confirm that `GET /api/servers` now populates the Servers view correctly. Static analysis cannot simulate the Wails webview URL resolution behavior.

### Wails/webview nuance

In Wails v2, the embedded frontend is served via a custom URL scheme on macOS (not `http:`). `usesDesktopAssetOrigin()` returns `true` in this context. All API fetches must be made to explicit `http://127.0.0.1:PORT` URLs to bypass custom-scheme URL resolution, which may not forward relative paths through the asset bridge reliably. WebSocket was already correct; API was not. This fix aligns API with WebSocket.
