# Nightshift Report — SPEC-BUG-168

## Summary

Defined the policy governing semantic near-duplicate scanner findings. It keeps
similarity triage separate from exact spec identity and graph validation, and
requires evidence plus explicit maintainer approval before historical records
are consolidated, retired, or relinked.

## Changes

- Added `.nightshift/reports/semantic-near-duplicate-consolidation-policy.md`
  with classifications, evidence/approval gate, audit schema, and
  non-regression rule.
- No production Go code, existing spec identity, historical status, dependency,
  or scanner algorithm changed.

## Validation

- PASS — `python3 .nightshift/preflight.py --spec-id SPEC-BUG-168` completed.
- EXPECTED REVIEW INVENTORY — `python3 .nightshift/check_followup_spec.py --scan-all --specs-dir .nightshift/specs` exited 1 and reported semantic candidates across 218 specs; this is scanner output, not an exact-ID failure.
- PASS — `make coverage-check` (75.3% total; ratchet passed).
- PASS — `make lint`, `make type-check`, `make format-check`, and `make quality`.
- NOTE — `make quality` completed with existing macOS linker deployment-target
  warnings but exited 0; Go tests and race tests passed.

## Acceptance Criteria

- [x] AC1: Policy distinguishes exact identity defects from semantic findings.
- [x] AC2: Policy names identity, status, dependency, and approval evidence.
- [x] AC3: Policy defines informational, review-needed, and
  approved-consolidation outcomes with a recorded rationale.
- [x] AC4: Policy explicitly preserves SPEC-BUG-157 exact-ID and
  structured-reference validation.

## Blockers / discoveries

- The whole-corpus scanner currently reports many threshold matches. This policy
  intentionally treats them as review inventory, preventing similarity scores
  from rewriting historical truth.

## Suggested Follow-up Specs

None. No candidate was supplied, so no `check_followup_spec.py` conflict check
was applicable.
