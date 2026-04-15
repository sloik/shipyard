---
id: SPEC-BUG-090
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

# Server column text is 12px Inter, design has two variants (12px Inter in timeline, 13px in perf)

## Problem

The Timeline server column renders at 12px Inter which matches the timeline design (`r1ServerLbl: fontSize 12, Inter`). However, the expanded row detail and the Perf tab "Latency by Tool" table show server names in `JetBrains Mono` 12px with `fill: #b1bac4` (text-secondary). The live server column uses `text-primary` (#e6edf3) everywhere.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Perf table server column `oF6gs` has `fontFamily: "JetBrains Mono"`, `fill: #b1bac4`, `fontSize: 12`.

## Reproduction

1. If Perf tab exists, check server column font and color
2. **Actual:** Inter 12px, color text-primary
3. **Expected:** JetBrains Mono 12px, color text-secondary (#b1bac4) in perf table

## Root Cause

`renderPerfTable` in `index.html` built server column spans with inline styles that set `font-size` and `color` but omitted `font-family`, so they inherited Inter from the body instead of JetBrains Mono as required by the perf table design spec (`oF6gs`).

## Requirements

- [x] R1: Timeline server column stays at Inter 12px text-primary (matches design)
- [x] R2: If Perf/latency table exists, server column uses JetBrains Mono, text-secondary

## Acceptance Criteria

- [x] AC 1: Timeline server column: Inter 12px text-primary (already correct — inherits font-sans from body via .table-row > *)
- [x] AC 2: Perf table server column: JetBrains Mono 12px text-secondary (added font-family:var(--font-mono) to inline style in renderPerfTable)
- [x] AC 3: `go build ./...` passes

## Context

- Design reference: Timeline `r1ServerLbl` — Inter, 12px, #e6edf3. Perf table server — JetBrains Mono, 12px, #b1bac4.
- Live: all server columns use Inter 12px text-primary

## Out of Scope

- Server column width
- Server card styling (separate spec series)

## Code Pointers

- `internal/web/ui/ds.css` — server column styling
- `internal/web/ui/index.html` — perf table rendering (if exists)

## Gap Protocol

- Research-acceptable gaps: whether perf tab is implemented yet
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
