---
id: SPEC-BUG-039
template_version: 2
priority: 2
layer: 2
type: bugfix
status: ready
after: [UX-002]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Response header latency pill is on the left — design places it on the right with Copy

## Problem

In the response header (`Q9lu4 / respHeader`) the design defines two groups separated
by `justifyContent: space_between`:

- **Left group** `uo10d` (respTitle): "Response" label + status badge
- **Right group** `Eurmv` (respMeta): latency pill + Copy button (gap 12px)

The implementation places the latency pill on the **left**, between the status badge
and the flex spacer, rather than on the right alongside the Copy button:

```
ACTUAL:   [Response] [badge] [latency]  ─────spacer─────  [Copy] [Retry]
EXPECTED: [Response] [badge]  ──────────spacer──────────  [latency] [Copy]
```

This misplaces latency visually, breaks the left/right information hierarchy of the
design, and puts latency far away from the Copy action it accompanies.

**Violated spec:** UX-002 (dashboard design)
**Violated criteria:** respMeta (Eurmv) — latency pill must be the first child in the
right-hand meta group, not in the left-hand title group.

## Reproduction

1. Open the Tools tab
2. Select any tool, execute it, wait for response
3. Observe the response header row

4. **Actual:** latency pill appears immediately after the status badge on the left side
5. **Expected:** latency pill appears to the left of the Copy button on the right side

## Root Cause

(To be filled by agent.)

The header row is implemented as a flat flex row with a spacer rather than two
logical groups. The latency `<span>` was placed before the spacer instead of after:

```html
<span>Response</span>
<span id="tool-response-status" class="badge">…</span>
<span id="tool-response-latency" class="pill">…</span>   ← WRONG SIDE
<div style="flex:1;"></div>
<button id="tool-response-copy">Copy</button>
```

## Requirements

- [ ] R1: The latency pill is rendered to the right of the flex spacer, immediately
  before the Copy button.
- [ ] R2: The gap between the latency pill and the Copy button is 12px (matching
  the design's `Eurmv` gap of 12px).
- [ ] R3: The "Response" label and status badge remain on the left side, with a
  gap of 8px between them (matching the design's `uo10d` gap of 8px).

## Acceptance Criteria

- [ ] AC 1: After execution the latency pill appears to the right of the spacer,
  directly before the Copy button.
- [ ] AC 2: The left side of the header shows only the "Response" label and status
  badge.
- [ ] AC 3: The gap between latency pill and Copy button is 12px.
- [ ] AC 4: `ui_layout_test.go` contains a test verifying the DOM order: spacer →
  latency pill → Copy button.
- [ ] AC 5: `go test ./...` passes.
- [ ] AC 6: `go vet ./...` passes.
- [ ] AC 7: `go build ./...` passes.

## Context

- Design frame: `Q9lu4` (respHeader)
  - Left child `uo10d` (respTitle): gap 8, children: label `RXL60` + badge `wGu0s`
  - Right child `Eurmv` (respMeta): gap 12, children: latency `HtHfA` + copy `zWObG`
  - justifyContent: space_between
- Implementation: `internal/web/ui/index.html` lines ~210–218
- JS vars: `toolResponseLatency` (line ~1528), `toolResponseCopy` (line ~1530)
- Test file: `internal/web/ui_layout_test.go`

## Notes for the Agent

- The simplest fix: move the `<span id="tool-response-latency">` element to after
  the spacer `<div style="flex:1;">`, before the Copy button.
- Adjust `gap` on the header row or wrap latency + copy in a sub-container with
  `gap:12px` so the two right-hand elements stay 12px apart regardless of overall
  row gap.
- The JS code that sets `toolResponseLatency` content does not depend on DOM
  position — no JS changes required.

## Out of Scope

- Changing how latency pill colours are computed (fast/moderate/slow)
- Restructuring the full response section layout
- Removing the Retry button (separate spec)

## Gap Protocol

- Research-acceptable gaps: exact container/gap approach (wrapper vs gap override)
- Stop-immediately gaps: any change to latency JS wiring or colour logic
- Max research subagents before stopping: 0
