# Nightshift Report — 2026-05-30

## Summary Stats

- Spec: `SPEC-BUG-131`, `SPEC-BUG-132`, `SPEC-BUG-133`
- Current branch: `nightshift/SPEC-BUG-133`
- Current worktree: `/Users/ed/Dropbox/Developer/Repos/shipyard-nightshift-SPEC-BUG-133`
- Domain: code
- Specs completed: 3
- Current run files changed: 5
- Blockers: none

## Per-Spec Changes

### SPEC-BUG-133 — Phase 4 Sessions, Profiling, and Schema Views Hidden Behind Subnavigation

- Added top-level dashboard nav tabs for Sessions, Profiling, and Schema while keeping Tokens out of the top-level tab set.
- Promoted the existing Sessions, Profiling, and Schema DOM blocks into their own `route-view` owners without redesigning the feature surfaces.
- Added top-level route targets for `#sessions`, `#profiling`, and `#schema`.
- Kept old nested hashes working by mapping `#/history/sessions`, `#/history/performance`, `#/performance`, and `#/servers/schema` to the promoted views.
- Updated non-JS/hash fallback CSS so the promoted views participate in route isolation.
- Added regression tests for Phase 4 top-level tab presence, route activation, old alias handling, route isolation, Tokens exclusion, and tab-nav no-wrap behavior.
- Documented the root cause and checked completed requirements/acceptance criteria in the spec.

### SPEC-BUG-132 — Remaining Unicode and HTML Entity Icons Violate UX-002 Lucide Icon Contract

- Replaced remaining visible dashboard icon entities in `internal/web/ui/index.html` with inline Lucide-style SVGs or local SVG helper functions.
- Added local SVG helpers for dynamic alert, add, import, search, chart, shield, lock/key, record, play, stop, chevron, and sort indicator rendering.
- Updated dynamic Tool Browser, Sessions, Performance, Servers, Schema, and Tokens UI strings so warning banners, controls, sort states, empty states, and record/status markers no longer depend on entity or emoji text.
- Changed `DS.toast()` to render only the provided message text; toast type remains represented by CSS classes.
- Added structural regression coverage that rejects visible dashboard icon entities while allowing semantic text examples such as newline placeholders and literal `${VAR}` documentation.
- Documented the root cause and checked completed requirements/acceptance criteria in the spec.

### SPEC-BUG-131 — Servers Tab Cards Reorder on Refresh

- Added stable child-server registration order to `internal/proxy.Manager`.
- Changed `Manager.Servers()` and `ServersForAuth()` to return names in registration order instead of Go map iteration order.
- Preserved original index when a server is re-registered during restart handling.
- Added manager regression tests for repeated snapshots, status transitions, tool-count changes, and re-registration.
- Added `/api/servers` regression coverage for `shipyard` first plus three child servers in proxy order.
- Added UI source regression coverage that `loadServers()` passes API order through and `renderServerCards()` does not sort.
- Documented the root cause and checked completed requirements/acceptance criteria in the spec.

## Test Results

### SPEC-BUG-133

- `go test ./internal/web -run 'SPECBUG133|SPECBUG109|SPECBUG099|SPECBUG012|SPEC00600'` — PASS
- `node --check /tmp/shipyard-spec-bug-133-inline.js` — PASS
- `python3 .nightshift/validate_specs.py .nightshift/specs/SPEC-BUG-133-phase4-views-hidden-behind-subnav.md` — PASS
- `go test ./...` — PASS
- `go vet ./...` — PASS
- `go build ./...` — PASS

Note: `go test` and `go build` emitted existing macOS linker warnings about object files built for macOS 26.0 while linking for 11.0. All commands exited 0.

### SPEC-BUG-132

- `go test ./internal/web -run 'TestSPECBUG132'` — PASS
- `go test ./internal/web` — PASS
- `node --check internal/web/ui/ds.js` — PASS
- Extracted inline script from `internal/web/ui/index.html` to `/tmp/shipyard-index-inline.js`; `node --check /tmp/shipyard-index-inline.js` — PASS
- `go test ./...` — PASS
- `go vet ./...` — PASS
- `go build ./...` — PASS

Note: `go test` and `go build` emitted existing macOS linker warnings about object files built for macOS 26.0 while linking for 11.0. All commands exited 0.

### SPEC-BUG-131

- `go test ./internal/proxy ./internal/web -run 'TestManager_Servers_RegistrationOrderStable|TestManager_Servers_StatusChangesKeepServerIndex|TestManager_RegisterExistingServerKeepsOriginalIndex|TestHandleServers_PreservesProxyOrderWithSelfFirst|TestSPECBUG131_RenderServerCardsUsesAPIOrderWithoutSorting' -count=1` — PASS
- `go test ./...` — PASS
- `go vet ./...` — PASS
- `go build ./...` — PASS
- `go test -race -count=1 -timeout 5m ./...` — PASS

Note: `go test`, `go build`, and the race gate emitted existing macOS linker warnings about object files built for macOS 26.0 while linking for 11.0. All commands exited 0.

## AC Checklist

### SPEC-BUG-133

- [x] AC 1: Main app navigation exposes Phase 4 surfaces according to UX-002: Sessions, Profiling, and Schema are not hidden only behind History/Servers subnavigation.
- [x] AC 2: `#/sessions`, `#/profiling`, and `#/schema` equivalent top-level routes render the existing feature views.
- [x] AC 3: Existing nested links such as `#/servers/schema` continue to work without a blank page.
- [x] AC 4: The app bar does not wrap vertically at the dashboard's supported desktop width.
- [x] AC 5: SPEC-BUG-109 tab-nav anti-regression coverage remains passing.
- [x] AC 6: SPEC-BUG-099's "Tokens is not a top-level design tab" contract remains passing.
- [x] AC 7: Regression tests cover tab presence, route activation, and route isolation for the Phase 4 views.
- [x] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

### SPEC-BUG-132

- [x] AC 1: No visible dashboard icon uses emoji or HTML entity code points for warning, plus/add, import/download, close, play/execute, red-dot record, chart/performance, shield/schema, lock/key/token, or sort direction.
- [x] AC 2: Global schema alert and all warning banners use Lucide warning/alert icons.
- [x] AC 3: Add/Create/Import/Close/Execute/Record buttons use SVG icons with stable icon+text spacing.
- [x] AC 4: History no-results, Sessions empty, Performance empty, Schema empty, and Tokens empty states use Lucide icons.
- [x] AC 5: `DS.toast()` no longer prefixes toast text with Unicode icons.
- [x] AC 6: Structural tests fail if new visible `&#...;` icon entities are added to `internal/web/ui/index.html` or `internal/web/ui/ds.js` outside text/content examples where an entity is semantically required.
- [x] AC 7: Existing UX-002 icon specs remain passing through `go test ./internal/web` and `go test ./...`.
- [x] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

### SPEC-BUG-131

- [x] AC 1: Repeated calls to `GET /api/servers` return the same server-name sequence when the server set is unchanged.
- [x] AC 2: A server status transition such as `online -> restarting -> online` does not change that server's index in the returned list.
- [x] AC 3: The Servers tab renders cards in the API order and does not apply a second unstable client-side ordering.
- [x] AC 4: The built-in `shipyard` card order is explicitly covered by tests.
- [x] AC 5: Existing tests proving `Config.ServerOrder` preservation still pass.
- [x] AC 6: Regression tests cover manager/API ordering with at least three child servers.
- [x] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and `go test -race -count=1 -timeout 5m ./...` pass.

## Blockers / Discoveries

### SPEC-BUG-133

- No blockers remain.
- Root cause was route ownership drift: the feature surfaces existed, but the app-shell route registry and top-level tab model still represented the older dashboard route set.
- Keeping nested hashes as aliases was less disruptive than redirecting because existing links can render the correct promoted view without changing the hash.
- The top app bar needed an explicit `flex-wrap: nowrap` guard after expanding from four to seven designed tabs.

### SPEC-BUG-132

- No blockers remain.
- The remaining violations were split between static markup and dynamic HTML strings; replacing only static page markup would not have closed the dashboard surfaces.
- Toast styling already carries the notification type, so text prefixes were unnecessary and could be removed without changing toast behavior.

### SPEC-BUG-131

- No blockers remain.
- Root cause was backend map iteration in `Manager.Servers()`, not client-side sorting.
- The API handler already documents and enforces the built-in `shipyard` entry as first.
- The UI already renders the API array directly; the new UI test guards that behavior.

## Suggested Follow-up Specs

None.
