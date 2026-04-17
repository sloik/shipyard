---
id: SPEC-BUG-126
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: [SPEC-029, SPEC-044]
violates: [SPEC-028, SPEC-029, SPEC-044]
prior_attempts: []
created: 2026-04-17
---

# `GET /api/tools?server=shipyard` Returns 502 Instead of Shipyard Tool List

## Problem

Shipyard's built-in tools are exposed through the gateway catalog and can be toggled via
`PUT /api/tools/shipyard/{tool}/enabled`, but the direct tool-browser API path for the
self-server is still broken:

```bash
curl -i 'http://127.0.0.1:9417/api/tools?server=shipyard'
```

Actual result:

```text
HTTP/1.1 502 Bad Gateway
server "shipyard" not found
```

This makes the self-server inconsistent with every child server and makes the toggle
feature hard to reason about in practice: some paths behave as if Shipyard is a normal
server, while the direct tool-list endpoint still behaves as if Shipyard does not exist.

Current live evidence from 2026-04-17:

- `GET /api/servers` includes the synthetic self entry:
  `{"name":"shipyard","is_self":true,"enabled":true,...}`
- `GET /api/gateway/tools` includes Shipyard tools:
  `shipyard__status`, `shipyard__list_servers`, `shipyard__restart`, `shipyard__stop`
- `PUT /api/tools/shipyard/status/enabled` works and updates gateway visibility
- `GET /api/tools?server=shipyard` still returns `502 server "shipyard" not found`

This is not the same as the earlier toggle-sync bug. The existing "supposedly fixed"
feature spec is `SPEC-029`, but the remaining failure is narrower: the self-server is not
fully wired into the direct `/api/tools` endpoint.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)  
**Violated criteria:** R9 / AC 10 — `GET /api/tools` includes tool enabled state. For the
synthetic Shipyard server, the endpoint does not return tools at all.

**Violated spec:** SPEC-029 (Toggle Behavior, Gateway Integration & MCP Compliance)  
**Violated criteria:** R12-R15 / AC 14-17 — Shipyard built-in tools should behave like
regular toggleable tools. Today they only work through the gateway-catalog workaround, not
through the normal per-server tools endpoint.

**Violated spec:** SPEC-044 (Shipyard Self-Server — Expose Shipyard as a First-Class Server)  
**Violated criteria:** R7 / AC 10 — the Tool Browser should show a first-class Shipyard
server group with its tools and forms. A first-class server should not fail its own
`/api/tools?server=...` path.

## Reproduction

Preconditions:

- Shipyard backend running on `http://127.0.0.1:9417`
- Self-server visible in `GET /api/servers`

Steps:

1. Verify the self-server exists:
   `curl -s http://127.0.0.1:9417/api/servers | jq '.[] | select(.name=="shipyard")'`
2. Verify Shipyard tools exist in the gateway catalog:
   `curl -s http://127.0.0.1:9417/api/gateway/tools | jq -r '.tools[] | select(.server=="shipyard") | .name'`
3. Request the direct per-server tools endpoint:
   `curl -i 'http://127.0.0.1:9417/api/tools?server=shipyard'`
4. **Actual:** `HTTP/1.1 502 Bad Gateway` with body `server "shipyard" not found`
5. **Expected:** `HTTP/1.1 200 OK` with a JSON body containing Shipyard's built-in tools in
   the same shape as other servers, including `enabled` and `server_enabled`

## Root Cause

`handleTools` in `internal/web/server.go` calls `fetchToolsResult(ctx, serverName)`, and
`fetchToolsResult` blindly forwards to:

```go
return s.proxies.SendRequest(ctx, serverName, "tools/list", json.RawMessage("{}"))
```

That works only for real child proxies. The synthetic Shipyard self-server is not present in
`proxies`, so the request fails with `server "shipyard" not found`.

Meanwhile the current UI avoids this path for Shipyard by special-casing `loadTools()` to
build the Shipyard group from `GET /api/gateway/tools?include_disabled=1` instead of calling
`/api/tools?server=shipyard`. That workaround makes sidebar toggles appear functional while
hiding the broken API path underneath.

## Requirements

- [ ] R1: `GET /api/tools?server=shipyard` must return `200 OK` and a JSON tool list for the
  Shipyard self-server instead of forwarding to `proxies.SendRequest`
- [ ] R2: The returned Shipyard tool list must use the same shape as child server tool lists:
  `{ "tools": [...] }` with bare tool names (`status`, `list_servers`, `restart`, `stop`)
- [ ] R3: Each Shipyard tool entry returned from `/api/tools?server=shipyard` must include
  `enabled` and `server_enabled` fields consistent with gateway policy
- [ ] R4: Shipyard must remain server-level enabled only; `server_enabled` is always `true`
  for the self-server, but individual tool-level toggles must still be reflected
- [ ] R5: The fix must not break existing child-server behavior for `/api/tools?server=<child>`

## Acceptance Criteria

- [ ] AC 1: `curl -i 'http://127.0.0.1:9417/api/tools?server=shipyard'` returns `200 OK`
- [ ] AC 2: The response body includes a `tools` array with at least `status`,
  `list_servers`, `restart`, and `stop`
- [ ] AC 3: Each returned Shipyard tool includes `enabled` and `server_enabled` fields
- [ ] AC 4: Disabling `shipyard__status` via `PUT /api/tools/shipyard/status/enabled` makes
  `/api/tools?server=shipyard` return that bare tool with `enabled: false`
- [ ] AC 5: `GET /api/gateway/tools` and `GET /api/tools?server=shipyard` stay consistent:
  gateway view uses namespaced names, direct per-server view uses bare names
- [ ] AC 6: `GET /api/tools?server=<real-child>` still works unchanged after the fix
- [ ] AC 7: Regression coverage is added in Go tests for the self-server `/api/tools` path
- [ ] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass

## Context

- Existing "supposedly fixed" toggle spec:
  `.nightshift/specs/SPEC-029-toggle-behavior-and-gateway-integration.md`
- Parent self-server spec:
  `.nightshift/specs/SPEC-044-shipyard-self-server.md`
- Relevant source:
  - `internal/web/server.go` — `handleTools`, `fetchToolsResult`
  - `internal/web/ui/index.html` — `loadTools()` special-cases Shipyard via
    `/api/gateway/tools?include_disabled=1`
  - `internal/gateway/policy.go` — tool enable/disable state

Relevant lines observed on 2026-04-17:

- `internal/web/server.go`: `fetchToolsResult` forwards `tools/list` only through
  `s.proxies.SendRequest(ctx, serverName, ...)`
- `internal/web/ui/index.html`: `loadTools()` builds `allTools['shipyard']` from gateway
  catalog data, not from `/api/tools?server=shipyard`

## Out of Scope

- Reworking the visual toggle UI
- Reopening the full SPEC-029 feature
- Changing MCP `tools/list` behavior
- Adding new Shipyard management tools

## Code Pointers

- Broken forwarding path: `internal/web/server.go`
- Self-server catalog source: `internal/web/server.go`
- UI workaround hiding the bug: `internal/web/ui/index.html`
- Related specs:
  - `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
  - `.nightshift/specs/SPEC-029-toggle-behavior-and-gateway-integration.md`
  - `.nightshift/specs/SPEC-044-shipyard-self-server.md`

## Gap Protocol

- Research-acceptable gaps:
  - Whether the self-server `/api/tools` path should reuse the gateway catalog builder or a
    dedicated internal helper
  - Whether tests should assert exact tool ordering or only membership + fields
- Stop-immediately gaps:
  - Any fix that would require removing the self-server from `/api/servers` or
    `/api/gateway/tools`
  - Any fix that breaks existing child proxy routing
- Max research subagents before stopping: 0
