---
id: SPEC-009-001
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-008]
prior_attempts: []
parent: SPEC-009
nfrs: []
created: 2026-04-05
---

# Regression Unit Test Expansion

## Problem

The current Go test suite proves every statement executes, but several higher-value invariants are still only indirectly covered. That leaves room for future regressions where code still hits the same branches yet subtly changes visible behavior across CLI routing, manager interactions, captured traffic shape, and API payload contracts.

## Requirements

- [x] Add new unit tests that assert behavior combinations not already locked down by the current suite
- [x] Prefer user-visible invariants over seam-specific implementation details
- [x] Keep changes scoped to tests unless a minimal seam is required for determinism
- [x] Keep `go test ./...` green

## Acceptance Criteria

- [x] AC 1: At least one new regression test is added for CLI/config behavior
- [x] AC 2: At least one new regression test is added for proxy or manager behavior
- [x] AC 3: At least one new regression test is added for web or capture behavior
- [x] AC 4: New tests assert meaningful output/state, not just that functions return
- [x] AC 5: `go test ./...` passes

## Context

- Existing test files:
  - `cmd/shipyard/*_test.go`
  - `internal/capture/store_test.go`
  - `internal/proxy/*_test.go`
  - `internal/web/*_test.go`

## Alternatives Considered

- **Approach A: More branch-level tests for already-covered code.**
  Rejected because coverage is already `100.0%`; that would add bulk, not confidence.

- **Approach B: Regression tests around behavior combinations and output contracts.**
  Preferred because it guards user-visible behavior against future refactors.

## Scenarios

1. CLI/config paths preserve expected routing and error semantics across combinations
2. Proxy/manager behavior keeps request/response and lifecycle invariants intact
3. Capture/web paths preserve expected payload shapes and filtering behavior

## Out of Scope

- Full process-level flows that belong in e2e tests
- Browser UI automation

## Notes for the Agent

- Pick tests that would still matter even if implementation seams changed.
