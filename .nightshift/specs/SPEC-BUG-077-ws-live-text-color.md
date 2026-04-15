---
id: SPEC-BUG-077
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

# WS live indicator text color is text-secondary instead of green (success-fg)

## Problem

The `.ws-indicator` base class sets `color: var(--text-secondary)` (#b1bac4) for the text. When the indicator is in "Live" state (`.ws-live`), only the `::before` pseudo-element dot turns green — the "Live" text remains gray. The UX-002 design specifies green (`#3fb950` / success-fg) for both the dot AND the "Live" text.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Indicator/Live node (`DNFbX`), text node `syr1q` (label "Live") has `fill: #3fb950` (success-fg), matching the dot color.

## Reproduction

1. Open Shipyard with an active connection (Live state)
2. Look at the header ws-indicator
3. **Actual:** Green dot + gray "Live" text (#b1bac4)
4. **Expected:** Green dot + green "Live" text (#3fb950)

## Root Cause

`.ws-indicator` sets `color: var(--text-secondary)` as the base text color. `.ws-live` only overrides the `::before` dot via `background: var(--success-fg)` but provides no `color:` override for the text itself, so the "Live" label inherits the gray secondary color instead of matching the green dot.

## Requirements

- [ ] R1: `.ws-live` sets `color: var(--success-fg)` for the text (in addition to the dot)

## Acceptance Criteria

- [ ] AC 1: When connected (`.ws-live`), the "Live" text is `var(--success-fg)` (#3fb950)
- [ ] AC 2: When disconnected (`.ws-disconnected`), text color should match the dot (danger-fg or secondary)
- [ ] AC 3: The `::before` dot colors are unchanged
- [ ] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `DNFbX` (Indicator/Live) — dot `fill: #3fb950`, text `fill: #3fb950`, `fontSize: 12, fontWeight: 500`
- Bug location: `internal/web/ui/ds.css`, `.ws-indicator` (line ~713) and `.ws-live` (no text color override)

## Out of Scope

- WS indicator font-size or font-weight (SPEC-BUG-078)
- WS indicator dot size (already 8px, matching design)

## Code Pointers

- `internal/web/ui/ds.css` — `.ws-indicator` (line ~713), `.ws-live::before` (line ~729)

## Gap Protocol

- Research-acceptable gaps: what color ws-disconnected and ws-reconnecting text should be
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
