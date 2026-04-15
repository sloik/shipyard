---
id: SPEC-BUG-124
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: []
violates: [SPEC-028]
prior_attempts: []
created: 2026-04-15
---

# Switch Toggle Renders Two Knob Circles (Old ::after + New .switch-knob)

## Problem

Every switch toggle in the tool browser shows two white circles instead of one. This makes the toggles visually broken and hard to interpret. The cause is two competing CSS implementations of the switch knob that both apply to the same `.switch` elements.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** AC 27 — Switch components should have a single knob (16px circle); the double-knob breaks the entire toggle visual

## Reproduction

1. Open Tools tab → look at any toggle switch in the sidebar
2. **Actual:** Two white circles visible inside each switch pill
3. **Expected:** One white circle (16px), positioned at flex-end for On or flex-start for Off

## Root Cause

(Agent fills in during run.)

Two `.switch` CSS blocks exist in `ds.css`:

1. **Old block (line ~900):** Sets `position: relative` on `.switch` and creates a `::after` pseudo-element (14×14px white circle, `position: absolute`, `left: 3px`) with `.switch.is-on::after { transform: translateX(16px) }`. Uses class `.switch.is-on`.

2. **New SPEC-028 block (line ~2013):** Uses flexbox with a `.switch-knob` child span (16×16px white circle) and `justify-content: flex-end/flex-start`. Uses classes `.switch-on` / `.switch-off`.

Both blocks target `.switch` elements. The old `::after` pseudo-element and the new `.switch-knob` span both render, producing two knob circles. Additionally, the old block uses `.switch.is-on` while the new HTML uses `.switch-on` (different class convention), so the old positioning rules don't apply to the new toggles either.

## Requirements

- [ ] R1: Remove the old `.switch` CSS block (lines ~900-930) including `.switch::after`, `.switch.is-on`, and `.switch.is-on::after`
- [ ] R2: Verify no other UI elements use the old `.switch.is-on` class convention
- [ ] R3: Only the SPEC-028 switch block (line ~2013) remains active

## Acceptance Criteria

- [ ] AC 1: Each switch toggle renders exactly one knob circle (16px)
- [ ] AC 2: Switch/On: knob at flex-end (right side), blue pill background
- [ ] AC 3: Switch/Off: knob at flex-start (left side), gray pill background
- [ ] AC 4: No `::after` pseudo-element on `.switch` elements
- [ ] AC 5: AC 27 from SPEC-028 passes (correct switch design tokens)
- [ ] AC 6: No regressions — search for `.switch.is-on` class usage in HTML/JS; if any exist, migrate them to `.switch-on`

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- The old CSS block was part of the original ds.css before SPEC-028 was implemented
- SPEC-028 added a new switch component at the end of ds.css but didn't remove the old one
- Both blocks share the `.switch` base class, causing style conflicts

## Out of Scope

- Switch animation polish (transition timing)
- Switch accessibility (keyboard/screen reader — separate concern)

## Code Pointers

- Old block to remove: `internal/web/ui/ds.css` (lines ~900-930) — `.switch`, `.switch::after`, `.switch.is-on`, `.switch.is-on::after`
- New block to keep: `internal/web/ui/ds.css` (lines ~2013-2048) — `.switch`, `.switch-on`, `.switch-off`, `.switch-knob`
- Check HTML/JS for `.is-on` class usage: `internal/web/ui/index.html`
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
