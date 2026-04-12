# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-BUG-014
**Status:** completed

## Summary

SPEC-BUG-014 was executed via an isolated Nightshift-style worktree run and
integrated back to `main`. The fix removed a conflicting source of truth for
the global server badge and refreshed server state when the user enters the
Servers route.

## Root Cause

`trackFilters()` on the traffic page was mutating the global `#server-count`
badge based on `knownServers`, which reflects observed traffic rather than the
configured server inventory from `/api/servers`. That stale traffic-derived
count could leave the desktop UI showing `0 servers` even when configured
servers existed. The Servers route also needed an explicit refresh path so it
re-synced from `/api/servers` on navigation.

## Validation Results

- `go test ./internal/web ./cmd/shipyard -run 'SPECBUG014|SPECBUG012'` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅

## Files Changed

- `internal/web/ui/index.html`
- `internal/web/ui_layout_test.go`
- `.nightshift/specs/SPEC-BUG-014-desktop-configured-servers-not-visible.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-BUG-014.md`

## Remaining Risk

SPEC-BUG-015 remains open as a narrower desktop runtime/render-path problem in
the Wails window. This run fixed the badge/source-of-truth bug but did not
validate the live embedded webview behavior end-to-end.
