---
id: SPEC-BUG-109
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Nav tabs stack vertically — header overflows

## Problem

`#tab-nav` has `display: block`, so its child `.tab` links (each 48px tall after BUG-106 fix) stack vertically. The nav becomes 192px tall (4 × 48px), blowing out the 48px header and causing the header to clip or overflow. Tabs should be in a horizontal row.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tab bar is a horizontal row of tabs inside the header (design node `2v74z`).

## Reproduction

1. Open any page, look at the header
2. **Actual:** Tabs are stacked vertically, header is taller than expected or clips
3. **Expected:** Tabs in a single horizontal row, header stays 48px tall

## Root Cause

`#tab-nav` in `ds.css` only appears in a `--wails-draggable: no-drag` rule (line ~793). It has no `display: flex` declaration, so it defaults to `display: block`. Each `.tab` is a block-level `<a>` element, so they stack vertically. This became a visible regression after BUG-106 set `height: 48px` on tabs.

## Requirements

- [ ] R1: `#tab-nav` must be `display: flex; flex-direction: row; align-items: center;`
- [ ] R2: Tabs should have `gap: 0` between them (design shows tabs touching)

## Acceptance Criteria

- [ ] AC 1: Nav tabs render in a single horizontal row
- [ ] AC 2: Header height remains 48px
- [ ] AC 3: All 4 tabs (Traffic, Tools, History, Servers) are visible in one row
- [ ] AC 4: Tab active border-bottom and border-radius still render correctly
- [ ] AC 5: `go build ./...` passes

## Context

- Design node `2v74z` (tab bar): tabs are horizontal, gap 0 between tabs
- Live: `#tab-nav` at index.html line 19, contains 4 `<a class="tab">` children
- CSS: `#tab-nav` has no layout rule — only `--wails-draggable` at ds.css line 793
- This is a regression introduced by BUG-106 (tab height 48px) — previously tabs were smaller and the stacking was less visually broken
- Fix: add `#tab-nav { display: flex; align-items: center; gap: 0; }` to ds.css

## Out of Scope

- Tab styling (font-size, padding, border-radius — already covered by BUG-104/106/107)
- Header left/right grouping (BUG-066)

## Code Pointers

- `internal/web/ui/ds.css` — add `#tab-nav` layout rule
- `internal/web/ui/index.html` — line 19, `<nav id="tab-nav">`

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
