---
id: SPEC-BUG-162
template_version: 7
priority: 2
layer: 1
type: refactor
status: in_progress
after: [SPEC-BUG-158, SPEC-BUG-161]
provides: [deterministic-async-test-contract, goroutine-leak-gate]
requires: [canonical-quality-command, drainable-audit-writes]
touches: [internal/auth, internal/proxy, internal/web]
prior_attempts: []
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: go
domain: code
output_type: code
devkb_required: [go.md, testing.md, architecture.md]
cortex_cites: []
karpathy_checklist: [simple, surgical, goal]
---

# Replace Timing Sleeps with Deterministic Async Test Synchronization

## Problem

The Go suite is large and currently green, including repeated and race runs, but 24
`time.Sleep` calls remain across ten test files in concurrency-heavy auth, proxy, and web
packages. Most encode scheduler timing instead of a completion condition, weakening
failure diagnostics and creating latent flakiness. No deterministic failure was reproduced;
this is preventive test-hardening, not a claim that the current runtime is broken.

## Requirements

- [ ] R1: Inventory every test sleep and classify it as replaceable synchronization or justified external-process polling.
- [ ] R2: Replace unit-level timing sleeps with explicit channels, conditions, wait groups, callbacks, or bounded eventually helpers tied to state.
- [ ] R3: Add lifecycle/leak checks for hub, proxy, and access-log workers touched by the replacements.
- [ ] R4: Keep a narrow documented allowlist only where a real child process/browser cannot expose deterministic readiness.
- [ ] R5: Make shuffled, repeated, and race stress commands reproducible in the canonical quality workflow.

## Acceptance Criteria

- [ ] AC1 (R1, R4): A checked inventory lists every original sleep, replacement/justification, owner package, and maximum bound.
- [ ] AC2 (R2): `rg -n 'time\.Sleep' --glob '*_test.go'` has no unapproved unit-level hit.
- [ ] AC3 (R2): Each replacement waits on the behavior under test and times out with a diagnostic naming the unmet condition.
- [ ] AC4 (R3): Tests prove hub subscriptions, proxy child workers, and access-log workers terminate after close/cancel; goroutine count is not asserted through brittle absolute totals.
- [ ] AC5 (R4): Any remaining polling helper has a bounded deadline, short interval, diagnostic context, and is restricted to process/browser E2E tests.
- [ ] AC6 (R5): `go test -race -shuffle=on -count=50 -timeout 10m ./internal/auth ./internal/proxy ./internal/web` passes three consecutive executions.
- [ ] AC7: Full ordinary/race suites and `make quality` remain green.

## Context

- Review baseline: 24 sleeps across ten `*_test.go` files; repeated x10 auth/proxy/web tests passed.
- High-value areas: proxy pipes/restart, WebSocket hub subscription, asynchronous auth/access-log recording.
- Use existing project convention: real lightweight dependencies, explicit cleanup, and no mock framework solely for timing control.

## Scenarios

1. Async event arrives immediately -> test observes the completion signal without sleeping.
2. Event never arrives -> bounded helper fails quickly with the missing state in its message.
3. Component closes -> worker goroutines exit -> repeated race test leaves no owned lifecycle behind.

## Out of Scope

- Replacing polling that is inherently external without an available readiness signal.
- Production refactors unrelated to exposing a narrow deterministic test seam.
- Arbitrary global goroutine-count thresholds.

## Documentation Impact

- Test-conventions documentation — deterministic async helper and approved polling exception policy.

## Research Hints

- Read `Argo Home/DevKB/go.md`, `testing.md`, and `architecture.md`.
- Prefer component-owned completion signals; use eventually polling only at true process boundaries.
- Make one package deterministic at a time and stress it before continuing.

## Validation Commands

```bash
rg -n 'time\.Sleep' --glob '*_test.go'
go test -race -shuffle=on -count=50 -timeout 10m ./internal/auth ./internal/proxy ./internal/web
go test -count=1 ./...
go test -race -count=1 -timeout 5m ./...
make quality
```
