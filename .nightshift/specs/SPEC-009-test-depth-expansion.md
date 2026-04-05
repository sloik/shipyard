---
id: SPEC-009
priority: 1
layer: 0
type: main
status: done
children:
  - SPEC-009-001
  - SPEC-009-002
implementation_order:
  - SPEC-009-001
  - SPEC-009-002
created: 2026-04-05
---

# Regression and E2E Test Depth Expansion

## Problem

The repository now has full statement coverage, but that does not mean the test suite has enough depth in the places most likely to regress. Coverage-heavy unit tests proved branch behavior, but there is still room for higher-signal regression tests around CLI/runtime flows and for true end-to-end verification of the shipped binary and HTTP surface.

If this gets done casually, it will collapse back into more coverage chasing. It needs to go through the Nightshift pipeline as two explicit testing tracks: one for higher-value unit regressions and one for black-box e2e smoke coverage.

## Goal

Increase confidence in Shipyard by adding meaningful regression-oriented unit tests and end-to-end smoke tests without weakening existing tests or overfitting to implementation seams.

## Success Criteria

1. Add new tests that exercise user-visible behavior beyond current branch coverage
2. Add at least one binary-level or process-level end-to-end smoke path
3. Keep `go test ./...` green
4. Keep the new tests deterministic and CI-safe

## Child Specs

### SPEC-009-001: Regression Unit Test Expansion
- Add high-signal unit tests around CLI/config/proxy/web behavior not already asserted today
- Focus on invariants and behavior combinations rather than raw coverage

### SPEC-009-002: Binary E2E Smoke Coverage
- Add end-to-end tests that launch Shipyard with a stub child process and verify real HTTP/runtime behavior
- Focus on startup, traffic capture, and tool-surface smoke behavior

## Acceptance Criteria

- [x] AC-1: `SPEC-009-001` completes through Nightshift with additional unit-regression coverage
- [x] AC-2: `SPEC-009-002` completes through Nightshift with at least one true e2e smoke flow
- [x] AC-3: New tests are deterministic and do not rely on flaky sleeps as their primary oracle
- [x] AC-4: `go test ./...` passes after integration

## Out of Scope

- Browser automation for the dashboard UI
- New product features
- Replacing the current test framework or repo layout

## Notes for the Agent

- This is a coordination spec. Execute the child specs independently and then verify them together.
