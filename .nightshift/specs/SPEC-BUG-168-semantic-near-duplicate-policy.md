---
id: SPEC-BUG-168
template_version: 7
priority: 2
layer: 0
type: refactor
status: done
after: [SPEC-BUG-157]
provides: [semantic-duplicate-consolidation-policy]
requires: [nightshift-valid-control-plane]
touches: [.nightshift/check_followup_spec.py, .nightshift/specs, .nightshift/reports]
prior_attempts: []
nfrs: [SPEC-NFR-001]
parent: SPEC-BUG-157
created: 2026-08-08
stack: nightshift
domain: code
output_type: policy
---

# Define a Policy for Semantic Near-Duplicate Consolidation

## Problem

SPEC-BUG-157 restored exact canonical spec identities but intentionally left
title/body-similarity findings from the semantic near-duplicate scanner out of
scope. Without a separate policy, maintainers may confuse similarity warnings
with identity corruption or consolidate historical records without evidence.

## Requirements

- [ ] R1: Define which semantic near-duplicate signals warrant review and
  which are informational only.
- [ ] R2: Define evidence and approval requirements before merging,
  retiring, or relinking historical specs.
- [ ] R3: Keep semantic consolidation separate from exact-ID uniqueness and
  structured-reference validation.
- [ ] R4: Specify auditable outcomes for every reviewed similarity finding.

## Acceptance Criteria

- [ ] AC1: The policy distinguishes exact identity defects from semantic
  similarity findings.
- [ ] AC2: The policy names the minimum evidence needed before changing an
  historical spec's identity, status, or dependencies.
- [ ] AC3: Scanner output can be classified as informational, review-needed,
  or approved consolidation with a recorded rationale.
- [ ] AC4: The policy does not weaken the exact-ID validation restored by
  SPEC-BUG-157.

## Context

- Created from the `## Suggested Follow-up Specs` section of
  `reports/2026-08-08-nightshift-report.md` for SPEC-BUG-157.
- `check_followup_spec.py --scan-all` is deliberately broader than exact-ID
  uniqueness and may report meaningful historical overlap.

## Out of Scope

- Automatically merging or retiring semantically similar specs.
- Altering production Go behavior.
