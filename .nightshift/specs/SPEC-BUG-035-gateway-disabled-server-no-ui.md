---
id: SPEC-BUG-035
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: [SPEC-BUG-034]
violates: []
prior_attempts: []
created: 2026-04-13
---

# Server disabled by gateway policy has no UI indicator and no way to re-enable

## Problem

When a server is disabled via Shipyard's gateway policy (persisted to
`gateway-policy.json`), the Servers tab shows the server as if it is normal (online, with
a green dot). But running any tool on that server returns:

> `server "lmstudio" is disabled by Shipyard gateway policy`

There is no visible indication in the Servers tab that the server is disabled at the
gateway level. The only way to re-enable it is to manually edit
`~/Library/Application Support/Shipyard/gateway-policy.json`.

## Root Cause

The `/api/servers` endpoint (`GET`) returns server process state (online/crashed/stopped)
but does NOT include the gateway policy state (enabled/disabled). The front-end has no
data to display the disabled state. The backend policy store (`gateway.Store`) is queried
at tool execution time but not exposed in the server listing API.

## Fix

Two-part fix:

### 1. Expose gateway policy state in `/api/servers` response

The server list response currently looks like:
```json
[{ "name": "lmstudio", "status": "online", "tool_count": 5, ... }]
```

Add a boolean field `gateway_disabled` to each server entry:
```json
[{ "name": "lmstudio", "status": "online", "tool_count": 5, "gateway_disabled": true }]
```

The backend `GET /api/servers` handler must query the gateway store for each server and
include `gateway_disabled: true` when `!gateway.ServerEnabled(server.Name)`.

### 2. Show "Disabled" indicator on the card and an "Enable" button

When `gateway_disabled` is true on a server card:

- **Status dot**: use `var(--text-muted)` color (grey) instead of green/red, regardless
  of process status
- **Header right**: show a "Disabled" badge (neutral pill, muted style) instead of tools
  pill
- **Body**: show a banner reading "Blocked by gateway policy" (warning-subtle bg,
  warning-fg text, with a lock icon or ⊘ symbol)
- **Actions**: show only an "Enable" button (btn-default) that calls the gateway re-enable
  API

The "Enable" button calls: `POST /api/gateway/server` with body
`{ "server": "NAME", "enabled": true }` — this endpoint already exists (SPEC-BUG-014 /
similar).

After successful enable, call `loadServers()` to refresh.

## Requirements

- [ ] R1: `GET /api/servers` response includes `gateway_disabled: bool` per server.
- [ ] R2: A server with `gateway_disabled: true` renders a grey status dot.
- [ ] R3: A server with `gateway_disabled: true` shows a "Disabled" badge on the header right.
- [ ] R4: A server with `gateway_disabled: true` shows a "Blocked by gateway policy" body banner.
- [ ] R5: A server with `gateway_disabled: true` shows only an "Enable" button in actions.
- [ ] R6: Clicking "Enable" calls the gateway API and reloads the servers view.

## Acceptance Criteria

- [ ] AC 1: The Go handler for `GET /api/servers` includes `GatewayDisabled bool` in the
  per-server response struct.
- [ ] AC 2: `renderServerCards` checks `s.gateway_disabled` and renders differently.
- [ ] AC 3: Grey dot is used for gateway-disabled servers.
- [ ] AC 4: "Disabled" badge appears in card header right when `gateway_disabled`.
- [ ] AC 5: "Blocked by gateway policy" banner appears in card body when `gateway_disabled`.
- [ ] AC 6: "Enable" button in actions calls `POST /api/gateway/server` then `loadServers()`.
- [ ] AC 7: `go test ./...` passes (add test for `gateway_disabled` field in server API response).
- [ ] AC 8: `go vet ./...` passes.
- [ ] AC 9: `go build ./...` passes.
- [ ] AC 10: `.shipyard-dev/verify-spec-035.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-035.sh` that:
1. Checks Go source for `GatewayDisabled` or `gateway_disabled` field in servers handler
2. Checks JS `renderServerCards` for `gateway_disabled` branch
3. Checks JS for the "Enable" button POST call to `/api/gateway/server`
4. Runs `go test ./...`
5. Prints PASS/FAIL + summary

## Context

### Find the gateway API endpoint

```bash
grep -r "gateway/server\|SetServerEnabled" internal/web/server.go
```

The existing `POST /api/gateway/server` endpoint takes `{ "server": "NAME", "enabled": true/false }`.
If no such endpoint exists, look for where `gateway.SetServerEnabled` is called from HTTP
handlers.

### Find the servers API handler

```bash
grep -n "api/servers\|ServeHTTP\|listServers\|handleServers" internal/web/server.go | head -20
```

Find the handler that returns the server list and add `GatewayDisabled` to its response struct.

### Gateway store access

The `server.go` handler already has access to `s.gateway` (a `*gateway.Store`). Use
`s.gateway.ServerEnabled(name)` — if it returns false, set `GatewayDisabled: true`.

Guard with `if s.gateway != nil` before calling (same pattern used in tool execution).

### JS pattern for the Enable button

```javascript
html += '<button class="btn btn-default btn-sm" onclick="window.__shipyard_enableServer(\'' + escapeHtml(s.name) + '\')">Enable</button>';
```

And globally expose the handler (same pattern as `__shipyard_stopServer`):
```javascript
window.__shipyard_enableServer = function(name) {
  fetch('/api/gateway/server', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server: name, enabled: true })
  }).then(function() { loadServers(); });
};
```

## Out of Scope

- Per-tool gateway disable indicators (separate concern)
- Disabling servers from the Servers tab (already possible via existing API, no UI needed
  for now)
- Persisting the re-enabled state across Shipyard restarts (the API already does this via
  `gateway-policy.json`)

## Gap Protocol

- Research-acceptable gaps: exact route path for gateway API — grep `server.go` for
  `gateway` to find the exact endpoint path
- Stop-immediately gaps: `go test` failures; gateway API call not found in server.go
- Max research subagents before stopping: 0
