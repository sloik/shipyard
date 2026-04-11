---
id: SPEC-008-001
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-007]
prior_attempts: []
parent: SPEC-008
nfrs: []
created: 2026-04-05
---

# Capture Store Coverage Gap Closure

## Problem

`internal/capture/store.go` still has uncovered branches in initialization, insertion, and query error handling. These are exactly the paths that are least likely to be exercised manually and most likely to break under unusual environments or corrupted state.

## Requirements

- [ ] Add tests for the remaining uncovered branches in `NewStore`
- [ ] Add tests for the remaining uncovered branches in `Insert`
- [ ] Add tests for the remaining uncovered branches in `Query`
- [ ] Use real assertions around store behavior or narrowly scoped failure injection
- [ ] Keep `go test ./...` green

## Acceptance Criteria

- [ ] AC 1: `internal/capture/store.go:NewStore` reaches `100.0%`
- [ ] AC 2: `internal/capture/store.go:Insert` reaches `100.0%`
- [ ] AC 3: `internal/capture/store.go:Query` reaches `100.0%`
- [ ] AC 4: Tests cover initialization failure and query/scan failure behavior where reachable
- [ ] AC 5: Existing store correlation tests continue to pass
- [ ] AC 6: `go test ./...` passes

## Context

- File under test: `internal/capture/store.go`
- Existing tests: `internal/capture/store_test.go`
- Current low-coverage functions:
  - `NewStore`
  - `Insert`
  - `Query`

## Alternatives Considered

- **Approach A: Narrow failure injection seams for DB/file init paths.**
  Acceptable if real environment failures are impractical to trigger deterministically.

- **Approach B: Skip hard failure paths.**
  Rejected because this spec exists to close them deliberately.

## Scenarios

1. Store initialization succeeds and enables normal persistence
2. Store initialization fails during DB or JSONL setup and returns a clear error
3. Querying with filter combinations returns expected pagination metadata
4. Insert/query failure paths are exercised deterministically and asserted explicitly

## Out of Scope

- Schema redesign
- Performance tuning
- JSONL format changes

## Research Hints

- Study `internal/capture/store.go` and `internal/capture/store_test.go`
- Prefer deterministic seams over global monkeypatching
- Preserve current persistence semantics

## Gap Protocol

- Research-acceptable gaps:
  - best seam for DB/file init failure
  - deterministic triggering of row scan/query failures
- Stop-immediately gaps:
  - reaching `100%` would require invasive redesign of the store API
- Max research subagents before stopping: 2

## Notes for the Agent

- Start with RED tests for the concrete uncovered branches reported by coverage.
