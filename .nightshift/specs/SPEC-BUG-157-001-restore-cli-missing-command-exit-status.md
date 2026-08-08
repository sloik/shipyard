---
id: SPEC-BUG-157-001
template_version: 7
priority: 1
layer: 0
type: bugfix
status: done
parent: SPEC-BUG-157
after: []
provides: [cli-config-validation-exit-contract]
requires: []
touches: [cmd/shipyard/main.go, cmd/shipyard/main_test.go]
prior_attempts: []
nfrs: [SPEC-NFR-001]
technologies: [go]
created: 2026-08-08
stack: go
domain: code
output_type: code
devkb_required: [go.md, testing.md, git.md]
karpathy_checklist: [think, surgical, goal]
---

# Restore the CLI exit status for a missing config command

## Problem

The full race gate required by SPEC-BUG-157 fails before its control-plane
changes are exercised. `cmd/shipyard.TestMain_ConfigMissingCommand` expects the
CLI to reject a configuration with a required command missing and exit with
status 1, but the current program exits 0. The same failure occurs on the
SPEC-BUG-157 parent base (`0a3aab7`) and its implementation branch, so it is a
baseline Shipyard CLI contract defect rather than a regression introduced by
the control-plane repair.

## Requirements

- [ ] R1: When Shipyard receives the test fixture representing a missing required
  config command, it returns a non-zero process exit status and a useful
  validation diagnostic.
- [ ] R2: Preserve successful startup and exit behavior for valid configurations.
- [ ] R3: Add or correct focused regression coverage that proves the process exit
  contract, without weakening the assertion.
- [ ] R4: Do not change MCP proxy routing, bridge behavior, or Nightshift
  control-plane files.

## Acceptance Criteria

- [ ] AC1 (R1): `TestMain_ConfigMissingCommand` passes and asserts a non-zero
  exit status for its missing-command fixture.
- [ ] AC2 (R1): The test evidence shows a clear configuration-validation
  diagnostic for that fixture.
- [ ] AC3 (R2): Existing valid-configuration CLI tests continue to pass.
- [ ] AC4 (R3): `go test ./cmd/shipyard -run TestMain_ConfigMissingCommand -count=1`
  passes without skipped or weakened assertions.
- [ ] AC5 (R1-R3): `go test -race -count=1 -timeout 5m ./...` exits 0 with no
  data-race warnings.
- [ ] AC6 (R4): Review diff contains changes only under `cmd/shipyard/` and
  documentation/report/metrics artifacts required by this spec.

## Context

- Failing test: `cmd/shipyard/main_test.go:149`.
- Candidate implementation path: `cmd/shipyard/main.go`.
- Reproduction from the parent kickoff evidence:
  `go test -race -count=1 -timeout 5m ./...` exits 1 with
  `expected exit code 1, got 0`.
- This spec was created to satisfy the unblock condition recorded in
  `SPEC-BUG-157`: repair the baseline defect, then re-run its full race gate.

## Scenarios

1. A user supplies a configuration missing a required command; Shipyard rejects
   it with an actionable diagnostic and a non-zero exit status.
2. A user supplies a valid configuration; Shipyard retains its existing normal
   startup behavior.
3. The full race suite runs after the fix and exits successfully.

## Out of Scope

- Reworking the broader configuration schema.
- Changing MCP bridge timeout, proxy routing, or Wails behavior.
- Editing the SPEC-BUG-157 control-plane implementation.
- Marking SPEC-BUG-157 done; its evidence gate must be re-run independently.

## Validation Commands

```bash
go test ./cmd/shipyard -run TestMain_ConfigMissingCommand -count=1
go test -race -count=1 -timeout 5m ./...
go vet ./...
go build ./...
```
