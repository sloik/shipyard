# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-BUG-017
**Status:** completed

## Summary

SPEC-BUG-017 fixed the Tool Browser regression where managed FastMCP servers
showed `0 tools`, `/api/tools` failed with JSON-RPC `-32602`, and the UI never
reached the per-tool detail/control flow. Shipyard now bootstraps managed child
MCP sessions correctly before backend-originated requests and the Tool Browser
empty state matches the approved Phase 1 card treatment.

## Root Cause

Shipyard was proxying managed child MCP servers as if stdio framing alone were
sufficient. Real FastMCP children require MCP session setup first:
`initialize`, then `notifications/initialized`. Because Shipyard sent
`tools/list` before that bootstrap, `lmstudio-mcp` rejected the request and the
Tool Browser stayed empty. Separately, the Tool Browser empty-state container
was missing the bordered card styling from Pencil node `b6Dqw`.

## Fix

- Added managed child session bootstrap in `internal/proxy/manager.go`
  before non-initialization requests.
- Ensured successful `tools/list` responses refresh cached `tool_count`.
- Added proxy regression coverage for the initialization-before-discovery path.
- Updated the Tool Browser empty state in `internal/web/ui/index.html` and
  `internal/web/ui/ds.css` to match the Phase 1 design card treatment and copy.
- Added UI layout regression coverage for the bordered empty-state contract.

## Validation Results

- `go test ./internal/proxy -run 'BootstrapsManagedChildBeforeToolsList|SendRequest|SetToolCount' -v` ✅
- `go test ./internal/web -run 'SPECBUG017|BUG007|SPECBUG016|SPECBUG014|SPECBUG015' -v` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅
- `make wails-build` ✅
- Live runtime verification against `/Users/ed/servers.json` ✅
  - `GET /api/servers` reported `lmstudio` with `tool_count: 13`
  - `GET /api/tools?server=lmstudio` returned the live FastMCP tool catalog

## Files Changed

- `internal/proxy/manager.go`
- `internal/proxy/manager_test.go`
- `internal/proxy/proxy_additional_test.go`
- `internal/web/ui/index.html`
- `internal/web/ui/ds.css`
- `internal/web/ui_layout_test.go`
- `.nightshift/specs/SPEC-BUG-017-tool-browser-fastmcp-bootstrap-and-phase1-fidelity.md`
- `.nightshift/knowledge/attempts/SPEC-BUG-017-managed-fastmcp-children-need-session-bootstrap.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-BUG-017.md`

## Remaining Risk

The child bootstrap payload is currently one shared MCP client profile. If
future managed servers require transport-specific initialization fields or
version negotiation beyond the current shared payload, Shipyard may need
per-server bootstrap configuration.
