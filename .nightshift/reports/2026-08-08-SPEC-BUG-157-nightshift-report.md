# Nightshift Report — SPEC-BUG-157

**Date:** 2026-08-08
**Branch:** `nightshift/SPEC-BUG-157-C4A9FD7D`

## Summary

Repaired the Nightshift control plane: config parsing now uses one YAML document,
the four exact duplicate IDs were assigned deterministic canonical replacements,
and graph validation now detects duplicate IDs plus unresolved structured
references. No product Go code or historical completion state changed.

## Per-spec changes

- Renamed the four duplicate-ID records documented in `spec-id-migration.md`.
- Repointed three Phase-4 child `parent` fields to `SPEC-006-004`.
- Removed two dangling structured references where no live canonical target
  exists, recording the ambiguity in the migration map.
- Preserved all requirement, acceptance-criterion, status, and checkbox history.

## Validation

- PASS — `yaml.safe_load(.nightshift/config.yaml)` returns one mapping.
- PASS — exact non-template ID scan reports zero duplicate IDs.
- PASS — graph validator reports zero duplicate or unresolved
  `after`/`parent`/`children`/`implementation_order` references.
- PASS — `python3 -m py_compile .nightshift/validate_specs.py .nightshift/preflight.py`.
- EXPECTED LEGACY FINDINGS — `python3 .nightshift/validate_specs.py .nightshift/specs`
  still exits 1 with 98 historical checkbox/status-content errors; no config-load,
  duplicate-ID, or graph-reference errors remain.
- BLOCKED BASELINE — preflight reaches config/spec validation without a YAML
  composer error, then fails because the worktree is intentionally dirty and
  `go test ./...` has an unrelated existing `cmd/shipyard` failure.
- BLOCKED — `go test -race -count=1 -timeout 5m ./...` fails only at
  `TestMain_ConfigMissingCommand` (expected exit code 1, got 0).

## Acceptance criteria

- [x] AC1
- [x] AC2
- [x] AC3
- [x] AC4
- [x] AC5 (legacy findings itemized)
- [x] AC6 (composer error eliminated)
- [x] AC7
- [ ] AC8 — blocked by the unrelated baseline test failure above.

## Review

Diff review confirms only YAML document handling, validator mechanics, IDs, and
structured reference edges changed. Historical bodies and checkboxes were not
edited to obtain a green validator result.
