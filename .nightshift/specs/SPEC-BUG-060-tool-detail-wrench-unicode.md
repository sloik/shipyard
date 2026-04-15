---
id: SPEC-BUG-060
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Tool detail header uses Unicode wrench emoji instead of Lucide wrench SVG

## Problem

The tool detail header shows a Unicode wrench emoji (`&#128295;` / 🔧) at 18px. The UX-002 design specifies a Lucide `wrench` icon at 18px with fill `#58a6ff` (accent-fg color), not a Unicode character.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tool detail header (`nXdVa` / toolTitleRow) contains icon_font node `YGSwQ` (toolIcon) — Lucide `wrench`, 18×18px, fill `#58a6ff` (--accent-fg).

## Reproduction

1. Open the Tools tab and select any tool
2. Look at the tool detail header (icon + tool name + server badge)
3. **Actual:** Unicode wrench emoji (🔧) at 18px, default text color
4. **Expected:** Lucide `wrench` SVG icon, 18px, color `var(--accent-fg)` (#58a6ff)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Tool detail header icon is a Lucide `wrench` SVG, not Unicode emoji
- [ ] R2: Icon is 18px, colored `var(--accent-fg)`

## Acceptance Criteria

- [ ] AC 1: Tool detail header contains a Lucide `wrench` SVG (18×18px, `stroke="var(--accent-fg)"`)
- [ ] AC 2: No Unicode `&#128295;` character in the tool detail header
- [ ] AC 3: Icon color is `var(--accent-fg)` (#58a6ff)
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `YGSwQ` (toolIcon) in `nXdVa` (toolTitleRow) — `iconFontFamily: "lucide", iconFontName: "wrench", width: 18, height: 18, fill: #58a6ff`
- Bug location: `internal/web/ui/index.html`, line ~183

## Out of Scope

- Tool detail title font changes
- Tool detail server badge styling
- Tool detail description styling

## Code Pointers

- `internal/web/ui/index.html` — `<span style="font-size:18px;">&#128295;</span>` (line ~183)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
