---
id: SPEC-BUG-101
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

# Settings cog SVG has corrupted arc causing visual artifact

## Problem

The settings gear icon (`#settings-btn`) renders with a visible artifact. The SVG path contains a corrupted arc command: `a2 2 0 1 1 2 0` where the `large-arc-flag` is `1` but should be `0`. This causes the arc to take the long way around, creating an unexpected loop/bulge in the gear outline.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Settings icon should render as a clean Lucide `settings` gear icon.

## Reproduction

1. Open any page, look at the settings gear icon in the top-right header area
2. **Actual:** Gear icon has a visible artifact/extra loop on one side
3. **Expected:** Clean gear/cog icon matching Lucide `settings`

## Root Cause

In the SVG path at `index.html` line 32, the arc command `a2 2 0 1 1 2 0` has `large-arc-flag=1` instead of `0`. The correct command should be `a2 2 0 0 1 2 0`.

Specifically, the path segment:
```
...l.15-.08a2 2 0 1 1 2 0l.43.25...
```
Should be:
```
...l.15-.08a2 2 0 0 1 2 0l.43.25...
```

## Requirements

- [ ] R1: Fix the SVG path `large-arc-flag` from `1` to `0`

## Acceptance Criteria

- [ ] AC 1: Settings gear icon renders cleanly without artifacts
- [ ] AC 2: Icon matches the Lucide `settings` icon
- [ ] AC 3: `go build ./...` passes

## Context

- SVG arc command format: `a rx ry x-rotation large-arc-flag sweep-flag dx dy`
- The bug: `a2 2 0 1 1 2 0` → large-arc=1 draws the long arc
- The fix: `a2 2 0 0 1 2 0` → large-arc=0 draws the short (correct) arc
- Location: `#settings-btn > svg > path` at index.html line 32

## Out of Scope

- Settings icon size or color
- Settings panel functionality

## Code Pointers

- `internal/web/ui/index.html` — line 32, the `<path d="..."/>` inside `#settings-btn`

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
