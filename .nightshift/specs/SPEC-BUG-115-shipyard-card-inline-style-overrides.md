---
id: SPEC-BUG-115
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

# Built-in Shipyard server card has inline styles that override design system

## Problem

The built-in "Shipyard" server card has an inline `style` attribute that overrides the `.server-card` CSS class, causing it to look different from other server cards:

- `border-radius: var(--radius-m)` → 6px (should be `--radius-l` = 8px like other cards)
- `background: var(--bg-raised)` → #1c2128 (should be `--bg-surface` = #161b22)
- `border: 1px solid var(--border-muted)` → #21262d (should be `--border-default` = #30363d)

The lmstudio card uses the correct `.server-card` styles. Both should look identical per the design.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** All server cards should use Card/Server component styling (node `YYMTJ`): cornerRadius 8, fillColor #161b22, border #30363d.

## Reproduction

1. Navigate to Servers tab
2. Compare Shipyard card to lmstudio card
3. **Actual:** Shipyard card has lighter background, smaller radius, dimmer border
4. **Expected:** Both cards have identical styling

## Root Cause

The Shipyard built-in card was rendered with an inline `style="border:1px solid var(--border-muted); border-radius:var(--radius-m); overflow:hidden; background:var(--bg-raised);"` that overrode the `.server-card` CSS. The inline style used wrong design tokens (`--border-muted`, `--radius-m`, `--bg-raised`) instead of the correct ones (`--border-default`, `--radius-l`, `--bg-surface`). Fixed by removing the inline style from `index.html` and adding `overflow: hidden` to `.server-card` in `ds.css` (since it was needed to clip card contents).

## Requirements

- [x] R1: Remove inline style overrides from the Shipyard built-in server card
- [x] R2: Shipyard card uses the same `.server-card` class styles as all other cards

## Acceptance Criteria

- [x] AC 1: Shipyard card has border-radius 8px (`--radius-l`)
- [x] AC 2: Shipyard card has background `--bg-surface` (#161b22)
- [x] AC 3: Shipyard card has border color `--border-default` (#30363d)
- [x] AC 4: Shipyard card is visually identical to lmstudio card in shape/color
- [x] AC 5: `go build ./...` passes

## Context

- Design Card/Server (`YYMTJ`): cornerRadius [8,8,8,8], fillColor #161b22, border via $border-default
- Live Shipyard card: inline style sets radius-m (6px), bg-raised (#1c2128), border-muted (#21262d)
- Live lmstudio card: no inline style, uses .server-card CSS correctly (8px, #161b22, #30363d)
- The `overflow:hidden` from the inline style may be needed — if so, add it to `.server-card` CSS instead

## Out of Scope

- Server card content/layout
- Server count accuracy (BUG-111)

## Code Pointers

- `internal/web/ui/index.html` — JS that renders the Shipyard built-in card (search for "Built-in" or inline style)

## Gap Protocol

- Research-acceptable gaps: whether overflow:hidden is needed for the card
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
