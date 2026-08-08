---
id: SPEC-BUG-160
template_version: 7
priority: 4
layer: 0
type: refactor
status: in_progress
after: [SPEC-BUG-157, SPEC-BUG-158]
provides: [coverage-ratchet, stable-coverage-run]
requires: [nightshift-valid-control-plane, canonical-quality-command]
touches: [Makefile, .github/workflows/ci.yml, .nightshift/config.yaml, internal/proxy/proxy_more_test.go]
prior_attempts: [SPEC-008, SPEC-009]
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: go
domain: code
output_type: mixed
devkb_required: [go.md, testing.md, architecture.md]
cortex_cites: []
karpathy_checklist: [think, simple, surgical, goal]
---

# Add an Honest Coverage Ratchet and Stabilize Coverage Execution

## Problem

Completed SPEC-008 records a 100% statement-coverage goal, but the current verified
repository total is 73.4% and CI collects no coverage. A concurrent diagnostic coverage
run also failed once in `TestRunChild_SuccessCapturesOutput`; isolated stress runs passed,
so this is a test-determinism signal rather than a confirmed production defect. Without a
truthful checked-in baseline and ratchet, new untested code silently invalidates historical
claims and unstable coverage runs cannot be trusted as gates.

## Requirements

- [ ] R1: Establish a reproducible repository and per-package coverage baseline from a clean, count-one run.
- [ ] R2: Add a blocking ratchet that fails on total or package regression while allowing improvement without manual threshold edits.
- [ ] R3: Stabilize `TestRunChild_SuccessCapturesOutput` so it does not depend on process-global stdout timing or implicit goroutine completion.
- [ ] R4: Publish human-readable coverage evidence in CI and make Nightshift invoke the same command.
- [ ] R5: Correct or annotate the historical 100% coverage record without rewriting evidence or pretending the current baseline is higher.
- [ ] R6: Exclude generated/test-stub-only code only through explicit reviewed policy.

## Acceptance Criteria

- [ ] AC1 (R1): `make coverage` exits 0 and records the accepted baseline, including total 73.4% (or the freshly measured value after prerequisite-only changes) and each package's percentage.
- [ ] AC2 (R2): `make coverage-check` fails when a controlled fixture/probe lowers a package or total below baseline and passes when coverage is equal or higher.
- [ ] AC3 (R2): New or materially changed non-generated Go code has an explicit diff-coverage policy and cannot reduce an existing package floor unnoticed.
- [ ] AC4 (R3): `TestRunChild_SuccessCapturesOutput` passes 100 ordinary runs, 20 race runs, and 20 coverage runs using deterministic completion—not sleeps as the primary oracle.
- [ ] AC5 (R4): PR CI publishes total and per-package summaries and blocks on ratchet regression; `.nightshift/config.yaml` references the same command.
- [ ] AC6 (R5): SPEC-008/009 drift is recorded through an addendum or migration report that states the date, measured baseline, and why historical `done` does not imply a permanent 100% gate.
- [ ] AC7 (R6): Every excluded package/file is listed with rationale; no production package is blanket-excluded.
- [ ] AC8: Ordinary tests and `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- Historical claim: `.nightshift/specs/SPEC-008-statement-coverage-closure.md:30-34,57-63`.
- Current package coverage (2026-07-18): `cmd/shipyard` 58.0%, `cmd/shipyard-mcp` 68.9%, `internal/auth` 66.4%, `internal/capture` 82.0%, `internal/gateway` 68.1%, `internal/performance` 63.0%, `internal/proxy` 92.1%, `internal/web` 72.7%, total 73.4%.
- Flake signal: `internal/proxy/proxy_more_test.go:344-377`; one concurrent coverage run observed empty forwarded stdout, while isolated repeated runs passed.
- Coverage improvement should be risk-weighted; do not chase 100% by weakening assertions or removing legitimate branches.

## Scenarios

1. A PR adds an untested branch to `internal/auth` -> package/total ratchet fails with the exact delta.
2. A PR improves coverage -> gate passes and the report shows the new high-water mark.
3. Coverage runs under ordinary, race, and repeated modes -> proxy stdout test completes deterministically every time.

## Out of Scope

- Restoring 100% coverage in one monolithic change.
- Testing generated or third-party code.
- Weakening assertions or deleting branches to improve percentages.
- Broad production refactors unrelated to a required test seam.

## Documentation Impact

- Coverage policy document or contributor section — baseline, ratchet rules, exclusions, and update procedure.
- Historical spec drift record — measured reality without altering past evidence.

## Research Hints

- Read `Argo Home/DevKB/go.md`, `testing.md`, and `architecture.md`.
- Create a narrow injected writer/completion seam for the proxy test; avoid process-global stdout mutation.
- Store the baseline in a machine-readable file and compare package names deterministically.
- Generate coverage with `-count=1` to avoid cached results.

## Validation Commands

```bash
make coverage
make coverage-check
go test -count=100 -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -race -count=20 -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -count=20 -cover -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -race -count=1 -timeout 5m ./...
```
