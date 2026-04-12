---
id: SPEC-BUG-017
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-004, SPEC-017, SPEC-019]
violates: [SPEC-004, UX-002]
prior_attempts: []
created: 2026-04-12
---

# Tool Browser shows `0 tools`, no detail panel, and misses Phase 1 empty-state styling for FastMCP servers

## Problem

The Tools tab currently fails against at least one real managed MCP server:
`lmstudio` from `/Users/ed/servers.json`.

**Observed live behavior on 2026-04-12:**
- `/api/servers` reports `lmstudio` as `online`
- the Tools tab shows `lmstudio` but with `0 tools`
- clicking the entry does not reveal any tool detail UI
- the empty-state panel is visually incomplete compared with the approved
  Pencil design Phase 1 Tool Browser
- design node `b6Dqw` includes an inside stroke that is missing in the app

**Observed protocol behavior:**
- `GET /api/tools?server=lmstudio` returns HTTP 502 with JSON-RPC error:
  `{"code":-32602,"message":"Invalid request parameters"}`
- a direct subprocess probe against `lmstudio-mcp` reproduces the failure when
  `tools/list` is sent before MCP session initialization
- the same server returns the full tool catalog immediately after a correct
  `initialize` request followed by `notifications/initialized`

This means Shipyard is currently acting like a raw stdio forwarder for managed
children, but many modern MCP servers expect Shipyard to establish an MCP
session before asking for tools. As a result, Tool Browser discovery fails,
the UI has no tools to select, and the per-tool control surface never appears.

## Reproduction

1. Launch Shipyard against `/Users/ed/servers.json`
2. Open the Tools tab
3. Observe `lmstudio` listed with `0 tools`
4. Click the `lmstudio` group and note that no tool detail panel becomes useful
5. Request `GET /api/tools?server=lmstudio`
6. Observe HTTP 502 with JSON-RPC `-32602 Invalid request parameters`
7. Reproduce directly against the child process:
   - send `tools/list` first → server rejects request
   - send `initialize`, then `notifications/initialized`, then `tools/list` →
     server returns the expected tool catalog

## Root Cause

Shipyard does not bootstrap an MCP session for managed child servers before
issuing backend-originated requests such as `tools/list`.

For `FastMCP` servers, this violates protocol expectations:
- requests before initialization are rejected
- Shipyard caches `tool_count: 0`
- `/api/tools` fails instead of returning the child catalog
- Tool Browser sidebar/detail state never hydrates

Separately, the Tool Browser empty-state container does not fully match the
approved Phase 1 design. Pencil node `b6Dqw` specifies:
- `padding: 32`
- `cornerRadius: 8`
- inside stroke `#21262d`, thickness `1`

The app currently renders the content but not the bordered card treatment.

## Requirements

- [x] R1: Managed child MCP servers that require session initialization must be
  initialized once before Shipyard sends `tools/list`, `tools/call`, or other
  backend-originated MCP requests.
- [x] R2: The initialization flow must send a valid `initialize` request and
  `notifications/initialized` exactly once per child-process lifetime.
- [x] R3: If a child process restarts, Shipyard must treat it as uninitialized
  and bootstrap the new session again.
- [x] R4: Successful tool discovery must update Shipyard’s cached `tool_count`
  so the rest of the UI does not stay at `0`.
- [x] R5: The Tools tab must show the real tool count for `lmstudio` and render
  selectable tool rows from the live catalog.
- [x] R6: Selecting a tool must reveal the detail panel with description and
  per-tool parameter controls.
- [x] R7: The Tool Browser empty-state styling must match the approved Phase 1
  Pencil design for node `b6Dqw`, including the visible border.
- [x] R8: The fix must be recorded in Nightshift artifacts so the failed
  pre-init assumptions are not repeated.

## Acceptance Criteria

- [x] AC 1: In a live Shipyard run against `/Users/ed/servers.json`, the Tools
  tab no longer shows `lmstudio` with `0 tools` if the child server exposes
  tools after initialization.
- [x] AC 2: `GET /api/tools?server=lmstudio` succeeds and returns the live tool
  catalog instead of JSON-RPC `-32602`.
- [x] AC 3: The cached server/tool count path reflects the discovered tool
  count rather than remaining at `0`.
- [x] AC 4: Clicking a tool in the Tools tab reveals the detail panel and form
  controls derived from the tool schema.
- [x] AC 5: The `No tool selected` empty state has the missing border treatment
  required by Pencil node `b6Dqw`.
- [x] AC 6: Regression tests cover the MCP initialization requirement and the
  Tool Browser markup/styling contract that caused the UI mismatch.
- [x] AC 7: `go test ./...` passes.
- [x] AC 8: `go vet ./...` passes.
- [x] AC 9: `go build ./...` passes.

## Context

- Relevant files:
  - `internal/proxy/manager.go`
  - `internal/proxy/proxy.go`
  - `internal/proxy/manager_test.go`
  - `internal/web/server.go`
  - `internal/web/server_test.go`
  - `internal/web/ui/index.html`
  - `internal/web/ui/ds.css`
  - `internal/web/ui_layout_test.go`
- Live config:
  - `/Users/ed/servers.json`
- Managed child under test:
  - `/Users/ed/Dropbox/Argo/ManagedProjects/Tools/mcp/lmstudio-mcp/server.py`
- Pencil design source:
  - `.nightshift/specs/UX-002-dashboard-design.pen`
- Specific design node:
  - `b6Dqw`

## Out of Scope

- Reworking Shipyard into a different child-process architecture
- Adding new tool-policy features from `SPEC-020`
- Redesigning the broader Tool Browser beyond the approved Phase 1 contract

## Research Hints

- Reproduce the failure directly against the child process before changing code
- Prefer fixing child-session bootstrap in the proxy/manager layer, not by
  adding special cases to `/api/tools`
- Update the cached tool count from the same successful discovery path used by
  Tool Browser
- Verify the empty-state styling against Pencil node `b6Dqw`, not memory

## Gap Protocol

- Research-acceptable gaps:
  - exact bootstrap payload details for MCP initialization
  - whether tool-count refresh belongs in manager or web layer
- Stop-immediately gaps:
  - any fix that hardcodes `lmstudio`
  - any fix that only changes the Tools tab UI while `/api/tools` still fails
  - any assumption that all MCP children accept pre-init requests
- Max research subagents before stopping: 0
