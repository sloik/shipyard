# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-BUG-016
**Status:** completed

## Summary

SPEC-BUG-016 fixed the real Wails desktop runtime bug that kept the Servers
view empty even when `/api/servers` was non-empty. The desktop frontend now
bootstraps explicit localhost API/WS bases, and the localhost HTTP server now
returns the CORS headers needed for desktop-origin fetches.

## Root Cause

Earlier route-level fixes were real but incomplete. In the packaged Wails app,
the page could load runtime config and open its WebSocket, but the fetch-driven
`/api/*` path still failed to hydrate UI state because the localhost HTTP
server did not allow desktop-origin cross-origin requests.

## Fix

- Added `api_base` to the desktop bootstrap config in `cmd/shipyard/desktop.go`.
- Wrapped the embedded page fetch path so desktop mode resolves API calls
  against the explicit localhost backend.
- Added CORS headers and OPTIONS preflight handling in `internal/web/server.go`.
- Added regression coverage for the desktop bootstrap path and CORS behavior.

## Validation Results

- `go test ./internal/web -run 'WithCORS|SPECBUG016|SPECBUG014|SPECBUG015' -v` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅
- `make wails-build` ✅
- Live packaged-app verification with `--config /Users/ed/servers.json` ✅
  The window exposed `1 server`, and the real `Servers` tab rendered the
  `lmstudio` card with `1 online, 0 tools`.

## Files Changed

- `cmd/shipyard/desktop.go`
- `cmd/shipyard/desktop_test.go`
- `internal/web/server.go`
- `internal/web/server_test.go`
- `internal/web/ui/index.html`
- `internal/web/ui_layout_test.go`
- `.nightshift/specs/SPEC-BUG-016-live-wails-servers-ui-not-consuming-api-state.md`
- `.nightshift/knowledge/attempts/SPEC-BUG-016-wails-desktop-fetch-needed-cors.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-BUG-016.md`

## Remaining Risk

The desktop path now depends on explicit localhost API access plus permissive
CORS for local requests. If Shipyard later introduces authenticated browser
state or changes the desktop serving model, that contract should be reviewed.
