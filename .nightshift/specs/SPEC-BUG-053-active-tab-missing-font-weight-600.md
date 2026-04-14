---
id: SPEC-BUG-053
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# Active tab does not use font-weight 600 as specified in design

## Problem

The active tab in the header nav uses the same font-weight as inactive tabs (500). The UX-002 design specifies that the active tab should have `fontWeight: 600` while inactive tabs use `fontWeight: 500`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tab/Active component (`ae085`) specifies `fontWeight: 600` for the label text. Tab/Default component (`3wZYe`) specifies `fontWeight: 500`. The live CSS `.tab-active` only changes color and border, not weight.

## Reproduction

1. Open any page in Shipyard UI
2. Inspect the active tab's computed font-weight
3. **Actual:** font-weight is 500 (inherited from `.tab` base rule)
4. **Expected:** font-weight should be 600 for the active tab

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Active tab uses font-weight 600
- [ ] R2: Default/inactive tabs remain at font-weight 500

## Acceptance Criteria

- [ ] AC 1: `.tab-active, .tab.is-active` includes `font-weight: 600` in `ds.css`
- [ ] AC 2: Inactive tabs remain at `font-weight: 500`
- [ ] AC 3: Tab width does not visibly shift when switching between active/inactive (font-weight change may cause width change — verify)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, Tab/Active (`ae085`) label `fontWeight: 600`; Tab/Default (`3wZYe`) label `fontWeight: 500`
- Bug location: `internal/web/ui/ds.css`, `.tab-active` rule (line ~796)

## Out of Scope

- Tab icons (SPEC-BUG-047)
- Tab padding or gap adjustments

## Code Pointers

- `internal/web/ui/ds.css` — `.tab` (line ~773), `.tab-active` (line ~796)

## Gap Protocol

- Research-acceptable gaps: whether font-weight 600 causes layout shift in the tab bar
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
