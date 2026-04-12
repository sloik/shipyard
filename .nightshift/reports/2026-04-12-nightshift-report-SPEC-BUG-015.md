# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-BUG-015
**Status:** completed

## Summary

SPEC-BUG-015 was fixed in an isolated Shipyard worktree by adding a desktop-runtime
refresh hook for the Servers tab. The UI now re-syncs from `/api/servers` on
same-route Servers tab activation, which closes the Wails/webview gap where a
same-hash click could leave the empty-state render path in place.

## Root Cause

The Servers view depended on hashchange-driven navigation to refresh live server
state. In the Wails webview, clicking the already-active Servers tab does not
always emit a new hashchange, so the live `/api/servers` render path could be
skipped even when the backend already had configured servers.

## Fix

- Added a `pointerup` refresh hook for the Servers tab that re-runs `loadServers()`
  when the current route is already `servers`.
- Added a regression test covering the same-route Servers tab refresh contract.

## Validation Results

- `go test ./internal/web -run 'SPECBUG014|SPECBUG015|SPECBUG012|SPECBUG013|BUG007' -v` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅

## Files Changed

- `internal/web/ui/index.html`
- `internal/web/ui_layout_test.go`
- `.nightshift/specs/SPEC-BUG-015-desktop-servers-view-stays-empty-despite-api-data.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-BUG-015.md`

## Remaining Risk

This fix addresses the same-route Wails/webview refresh gap. If the desktop
runtime exposes a different route-activation behavior on another platform or
webview engine, that path should be validated separately.
