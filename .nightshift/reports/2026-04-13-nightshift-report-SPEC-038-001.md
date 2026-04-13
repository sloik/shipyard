# Nightshift Report — SPEC-038-001

**Date:** 2026-04-13
**Spec:** SPEC-038-001 — Secure Secrets Core Package (Resolvers + Registry)
**Status:** DONE
**Duration:** ~35 minutes
**Review cycles:** 0 (no review loops needed)
**Build errors:** 0
**Test results:** 13 pass, 1 skip (keychain integration, item not present in CI)

---

## Files Created

| File | Purpose |
|------|---------|
| `internal/secrets/resolver.go` | `SecretResolver` interface |
| `internal/secrets/ref.go` | `parseSecretRef` + `refKind` type |
| `internal/secrets/registry.go` | `Registry` struct + `DefaultRegistry` |
| `internal/secrets/registry_darwin.go` | Darwin-specific keychain registration |
| `internal/secrets/registry_other.go` | No-op stub for non-darwin platforms |
| `internal/secrets/env.go` | `resolveEnv` helper for SPEC-038-002 |
| `internal/secrets/keychain/resolver_darwin.go` | macOS Keychain resolver (`//go:build darwin`) |
| `internal/secrets/env/resolver.go` | Env var resolver |
| `internal/secrets/op/resolver.go` | 1Password CLI resolver |
| `internal/secrets/ref_test.go` | `TestParseSecretRef` |
| `internal/secrets/registry_test.go` | Registry tests |
| `internal/secrets/keychain/resolver_darwin_test.go` | Keychain tests |
| `internal/secrets/env/resolver_test.go` | Env resolver tests |
| `internal/secrets/op/resolver_test.go` | OP resolver tests |
| `.shipyard-dev/verify-spec-038-001.sh` | Verification script |

---

## AC Checklist

| AC | Description | Result |
|----|-------------|--------|
| AC 1 | `resolver.go` defines `SecretResolver` with `CanResolve(string) bool` and `Resolve(context.Context, string) (string, error)` | ✅ |
| AC 2 | `registry.go` defines `Registry` with `Register`, `Resolve` (plain fallback), and `DefaultRegistry` | ✅ |
| AC 3 | `ref.go` defines `parseSecretRef` covering all 4 ref types; `TestParseSecretRef` covers all cases | ✅ |
| AC 4 | `keychain/resolver_darwin.go` exists with `//go:build darwin`; `TestKeychainResolver_CanResolve` passes | ✅ |
| AC 5 | `TestKeychainResolver_ParseRef` tests `svc="my-service"` and `acct="my-account"` from `@keychain:my-service/my-account` | ✅ |
| AC 6 | `op/resolver.go` exists; `TestOPResolver_CanResolve` passes; `TestOPResolver_CanResolve_NotInPath` skips correctly when `op` is present | ✅ |
| AC 7 | `env/resolver.go` exists; `TestEnvResolver_Resolve` verifies `${MY_VAR}` resolves to env value when set and `""` when unset | ✅ |
| AC 8 | `TestRegistry_FallbackToPlainText` verifies ref unchanged when no resolver matches | ✅ |
| AC 9 | `TestRegistry_FirstMatchWins` verifies only first matching resolver is called | ✅ |
| AC 10 | `go test ./internal/secrets/...` passes | ✅ |
| AC 11 | `go build ./...` passes | ✅ |
| AC 12 | `.shipyard-dev/verify-spec-038-001.sh` exits 0 (11/11 checks) | ✅ |

**All 12 ACs: PASS**

---

## Security Constraint Check (R8)

Grep for logging calls in `internal/secrets/`: **0 matches**. No `slog.*`, `log.Printf`, `log.Println`, or `fmt.Print` calls in any secrets file. Resolved values are never logged at any level.

---

## Design Decisions

### Platform split via build tags + stub files
The Keychain resolver package uses `//go:build darwin`. Rather than import it conditionally with runtime checks in `registry.go`, I used two files:
- `registry_darwin.go` — imports and registers `keychain.Resolver` on darwin
- `registry_other.go` — provides a no-op `addKeychainResolver` stub on non-darwin

This keeps `registry.go` clean of `runtime.GOOS` checks and lets the compiler enforce platform constraints at build time.

### OP resolver: CanResolve checks PATH at call time
`op.Resolver.CanResolve` calls `exec.LookPath("op")` on every invocation. This is safe for the use case (called at server spawn time, not in a hot loop) and avoids stale state if `op` is installed between process starts.

### Keychain integration test: t.Skip pattern
The integration test skips when the keychain item `@keychain:shipyard-test/test-api-key` doesn't exist, which is the expected state in CI. The skip message includes the exact `security` command to create the test item.

---

## Discoveries / Notes

- `registry_darwin.go` / `registry_other.go` split is an extra pair of files not listed in the original spec target files. This was necessary to make the cross-platform build work cleanly. The spec listed only platform-specific resolver files, but the registry itself needed a platform seam.
- `TestOPResolver_CanResolve_NotInPath` skips when `op` IS in PATH (inverse of the usual skip pattern). This ensures the test doesn't false-fail when `op` is installed on the dev machine.

---

## Verification Script Output

```
=== SPEC-038-001 Verification ===
  PASS: resolver.go exists
  PASS: SecretResolver has CanResolve
  PASS: SecretResolver has Resolve
  PASS: registry.go exists
  PASS: ref.go exists
  PASS: keychain/resolver_darwin.go exists
  PASS: keychain resolver has darwin build tag
  PASS: op/resolver.go exists
  PASS: env/resolver.go exists
  PASS: go test ./internal/secrets/...
  PASS: go build ./...

Results: 11 passed, 0 failed
```
