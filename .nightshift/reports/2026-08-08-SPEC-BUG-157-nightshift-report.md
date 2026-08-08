# Nightshift Report — SPEC-BUG-157

**Date:** 2026-08-08
**Branch:** `nightshift/SPEC-BUG-157-20260808R1`

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
  still exits 1 with 99 historical checkbox/status-content errors; no config-load,
  duplicate-ID, or graph-reference errors remain.
- PASS — `python3 .nightshift/preflight.py --spec-id SPEC-BUG-157` completes
  successfully without a YAML composer error.
- PASS — `go test -race -count=1 -timeout 5m ./...` exits 0; linker deployment
  target warnings are non-failing environment warnings.

## Acceptance criteria

- [x] AC1
- [x] AC2
- [x] AC3
- [x] AC4
- [x] AC5 (legacy findings itemized)
- [x] AC6 (composer error eliminated)
- [x] AC7
- [x] AC8

## Review

Diff review confirms only YAML document handling, validator mechanics, IDs, and
structured reference edges changed. Historical bodies and checkboxes were not
edited to obtain a green validator result.
