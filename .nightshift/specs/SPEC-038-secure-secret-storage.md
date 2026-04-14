---
id: SPEC-038
template_version: 2
priority: 1
layer: 1
type: main
status: done
children:
  - SPEC-038-001
  - SPEC-038-002
  - SPEC-038-003
implementation_order:
  - SPEC-038-001
  - SPEC-038-002
  - SPEC-038-003
after: []
prior_attempts: []
created: 2026-04-13
---

# Secure Secret Storage for Server Environment Variables

## Problem

`ServerConfig.Env` (the map used to inject environment variables into managed MCP server
processes) stores all values as plain text in the config file
(`~/Library/Application Support/Shipyard/config.yaml`). This means API keys, tokens,
and passwords sit in an unencrypted file on disk — readable by any process with user
permissions, visible in config backups, and easily leaked via `cat`, version control, or
log output.

Immediate evidence: the lmstudio server required `LMS_API_KEY` to be set, and the only
way to do it was to embed the key as plain text in the config. The longer-term risk is
that as Shipyard manages more servers, the config file becomes a credential dump.

Users need a way to store sensitive env values in their platform's secret manager and
reference them from the Shipyard config using a safe, non-secret string.

## Requirements

- [ ] R1: A `SecretResolver` abstraction that can look up a value from an external store
  given a reference string, with pluggable backends (Keychain, 1Password, env vars, plain).
- [ ] R2: Reference format `@keychain:service/account` resolves via macOS Keychain CLI.
- [ ] R3: Reference format `op://vault/item/field` resolves via 1Password `op` CLI.
- [ ] R4: Reference format `${VAR}` resolves via `os.Getenv` (reuse existing pattern).
- [ ] R5: Plain-text values are returned as-is (backward compatible — existing configs work
  without modification).
- [ ] R6: Resolved values are never logged, never returned in API responses, and not cached.
- [ ] R7: Config format supports `secrets.backend` field (`"keychain"`, `"1password"`,
  `"env"`, `""` for auto-detect).
- [ ] R8: Settings UI lets the user choose the active secret backend.
- [ ] R9: Servers view shows an amber warning banner when plain-text secrets are detected
  in any server's env config.

## Acceptance Criteria

- [ ] AC 1: `internal/secrets/` package exists with `SecretResolver` interface and `Registry`.
- [ ] AC 2: `@keychain:service/account` reference resolves via `security` CLI on macOS.
- [ ] AC 3: `op://vault/item/field` reference resolves via `op read` CLI.
- [ ] AC 4: `${VAR}` reference expands from environment.
- [ ] AC 5: Existing plain-text env values continue to work unchanged.
- [ ] AC 6: `GET /api/servers` response does not include env var values.
- [ ] AC 7: `resolveEnv()` is called at each server spawn (startup + restart), so rotated
  secrets take effect without restarting Shipyard.
- [ ] AC 8: Settings tab has a "Secret Manager" section with backend selection.
- [ ] AC 9: Servers view shows amber warning banner when plain-text secrets detected.
- [ ] AC 10: `go test ./...` passes. `go build ./...` passes.

## Context

### Target files
- `cmd/shipyard/main.go` — `ServerConfig`, `seedConfiguredServers()`, `runServerWithRestart()`
- `internal/proxy/proxy.go` — `mergeEnv()`, env passing to child process
- `internal/web/server.go` — `serverInfoResponse`, `handleServers()`
- `internal/web/ui/index.html` — Settings tab, Servers view
- `internal/web/ui/ds.css` — warning banner styles
- NEW: `internal/secrets/` package (resolver.go, registry.go, ref.go, env.go)
- NEW: `internal/secrets/keychain/resolver_darwin.go` (build tag: darwin)
- NEW: `internal/secrets/op/resolver.go` (1Password)

### Key current code
- `ServerConfig.Env map[string]string` at `main.go:~126`
- `mergeEnv()` at `proxy.go:~394` — where env vars are passed to child process
- `seedConfiguredServers()` at `main.go:~305` — initial server spawn
- `expandEnvVars()` at `main.go:~146` — existing but only used for auth bootstrap token
- `serverInfoResponse` at `internal/web/server.go` — already embeds `ServerInfo` + `GatewayDisabled`

### Security constraints (non-negotiable)
- Resolved values MUST NOT appear in slog output at any level
- Resolved values MUST NOT appear in `GET /api/servers` JSON response
- Resolved values MUST NOT be written back to the config file
- On resolution failure: log the error (not the ref or the expected value), use empty string

### Platform scope (Phase 1 = macOS only)
macOS Keychain and 1Password are the only resolvers implemented in this spec.
Linux (`secret-tool`, `pass`) and Windows (`wincred`) are explicitly out of scope.

## Out of Scope

- Linux secret-tool / pass integration (future SPEC-039)
- Windows wincred integration (future SPEC-040)
- Bitwarden / HashiCorp Vault / custom backends (future)
- Reveal button (ephemeral 30s modal to see current resolved value) — future
- Migration wizard (UI to move plain-text values to Keychain) — future
- Encrypting the Shipyard config file at rest — out of scope

## Gap Protocol

- Research-acceptable gaps: exact `security` CLI exit codes (see macOS man page), `op` CLI
  stderr messages for different failure modes
- Stop-immediately gaps: `go test` failures; API response leaks env values
- Max research subagents before stopping: 1

---

## Notes for the Agent

Do NOT implement this spec directly. Execute children in `implementation_order`:
1. SPEC-038-001 — core package
2. SPEC-038-002 — config integration
3. SPEC-038-003 — settings UI + warning banner
