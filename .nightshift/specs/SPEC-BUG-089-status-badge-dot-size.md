---
id: SPEC-BUG-089
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

# Status badge dot may not match design size (6px) and gap (4px)

## Problem

Status badges have a `.badge-dot` span element. The UX-002 design specifies a 6px colored dot with `gap: 4` between dot and label text. Need to verify the dot renders at 6px diameter with correct gap.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Badge/Success (ddcEr) — dot `width: 6, height: 6`, `gap: 4`.

## Reproduction

1. Open Timeline tab, inspect a status badge (e.g., "ok" or "pending")
2. Check the dot element size and the gap between dot and text
3. **Actual:** (needs verification — dot may be wrong size or gap)
4. **Expected:** 6px diameter dot, 4px gap to label text

## Root Cause

`.badge-dot` was already 6×6px with `border-radius: 50%` — correct per design. The only change needed was reducing `.badge` gap from `5px` to `4px` to match the UX-002 specification.

## Requirements

- [x] R1: `.badge-dot` renders as a 6px × 6px circle
- [x] R2: Badge `gap` is 4px between dot and text

## Acceptance Criteria

- [x] AC 1: `.badge-dot` is 6×6px with border-radius 50%
- [x] AC 2: Badge gap between dot and text is 4px
- [x] AC 3: Dot color matches the badge variant (green for success, red for error, etc.)
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — Badge/Success `gap: 4`, dot ellipse 6×6
- Badge/Info dot: 6×6, fill: #58a6ff
- Row instances (r1StatusBadge): dot 5×5, gap 3 — slightly smaller variant for compact rows

## Out of Scope

- Badge padding (SPEC-BUG-088)
- Badge font-size or font-weight

## Code Pointers

- `internal/web/ui/ds.css` — `.badge-dot`, `.badge` gap rule

## Gap Protocol

- Research-acceptable gaps: whether row badges use 5px dot vs 6px (design has both)
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
