# Nightshift Report — 2026-05-30

## Summary Stats

- Spec: `SPEC-BUG-131`
- Branch: `nightshift/SPEC-BUG-131`
- Worktree: `/Users/ed/Dropbox/Developer/Repos/shipyard-SPEC-BUG-131`
- Domain: code
- Specs completed: 1
- Files changed: 5
- Blockers: none

## Per-Spec Changes

### SPEC-BUG-131 — Servers Tab Cards Reorder on Refresh

- Added stable child-server registration order to `internal/proxy.Manager`.
- Changed `Manager.Servers()` and `ServersForAuth()` to return names in registration order instead of Go map iteration order.
- Preserved original index when a server is re-registered during restart handling.
- Added manager regression tests for repeated snapshots, status transitions, tool-count changes, and re-registration.
- Added `/api/servers` regression coverage for `shipyard` first plus three child servers in proxy order.
- Added UI source regression coverage that `loadServers()` passes API order through and `renderServerCards()` does not sort.
- Documented the root cause and checked completed requirements/acceptance criteria in the spec.

## Test Results

- `go test ./internal/proxy ./internal/web -run 'TestManager_Servers_RegistrationOrderStable|TestManager_Servers_StatusChangesKeepServerIndex|TestManager_RegisterExistingServerKeepsOriginalIndex|TestHandleServers_PreservesProxyOrderWithSelfFirst|TestSPECBUG131_RenderServerCardsUsesAPIOrderWithoutSorting' -count=1` — PASS
- `go test ./...` — PASS
- `go vet ./...` — PASS
- `go build ./...` — PASS
- `go test -race -count=1 -timeout 5m ./...` — PASS

Note: `go test`, `go build`, and the race gate emitted existing macOS linker warnings about object files built for macOS 26.0 while linking for 11.0. All commands exited 0.

## AC Checklist

- [x] AC 1: Repeated calls to `GET /api/servers` return the same server-name sequence when the server set is unchanged.
- [x] AC 2: A server status transition such as `online -> restarting -> online` does not change that server's index in the returned list.
- [x] AC 3: The Servers tab renders cards in the API order and does not apply a second unstable client-side ordering.
- [x] AC 4: The built-in `shipyard` card order is explicitly covered by tests.
- [x] AC 5: Existing tests proving `Config.ServerOrder` preservation still pass.
- [x] AC 6: Regression tests cover manager/API ordering with at least three child servers.
- [x] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and `go test -race -count=1 -timeout 5m ./...` pass.

## Blockers / Discoveries

- No blockers remain.
- Root cause was backend map iteration in `Manager.Servers()`, not client-side sorting.
- The API handler already documents and enforces the built-in `shipyard` entry as first.
- The UI already renders the API array directly; the new UI test guards that behavior.
