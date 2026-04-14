---
id: SPEC-010
template_version: 2
priority: 2
layer: 1
type: feature
status: done
after: [SPEC-004]
prior_attempts: []
parent:
nfrs: []
created: 2026-04-05
---

# Bearer Token Authentication for MCP Proxy

## Problem

Shipyard's MCP proxy has no authentication. Anyone who can reach the proxy port can call any tool on any server. In multi-user or network-exposed environments this is a security gap — there is no way to restrict which clients can access which tools, no audit trail of who called what, and no rate limiting. This spec adds bearer token authentication with per-token scoping to solve all three.

This originates from the MCP Relay review (`_Ideas/Friend/mcp-relay/argo-claude-review.md`). The relay project was reviewed and the verdict was "merge into Shipyard v2" — this is one of 3 specs capturing the relay's unique value.

## Requirements

- [ ] R1: Add a `tokens` table to SQLite storing token hashes (SHA-256), names, creation timestamps, last-used timestamps, and per-token rate limits
- [ ] R2: Add a `token_scopes` table storing scope patterns per token (`{server}:{tool_pattern}` format with glob matching)
- [ ] R3: Support bearer header authentication (`Authorization: Bearer rl_<hex32>`) on `POST /mcp`
- [ ] R4: Support path-based token authentication (`POST /mcp/{token}`) for clients that cannot send custom headers (e.g. claude.ai)
- [ ] R5: On `tools/list` responses, filter tools to only those matching the token's scopes
- [ ] R6: On `tools/call` requests, reject calls to tools outside the token's scopes with a JSON-RPC error
- [ ] R7: Implement glob matching for scope patterns (`*` matches any sequence, `?` matches single char)
- [ ] R8: Add admin API endpoints for token CRUD: create, list, delete, update scopes, usage stats
- [ ] R9: Implement bootstrap flow — first token created via `bootstrap_token` from config/env; bootstrap token invalidated after first admin token is created
- [ ] R10: Implement per-token rate limiting (calls per minute); return JSON-RPC error code `-32000` when exceeded
- [ ] R11: Auth is opt-in via `auth.enabled` in `servers.json`; when false, proxy works without tokens (current behavior)
- [ ] R12: Web dashboard endpoints (`GET /`, `GET /api/*`, `GET /ws`) are NOT gated by bearer tokens
- [ ] R13: Token plaintext value is shown exactly once at creation and never stored or retrievable again
- [ ] R14: Proxy issues `Mcp-Session-Id` on initialize but never requires it — token is the primary identity (workaround for Claude Code bug CC#27142)

## Acceptance Criteria

- [ ] AC-1: With `auth.enabled: true`, a `POST /mcp` without a valid bearer token returns JSON-RPC error `-32001` ("Unauthorized")
- [ ] AC-2: With `auth.enabled: false`, a `POST /mcp` without any token succeeds (backward compatible)
- [ ] AC-3: A token with scope `filesystem:*` can call `filesystem:read_file` but not `cortex:cortex_search`
- [ ] AC-4: A token with scope `*:*` can call any tool on any server
- [ ] AC-5: `tools/list` response for a scoped token contains only tools matching the token's scope patterns
- [ ] AC-6: `tools/call` for an out-of-scope tool returns JSON-RPC error `-32001` with message "Tool not authorized for this token"
- [ ] AC-7: `POST /mcp/{token}` with a valid token in the path authenticates successfully (no header needed)
- [ ] AC-8: `POST /mcp/{token}` with an invalid token returns JSON-RPC error `-32001`
- [ ] AC-9: `POST /api/tokens` with a valid bootstrap token creates a new token and returns the plaintext value once
- [ ] AC-10: After the first admin token is created, the bootstrap token is invalidated and returns error on subsequent use
- [ ] AC-11: `GET /api/tokens` returns token metadata (name, created_at, last_used_at, scopes) but never the token value
- [ ] AC-12: `DELETE /api/tokens/{id}` revokes a token; subsequent requests using that token fail with `-32001`
- [ ] AC-13: A token with `rate_limit_per_minute: 60` that sends 61 requests in one minute gets JSON-RPC error `-32000` ("Rate limit exceeded")
- [ ] AC-14: Rate limit counter resets after the minute window expires
- [ ] AC-15: `GET /`, `GET /api/traffic`, `GET /api/servers`, `GET /ws` all work without any token when `auth.enabled: true`
- [ ] AC-16: Tokens are stored as SHA-256 hashes in SQLite; no plaintext tokens exist in the database
- [ ] AC-17: Scope pattern `cortex:cortex_*` matches `cortex:cortex_search` and `cortex:cortex_add` but not `cortex:list_tools`
- [ ] AC-18: `PUT /api/tokens/{id}/scopes` updates scopes; subsequent requests use the new scopes immediately
- [ ] AC-19: `GET /api/tokens/{id}/stats` returns call count and last-used timestamp for the token
- [ ] AC-20: Config supports `bootstrap_token` via env var expansion (`${MCP_RELAY_BOOTSTRAP_TOKEN}`)

## Context

### Key source files

- `internal/proxy/proxy.go` — stdio bidirectional proxying; auth middleware intercepts before forwarding to proxy
- `internal/proxy/manager.go` — child process management (`Manager` struct, `map[string]*managedProxy`); scope filtering needs access to server names here
- `internal/capture/store.go` — SQLite store; new `tokens` and `token_scopes` tables go here (or a new `internal/auth/store.go`)
- `internal/web/server.go` — HTTP server; new `/api/tokens` endpoints and auth middleware registration happen here
- `cmd/shipyard/main.go` — CLI entry; config parsing for `auth` section
- `servers.json` — config file; extended with `auth` block

### Existing SQLite schema (in store.go)

```sql
CREATE TABLE IF NOT EXISTS traffic (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    direction   TEXT NOT NULL,
    server_name TEXT NOT NULL,
    method      TEXT NOT NULL DEFAULT '',
    message_id  TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ok',
    latency_ms  INTEGER,
    matched_id  INTEGER
);
```

### New tables

```sql
CREATE TABLE IF NOT EXISTS tokens (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL UNIQUE,
    token_hash           TEXT NOT NULL UNIQUE,
    created_at           TEXT NOT NULL,
    last_used_at         TEXT,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS token_scopes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id     INTEGER NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    scope_pattern TEXT NOT NULL
);
```

### Config extension

```json
{
  "servers": { "..." : "..." },
  "web": { "port": 9417 },
  "auth": {
    "enabled": true,
    "bootstrap_token": "${MCP_RELAY_BOOTSTRAP_TOKEN}"
  }
}
```

### Tech stack constraints

- Go 1.22+ stdlib-first; avoid third-party auth libraries
- SQLite via `github.com/ncruces/go-sqlite3`
- `net/http` for routing; use `http.ServeMux` patterns with `{token}` path variable (Go 1.22 enhanced routing)
- `crypto/sha256` for token hashing
- `crypto/rand` for token generation
- `log/slog` for structured logging
- Token format: `rl_` prefix + 32 hex chars (from 16 random bytes)

### Two auth paths

1. **Bearer header** — `Authorization: Bearer rl_<hex32>` — for Claude Code and programmatic clients
2. **Path-based token** — `POST /mcp/{token}` — for claude.ai which cannot send custom headers

Both paths resolve to the same token lookup and scope enforcement.

## Alternatives Considered

- **Approach A (this spec): Bearer tokens with SQLite storage** — chosen because it matches Go stdlib patterns, integrates with existing SQLite store, and supports both header and path-based auth. Minimal dependencies.
- **Approach B: API key in query parameter** — rejected; query params appear in logs and browser history. Path-based token is cleaner.
- **Approach C: mTLS / client certificates** — rejected; too complex for the target audience (developers running local MCPs). Would make setup friction unacceptable.
- **Approach D: OAuth2 / OIDC** — rejected; massive scope increase, requires external identity provider. Overkill for a local dev tool.
- **Prior art: MCP Relay** — the relay project implemented bearer auth with scope filtering. This spec captures its design but adapts it to Shipyard's architecture (SQLite instead of file-based config, Go instead of TypeScript, integrated proxy instead of standalone).

## Scenarios

1. **First-time setup:** User enables `auth.enabled: true` in `servers.json`, sets `MCP_RELAY_BOOTSTRAP_TOKEN=mysecret` env var → starts Shipyard → calls `POST /api/tokens` with `Authorization: Bearer mysecret` and body `{"name": "claude-personal", "scopes": ["*:*"]}` → gets back `{"token": "rl_a1b2c3..."}` → bootstrap token is now invalid → user configures Claude Code with the new token
2. **Scoped CI token:** Admin creates token with scopes `["filesystem:read_*", "cortex:cortex_search"]` → CI bot can read files and search Cortex but cannot write files or call other servers → bot attempts `filesystem:write_file` → gets JSON-RPC error `-32001`
3. **Claude.ai integration:** User creates a token → configures claude.ai MCP connection to `http://localhost:9417/mcp/rl_a1b2c3...` → claude.ai sends `POST /mcp/rl_a1b2c3...` with no auth header → Shipyard extracts token from path → authenticates and proxies the request
4. **Rate limit hit:** Token has `rate_limit_per_minute: 30` → automated script fires 31 requests in quick succession → 31st request gets `{"jsonrpc": "2.0", "error": {"code": -32000, "message": "Rate limit exceeded"}, "id": ...}` → script waits → after 60s, requests succeed again
5. **Token revocation:** Admin deletes token via `DELETE /api/tokens/3` → in-flight requests with that token still complete → next request with that token gets `-32001` → no stale sessions linger because session ID is not the identity
6. **Dashboard unaffected:** User opens `http://localhost:9417/` in browser with `auth.enabled: true` → dashboard loads normally → can view traffic, servers, tools → no token needed for dashboard endpoints

## Out of Scope

- Dashboard authentication (web UI access control) — future spec
- Token rotation / expiry (TTL-based tokens) — future spec
- Multi-user role-based access control (admin vs read-only) — future spec
- OAuth2 / OIDC integration — rejected, see Alternatives
- Encryption at rest for token hashes (SHA-256 is one-way, sufficient for local use)
- Audit log table for auth events (can be added later; traffic table already captures calls)
- HTTPS / TLS termination (orthogonal concern, separate spec)

## Research Hints

- Files to study: `internal/web/server.go` (existing endpoint registration pattern), `internal/capture/store.go` (SQLite table creation and migration pattern), `internal/proxy/proxy.go` (message interception points for scope filtering)
- Patterns to look for: how `http.ServeMux` routes are registered in `server.go`; how JSON-RPC responses are constructed; how `tools/list` and `tools/call` messages are identified in the proxy
- Go 1.22 enhanced routing: `mux.HandleFunc("POST /mcp/{token}", handler)` — supports path variables natively
- Rate limiting: use `sync.Map` keyed by token ID with atomic counters and a background goroutine that resets counters every minute (or use sliding window with `time.Now()` comparison)
- DevKB: `DevKB/go.md`

## Gap Protocol

- Research-acceptable gaps: Go 1.22 `ServeMux` path variable syntax, `crypto/rand` hex encoding patterns, `ncruces/go-sqlite3` foreign key support
- Stop-immediately gaps: unclear how JSON-RPC messages are intercepted in the proxy pipeline (must understand `proxy.go` message flow before implementing scope filtering), ambiguous scope pattern semantics
- Max research subagents before stopping: 3

---

## Notes for the Agent

- **Do not add auth to dashboard endpoints.** Only `POST /mcp` and `POST /mcp/{token}` are gated. This is intentional — dashboard auth is a separate concern.
- **Token generation:** Use `crypto/rand.Read(16 bytes)` → `hex.EncodeToString` → prepend `rl_`. Store `sha256(full_token)` in DB.
- **Bootstrap token is NOT stored in the DB.** It comes from config/env and is compared directly. Once the first admin token is created, set an internal flag (or a `bootstrap_used` row in a `settings` table) so the bootstrap token is permanently rejected.
- **Scope matching order:** Check scopes in order. First match wins. Use `path.Match` for glob matching (it supports `*` and `?`). The pattern format is `{server}:{tool}` so split on `:` first, then match each part independently.
- **Rate limiting data structure:** Keep in memory, not in SQLite. Rate limit state is ephemeral — a restart resets counters, which is fine. Use a `sync.Mutex`-guarded map or `sync.Map` with a struct holding count and window start time.
- **`Mcp-Session-Id` handling:** Issue it on `initialize` response (generate a UUID), but never validate or require it on subsequent requests. This is a deliberate workaround for Claude Code bug CC#27142 where stale session IDs cause permanent connection failure.
- **JSON-RPC error format:** All auth errors use standard JSON-RPC error response: `{"jsonrpc": "2.0", "error": {"code": -32001, "message": "..."}, "id": <request_id>}`. Rate limit errors use code `-32000`.
- **Config env var expansion:** Parse `${VAR_NAME}` patterns in string values during config load. Only needed for `auth.bootstrap_token` for now but implement generically.
- **Migration:** The new tables should be created in the same `initDB` function in `store.go` (or a new auth-specific store). Use `CREATE TABLE IF NOT EXISTS` — no migration framework needed.
- **Testing:** Write table-driven tests for scope matching (glob patterns), token validation (valid/invalid/expired bootstrap), rate limiting (window reset), and the full auth middleware chain. Use `httptest` for endpoint tests.
