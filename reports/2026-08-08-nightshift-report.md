# Nightshift Human Review — SPEC-BUG-157

**Run:** `nightshift/SPEC-BUG-157-20260808R1`
**Worktree:** `/private/tmp/nightshift-bug157/shipyard-0e3a9e14b3bd/SPEC-BUG-157`
**Status:** complete

## Summary

Recovered the Nightshift control plane on a fresh worktree from `main`. The
configuration is one YAML mapping; the four exact duplicate historical IDs now
have unique canonical replacements; and validation checks duplicate IDs plus
the four structured graph-reference fields. The required Go race suite is
green.

## Changes

- Converted the malformed second YAML document boundary to a comment while
  retaining the multi-stack guidance.
- Repaired the four duplicate IDs and their structured graph edges; the
  permanent old-to-new record is `.nightshift/reports/spec-id-migration.md`.
- Extended `validate_specs.py` to surface exact duplicate IDs and unresolved
  `after`, `parent`, `children`, and `implementation_order` references.
- Updated preflight config handling to reject a non-mapping config explicitly.

## Validation

| Check | Result |
| --- | --- |
| YAML safe-load to one mapping | PASS |
| Exact graph audit (207 non-template specs) | PASS — 0 findings |
| `preflight.py --spec-id SPEC-BUG-157` | PASS |
| `go test -race -count=1 -timeout 5m ./...` | PASS |
| `validate_specs.py .nightshift/specs` | EXPECTED LEGACY FINDINGS — 99 historical unchecked-checkbox/status errors; no config, exact-ID, or graph-reference errors |
| `check_followup_spec.py --scan-all` | EXPECTED OUT-OF-SCOPE FINDINGS — semantic near-duplicates, not exact ID duplicates |
| `git diff --check main...HEAD` | PASS |

The Go link step emitted macOS deployment-target warnings but exited 0 and all
packages passed.

## Acceptance Criteria

- [x] AC1 — YAML safe-load succeeds and returns a mapping.
- [x] AC2 — exact-ID scan has zero duplicates.
- [x] AC3 — all four structured references resolve once.
- [x] AC4 — migration map records IDs, files, and rewritten references.
- [x] AC5 — config/duplicate errors are gone; legacy content findings are explicit.
- [x] AC6 — preflight reaches and passes validation without composer failure.
- [x] AC7 — review diff changes only IDs/references, config handling, and validator mechanics.
- [x] AC8 — race suite passes.

## Discoveries

The legacy semantic duplicate scanner is intentionally broader than this
identity repair: it reports content/title similarity even with unique IDs. The
remaining 99 validator findings are historical `done` specs with unchecked
checkboxes; they were neither hidden nor changed by this run.

## Suggested Follow-up Specs

- Audit and repair historical checkbox/status consistency if maintaining a
  globally green `validate_specs.py` result becomes a desired invariant.
- Define a separate policy for semantic near-duplicate consolidation; do not
  conflate it with canonical exact-ID identity.
