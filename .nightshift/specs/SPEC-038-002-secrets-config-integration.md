---
id: SPEC-038-002
template_version: 2
priority: 1
layer: 1
type: feature
status: in_progress
parent: SPEC-038
after: [SPEC-038-001]
prior_attempts: []
created: 2026-04-13
---

# Secure Secrets — Config Format + Runtime Integration

## Problem

The `internal/secrets` package from SPEC-038-001 provides resolvers but nothing calls
them. This spec wires the resolver into the server spawn lifecycle so that reference
strings in `ServerConfig.Env` are resolved before the child process inherits them.

Additionally, `GET /api/servers` currently serialises the full `ServerInfo` struct which
may include env var values — this must be fixed so the API never leaks credentials.

## Requirements

- [ ] R1: `Config` struct gains a `Secrets SecretsConfig` field:
  ```go
  type SecretsConfig struct {
    Backend string `yaml:"backend"` // "keychain" | "1password" | "env" | "" (auto)
  }
  ```
  Loaded from the YAML config file alongside existing `Servers`, `Auth`, etc.
- [ ] R2: `resolveEnv(ctx context.Context, env map[string]string, reg *secrets.Registry) (map[string]string, error)`
  function that iterates the map and calls `reg.Resolve()` on each value, returning a new
  map with resolved values. Original map is not mutated.
- [ ] R3: `seedConfiguredServers()` calls `resolveEnv()` on each server's `Env` before
  passing it to `runServerWithRestart`. On per-key resolution failure: log
  `slog.Warn("secret resolution failed", "key", k, "err", err)` (key name logged, value
  is NEVER logged) and use the original unresolved ref string as the value (non-fatal).
- [ ] R4: Inside the `runServerWithRestart` goroutine, `resolveEnv()` is called once per
  restart cycle (before each `cmd.Start()`), not once per process lifetime. This ensures
  rotated secrets take effect automatically.
- [ ] R5: `secrets.DefaultRegistry(cfg.Secrets.Backend)` is constructed once at startup
  in `main()` and passed to `seedConfiguredServers()`.
- [ ] R6: `serverInfoResponse` in `internal/web/server.go` must NOT include env var values.
  If `ServerInfo` or its embedded struct currently serialises an `Env` field, add
  `json:"-"` to suppress it or remove the field from the response struct.
- [ ] R7: `TestHandleServers_NoEnvInResponse` verifies that the JSON body from
  `GET /api/servers` does not contain `"env"` or any value from a test server's env map.

## Acceptance Criteria

- [ ] AC 1: `Config` in `cmd/shipyard/main.go` has `Secrets SecretsConfig` field with
  yaml tag `"secrets"`.
- [ ] AC 2: `resolveEnv(ctx, env, reg)` function exists in `cmd/shipyard/` (either
  `main.go` or a new `resolve.go` file).
- [ ] AC 3: `seedConfiguredServers()` calls `resolveEnv()` for each server's env.
- [ ] AC 4: `runServerWithRestart` goroutine calls `resolveEnv()` at each spawn cycle
  (verifiable by grepping for `resolveEnv` inside the goroutine's `for` loop).
- [ ] AC 5: `serverInfoResponse` struct has no `Env` field (neither direct nor embedded
  from `ServerInfo`) in its JSON output — verified by `TestHandleServers_NoEnvInResponse`.
- [ ] AC 6: `TestHandleServers_NoEnvInResponse` exists in `internal/web/server_test.go`
  and passes.
- [ ] AC 7: `TestResolveEnv_PlainPassthrough` verifies a plain-text value passes through
  unchanged.
- [ ] AC 8: `TestResolveEnv_ErrorIsNonFatal` verifies that a resolution error on one key
  does not prevent other keys from resolving.
- [ ] AC 9: `go test ./...` passes.
- [ ] AC 10: `go build ./...` passes.
- [ ] AC 11: `.shipyard-dev/verify-spec-038-002.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-038-002.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-002 Verification ==="

grep -q 'SecretsConfig' cmd/shipyard/main.go
check "SecretsConfig type exists in main.go" $?

grep -q 'Secrets.*SecretsConfig' cmd/shipyard/main.go
check "Config struct has Secrets field" $?

grep -q 'resolveEnv' cmd/shipyard/main.go
check "resolveEnv called in main.go" $?

# Verify resolveEnv is called inside the restart goroutine
grep -A 50 'runServerWithRestart' cmd/shipyard/main.go | grep -q 'resolveEnv'
check "resolveEnv called inside runServerWithRestart" $?

# API must not leak env values
! grep -q '"env"' internal/web/server.go || grep -q 'json:"-"' internal/web/server.go
check "serverInfoResponse does not expose env field" $?

go test ./...
check "go test ./..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
```

## Context

### Key locations in existing code

`cmd/shipyard/main.go`:
- `type Config struct` — add `Secrets SecretsConfig` here
- `seedConfiguredServers(cfg Config, ...)` at ~line 305 — iterate `cfg.Servers`, call
  `resolveEnv()` per server before spawning
- `runServerWithRestart(...)` goroutine — add `resolveEnv()` call inside the `for` loop,
  before the `cmd.Start()` equivalent

`internal/web/server.go`:
- `serverInfoResponse` struct — verify embedded `ServerInfo` does not include `Env`;
  add `json:"-"` tag to suppress if present

### Config file format after this spec

Users can now write:
```yaml
secrets:
  backend: "keychain"   # or "1password", "env", "" (auto-detect)

servers:
  - name: "lmstudio"
    command: "lms server start"
    env:
      LMS_API_KEY: "@keychain:lmstudio/api-key"
      # or: LMS_API_KEY: "op://Personal/LM Studio/api-key"
      # or: LMS_API_KEY: "${LMS_API_KEY_FROM_ENV}"
      # or: LMS_API_KEY: "sk-plaintext-still-works"
```

### resolveEnv signature

```go
// resolveEnv resolves secret references in an env map using the given registry.
// It returns a new map; the original is not mutated.
// Per-key errors are non-fatal: the original ref is used and a warning is logged.
// The resolved value is NEVER logged.
func resolveEnv(ctx context.Context, env map[string]string, reg *secrets.Registry) map[string]string {
    resolved := make(map[string]string, len(env))
    for k, v := range env {
        r, err := reg.Resolve(ctx, v)
        if err != nil {
            slog.Warn("secret resolution failed", "key", k, "err", err)
            resolved[k] = v // use original ref on error
        } else {
            resolved[k] = r
        }
    }
    return resolved
}
```

Note: returns `map[string]string`, not `(map[string]string, error)` — errors are
absorbed per-key with a warning. This avoids blocking server startup on a single
mis-configured secret.

### API leak check

Grep `internal/web/server.go` for all structs that embed `ServerInfo` or have `Env`
fields. Ensure JSON serialization omits env values. The simplest fix is to ensure
`ServerInfo` does not carry `Env` at all (it shouldn't — that's in `ServerConfig`
not `ServerInfo`). Verify by checking what `handleServers` constructs.

If `ServerConfig` is being serialized (accidentally or intentionally), add `Env map[string]string \`json:"-"\`` to suppress it.

### Testing the restart cycle

For `TestResolveEnv_ErrorIsNonFatal`: use a mock `Registry` that returns an error for
key `"BAD_KEY"` and a value for `"GOOD_KEY"`. Verify output map has original ref for
`"BAD_KEY"` and resolved value for `"GOOD_KEY"`.

## Out of Scope

- Migration of existing plain-text values to Keychain (future migration wizard)
- Displaying resolution status in the UI (future)
- Retry logic on transient CLI failures (future — for now log and use original)
- Config validation: warning if backend is `"keychain"` but no `@keychain:` refs exist

## Gap Protocol

- Research-acceptable gaps: exact field names in `ServerInfo` vs `ServerConfig` —
  read `cmd/shipyard/main.go` and `internal/web/server.go` to verify before editing
- Stop-immediately gaps: `go test` failures; any log line that outputs a resolved value
- Max research subagents before stopping: 0
