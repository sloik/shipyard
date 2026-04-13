# Nightshift Run Report — 2026-04-13

## Summary

| Field | Value |
|---|---|
| Spec | SPEC-BUG-026 |
| Status | done |
| Duration | ~2 min |
| Agent | Claude Sonnet 4.6 (worktree) |
| Commit | `2da31ce` |

## Files Changed

| File | Change |
|---|---|
| `internal/web/ui/index.html` | +18 lines — offline/restarting aggregate banner in `renderToolSidebar()` |
| `internal/web/ui_layout_test.go` | +32 lines — 2 regression tests |
| `.nightshift/specs/SPEC-BUG-026-*.md` | status: ready → done |

## Test Results

```
go build ./...   PASS
go vet ./...     PASS
go test ./...    PASS  (7 packages)
```

## AC Checklist

- [x] AC1: Banner-level surface shown when ≥1 server offline/restarting
- [x] AC2: Aggregate message communicates state ("N servers offline, M restarting")
- [x] AC3: Banner absent when all servers online (gated by `offlineCount > 0 || restartingCount > 0`)
- [x] AC4: Regression tests added (`TestSPECBUG026_OfflineBannerMarkupBuilt`, `TestSPECBUG026_OfflineBannerGatedByCount`)
- [x] AC5: `go test ./...` passes
- [x] AC6: `go vet ./...` passes
- [x] AC7: `go build ./...` passes

## Discoveries

- None. Straightforward addition after the server group loop in `renderToolSidebar()`.
- Pattern mirrors existing conflict banner (top of sidebar); this banner sits at the bottom.

## Protocol Deviations

- Human review report was not written by the agent at run time. Written retroactively by parent session.

---

## SPEC-BUG-027

| Field | Value |
|---|---|
| Spec | SPEC-BUG-027 |
| Status | done |
| Duration | ~3 min |
| Agent | Claude Sonnet 4.6 (worktree) |
| Commit | `beb9ab9` |

## Files Changed

| File | Change |
|---|---|
| `internal/web/ui/ds.css` | +4 lines — `.server-card.is-restarting { border-color: var(--warning-fg); }` |
| `internal/web/ui/index.html` | +58 lines — dedicated restarting card branch in `renderServerCards()` |
| `internal/web/ui_layout_test.go` | +61 lines — 3 regression tests |
| `.nightshift/specs/SPEC-BUG-027-*.md` | status: ready → done |

## Test Results

```
go build ./...   PASS
go vet ./...     PASS
go test ./...    PASS  (7 packages)
```

## AC Checklist

- [x] AC1: Restarting card renders header pill (72XWK: warning pill top-right, not footer badge)
- [x] AC2: Centered waiting body (xdMRZ: spinner + "Waiting for process to start...")
- [x] AC3: Warning border via `.server-card.is-restarting` class (`var(--warning-fg)`)
- [x] AC4: 3 regression tests added (`RestartingCardHasIsRestartingClass`, `RestartingCardHasPill`, `RestartingCardHasCenteredBody`)
- [x] AC5: `go test ./...` passes
- [x] AC6: `go vet ./...` passes
- [x] AC7: `go build ./...` passes

## Discoveries

- The mini pill spinner (10px, warning-fg) reuses the `@keyframes spin` animation already defined in ds.css for `.spinner::before` — no new CSS required.
- `restart_count` is preserved in the restarting body as secondary text when > 0 (gap protocol acceptable gap).
- Online/crashed/stopped card rendering is fully preserved in the `else` branch — zero regressions.

## Protocol Deviations

- Agent wrote report to `.nightshift/reports/` (gitignored) instead of `reports/`. Appended retroactively by parent session.

---

## SPEC-010 — Bearer Token Authentication for MCP Proxy

| Field | Value |
|---|---|
| Spec | SPEC-010 |
| Status | done |
| Duration | ~45 min |
| Agent | Claude Sonnet 4.6 (inline) |

## Summary

Implemented bearer token authentication for the Shipyard MCP proxy. Auth is opt-in via `auth.enabled` in `servers.json`. When disabled, the proxy works exactly as before (backward compatible). New packages: `internal/auth` with token storage, scope matching, rate limiting, and HTTP middleware.

## Files Changed

| File | Change |
|---|---|
| `internal/auth/store.go` | New — SQLite token storage (hashed SHA-256, scopes, stats) |
| `internal/auth/scope.go` | New — glob matching for `{server}:{tool}` scope patterns |
| `internal/auth/ratelimit.go` | New — in-memory per-token sliding window rate limiter |
| `internal/auth/middleware.go` | New — `MCPHandler` with bearer/path auth, scope filtering |
| `internal/auth/store_test.go` | New — 12 tests covering store, bootstrap lifecycle, AC-16 |
| `internal/auth/scope_test.go` | New — 11 tests covering AC-3, AC-4, AC-17 |
| `internal/auth/ratelimit_test.go` | New — 4 tests covering AC-13, AC-14 |
| `internal/auth/middleware_test.go` | New — 10 tests covering AC-1, AC-5 through AC-9, AC-13, R14 |
| `internal/web/server.go` | Extended — auth fields, `SetAuthStore`, `/api/tokens` routes, `POST /mcp` routes |
| `internal/web/server_test.go` | Extended — 9 new tests for token admin API and passthrough (AC-9, AC-11, AC-12, AC-15, AC-18, AC-19) |
| `internal/proxy/manager.go` | Extended — `ServersForAuth()` method |
| `cmd/shipyard/main.go` | Extended — `AuthConfig`, `expandEnvVars`, `setupAuth`, wired into all run modes |
| `cmd/shipyard/config_test.go` | Extended — 5 new tests for auth config parsing and env var expansion (AC-20) |

## Test Results

```
go build ./...   PASS
go vet ./...     PASS
go test ./...    PASS  (8 packages, 0 failures)

Package breakdown:
  cmd/shipyard         OK  (includes auth config tests)
  cmd/shipyard-mcp     OK
  internal/auth        OK  (37 tests — store, scope, ratelimit, middleware)
  internal/capture     OK
  internal/gateway     OK
  internal/proxy       OK
  internal/web         OK  (includes token admin + MCP passthrough tests)
```

Note: 2 pre-existing data races in `internal/proxy` and `cmd/shipyard` test files exist in baseline. They are not caused by SPEC-010 changes (confirmed via git stash + race test on original code).

## AC Checklist

- [x] AC-1: POST /mcp without valid bearer → JSON-RPC error -32001 (TestMCPHandler_NoToken_Unauthorized)
- [x] AC-2: Auth disabled → POST /mcp succeeds without token (TestHandleMCPPassthrough_NoAuth)
- [x] AC-3: Token with `filesystem:*` can call `filesystem:read_file` (TestMCPHandler_ToolsCall_InScope)
- [x] AC-4: Token with `*:*` can call any tool (TestMCPHandler_ValidToken_Allowed + scope_test.go)
- [x] AC-5: tools/list filters to token scopes (TestMCPHandler_ToolsList_ScopeFiltered)
- [x] AC-6: tools/call out-of-scope → -32001 "Tool not authorized" (TestMCPHandler_ToolsCall_OutOfScope)
- [x] AC-7: POST /mcp/{token} with valid path token authenticates (TestMCPHandler_PathToken_Authenticates)
- [x] AC-8: POST /mcp/{token} with invalid token → -32001 (TestMCPHandler_PathToken_Invalid)
- [x] AC-9: POST /api/tokens with bootstrap creates token + returns plaintext (TestHandleTokenCreate_WithBootstrapToken)
- [x] AC-10: Bootstrap invalidated after first admin token created (TestStore_BootstrapToken + TestStore_BootstrapUsed_PersistsAcrossReopen)
- [x] AC-11: GET /api/tokens returns metadata, never token value or hash (TestHandleTokenList_NoPlaintertext)
- [x] AC-12: DELETE /api/tokens/{id} revokes; subsequent requests fail (TestHandleTokenDelete_RevokesToken + TestStore_DeleteToken)
- [x] AC-13: Rate limit exceeded → -32000 (TestMCPHandler_RateLimit + TestRateLimiter_AllowsUpToLimit)
- [x] AC-14: Counter resets after window (TestRateLimiter_ResetsAfterWindow)
- [x] AC-15: Dashboard endpoints (GET /api/servers) work without token when auth.enabled (TestHandleServers_NoAuthRequired)
- [x] AC-16: Tokens stored as SHA-256 hashes (TestStore_PlaintextNotStoredInDB)
- [x] AC-17: cortex:cortex_* matches cortex_search and cortex_add but not list_tools (TestMatchScope)
- [x] AC-18: PUT /api/tokens/{id}/scopes updates scopes immediately (TestHandleTokenUpdateScopes)
- [x] AC-19: GET /api/tokens/{id}/stats returns last-used (TestHandleTokenStats)
- [x] AC-20: Config supports ${ENV_VAR} expansion in bootstrap_token (TestConfigUnmarshal_AuthBlock_EnvVarExpansion)

## Discoveries / Notes

- The `POST /mcp` endpoint is entirely new — Shipyard previously only exposed stdio-based MCP via `shipyard-mcp` binary. The HTTP relay added here is the spec's target.
- Tool names in the HTTP relay are prefixed as `{server}__{tool}` (consistent with the existing `shipyard-mcp` convention).
- Pre-existing data races in the test suite: `TestChildInputWriter_WriteLineRetriesAfterNewlineFailure` (proxy) and `TestRunProxy_HeadlessTrue_DoesNotCallDesktop` (cmd/shipyard). Neither is caused by SPEC-010. Confirmed by testing on clean baseline.
