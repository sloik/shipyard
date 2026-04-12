# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-020
**Status:** completed

## Summary

SPEC-020 moved gateway policy ownership into the shared Shipyard backend.
Shipyard now persists global server/tool enablement, exposes a backend-owned
namespaced catalog API, enforces policy on execution, and `shipyard-mcp` now
consumes that filtered backend catalog instead of rebuilding one from raw child
discovery.

## Root Cause

After `SPEC-019`, each `shipyard-mcp` bridge process still stitched together
its own namespaced tool list from `/api/servers` plus `/api/tools?server=...`.
That meant enable/disable policy could only be local or ad hoc, which violated
Shipyard’s intended role as the shared proxy between clients and child MCP
servers.

## Fix

- Added persisted gateway policy storage in `internal/gateway/policy.go`
  backed by `gateway-policy.json` under Shipyard’s existing data directory.
- Wired the policy store into Shipyard startup in `cmd/shipyard/main.go`.
- Added backend gateway endpoints in `internal/web/server.go`:
  - `GET /api/gateway/tools`
  - `GET /api/gateway/policy`
  - `POST /api/gateway/servers/{name}/enable|disable`
  - `POST /api/gateway/tools/{server}/{tool}/enable|disable`
- Enforced gateway policy in raw `POST /api/tools/call`, returning `403` for
  disabled servers/tools even if a client uses stale local state.
- Switched `cmd/shipyard-mcp/main.go` to use `/api/gateway/tools` as the source
  of truth for `tools/list`.

## Validation Results

- `go test ./internal/gateway ./internal/web ./cmd/shipyard-mcp -run 'Gateway|HandleGateway|Disabled|ToolsListUsesBackendFilteredGatewayCatalog|InitializeAndToolsList|ToolCallRoutesToShipyard|ConcurrentToolCallsPreserveIDs|Persists' -v` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅
- Live backend verification on `http://127.0.0.1:9421` with a headless Shipyard instance ✅
  - `GET /api/gateway/tools` returned namespaced enabled tools
  - disabling `lmstudio` emptied the gateway catalog
  - `shipyard-mcp tools/list` collapsed to only `shipyard_status`
  - direct raw `POST /api/tools/call` returned `403`
  - policy persisted across Shipyard restart and remained enforced

## Files Changed

- `cmd/shipyard/main.go`
- `cmd/shipyard-mcp/main.go`
- `cmd/shipyard-mcp/main_test.go`
- `internal/gateway/policy.go`
- `internal/gateway/policy_test.go`
- `internal/web/server.go`
- `internal/web/server_test.go`
- `internal/proxy/manager_test.go`
- `.nightshift/specs/SPEC-020-global-gateway-tool-policy.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-020.md`

## Remaining Risk

The backend policy layer now controls discovery and execution, but there is
still no dedicated UI for toggling server/tool enablement in the desktop Tools
view. The HTTP API and bridge are ready; the next product step is exposing that
policy cleanly in the dashboard.
