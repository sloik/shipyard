---
id: SPEC-BUG-124
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
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

Two `.switch` CSS blocks coexisted in `ds.css`. The original block (~line 900) used `position: relative` on `.switch` and a `::after` pseudo-element (14×14px white circle, absolutely positioned) with `.switch.is-on::after { transform: translateX(16px) }`. SPEC-028 added a second `.switch` block at line ~2013 using flexbox and a `.switch-knob` child span (16×16px), but never removed the old block. Because both blocks targeted `.switch` elements, both the `::after` pseudo-element and the `.switch-knob` span rendered simultaneously — producing two visible knob circles. Additionally, the old block used `.switch.is-on` while new HTML used `.switch-on`/`.switch-off`, so the old toggle logic was also broken for all SPEC-028 switches.

Two `.switch` CSS blocks exist in `ds.css`:

1. **Old block (line ~900):** Sets `position: relative` on `.switch` and creates a `::after` pseudo-element (14×14px white circle, `position: absolute`, `left: 3px`) with `.switch.is-on::after { transform: translateX(16px) }`. Uses class `.switch.is-on`.

2. **New SPEC-028 block (line ~2013):** Uses flexbox with a `.switch-knob` child span (16×16px white circle) and `justify-content: flex-end/flex-start`. Uses classes `.switch-on` / `.switch-off`.

Both blocks target `.switch` elements. The old `::after` pseudo-element and the new `.switch-knob` span both render, producing two knob circles. Additionally, the old block uses `.switch.is-on` while the new HTML uses `.switch-on` (different class convention), so the old positioning rules don't apply to the new toggles either.

## Requirements

- [x] R1: Remove the old `.switch` CSS block (lines ~900-930) including `.switch::after`, `.switch.is-on`, and `.switch.is-on::after`
- [x] R2: Verify no other UI elements use the old `.switch.is-on` class convention
- [x] R3: Only the SPEC-028 switch block (line ~2013) remains active

## Acceptance Criteria

- [x] AC 1: Each switch toggle renders exactly one knob circle (16px)
- [x] AC 2: Switch/On: knob at flex-end (right side), blue pill background
- [x] AC 3: Switch/Off: knob at flex-start (left side), gray pill background
- [x] AC 4: No `::after` pseudo-element on `.switch` elements
- [x] AC 5: AC 27 from SPEC-028 passes (correct switch design tokens)
- [x] AC 6: No regressions — `is-on` class usage in `index.html`, `ds.js` migrated to `switch-on`/`switch-off`; zero remaining `is-on` references in `internal/`

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
