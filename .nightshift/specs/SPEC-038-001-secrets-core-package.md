---
id: SPEC-038-001
template_version: 2
priority: 1
layer: 1
type: feature
status: done
parent: SPEC-038
after: []
prior_attempts: []
created: 2026-04-13
---

# Secure Secrets — Core Package (Resolvers + Registry)

## Problem

There is no secrets abstraction in Shipyard. All env var values in `ServerConfig.Env`
are plain strings. To support external secret stores (macOS Keychain, 1Password), a
clean interface is needed that the rest of the codebase can program against without
knowing which backend is in use.

## Requirements

- [ ] R1: `SecretResolver` interface with `CanResolve(ref string) bool` and
  `Resolve(ctx context.Context, ref string) (string, error)` methods.
- [ ] R2: `Registry` struct that holds a slice of resolvers, tries them in registration
  order via `Resolve()`, and falls back to returning the ref unchanged when no resolver
  claims it (`CanResolve` returns false for all).
- [ ] R3: `parseSecretRef(s string) refKind` helper that identifies the ref type:
  `refKeychain` (`@keychain:...`), `refOP` (`op://...`), `refEnv` (`${...}`),
  `refPlain` (anything else).
- [ ] R4: macOS Keychain resolver (file: `keychain/resolver_darwin.go`, build tag:
  `//go:build darwin`):
  - `CanResolve`: returns true when ref starts with `@keychain:`
  - `Resolve`: parses `@keychain:service/account`, runs
    `security find-generic-password -a <account> -s <service> -w`, returns trimmed
    stdout on exit 0; returns typed errors for exit 44 (not found), 36 (user cancelled),
    51 (no GUI/headless)
- [ ] R5: 1Password resolver (file: `op/resolver.go`):
  - `CanResolve`: returns true when ref starts with `op://`
  - `Resolve`: runs `op read <ref>`, returns trimmed stdout on exit 0; on exit non-0,
    returns error with stderr message (never the secret value)
  - If `op` binary is not in PATH, `CanResolve` returns false
- [ ] R6: Env var resolver (file: `env/resolver.go`):
  - `CanResolve`: returns true when ref matches `${...}`
  - `Resolve`: extracts var name, calls `os.Getenv`, returns empty string (no error) if
    not set (consistent with shell behavior)
- [ ] R7: `DefaultRegistry(backend string) *Registry` — constructs a Registry with the
  appropriate resolvers registered based on `backend`:
  - `"keychain"` → only Keychain resolver + env resolver
  - `"1password"` → only OP resolver + env resolver
  - `"env"` → only env resolver
  - `""` (auto) → all available resolvers registered (Keychain if darwin, OP if `op` in
    PATH, always env resolver)
  - plain resolver is the fallback built into `Registry.Resolve` — not a separate
    registered resolver
- [ ] R8: Resolved values MUST NOT be passed to `slog` at any level. No `log.Printf`,
  no `slog.Debug`, no error messages that include the resolved value.

## Acceptance Criteria

- [ ] AC 1: `internal/secrets/resolver.go` defines `SecretResolver` interface with
  `CanResolve(string) bool` and `Resolve(context.Context, string) (string, error)`.
- [ ] AC 2: `internal/secrets/registry.go` defines `Registry` with `Register(SecretResolver)`,
  `Resolve(ctx, ref) (string, error)` (falls back to plain when no resolver matches), and
  `DefaultRegistry(backend string) *Registry`.
- [ ] AC 3: `internal/secrets/ref.go` defines `parseSecretRef` covering all 4 ref types;
  `TestParseSecretRef` covers `@keychain:s/a`, `op://v/i/f`, `${VAR}`, and `plain-value`.
- [ ] AC 4: `internal/secrets/keychain/resolver_darwin.go` exists with `//go:build darwin`
  tag; `TestKeychainResolver_CanResolve` passes; integration test skipped when not darwin.
- [ ] AC 5: `internal/secrets/keychain/resolver_darwin.go` parses `@keychain:service/account`
  correctly — `TestKeychainResolver_ParseRef` tests `svc="my-service"` and
  `acct="my-account"` from `@keychain:my-service/my-account`.
- [ ] AC 6: `internal/secrets/op/resolver.go` exists; `TestOPResolver_CanResolve` passes;
  `TestOPResolver_CanResolve_NotInPath` returns false when `op` is not in PATH.
- [ ] AC 7: `internal/secrets/env/resolver.go` exists; `TestEnvResolver_Resolve` verifies
  `${MY_VAR}` resolves to env value when set and `""` when unset.
- [ ] AC 8: `TestRegistry_FallbackToPlainText` verifies that a ref with no matching resolver
  is returned unchanged.
- [ ] AC 9: `TestRegistry_FirstMatchWins` verifies that only the first matching resolver's
  `Resolve` is called (second resolver is not called even if it also matches).
- [ ] AC 10: `go test ./internal/secrets/...` passes.
- [ ] AC 11: `go build ./...` passes.
- [ ] AC 12: `.shipyard-dev/verify-spec-038-001.sh` exits 0.

## Verification Script

Create `.shipyard-dev/verify-spec-038-001.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-001 Verification ==="

[ -f internal/secrets/resolver.go ]
check "resolver.go exists" $?

grep -q 'CanResolve' internal/secrets/resolver.go
check "SecretResolver has CanResolve" $?

grep -q 'Resolve' internal/secrets/resolver.go
check "SecretResolver has Resolve" $?

[ -f internal/secrets/registry.go ]
check "registry.go exists" $?

[ -f internal/secrets/ref.go ]
check "ref.go exists" $?

[ -f internal/secrets/keychain/resolver_darwin.go ]
check "keychain/resolver_darwin.go exists" $?

grep -q 'go:build darwin' internal/secrets/keychain/resolver_darwin.go
check "keychain resolver has darwin build tag" $?

[ -f internal/secrets/op/resolver.go ]
check "op/resolver.go exists" $?

[ -f internal/secrets/env/resolver.go ]
check "env/resolver.go exists" $?

go test ./internal/secrets/...
check "go test ./internal/secrets/..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
```

## Context

### Target files (all new)

- `internal/secrets/resolver.go` — interface only, no imports beyond `context`
- `internal/secrets/registry.go` — Registry struct + DefaultRegistry
- `internal/secrets/ref.go` — parseSecretRef + refKind type
- `internal/secrets/env.go` — resolveEnv helper (used by SPEC-038-002)
- `internal/secrets/keychain/resolver_darwin.go` — darwin-only, calls `security` CLI
- `internal/secrets/op/resolver.go` — calls `op` CLI, uses `exec.LookPath` to detect
- `internal/secrets/env/resolver.go` — os.Getenv expansion

### No changes to existing files in this spec

All new files. SPEC-038-002 does the integration into `main.go`.

### Keychain error types

Define typed errors:
```go
var ErrKeychainNotFound    = errors.New("keychain: item not found")
var ErrKeychainCancelled   = errors.New("keychain: user cancelled")
var ErrKeychainHeadless    = errors.New("keychain: no GUI available (headless)")
```

Map from `security` exit codes: 44→NotFound, 36→Cancelled, 51→Headless. Any other
non-zero exit code → wrap stderr as generic error.

### OP CLI note

`op read` exit code is always 1 on failure regardless of failure mode. Inspect stderr
to get the message. Do not try to categorize OP errors — just return `fmt.Errorf("op: %s", stderr)`.

### Testing approach

Keychain and OP resolvers require the CLI tools to actually be present and configured.
Unit tests should only test `CanResolve` and `parseRef` logic (pure functions). Integration
tests (actual `Resolve` calls) should use `t.Skip()` when the tool is unavailable or the
test item doesn't exist. Use a test item like `@keychain:shipyard-test/test-api-key` and
document it in a comment.

### Style

- Use `exec.CommandContext(ctx, ...)` so callers can time out CLI calls
- Trim trailing newline from CLI output: `strings.TrimRight(out, "\n")`
- No goroutines or channels — resolvers are called synchronously at spawn time

## Alternatives Considered

- **Custom encrypted config format**: Rejected. Rolling a custom encryption scheme is
  harder to audit and provides no UX benefit over delegating to the OS key store, which
  already has user-visible access prompts.
- **In-process keychain via CGo**: Rejected. `security` CLI is simpler to test, doesn't
  require CGo, and is the pattern used by all major macOS CLI tools (Homebrew, git-credential-osxkeychain, etc.).
- **Single flat file with all resolvers** (no sub-packages): Viable for simpler cases,
  but sub-packages make build tags cleaner and make it easier to add platform resolvers
  without touching existing files.

## Out of Scope

- Linux `secret-tool` or `pass` resolvers
- Windows `wincred` resolver
- Bitwarden / HashiCorp Vault resolvers
- Caching resolved values (never — resolvers are always called fresh)
- Concurrent access (resolvers are called sequentially per server spawn)

## Gap Protocol

- Research-acceptable gaps: exact `security` binary path on older macOS versions, `op`
  subcommand syntax differences between op CLI v1 and v2
- Stop-immediately gaps: `go test` failures; any code path that logs a resolved value
- Max research subagents before stopping: 1
