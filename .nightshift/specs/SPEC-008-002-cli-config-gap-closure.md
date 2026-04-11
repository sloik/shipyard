---
id: SPEC-008-002
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-008-001]
prior_attempts: []
parent: SPEC-008
nfrs: []
created: 2026-04-05
---

# CLI and Config Coverage Gap Closure

## Problem

`cmd/shipyard/main.go` still has uncovered branches around config decoding, config-mode defaults and warnings, and some `runProxy` failure paths. These are user-facing startup paths and should be fully specified by tests if the project is claiming complete coverage.

## Requirements

- [ ] Add tests for the remaining uncovered branches in `Config.UnmarshalJSON`
- [ ] Add tests for the remaining uncovered branches in `runConfig`
- [ ] Add tests for the remaining uncovered branches in `runProxy`
- [ ] Use subprocess tests or minimal seams where `os.Exit` and signal/runtime behavior require it
- [ ] Keep `go test ./...` green

## Acceptance Criteria

- [ ] AC 1: `cmd/shipyard/main.go:UnmarshalJSON` reaches `100.0%`
- [ ] AC 2: `cmd/shipyard/main.go:runConfig` reaches `100.0%`
- [ ] AC 3: `cmd/shipyard/main.go:runProxy` reaches `100.0%`
- [ ] AC 4: Tests cover config-mode default-port and multi-server-warning behavior
- [ ] AC 5: Tests cover startup failure paths without weakening runtime behavior
- [ ] AC 6: `go test ./...` passes

## Context

- File under test: `cmd/shipyard/main.go`
- Existing tests:
  - `cmd/shipyard/config_test.go`
  - `cmd/shipyard/main_test.go`

## Alternatives Considered

- **Approach A: Subprocess harness for exit-heavy CLI behavior.**
  Preferred where behavior is already process-oriented.

- **Approach B: Large refactor to eliminate `os.Exit`.**
  Rejected for this spec; coverage work should not force broad CLI redesign.

## Scenarios

1. Config mode uses the first configured server and warns when multiple servers exist
2. Config mode defaults the port when omitted
3. Invalid config structure fails with precise errors
4. Runtime startup failures are asserted through deterministic tests

## Out of Scope

- New CLI features
- Multi-server execution support
- Config format redesign

## Research Hints

- Reuse the existing helper-process pattern in `cmd/shipyard/main_test.go`
- Keep seams narrow if `runProxy` failures are otherwise unreachable

## Gap Protocol

- Research-acceptable gaps:
  - smallest seam for `runProxy` startup failure injection
  - process-level assertion strategy for config-mode exits
- Stop-immediately gaps:
  - achieving coverage would require broad CLI restructuring
- Max research subagents before stopping: 2

## Notes for the Agent

- Prefer asserting exact visible CLI/runtime behavior over testing implementation trivia.
