---
id: SPEC-BUG-041
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [UX-002]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Response section expands to fill whole view on long response and breaks the resize handle

## Problem

When a tool returns a long response, the response section visually expands to cover
the entire tool detail area, obscuring the input parameters and execute button above
it. After this happens the resize handle stops working — dragging it has no effect.

The expected layout is a stable split-pane: the parameters section (scrollable) on
top, the response section (fixed height, content scrollable inside) on the bottom,
separated by a draggable resize handle.

**Violated spec:** UX-002 (dashboard design)
**Violated criteria:** the response panel must stay at its set height; its content
must scroll; the resize handle must remain functional at all times.

## Reproduction

1. Open the Tools tab
2. Select a tool that returns a large response (e.g. a tool that dumps many records
   or a large JSON blob)
3. Click Execute and wait for the response

4. **Actual:** the response section grows to fill the full view; the parameters
   panel above it disappears or is obscured; dragging the resize handle does nothing
5. **Expected:** the response section stays at its current height; the JSON content
   scrolls inside the fixed-height panel; the resize handle continues to work

## Root Cause

(To be filled by agent — investigation starting points below.)

The response section `#tool-response-section` has `flex:0 0 300px`
(`flex-grow:0; flex-shrink:0`) in the flex column of `#tool-detail`. This should
prevent growth. However several weaknesses in the overflow containment chain allow
tall content to escape:

1. **No `overflow:hidden` on `#tool-response-section`** — without it, content that
   is taller than the section's flex-basis can visually overflow into the sibling
   `#tool-detail-scroll` above it.

2. **`#tool-response-body` (`.code-block`) has `overflow:hidden` in CSS**, but this
   only clips effectively when the element has a definite computed height. With
   `flex:1; min-height:0` in a column flex, some WebKit/Blink versions treat the
   height as indefinite for clipping purposes, letting content bleed through.

3. **`#tool-response-json` has `overflow:auto` for scroll**, but this also requires
   a definite constrained height. If the flex chain does not deliver one, the element
   grows to fit content instead of scrolling.

4. **Resize reads `offsetHeight` at mousedown** (`toolResizeStartHeight`). Once the
   section is in an expanded/broken layout state, `offsetHeight` returns a wrong
   baseline and all subsequent resize deltas are computed from that wrong value,
   making the handle appear frozen.

## Requirements

- [ ] R1: The response section height stays at its configured value (default 300px,
  or the value last set by drag-resize) regardless of response content length.
- [ ] R2: When response content is taller than the available space inside the
  response section, it scrolls — no overflow escape into sibling elements.
- [ ] R3: The drag resize handle remains functional after any response (short, long,
  or error).
- [ ] R4: Minimum response section height is 150px; maximum is `containerH - 150px`.
  These bounds already exist in the resize JS and must remain in effect.
- [ ] R5: The parameters section above the resize handle must never be obscured by
  response content.

## Acceptance Criteria

- [ ] AC 1: After receiving a response with 500+ JSON lines, the response section
  height does not change from its configured value.
- [ ] AC 2: A vertical scrollbar (or momentum scroll on macOS) appears inside the
  response body when content exceeds the section height.
- [ ] AC 3: The parameters section (input form, execute button) remains fully visible
  after a long response.
- [ ] AC 4: Dragging the resize handle up and down correctly changes the response
  section height after a long response has been received.
- [ ] AC 5: `offsetHeight` of `#tool-response-section` equals `flexBasis` (within
  1px rounding) at all times after a response arrives.
- [ ] AC 6: `ui_layout_test.go` contains tests covering:
  - response section height is stable after long content injection
  - scroll container presence when content exceeds panel height
- [ ] AC 7: `go test ./...` passes.
- [ ] AC 8: `go vet ./...` passes.
- [ ] AC 9: `go build ./...` passes.

## Context

- Layout HTML: `internal/web/ui/index.html` lines 163–234
  - `#tool-detail` (line 163): `height:100%; flex-direction:column; overflow:hidden`
    — shown via JS as `display:flex` (line 1890)
  - `#tool-detail-scroll` (line 164): `flex:1 1 0; min-height:0; overflow-y:auto`
    — the parameters pane
  - `#tool-resize-handle` (line 207): drag handle between panes
  - `#tool-response-section` (line 210): `flex:0 0 300px; flex-direction:column`
    — **no `overflow:hidden`**
  - `#tool-response-body` (line 226): `flex:1; min-height:0; display:flex;
    flex-direction:column` + `.code-block { overflow:hidden }` from CSS
  - `#tool-response-json` (line 227): `flex:1; min-height:0; max-height:none;
    overflow:auto`
- Resize JS: `internal/web/ui/index.html` lines 1543–1573
  - mousedown reads `toolResponseSection.offsetHeight` as start baseline
  - mousemove computes delta and clamps to [150, containerH-150]
  - saves to `localStorage.getItem('shipyard_tool_response_height')`
- CSS: `internal/web/ui/ds.css`
  - `.code-block { overflow:hidden }` — needs definite height to clip
- Test file: `internal/web/ui_layout_test.go`

## Notes for the Agent

- The first fix to try: add `overflow:hidden` to `#tool-response-section`'s
  inline style. This stops content escaping the section boundary.
- The second fix: verify the flex chain delivers a definite height to
  `#tool-response-body` and `#tool-response-json`. If `.code-block { overflow:hidden }`
  isn't clipping, the issue is that `flex:1; min-height:0` doesn't give a definite
  height in the current browser engine — replace with explicit `height:0` flex-basis
  or add `overflow:hidden` at each level.
- For the resize: after fixing overflow, verify that `offsetHeight` returns the
  correct value. If it still reads wrong, clamp `toolResizeStartHeight` with the
  same [150, containerH-150] bounds used in the mousemove handler.
- JS conventions for this project: `var`, `.then()`, no `async/await`, no `let`/`const`.
- Do NOT change the resize bounds logic (150 / containerH-150). Do NOT change the
  localStorage key or save/restore behaviour.
- Related resolved bugs for context: SPEC-BUG-029, SPEC-BUG-030, SPEC-BUG-031
  (prior scroll/flex issues in the same area).

## Out of Scope

- Changing the default response section height (300px)
- Virtual scrolling or pagination for large responses
- Response size limits or truncation
- Horizontal scroll behaviour (separate)

## Gap Protocol

- Research-acceptable gaps: exact CSS property combination needed to make the
  flex height chain definite in WebKit
- Stop-immediately gaps: any change to the resize JS delta logic or localStorage
  key; any change to `highlightJSON()` output format
- Max research subagents before stopping: 1
