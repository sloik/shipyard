---
id: SPEC-012
template_version: 2
priority: 2
layer: 1
type: feature
status: done
after: [SPEC-010]
prior_attempts: []
parent:
nfrs: []
created: 2026-04-05
---

# Tool Filtering per Token Scope and Structured Access Logging

## Problem

Shipyard v2 currently proxies all tool calls from any connected client to any child MCP server without restriction. When token-based auth lands (SPEC-010), there is no mechanism to limit which tools a token can see or invoke. A token that authenticates successfully gets full access to every tool on every server.

This is insufficient for multi-tenant and least-privilege scenarios. An API token issued for a CI pipeline should only reach the tools it needs, not every tool across all servers. Additionally, there is no structured audit trail for tool calls -- the existing `traffic` table captures raw JSON-RPC payloads but is not optimized for querying "who called what, when, and whether it was allowed."

These two features -- scope-based tool filtering and structured access logging -- were identified in the MCP Relay review as the relay's core value proposition. They belong in Shipyard v2.

## Requirements

### Feature A: Tool Filtering per Token Scope

- [ ] R1: On `tools/list`, filter the aggregated tool list to only include tools matching the authenticated token's scope patterns
- [ ] R2: On `tools/call`, verify the called tool matches at least one scope pattern on the token before forwarding to the upstream server
- [ ] R3: Return a JSON-RPC error (`code: -32001`, `message: "Tool not permitted by token scope"`) when a tool call is denied
- [ ] R4: Implement scope matching with the pattern format `{server}:{tool_pattern}` supporting `*` (any sequence) and `?` (single character) wildcards
- [ ] R5: A tool is permitted if ANY scope pattern on the token matches (logical OR)
- [ ] R6: Scope matching is case-sensitive
- [ ] R7: When auth is disabled, no filtering occurs -- all tools are visible and callable (preserve current behavior)

### Feature B: Structured Access Log

- [ ] R8: Create an `access_log` table in the existing SQLite database, separate from the `traffic` table
- [ ] R9: Log every tool call with: timestamp, token name, server name, tool name, status, latency, error message, sanitized arguments, and log level
- [ ] R10: Support per-tool log levels: `full`, `args_only`, `status_only`, `none`
- [ ] R11: Always log denied calls (`status: "denied"` or `"rate_limited"`) regardless of the configured log level
- [ ] R12: Add `GET /api/access-log` endpoint with pagination and filtering by token, server, tool, status, and date range
- [ ] R13: Add `GET /api/access-log/stats` endpoint returning aggregate stats (total calls, error rate, top tools, per-token breakdown)
- [ ] R14: Support per-tool log level configuration in the server config file
- [ ] R15: Default log level is `full` when not specified per tool

## Acceptance Criteria

### Tool Filtering

- [ ] AC1: A token with scope `["filesystem:*"]` calling `tools/list` sees only filesystem server tools, not tools from other servers
- [ ] AC2: A token with scope `["cortex:cortex_search"]` calling `tools/list` sees exactly one tool (`cortex_search`), not `cortex_add` or others
- [ ] AC3: A token with scope `["*:*"]` sees all tools from all servers (admin token)
- [ ] AC4: A token with scope `["cortex:cortex_*"]` sees `cortex_search`, `cortex_add`, `cortex_query` but not `filesystem:read_file`
- [ ] AC5: A token with scope `["filesystem:read_file"]` calling `tools/call` with `write_file` receives JSON-RPC error `{"jsonrpc":"2.0","id":...,"error":{"code":-32001,"message":"Tool not permitted by token scope"}}`
- [ ] AC6: A token with scope `["filesystem:read_?ile"]` matches `read_file` but not `read_bigfile`
- [ ] AC7: Scope matching is case-sensitive: scope `["cortex:Cortex_Search"]` does NOT match tool `cortex_search`
- [ ] AC8: With auth disabled, `tools/list` returns all tools and `tools/call` forwards without filtering (existing tests still pass)
- [ ] AC9: A token with multiple scopes `["cortex:cortex_search", "filesystem:*"]` sees union of both matches

### Access Logging

- [ ] AC10: After a successful tool call, the `access_log` table contains a row with `status = 'ok'`, correct `token_name`, `server_name`, `tool_name`, and non-null `latency_ms`
- [ ] AC11: After a denied tool call, the `access_log` table contains a row with `status = 'denied'` and the token name that was denied
- [ ] AC12: A tool with `log_level: "none"` produces no access log row on successful call, but DOES produce a row when denied
- [ ] AC13: A tool with `log_level: "status_only"` produces a row with `args_json` as NULL/empty
- [ ] AC14: `GET /api/access-log?token_name=ci-bot&status=denied` returns only denied calls for the `ci-bot` token
- [ ] AC15: `GET /api/access-log` supports pagination via `offset` and `limit` query parameters, defaulting to `limit=100`
- [ ] AC16: `GET /api/access-log/stats` returns JSON with `total_calls`, `error_rate`, `top_tools` (array), and `per_token` breakdown
- [ ] AC17: The `access_log` table has indexes on `ts`, `token_name`, `tool_name`, and `status`

## Context

### Key Source Files

- `internal/proxy/proxy.go` -- stdio bidirectional proxying, reads JSON-RPC from client stdin, forwards to child server
- `internal/proxy/manager.go` -- `Manager` struct, `SendRequest(ctx, serverName, method, params)`, `responseTracker` for ID correlation
- `internal/capture/store.go` -- SQLite store with `traffic` table, `Record()` method, WAL mode
- `internal/web/server.go` -- `handleTools` returns all tools, `handleToolCall` forwards to proxy manager

### Current Tool Call Flow

1. Client sends `tools/call` JSON-RPC request to proxy
2. Proxy parses `method` and `params` (including tool name)
3. Proxy forwards to the correct child server (matched by server name prefix or routing logic)
4. Child server responds
5. Response forwarded to client
6. Traffic captured in `traffic` table

### Current `tools/list` Flow

1. Client sends `tools/list` JSON-RPC request
2. Proxy aggregates tools from all child servers
3. Returns combined list to client

### Existing Traffic Table Schema

```sql
CREATE TABLE IF NOT EXISTS traffic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    direction TEXT NOT NULL,
    server_name TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    latency_ms INTEGER,
    matched_id INTEGER
);
```

### New Access Log Table Schema

```sql
CREATE TABLE IF NOT EXISTS access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    token_name  TEXT NOT NULL DEFAULT '',
    server_name TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    status      TEXT NOT NULL,  -- ok | error | denied | timeout | rate_limited
    latency_ms  INTEGER,
    error_msg   TEXT,
    args_json   TEXT,           -- tool call arguments (sanitized)
    log_level   TEXT NOT NULL DEFAULT 'full'  -- full | args_only | status_only | none
);
CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts);
CREATE INDEX IF NOT EXISTS idx_access_token ON access_log(token_name);
CREATE INDEX IF NOT EXISTS idx_access_tool ON access_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_access_status ON access_log(status);
```

### Config Extension for Per-Tool Log Levels

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["..."],
      "tools": {
        "read_file": { "log_level": "full" },
        "list_directory": { "log_level": "status_only" }
      }
    }
  }
}
```

### Scope Pattern Format

- Format: `{server}:{tool_pattern}`
- `*` matches any sequence of characters (including empty)
- `?` matches exactly one character
- Examples: `filesystem:*`, `cortex:cortex_search`, `*:*`, `cortex:cortex_*`

## Alternatives Considered

- **Approach A (this spec): Scope patterns with glob-style matching.** Chosen for simplicity and expressiveness. Covers the common cases (all tools on a server, exact match, prefix match) with minimal syntax. Go's `path.Match` provides a near-complete implementation of the matching algorithm.
- **Approach B (rejected): Regex-based scopes.** More powerful but harder to validate, harder to read in config files, and error-prone for users. Overkill for tool name matching.
- **Approach C (rejected): Explicit allow-lists per token.** Simpler but requires updating the token config every time a new tool is added to a server. Pattern matching avoids this maintenance burden.
- **Approach D (rejected): Reuse `traffic` table for access logging.** The `traffic` table captures full JSON-RPC payloads bidirectionally. Adding filtered columns there would bloat an already-busy table and make analytics queries slow. A dedicated `access_log` table is cleaner and independently queryable.

## Scenarios

1. **CI pipeline token:** Admin creates token `ci-bot` with scopes `["filesystem:read_file", "filesystem:list_directory"]`. CI bot calls `tools/list` and sees only `read_file` and `list_directory`. CI bot attempts `write_file` and gets a `-32001` error. The denied call appears in `access_log` with `status = 'denied'` and `token_name = 'ci-bot'`.
2. **Admin token:** Admin creates token `admin` with scope `["*:*"]`. Admin calls `tools/list` and sees all tools from all servers. All calls succeed and are logged.
3. **Cortex-only integration:** Token `cortex-reader` has scope `["cortex:cortex_*"]`. It sees all cortex tools. It tries to call `filesystem:read_file` and gets denied. Admin checks `GET /api/access-log?token_name=cortex-reader&status=denied` and sees the denied attempt.
4. **High-traffic server with minimal logging:** Config sets `list_directory` to `log_level: "status_only"`. Repeated `list_directory` calls produce compact log rows (no `args_json`). A denied call to `list_directory` is still logged with full detail.
5. **Auth disabled:** Proxy runs without auth config. All tools are visible to all clients. Access log entries have `token_name = ''`. No filtering occurs on `tools/list` or `tools/call`.
6. **Stats dashboard:** Operator hits `GET /api/access-log/stats` and sees that `cortex_search` is the most-called tool, `ci-bot` has a 2% denial rate, and overall error rate is 0.3%.

## Out of Scope

- Token management CRUD (covered by SPEC-010)
- Rate limiting enforcement (future spec; access log records `rate_limited` status but this spec does not implement rate limiting)
- Web UI for access log browsing (future spec; this spec provides API endpoints only)
- Argument sanitization rules beyond "store as JSON" (future spec for PII redaction)
- Log rotation or retention policies for the `access_log` table (future spec)
- Real-time streaming of access log events (websocket push; future spec)

## Research Hints

- Files to study: `internal/proxy/proxy.go`, `internal/proxy/manager.go`, `internal/capture/store.go`, `internal/web/server.go`
- Patterns to look for: how `handleTools` aggregates tools (this is where filtering hooks in), how `handleToolCall` routes calls (this is where the deny check hooks in), how `Store.Record()` writes to SQLite (pattern for `access_log` writes)
- Go stdlib: `path.Match` implements glob matching with `*` and `?` -- evaluate whether it fits the scope pattern format (note: `path.Match` treats `/` specially, which may not apply here; consider a custom matcher or `filepath.Match`)
- Config parsing: check how server configs are currently parsed to understand where `tools` log-level config should be added
- DevKB: `DevKB/go.md`

## Gap Protocol

- Research-acceptable gaps: existing config parsing patterns, existing test helper patterns, exact `handleTools`/`handleToolCall` signatures
- Stop-immediately gaps: SPEC-010 token model not yet defined (scope field structure), ambiguity in how tool names are namespaced (server prefix convention), changes to the JSON-RPC error code conventions
- Max research subagents before stopping: 3

---

## Notes for the Agent

- SPEC-010 (token auth) must land first. This spec assumes tokens have a `scopes` field that is a list of strings in `{server}:{tool_pattern}` format. If SPEC-010 uses a different structure, adapt accordingly.
- The scope matcher should be a standalone, well-tested function (e.g., `internal/auth/scope.go` with `MatchScope(patterns []string, server, tool string) bool`). Keep it separate from proxy logic for testability.
- For `path.Match` compatibility: the scope format uses `:` as a separator between server and tool, not `/`. You may need to split on `:` first, then match server and tool parts independently, or write a simple custom glob matcher. Do not use `path.Match` directly on the full `server:tool` string without verifying its behavior with `:`.
- The `access_log` table should be created in the same SQLite database and managed by the same `Store` struct in `internal/capture/store.go`. Add a `RecordAccess()` method alongside the existing `Record()`.
- For the `/api/access-log` endpoint, follow the pagination pattern: `?offset=0&limit=100` with sensible defaults. Support query params: `token_name`, `server_name`, `tool_name`, `status`, `from` (ISO timestamp), `to` (ISO timestamp).
- For `/api/access-log/stats`, keep the initial implementation simple: aggregate counts with `GROUP BY`. No need for time-series bucketing in this spec.
- Access log writes should not block the tool call response. Consider writing asynchronously (goroutine or buffered channel) to avoid adding latency to the proxy path.
- Preserve all existing tests. The `traffic` table and its capture flow are unchanged.
