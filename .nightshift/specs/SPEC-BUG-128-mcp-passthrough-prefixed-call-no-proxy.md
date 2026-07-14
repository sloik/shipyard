---
id: SPEC-BUG-128
template_version: 3
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-010, SPEC-029]
violates: [SPEC-010, SPEC-029]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-29
completed: 2026-05-29
---

# MCP Passthrough Prefixed Calls Handle Missing Proxy Manager

## Problem

When auth is disabled, `POST /mcp` uses the unauthenticated MCP passthrough
handler. That handler correctly supports gateway-level `initialize`, merged
`tools/list`, and Shipyard self-tool calls without requiring a child proxy
manager. However, a prefixed non-Shipyard `tools/call` such as
`filesystem__read_file` can reach `s.proxies.SendRequest(...)` before the
handler's existing nil proxy guard.

In test or startup states where the proxy manager is not configured, this path
can panic instead of returning a JSON-RPC error response. The lower fallback path
already returns `-32603` with "no proxy manager configured"; prefixed
`tools/call` should have the same failure shape.

**Violated spec:** SPEC-010 (Bearer Token Authentication for MCP Proxy)

**Violated criteria:** AC-2 requires auth-disabled `POST /mcp` to remain
backward compatible. A panic is not a compatible MCP response.

**Violated spec:** SPEC-029 (Toggle Behavior, Gateway Integration & MCP Compliance)

**Violated criteria:** R10/AC 11 require MCP `tools/call` failures to be
returned as JSON-RPC protocol/error responses, not process panics.

## Reproduction

Initial state:

- A `Server` exists without a configured proxy manager.
- Auth is disabled or absent.

Steps:

1. Send `POST /mcp` with body:

   ```json
   {
     "jsonrpc": "2.0",
     "id": 1,
     "method": "tools/call",
     "params": {
       "name": "filesystem__read_file",
       "arguments": {}
     }
   }
   ```

2. **Actual:** the handler can panic while dereferencing the nil proxy manager.
3. **Expected:** the handler returns a valid JSON-RPC error with code `-32603`
   and message "no proxy manager configured".

## Root Cause

`handleMCPPassthrough` had a nil proxy manager guard only after the special
`tools/call` handling block. Prefixed child-tool calls (`server__tool`) were
routed inside that block and called `s.proxies.SendRequest(...)` before reaching
the existing guard.

## Requirements

- [x] R1: Prefixed non-Shipyard `tools/call` requests must not dereference a
  nil proxy manager.
- [x] R2: When no proxy manager is configured, prefixed non-Shipyard
  `tools/call` must return a JSON-RPC error response with code `-32603`.
- [x] R3: Existing Shipyard self-tool calls such as `shipyard__status` must
  continue to work without a child proxy manager.
- [x] R4: Existing `initialize`, `tools/list`, and fallback passthrough behavior
  must remain unchanged.
- [x] R5: Gateway disabled-server/disabled-tool behavior for configured proxy
  managers must remain unchanged.

## Acceptance Criteria

- [x] AC 1: `POST /mcp` `tools/call` with `name:
  "filesystem__read_file"` and no proxy manager returns HTTP 200 with a
  JSON-RPC error body.
- [x] AC 2: The JSON-RPC error body has `error.code == -32603` and message
  "no proxy manager configured".
- [x] AC 3: `POST /mcp` `tools/call` with `name: "shipyard__status"` still
  returns a successful result without a child proxy manager.
- [x] AC 4: The violated SPEC-010 auth-disabled passthrough compatibility
  criterion now passes for this prefixed call path.
- [x] AC 5: The violated SPEC-029 JSON-RPC error-shape criterion now passes
  for this prefixed call path.
- [x] AC 6: Regression coverage exists in Go unit tests.
- [x] AC 7: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

## Context

- Parent auth spec: `.nightshift/specs/SPEC-010-token-based-auth.md`
- Parent gateway spec: `.nightshift/specs/SPEC-029-toggle-behavior-and-gateway-integration.md`
- NFR: `.nightshift/specs/SPEC-NFR-001-zero-data-races.md`
- Existing passthrough handler: `internal/web/server.go`
- Existing passthrough tests: `internal/web/server_test.go`

## Out of Scope

- Changing MCP tool naming or `server__tool` prefix semantics
- Changing gateway policy behavior for disabled tools or servers
- Changing child proxy manager lifecycle
- Adding retries or startup waiting behavior

## Code Pointers

- `internal/web/server.go` - `handleMCPPassthrough`
- `internal/web/server.go` - `writeJSONRPCError`
- `internal/web/server_test.go` - MCP passthrough tests
- `.nightshift/specs/SPEC-010-token-based-auth.md` - auth-disabled
  compatibility
- `.nightshift/specs/SPEC-029-toggle-behavior-and-gateway-integration.md` -
  gateway MCP error behavior

## Gap Protocol

- Research-acceptable gaps:
  - Whether existing test helpers already decode JSON-RPC error responses
  - Whether tests should assert exact HTTP status or only JSON-RPC error shape
- Stop-immediately gaps:
  - Any fix that makes Shipyard self-tools require a child proxy manager
  - Any fix that bypasses gateway disabled-tool policy for configured proxies
- Max research subagents before stopping: 0
