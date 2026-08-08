---
id: SPEC-BUG-167
template_version: 7
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-BUG-157]
provides: [historical-spec-status-consistency]
requires: [nightshift-valid-control-plane]
touches: [.nightshift/specs, .nightshift/validate_specs.py]
prior_attempts: []
nfrs: [SPEC-NFR-001]
parent: SPEC-BUG-157
created: 2026-08-08
stack: nightshift
domain: code
output_type: spec-metadata
---

# Audit Historical Checkbox and Status Consistency

## Problem

SPEC-BUG-157 restored deterministic control-plane validation but documented 99
historical checkbox/status findings. They remain visible rather than hidden,
yet a globally green `validate_specs.py` run requires a separate, auditable
decision for each historical inconsistency.

## Requirements

- [x] R1: Inventory every remaining checkbox/status consistency finding emitted
  by `.nightshift/validate_specs.py`.
- [x] R2: Classify each finding as metadata repair, intentional historical
  record, or unresolved evidence gap without inferring implementation status.
- [x] R3: Apply only justified metadata repairs and retain an audit record for
  every changed spec.
- [x] R4: Make the validator's remaining findings, if any, explicit and
  actionable.

## Acceptance Criteria

- [x] AC1: The full validation output is inventoried with one disposition per
  historical finding.
- [x] AC2: Every changed historical spec has an auditable rationale and no
  requirement or acceptance-criterion prose is rewritten solely to satisfy the
  validator.
- [x] AC3: `python3 .nightshift/validate_specs.py .nightshift/specs` reports
  only explicitly documented residual findings, or exits clean.
- [x] AC4: The change record distinguishes historical evidence repair from any
  implementation-status claim.

## Context

- Created from the `## Suggested Follow-up Specs` section of
  `reports/2026-08-08-nightshift-report.md` for SPEC-BUG-157.
- SPEC-BUG-157 deliberately left the 99 legacy findings out of scope.

## Out of Scope

- Implementing product behavior.
- Treating a checkbox as proof that a historical feature shipped.
