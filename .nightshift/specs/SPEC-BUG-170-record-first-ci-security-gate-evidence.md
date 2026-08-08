---
id: SPEC-BUG-170
template_version: 7
priority: 2
layer: 0
type: refactor
status: draft
after: [SPEC-BUG-159]
provides: [first-ci-security-gate-evidence]
requires: [vulnerability-gate]
touches: [.github/workflows, reports]
prior_attempts: []
nfrs: []
parent: SPEC-BUG-159
created: 2026-08-08
stack: go
domain: code
output_type: evidence
---

# Record First CI Security-Gate Evidence

## Problem

SPEC-BUG-159 configured the CI security gate but has no retained first-run CI
outcome showing that the scheduled/PR path behaves as intended.

## Requirements

- [ ] R1: Trigger or identify the first CI run executing the security gate.
- [ ] R2: Preserve a concise non-sensitive outcome record without raw scanner logs.
- [ ] R3: Confirm the workflow's configured permissions and pinned actions apply.

## Acceptance Criteria

- [ ] AC1: Evidence identifies the CI run, conclusion, and executed security steps.
- [ ] AC2: No scanner output containing secret material is stored or uploaded.
- [ ] AC3: The evidence links back to SPEC-BUG-159 and documents any CI-only gap.
