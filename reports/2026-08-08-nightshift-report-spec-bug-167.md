# Nightshift Report — SPEC-BUG-167

## Summary

Audited the validator baseline at `cc93b62`. The prior estimate of 99 was not
the current corpus: the baseline emitted 1,068 unchecked Requirement/Acceptance
Criterion findings in 106 `done` specs, plus three invalid legacy NFR statuses.

The full, per-finding inventory is
`.nightshift/historical-checkbox-status-dispositions.json`. Each entry records
the filename, original line, section, and unchecked text, with the explicit
disposition `intentional_historical_record`. This is evidence preservation, not
an assertion that any listed requirement or AC was implemented.

## Changes

- Added a fail-closed validator allowlist: only an exact inventory match is
  downgraded to a warning; changed, added, or unlisted unchecked items remain
  errors.
- Added the 106-spec / 1,068-finding inventory, sourced from the unmodified
  validator output at the lifecycle baseline.
- Repaired only three invalid `type: nfr` status values:
  `SPEC-013`, `SPEC-014`, and `SPEC-015` changed `done` to `retired`. This is
  NFR lifecycle metadata repair; it makes no product implementation claim.
- No historical requirement or acceptance-criterion prose was changed. No
  historical checkbox was checked.

## Validation

- `python3 .nightshift/validate_specs.py .nightshift/specs` — pass with 106
  warnings: 103 explicit historical-checkbox residuals (the three retired NFR
  records no longer participate in the terminal checkbox rule) and three
  pre-existing draft NFR-reconciliation warnings for SPEC-BUG-168–170.
- `python3 -m json.tool .nightshift/historical-checkbox-status-dispositions.json`
  — pass.

## Acceptance Criteria

- [x] AC1 — Inventory contains one exact disposition record for all 1,068
  baseline checkbox/status findings.
- [x] AC2 — The only historical-spec edits are three NFR status metadata
  repairs; all requirement/AC prose and historical checkbox states are intact.
- [x] AC3 — Validator exits cleanly while showing only explicitly documented
  historical-checkbox residual warnings.
- [x] AC4 — Inventory policy and report explicitly distinguish historical
  evidence preservation from implementation status.

## Residuals

103 intentional historical records remain visible as warnings. Any drift from
their exact recorded lines/text turns back into a validator error and needs a
fresh evidence decision.

## Suggested Follow-up Specs

None. The remaining warning inventory is intentionally retained, not hidden.
