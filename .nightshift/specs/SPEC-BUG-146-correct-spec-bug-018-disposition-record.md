---
id: SPEC-BUG-146
template_version: 3
priority: 2
layer: 3
type: refactor
status: draft
after: [SPEC-BUG-145]
nfrs: []
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Correct SPEC-BUG-018's disposition record — group collapse interactivity now exists

## Problem

SPEC-BUG-018 is marked `done` with a "Disposition: Invalidated" note asserting
that Tool Browser server groups already expand/collapse on click, and that the
reported bug was not real. SPEC-BUG-145 established that this disposition was
factually wrong: before SPEC-BUG-145, the `toolGroups` click handler only
handled `.tool-item`, and online groups had **no** user-driven collapse path —
only offline/restarting groups auto-collapsed. User-driven group collapse
interactivity was actually introduced by SPEC-BUG-145.

The stale disposition misleads future readers about when group-collapse
interactivity entered the codebase and why SPEC-BUG-145's diff is larger than a
pure retention fix.

## Requirements

- [ ] R1: SPEC-BUG-018's record reflects that its "groups already collapse on
  click" disposition was inaccurate, with a pointer to SPEC-BUG-145 as where
  user-driven group collapse was actually implemented.
- [ ] R2: SPEC-BUG-145 remains the authoritative record of the implemented
  behavior; this change only annotates SPEC-BUG-018's historical record.

## Acceptance Criteria

- [ ] AC1: SPEC-BUG-018 contains an annotation correcting the disposition and
  referencing SPEC-BUG-145.
- [ ] AC2: No code or test changes are made by this spec (record-only).

## Context

This is a documentation/record-accuracy correction surfaced by the SPEC-BUG-145
run report (`.nightshift/reports/2026-06-03-nightshift-report-SPEC-BUG-145.md`).

## Out of Scope

- Any change to UI behavior or tests.
- Re-opening or re-running SPEC-BUG-018.

## Code Pointers

- `.nightshift/specs/SPEC-BUG-018-tool-browser-groups-not-collapsible.md`

## Notes

This may be lighter-weight than a full spec warrants — a direct one-line
annotation to SPEC-BUG-018 could suffice instead of a tracked spec. Left as a
draft for the maintainer to decide.
