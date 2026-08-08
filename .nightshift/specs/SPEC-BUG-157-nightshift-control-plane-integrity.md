---
id: SPEC-BUG-157
template_version: 7
priority: 1
layer: 0
type: refactor
status: ready
after: []
provides: [nightshift-valid-control-plane, unique-spec-identities]
requires: []
touches: [.nightshift/config.yaml, .nightshift/specs, .nightshift/validate_specs.py]
prior_attempts: []
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: nightshift
domain: code
output_type: config
devkb_required: [python.md, architecture.md, git.md]
cortex_cites: []
karpathy_checklist: [think, surgical, goal]
---

# Restore Nightshift Control-Plane Integrity

## Prior Blocker Resolved

AC8's baseline failure was repaired by SPEC-BUG-157-001. On 2026-08-08,
`go test -race -count=1 -timeout 5m ./...` passed on main. This spec is ready
for its own recovery run and evidence gate; that recovery remains separate from
the unblock repair.


## Problem

Nightshift cannot reliably select or validate Shipyard work. `.nightshift/config.yaml`
contains a second YAML document beginning at line 80, so single-document loaders fail.
The live spec set also reuses `SPEC-006`, `SPEC-007`, `SPEC-008`, and `SPEC-009` for two
different files each. On 2026-07-18, `validate_specs.py` reported 98 invalid specs out of
204 and could not load the project config. Dependencies and status lookups are therefore
ambiguous before any new quality work begins.

## Requirements

- [ ] R1: Make `.nightshift/config.yaml` one valid YAML document without losing its active configuration or optional multi-stack guidance.
- [ ] R2: Give every non-template spec a unique canonical ID and update all structured references to renamed IDs.
- [ ] R3: Produce an auditable old-to-new ID migration map that distinguishes historical identity repair from implementation-status changes.
- [ ] R4: Restore deterministic validation for config parsing, exact IDs, references, and dependencies.
- [ ] R5: Preserve existing spec bodies and checkbox/status history except where an ID/reference must change.

## Acceptance Criteria

- [ ] AC1 (R1): `python3 -c 'import yaml; yaml.safe_load(open(".nightshift/config.yaml"))'` exits 0 and returns one mapping.
- [ ] AC2 (R2): An exact-ID scan across non-template `.nightshift/specs/*.md` reports zero duplicate IDs.
- [ ] AC3 (R2, R4): Every `after`, `parent`, `children`, and `implementation_order` reference resolves to exactly one spec.
- [ ] AC4 (R3): `.nightshift/reports/spec-id-migration.md` lists every renamed file, old ID, new ID, and each updated reference.
- [ ] AC5 (R4): `python3 .nightshift/validate_specs.py .nightshift/specs` reports no config-load or duplicate-ID errors; unrelated legacy content errors are itemized rather than hidden.
- [ ] AC6 (R4): `python3 .nightshift/preflight.py` reaches config/spec validation without a YAML composer error.
- [ ] AC7 (R5): A review diff confirms no historical requirement, AC, status, or completion checkbox changed solely to make validation green.
- [ ] AC8: `go test -race -count=1 -timeout 5m ./...` remains green.

## Context

- Invalid document boundary: `.nightshift/config.yaml:80`.
- Duplicate live IDs: the two files for each of `SPEC-006`, `SPEC-007`, `SPEC-008`, and `SPEC-009`.
- Validators: `.nightshift/validate_specs.py`, `.nightshift/preflight.py`, and `.nightshift/check_followup_spec.py`.
- Templates are examples and must be excluded from exact-ID uniqueness checks.
- The migration must not guess which historical spec was implemented; preserve evidence and record ambiguity.

## Scenarios

1. Nightshift loads Shipyard config -> receives one mapping -> validates the spec graph -> selects an unambiguous spec ID.
2. A maintainer follows an old ID in the migration report -> finds the canonical replacement and all rewritten dependencies.
3. A future duplicate ID is introduced -> validation fails with both conflicting filenames.

## Out of Scope

- Rewriting historical specifications for style or completeness.
- Resolving semantic near-duplicates reported only by title/body similarity.
- Changing production Go behavior.
- Promoting any draft spec to `ready`.

## Documentation Impact

- `.nightshift/reports/spec-id-migration.md` — permanent identity migration record.
- `.nightshift/config.yaml` — retain optional multi-stack documentation as YAML comments or move it to the config reference.

## Research Hints

- Read `Argo Home/DevKB/python.md`, `architecture.md`, and `git.md` before editing validators/spec metadata.
- Generate the duplicate/reference inventory before assigning replacement IDs.
- Use `.nightshift/check_followup_spec.py` for each replacement ID; do not increment IDs manually.
- Validate after each identity pair, then run the full graph check.

## Validation Commands

```bash
python3 -c 'import yaml; data=yaml.safe_load(open(".nightshift/config.yaml")); assert isinstance(data, dict)'
python3 .nightshift/validate_specs.py .nightshift/specs
python3 .nightshift/preflight.py
python3 .nightshift/check_followup_spec.py --specs-dir .nightshift/specs --scan-all
go test -race -count=1 -timeout 5m ./...
```
