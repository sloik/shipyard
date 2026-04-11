---
id: SPEC-007
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-001]
prior_attempts: []
parent:
nfrs: []
created: 2026-04-05
---

# Deterministic Integration Harness for `Proxy.Run` Restart Supervision

## Problem

`internal/proxy.Proxy.Run` is still the main uncovered runtime path in the proxy core. The existing tests now cover config parsing, helper logic, `runChild`, websocket behavior, and much of the CLI, but the orchestration loop that supervises child processes is still effectively unverified.

That leaves the most failure-prone behavior without deterministic protection:
- child crash detection and restart
- repeated crash cutoff
- context cancellation while supervising
- coordination between `Run`, `runChild`, `proxyClientInput`, and managed input writers

This matters now because recent coverage work pushed the repo to 85% overall, and `Proxy.Run` is the largest remaining blind spot. It also sits directly on top of the restart behavior described in Phase 0 proxy expectations.

## Requirements

- [ ] Add a deterministic integration test harness for `internal/proxy.Proxy.Run`.
- [ ] The harness must be able to simulate child lifecycle states relevant to supervision: clean exit, non-zero exit, repeated crash, stdout/stderr emission, and blocked or delayed execution.
- [ ] Add end-to-end tests that exercise `Proxy.Run` through a clean supervised run.
- [ ] Add end-to-end tests that prove `Proxy.Run` restarts a crashed child and continues supervising.
- [ ] Add end-to-end tests that prove `Proxy.Run` stops restarting after the configured crash threshold is exceeded.
- [ ] Add end-to-end tests that prove context cancellation stops supervision cleanly without hanging or leaking goroutines.
- [ ] Keep the harness test-oriented and local to `internal/proxy`; do not change runtime behavior unless a narrow test seam is truly required.
- [ ] Preserve the existing green state for `go test ./...`.

## Acceptance Criteria

- [ ] AC 1: `Proxy.Run` has deterministic integration tests that do not rely on arbitrary long sleeps; synchronization uses bounded polling, helper channels, or equivalent controlled coordination.
- [ ] AC 2: A test demonstrates a child process can start under `Proxy.Run`, exchange traffic, and exit cleanly while supervision unwinds correctly.
- [ ] AC 3: A test demonstrates a child crash triggers restart behavior and that supervision continues after the restart.
- [ ] AC 4: A test demonstrates repeated crashes eventually hit the configured crash ceiling and return a fatal error instead of restarting forever.
- [ ] AC 5: A test demonstrates context cancellation during active supervision or backoff causes `Proxy.Run` to return cleanly.
- [ ] AC 6: `go test ./...` passes after the harness and tests are added.
- [ ] AC 7: Coverage for `internal/proxy.Proxy.Run` increases from `0.0%` to a meaningful non-zero level.
- [ ] AC 8: Existing proxy helper tests continue to pass without weakening assertions or removing coverage.

## Context

- Primary code under test: `internal/proxy/proxy.go`
- Existing proxy tests:
  - `internal/proxy/proxy_test.go`
  - `internal/proxy/proxy_additional_test.go`
  - `internal/proxy/proxy_more_test.go`
- Related CLI subprocess pattern: `cmd/shipyard/main_test.go`
- Source spec for this runtime behavior: `.nightshift/specs/SPEC-001-phase0-mvp-proxy.md`
- Relevant DevKB files:
  - `/Users/ed/Dropbox/Argo/DevKB/go.md`
  - `/Users/ed/Dropbox/Argo/DevKB/testing.md`

Constraints:
- Prefer real subprocess fixtures over broad mocking.
- Keep the solution package-local if possible.
- Preserve current restart semantics unless an explicit testability seam is justified and documented.

## Alternatives Considered

- **Approach A: Deterministic subprocess harness in tests.**
  Chosen because it exercises the real supervision loop with minimal production distortion.

- **Approach B: Heavy mocking of `runChild` and timing primitives.**
  Rejected because it risks testing a fake control flow rather than the actual orchestration path.

- **Approach C: Leave `Proxy.Run` uncovered and rely on lower-level helper tests.**
  Rejected because the remaining risk is precisely in lifecycle coordination, not in the already-covered helper functions.

## Scenarios

1. A test-only child process starts, writes valid JSON-RPC output, stays alive long enough for supervision to observe it, then exits cleanly; `Proxy.Run` returns without hanging and captured traffic is persisted.
2. A test-only child process exits with a non-zero code on first launch, then behaves normally on restart; `Proxy.Run` performs one restart and continues supervising.
3. A test-only child process crashes repeatedly within the crash window; `Proxy.Run` stops restarting and returns a fatal error after the configured threshold.
4. A supervised child is running or waiting in restart backoff when the test cancels context; `Proxy.Run` exits cleanly and does not strand goroutines or child I/O.

## Out of Scope

- Reworking restart policy semantics
- Changing dashboard, API, or websocket behavior
- Adding replay/history capabilities
- Increasing coverage in unrelated packages
- Performance optimization beyond what is required to make the tests reliable

## Research Hints

- Files to study:
  - `internal/proxy/proxy.go`
  - `internal/proxy/proxy_test.go`
  - `internal/proxy/proxy_additional_test.go`
  - `internal/proxy/proxy_more_test.go`
  - `cmd/shipyard/main_test.go`
- Patterns to look for:
  - subprocess helper-process pattern
  - bounded wait helpers instead of open-ended sleeps
  - real store-backed assertions using `t.TempDir()`
- DevKB:
  - `go.md`
  - `testing.md`

## Gap Protocol

- Research-acceptable gaps:
  - choosing the smallest deterministic test seam
  - selecting between helper-process and scripted child fixtures
  - coordinating restart observation without flaky timing
- Stop-immediately gaps:
  - the required behavior of `Proxy.Run` is ambiguous
  - the only feasible approach requires broad production refactoring
  - restart semantics in code and spec materially disagree
- Max research subagents before stopping: 3

## Notes for the Agent

- Start with RED tests for the clean-exit, restart, and crash-cutoff paths before adding any seam.
- If a seam is required, keep it narrow, document why, and prefer dependency injection of timing/process hooks over broader architectural changes.
- This spec should improve confidence in SPEC-BUG-002-class behavior even if it does not directly implement a new user-facing feature.
