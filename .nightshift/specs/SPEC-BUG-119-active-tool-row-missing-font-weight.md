---
id: SPEC-BUG-119
template_version: 2
priority: 3
layer: 2
type: bugfix
status: ready
after: []
violates: [SPEC-028]
prior_attempts: []
created: 2026-04-15
---

# Active/Selected Sidebar Tool Row Missing font-weight 500

## Problem

When a tool is selected (active) in the sidebar, the tool name renders at font-weight 400 (normal). SPEC-028 R16/AC 21 specify that the active/selected tool row should use font-weight 500.

**Violated spec:** SPEC-028 (Tool & Server Enable/Disable Toggles)
**Violated criteria:** AC 21 — enabled + selected tool row should have text weight 500; R16 — font-weight 500 if active

## Reproduction

1. Open Tools tab → click any tool in the sidebar to select it
2. Inspect the tool name text on the selected (highlighted) row
3. **Actual:** font-weight is 400 (normal)
4. **Expected:** font-weight is 500

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Active/selected tool row name text uses font-weight 500

## Acceptance Criteria

- [ ] AC 1: Selected tool name text renders at font-weight 500
- [ ] AC 2: Non-selected tool names remain at font-weight 400 (normal)
- [ ] AC 3: AC 21 from SPEC-028 passes
- [ ] AC 4: No regressions — layout doesn't shift when selecting tools

## Context

- Violated spec: SPEC-028 (Tool & Server Enable/Disable Toggles)
- The `.tool-item.is-active` CSS rule in ds.css sets `background` and `color` but does not set `font-weight`

## Out of Scope

- Active row background color (separate bug)
- Active row icon color (separate bug)

## Code Pointers

- Bug area: `internal/web/ui/ds.css` (line ~1853) — `.tool-item.is-active` rule missing `font-weight: 500`
- Violated spec: `.nightshift/specs/SPEC-028-tool-server-enable-disable.md`
