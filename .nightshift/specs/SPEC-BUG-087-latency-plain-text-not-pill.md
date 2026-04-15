---
id: SPEC-BUG-087
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts:
  - date: 2026-04-15
    outcome: "Nightshift marked done but no changes made — latency cells still render as plain Inter 12px text with no background, no border-radius, no color coding. Root cause and ACs left blank."
created: 2026-04-15
---

# Latency column renders as plain text, design specifies color-coded pills

## Problem

The latency column on Timeline (and History) renders latency values as plain text in Inter font at 12px with `color: var(--text-primary)`. The UX-002 design specifies latency as **color-coded pills** with JetBrains Mono, colored text, and tinted backgrounds — green for fast, yellow for moderate, red for slow.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Latency cells use `Pill/Latency/*` components — `cornerRadius: 4`, `padding: [2, 5]`, colored `fill` bg, JetBrains Mono, fontSize 10, fontWeight 500.

## Reproduction

1. Open Timeline tab with traffic data showing latency values (e.g., "6ms", "245ms")
2. Inspect a latency cell
3. **Actual:** Plain text "6ms" in Inter 12px, color #e6edf3, no background
4. **Expected:** Pill with rounded corners (4px), tinted background (e.g., green-tinted for fast), JetBrains Mono 10px, colored text (#3fb950 for fast)

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Latency values render inside a pill element with `border-radius: 4px`
- [ ] R2: Pill text uses `font-family: var(--font-mono)` (JetBrains Mono)
- [ ] R3: Pill font-size is `var(--font-size-xs)` (10px), font-weight 500
- [ ] R4: Fast latency (<100ms): text `var(--success-fg)` (#3fb950), bg `#2ea04326`
- [ ] R5: Moderate latency (100–500ms): text `var(--warning-fg)` (#d29922), bg `#d2992226`
- [ ] R6: Slow latency (>500ms): text `var(--danger-fg)` (#f85149), bg `#f8514926`
- [ ] R7: Pending/no-value ("—"): text `var(--text-muted)`, bg `var(--bg-raised)`, 1px border

## Acceptance Criteria

- [ ] AC 1: Latency cells render as pills with border-radius 4px
- [ ] AC 2: Pill uses JetBrains Mono 10px font-weight 500
- [ ] AC 3: Color coding is applied based on latency threshold
- [ ] AC 4: Pending entries show muted pill with border
- [ ] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file — `Pill/Latency/Fast` (4QxOr), `Pill/Latency/Moderate` (RMNt0), `Pill/Latency/Slow` (ZwuWl), `Pill/Latency/Timeout` (jOLjW)
- Design thresholds inferred from sample values: 12ms=green, 245ms=yellow, 1240ms=red
- Live computed: Inter 12px, color text-primary, no background, right-aligned text

## Out of Scope

- Latency threshold exact cutoff values (use reasonable defaults: <100ms green, <500ms yellow, >=500ms red)
- History tab latency (same pattern, will inherit the fix)

## Code Pointers

- `internal/web/ui/ds.css` — latency cell styling (grep for `latency`)
- `internal/web/ui/index.html` — JS that renders latency values in table rows

## Gap Protocol

- Research-acceptable gaps: exact latency threshold breakpoints
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
