---
id: BUG-SHIPYD-004
template_version: 3
priority: 1
layer: 2
type: bugfix
status: in_progress
after:
- SPEC-SHIPYD-001
- SPEC-BUG-159
violates:
- SPEC-BUG-159
- SPEC-SHIPYD-001
nfrs:
- SPEC-NFR-001
prior_attempts: []
attachments: []
created: 2026-11-13
stack: go
devkb_required:
- go.md
- testing.md
scope:
  write:
  - internal/capture/retention.go
  - internal/capture/diskspace_unix.go
  - internal/capture/sizes.go
  - internal/capture/sizes_test.go
---

# CI security gate red: gosec G115 on two int64 to uint64 conversions in capture size code

## Problem

With BUG-SHIPYD-002 and BUG-SHIPYD-003 fixed, the CI job `test` fails in `make security-gosec`
(run 43417695636):

```
internal/capture/retention.go:199      G115 (CWE-190): integer overflow conversion int64 -> uint64
internal/capture/diskspace_unix.go:14  G115 (CWE-190): integer overflow conversion int64 -> uint64
Issues : 2
make: *** [Makefile:159: security-gosec] Error 1
```

Both lines came in with SPEC-SHIPYD-001. The first is a real defect, not only a lint: the three
`PRAGMA` scans ignore their errors, and a negative product (for example a freelist count above the
page count on a damaged database) wraps to a value near 2^64. The free-space check then always
fails, and the one-time `auto_vacuum` migration is skipped on every start with a misleading
"not enough free disk space" warning.

The second only appears when building for Linux, where `syscall.Statfs_t.Bsize` is `int64`.

**Violated spec:** SPEC-BUG-159 (vulnerability and supply-chain gates), SPEC-SHIPYD-001
**Violated criteria:** `make security` passes on `main` in CI with zero gosec suppressions.

## Reproduction

1. `GOTOOLCHAIN=go1.26.11 make security-gosec` reports `retention.go:199`.
2. `GOTOOLCHAIN=go1.26.11 GOOS=linux make security-gosec` reports both lines.
3. **Expected:** `Issues : 0` for both targets.

## Root Cause

Unchecked `uint64(...)` conversions of signed values: the SQLite page arithmetic in
`migrateAutoVacuum` and `st.Bsize` in `freeDiskBytes`.

## Requirements

- [ ] R1: The live database size used by the `auto_vacuum` migration is computed by a function that
      returns 0 when any input is negative or when the page count is not above the freelist count,
      and never wraps.
- [ ] R2: Free disk bytes are computed by a function that returns 0 for a negative block size or
      block count and never converts a negative value to `uint64`.
- [ ] R3: Behaviour for valid inputs is unchanged.
- [ ] R4: No gosec suppression (`#nosec`, exclusion, severity change) is added.

## Acceptance Criteria

- [ ] AC1 (R1): A unit test covers live-size computation for: normal values, zero values,
      freelist above page count, negative page count, negative page size. The non-normal cases
      return 0. The test fails against the pre-fix arithmetic.
- [ ] AC2 (R2): A unit test covers the free-bytes computation for normal values, a negative block
      size and a negative block count; the negative cases return 0.
- [ ] AC3 (R3): Existing `internal/capture` tests pass unchanged; `go test -race -count=1 ./...`
      passes.
- [ ] AC4 (R4): `GOTOOLCHAIN=go1.26.11 make security-gosec` and the same with `GOOS=linux` both
      report `Issues : 0`, and `git grep -n nosec -- '*.go'` finds nothing new.
- [ ] AC5: The CI job `test` passes in full on the PR, so the SPEC-BUG-159 gate passes again.
- [ ] AC6: `make lint`, `make type-check` and `make coverage-check` pass.

## Scope Amendments

| Date | Path or glob | Change (old → new) | Reason | Approved by |
| --- | --- | --- | --- | --- |
| 2026-11-13 | .nightshift/specs/BUG-SHIPYD-004-gosec-g115-capture-size-conversions.md | not in scope → this spec's own file may be created by the delivering commit | The spec file was first committed together with the fix (PR #53), not on `main` beforehand, so the scope gate reads the new file as a `scope_self_edit`. The declared `scope.write` list itself was never widened. | human |

## Context

- Violated specs: `.nightshift/specs/SPEC-BUG-159-vulnerability-supply-chain-gates.md`,
  `.nightshift/specs/SPEC-SHIPYD-001-capture-and-log-retention.md`
- `Makefile` states there are no gosec suppressions.
- Local gosec needs `GOTOOLCHAIN=go1.26.11`; built against the machine's Go 1.27.1 it cannot load
  packages.

## Out of Scope

- Handling the ignored `PRAGMA` scan errors beyond making the arithmetic safe.
- Any change to retention policy or the free-space headroom formula.

## Code Pointers

- `internal/capture/retention.go` (lines 195-200)
- `internal/capture/diskspace_unix.go` (line 14)
- Tests: `internal/capture/retention_test.go`

## State rationale

```yaml
schema_version: 1
status: in_progress
reason: mechanical transition to 'in_progress' via run run-20261113-shipyd004
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261113T174753Z-status-transition-ready-in-progress-mechanical-transition-.json
```
