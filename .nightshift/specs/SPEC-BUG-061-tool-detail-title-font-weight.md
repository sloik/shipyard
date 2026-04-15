---
id: SPEC-BUG-061
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

# Tool detail title uses font-weight 700 instead of 600

## Problem

The tool detail title (tool name) uses `font-weight: 700` (bold). The UX-002 design specifies `fontWeight: 600` (semibold) for the tool title text.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Tool title text node `6WO2w` (toolTitle) in `nXdVa` (toolTitleRow) — `fontWeight: 600`, not 700.

## Reproduction

1. Open the Tools tab and select any tool
2. Inspect the tool name text (e.g., "read_file")
3. **Actual:** font-weight is 700
4. **Expected:** font-weight should be 600

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: Tool detail title uses `font-weight: 600`

## Acceptance Criteria

- [x] AC 1: `#tool-detail-name` has `font-weight: 600` (not 700)
- [x] AC 2: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `6WO2w` (toolTitle) — `fontFamily: "JetBrains Mono", fontSize: 20, fontWeight: 600`
- Bug location: `internal/web/ui/index.html`, inline style on `#tool-detail-name` (line ~184)

## Out of Scope

- Tool title font-family or font-size changes
- Tool header icon changes (SPEC-BUG-060)

## Code Pointers

- `internal/web/ui/index.html` — `<span id="tool-detail-name" style="font-family:var(--font-mono); font-size:var(--font-size-2xl); font-weight:700; ...">`(line ~184)

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
