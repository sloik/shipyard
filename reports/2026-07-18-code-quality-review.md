# Shipyard Code-Quality Review — 2026-07-18

## Outcome

An agent team reviewed static tooling/CI, tests/correctness, and architecture/security.
The current build is behaviorally green: ordinary tests, vet, build, full race tests, and
repeated concurrency-heavy package tests passed. No deterministic production failure or
data race was confirmed. The main risks are missing quality gates, stale Nightshift truth,
and high-impact paths that are not tested through their production entrypoints.

## Review Limits

- Serena activation was required, but `gopls` is not installed. Serena explicitly blocked
  symbolic Go inspection, so reviewers did not install it or bypass that restriction.
- Go evidence comes from compiled diagnostics, coverage, test inventory, and already-read
  targeted paths; this is not a complete symbol-by-symbol security audit.
- Security/workflow findings below are control gaps or design risks unless marked confirmed.

## Verified Baseline

| Check | Result |
|---|---|
| `go test -count=1 ./...` | Pass |
| `go vet ./...` | Pass |
| `go build ./...` | Pass |
| `go test -race -count=1 -timeout 5m ./...` | Pass |
| auth/proxy/web repeated x10 | Pass |
| `go mod verify` / `go mod tidy -diff` | Pass |
| `node --check` and `zsh -n` | Pass |
| Repository statement coverage | 73.4% |
| `gofmt -l` | Fail: 7 tracked files |
| Nightshift single-document config parse | Fail at `.nightshift/config.yaml:80` |
| Exact live spec IDs | Fail: duplicated 006/007/008/009 |

## Prioritized Findings

### P1 — Nightshift control-plane integrity is broken (confirmed)

`.nightshift/config.yaml:80` begins a second YAML document. A single-document safe load
fails, and `validate_specs.py` reports 98/204 invalid specs while warning that config cannot
be read. Four live identities are duplicated: `SPEC-006`, `SPEC-007`, `SPEC-008`, and
`SPEC-009`. Dependency and status resolution is ambiguous.

Action: SPEC-BUG-157.

### P1 — Formatting/static analysis is not a real gate (confirmed)

CI only runs vet, race tests, and build (`.github/workflows/ci.yml:28-30`). Seven tracked
Go files are not gofmt-clean. No pinned Staticcheck/golangci-lint or workflow syntax analyzer
is configured. Nightshift's `type_check` repeats ordinary tests, `format` is empty, and the
local test target omits the active race NFR.

Action: SPEC-BUG-158.

### P1 — Dependency/workflow security automation is absent (confirmed gap)

Renovate is present, but no `govulncheck`, dependency-review, security analyzer, or workflow
security gate is configured. Workflows use mutable action tags; desktop grants broad write
permission and installs `wails3@latest` despite a pinned alpha module. This is not evidence
of compromise.

Action: SPEC-BUG-159.

### P1 — Coverage truth has drifted and is ungated (confirmed)

The current verified total is 73.4%, despite completed SPEC-008 recording a 100% goal.
CI does not collect or ratchet coverage. Current package lows include `cmd/shipyard` 58.0%,
`internal/auth` 66.4%, `internal/performance` 63.0%, `internal/gateway` 68.1%, and
`internal/web` 72.7%. One concurrent coverage run exposed a proxy stdout-test flake signal;
isolated stress runs passed, so no deterministic defect is claimed.

Action: SPEC-BUG-160.

### P1 — Access-log production behavior lacks correctness evidence (confirmed gap/risk)

`handleAccessLog` and `handleAccessLogStats` measure 0% coverage. Existing tests do not
prove authenticated `tools/call` produces queryable allowed/denied audit rows through the
real handlers. Async writes discard insert errors and have no tested shutdown drain. No
data loss was reproduced; the risk is silent loss/absence of observability at a security
boundary.

Action: SPEC-BUG-161.

### P2 — Async tests retain scheduler-timing debt (confirmed structure, unconfirmed flake)

There are 24 `time.Sleep` calls across ten test files. Repeated tests passed, but sleeps
remain weaker than state-based completion and obscure lifecycle leaks.

Action: SPEC-BUG-162.

### P2 — Untrusted parsers have no fuzz regression layer (confirmed gap)

No Go fuzz targets exist for JSON-RPC, config, scope, or query/filter parsing. Existing
examples are extensive but do not continuously explore malformed combinations.

Action: SPEC-BUG-163.

## Deferred Improvements

- Reproducible desktop PR gate: pin Wails CLI to the module-compatible version and build on
  relevant PR paths instead of push/tag only.
- Documentation contract tests: README says Go 1.22+ while `go.mod` requires 1.25; it links
  a missing LICENSE and does not clearly document current auth/secrets boundaries.
- Browser smoke promotion: current workflow is informational and can skip when Chrome is
  unavailable; promote only after deterministic browser provisioning is proven.
- Legacy near-duplicate spec cleanup: the duplicate scanner reports many historical overlaps;
  treat exact identity repair first, then semantic retirement/migration separately.
- GUI smoke temp retention: define whether evidence directories are retained or sanitized and
  removed; current script creates temp artifacts without cleanup.

## Created Nightshift Specs

1. `SPEC-BUG-157` — restore config/spec identity integrity.
2. `SPEC-BUG-158` — canonical formatting/static-analysis/race quality gate.
3. `SPEC-BUG-159` — vulnerability, dependency-review, and workflow supply-chain gates.
4. `SPEC-BUG-160` — honest coverage baseline/ratchet and stable coverage execution.
5. `SPEC-BUG-161` — production-path access-log tests, drain, and error observability.
6. `SPEC-BUG-162` — deterministic async synchronization and lifecycle/leak checks.
7. `SPEC-BUG-163` — parser fuzz targets and durable regression seeds.

All seven were conflict-checked before creation, remain `status: draft`, reference the active
race NFR where applicable, and pass per-file `validate_specs.py` validation. Global validation
is expected to remain red until SPEC-BUG-157 repairs the pre-existing control plane.

## Recommended Run Order

`157 -> 158 -> (159 and 160) -> 161 -> 162 -> 163`

The first two establish trustworthy orchestration and one canonical quality command. Security
and coverage gates can then proceed independently. Access-log durability precedes the broader
async-test cleanup so the latter can reuse its explicit worker lifecycle.
