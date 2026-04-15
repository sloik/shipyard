---
id: SPEC-BUG-099
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Tokens tab exists in live UI but has no UX-002 design

## Problem

The nav bar includes a "Tokens" tab (SPEC-011 feature) that links to `#tokens`. UX-002 does not include a Tokens tab — the design-specified tabs are: Traffic, Tools, History, Servers, Sessions, Profiling, Schema. The Tokens feature may belong inside Settings or behind a sub-route rather than as a top-level tab.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Navigation tabs should match the UX-002 tab set.

## Reproduction

1. Open any page, look at the nav bar
2. **Actual:** "Tokens" tab is present between Servers and the disabled tabs
3. **Expected:** No "Tokens" tab in the main nav (per UX-002 design)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Decide: remove Tokens tab from nav, move it into Settings, or update UX-002 design to include it
- [ ] R2: If moved to Settings, Tokens view should be accessible from the Settings panel

## Acceptance Criteria

- [ ] AC 1: Nav bar tabs match UX-002 design tab set (no "Tokens" top-level tab)
- [ ] AC 2: Token management remains accessible (via Settings or other route)
- [ ] AC 3: `go build ./...` passes

## Context

- Design tabs (node `2v74z`): Traffic, Tools, History, Servers (N), Sessions, Profiling, Schema
- Tokens feature is fully implemented (SPEC-011): view, create, delete, stats, scopes
- Tokens view code: `#view-tokens` in `index.html`, JS at line ~4361

## Out of Scope

- Token functionality changes
- Other missing tabs (Sessions, Profiling, Schema are not yet implemented)

## Code Pointers

- `internal/web/ui/index.html` — nav bar (line ~24), Tokens tab link, `#tokens` route-target (line ~43), view-tokens (line ~630)
- Tokens JS starts at line ~4361

## Gap Protocol

- Research-acceptable gaps: product decision on where Tokens should live
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
