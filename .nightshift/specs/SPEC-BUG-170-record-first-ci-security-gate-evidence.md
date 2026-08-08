---
id: SPEC-BUG-170
template_version: 7
priority: 2
layer: 0
type: refactor
status: done
after: [SPEC-BUG-159]
provides: [first-ci-security-gate-evidence]
requires: [vulnerability-gate]
touches: [.github/workflows, reports]
prior_attempts: []
nfrs: [SPEC-NFR-001]
parent: SPEC-BUG-159
created: 2026-08-08
stack: go
domain: code
output_type: evidence
---

# Record First CI Security-Gate Evidence

## Resolution

The required CI run is recorded in
`reports/2026-08-08-nightshift-report-SPEC-BUG-170.md`. It executed the
security gate and concluded `failure`; the report retains metadata only, not
scanner output.


## Problem

SPEC-BUG-159 configured the CI security gate but has no retained first-run CI
outcome showing that the scheduled/PR path behaves as intended.

## Requirements

- [x] R1: Trigger or identify the first CI run executing the security gate.
- [x] R2: Preserve a concise non-sensitive outcome record without raw scanner logs.
- [x] R3: Confirm the workflow's configured permissions and pinned actions apply.

## Acceptance Criteria

- [x] AC1: Evidence identifies the CI run, conclusion, and executed security steps.
- [x] AC2: No scanner output containing secret material is stored or uploaded.
- [x] AC3: The evidence links back to SPEC-BUG-159 and documents any CI-only gap.
