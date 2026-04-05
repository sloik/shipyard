---
id: SPEC-008
priority: 1
layer: 0
type: main
status: done
children:
  - SPEC-008-001
  - SPEC-008-002
  - SPEC-008-003
  - SPEC-008-004
implementation_order:
  - SPEC-008-001
  - SPEC-008-002
  - SPEC-008-003
  - SPEC-008-004
created: 2026-04-05
---

# Statement Coverage Closure to 100%

## Problem

The repo now has strong test coverage, but it still falls short of full statement coverage. The remaining gaps are concentrated in error handling, edge-case parsing, store failure paths, and a handful of runtime branches that matter precisely because they are less frequently exercised.

If this work is done casually, it will drift into opportunistic edits and weak assertions. It needs to go through the Nightshift Kit pipeline as deliberate, test-first work with explicit acceptance criteria and bounded scope per area.

## Goal

Drive repository statement coverage from the current high-water mark to `100.0%` using Nightshift-managed specs only.

## Success Criteria

1. `go test ./... -coverprofile=...` reports `100.0%` statement coverage for the repo
2. Coverage gains come from real assertions on meaningful behavior, not weakened code or disabled branches
3. All remaining uncovered paths are addressed through package-scoped specs
4. Any required test seam is narrow, justified, and documented in the child spec that introduces it

## Coverage Gaps to Close

### SPEC-008-001: Capture Store Gap Closure
- Close remaining gaps in `internal/capture/store.go`
- Focus on `NewStore`, `Insert`, and `Query` error/edge branches

### SPEC-008-002: CLI + Config Gap Closure
- Close remaining gaps in `cmd/shipyard/main.go`
- Focus on `Config.UnmarshalJSON`, `runConfig`, `runProxy`, and residual CLI branches

### SPEC-008-003: Proxy Residual Branch Closure
- Close remaining gaps in `internal/proxy/manager.go` and `internal/proxy/proxy.go`
- Focus on residual helper/error branches left after `SPEC-007`

### SPEC-008-004: Web Handler Residual Branch Closure
- Close remaining gaps in `internal/web/server.go`
- Focus on traffic/tool-call/websocket edge/error paths

## Acceptance Criteria

- [ ] AC-1: Child specs `SPEC-008-001` through `SPEC-008-004` are completed through the Nightshift loop, not via ad hoc coding
- [ ] AC-2: Repository-wide statement coverage reaches `100.0%`
- [ ] AC-3: `go test ./...` remains green throughout
- [ ] AC-4: No assertions are weakened and no runtime branches are removed solely to improve coverage
- [ ] AC-5: Any introduced seam is minimal and documented in the implementing child spec

## Out of Scope

- Switching to a different coverage metric or test framework
- Chasing meaningless coverage in generated code
- Refactoring unrelated product behavior

## Notes for the Agent

- This is a coordination spec. Do not execute it directly as one monolithic change.
- Execute the children in order.
- Treat hard-to-reach branches as legitimate test-design work, not license to alter semantics.
