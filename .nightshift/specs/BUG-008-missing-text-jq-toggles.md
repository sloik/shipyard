---
id: BUG-008
priority: 2
type: bug
status: open
after: [SPEC-006]
created: 2026-04-05
---

# BUG-008: Text/JQ Toggle Missing from Per-Panel Filter Bars

## Screenshot

- Actual: `docs/phase_1_feedback/005-missing-text-jq.png`
- Design: State — Error Row Expanded in `UX-002-dashboard-design.pen` (node `c95tP`)

## Problem

The design defines the Text/JQ mode toggle (`Toggle/TextJQ` component, node `ZpCI9`) in **three** locations within the timeline detail panel. The implementation only shows it in **one** (the combined filter bar). The two per-panel filter bars render a plain input without the toggle.

## Design Reference (.pen nodes) — Three Toggle Locations

### 1. Combined filter bar (top) — IMPLEMENTED ✓
- Node `qiHrm` (json-filter-bar): search input (`kkMtq`, 280px) + Text/JQ toggle (`EY7mp`) + match count
- Toggle uses `Toggle/TextJQ` component: `$radius-m`, `$bg-inset` background, `$border-default` stroke
- Text button: `$accent-emphasis` fill, `$text-on-emphasis`, fontSize 10, fontWeight 600
- JQ button: no fill, `$text-secondary`, `JetBrains Mono`, fontSize 10, fontWeight 500

### 2. Request panel filter — MISSING ✗
- Node `mrXZh` (req-filter): search icon + "Filter request..." + spacer + Text/JQ toggle (`T8OjT`)
- Smaller variant: `$radius-s` (not `$radius-m`), padding `[2,6]` (not `[4,8]`)
- Background: `$bg-surface`, padding `[4,8]`, border-bottom only (`$border-muted`)
- Font size 10px for both labels

### 3. Response panel filter — MISSING ✗
- Node `z3cj5` (res-filter): search icon + "Filter response..." + spacer + Text/JQ toggle (`JkfYj`)
- Same smaller variant as request filter: `$radius-s`, padding `[2,6]`
- Background: `$bg-surface`, padding `[4,8]`, border-bottom only (`$border-muted`)

## Current Implementation

The `renderDetailPanel()` function generates per-panel filters as:
```html
<div class="json-filter panel-filter">
  <input type="text" placeholder="Filter request...">
</div>
```

Missing: the Text/JQ toggle inside each panel-filter div.

## Acceptance Criteria

- [ ] AC-1: Request panel filter bar includes Text/JQ toggle after the input (smaller variant: `$radius-s`, padding `[2,6]`)
- [ ] AC-2: Response panel filter bar includes Text/JQ toggle after the input (same smaller variant)
- [ ] AC-3: Per-panel toggles operate independently from the combined filter toggle
- [ ] AC-4: Toggle styling matches design: active=`$accent-emphasis`+`$text-on-emphasis`, inactive=transparent+`$text-secondary`
- [ ] AC-5: Combined filter bar toggle remains unchanged (already implemented)

## Target Files

- `internal/web/ui/index.html` — `renderDetailPanel()` function
- `internal/web/ui/ds.css` — `.mode-toggle` (verify small variant styles exist)
