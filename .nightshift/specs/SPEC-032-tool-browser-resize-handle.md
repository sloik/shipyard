---
id: SPEC-032
template_version: 2
priority: 1
layer: 2
type: feature
status: done
after: [SPEC-BUG-031]
created: 2026-04-13
---

# Tool Browser: resize handle between form and response sections

## Problem

The Tool Browser detail pane has a fixed form/response split. Users with long
schemas need more form space; users reviewing complex responses need more response
space. There is no way to adjust the split.

The `.resize-handle` CSS class already exists in `ds.css` with correct styling
(6px bar, `row-resize` cursor, grip indicator). It is also used decoratively in
the timeline detail panel but has no drag JS anywhere. This spec adds the drag
logic for the Tool Browser.

## Goal

Add a draggable resize handle between `#tool-detail-scroll` (form) and
`#tool-response-section` (response) in the Tool Browser. Dragging adjusts the
response section height. The split persists across page reloads via localStorage.

## Architecture

```
#tool-detail (flex column, height:100%)
  #tool-detail-scroll     ← flex:1 1 0 — takes remaining space above handle
  .resize-handle          ← new: drag target, 6px, row-resize cursor
  #tool-response-section  ← flex:0 0 <px> — height set by drag, default 300px
```

Drag interaction:
1. `mousedown` on `.resize-handle` inside `#tool-detail` → start drag
2. `mousemove` on `document` → compute delta from drag start Y
3. New response height = (stored height at drag start) - delta
4. Clamp: `min 150px`, `max (container height - 150px)`
5. Apply: `toolResponseSection.style.height = newPx + 'px'`
   (override the `flex:0 0 300px` basis via explicit height)
6. `mouseup` on `document` → stop drag, persist height to localStorage
7. Key: `shipyard_tool_response_height`

On page load: read localStorage key and apply if present.

On window resize: re-clamp stored height to new container bounds.

## Requirements

- [x] R1: A `.resize-handle` element appears between the form section and the
  response section in the Tool Browser.
- [x] R2: Dragging the handle vertically adjusts the height of the response
  section in real time.
- [x] R3: The response section height is clamped to `[150px, container - 150px]`
  so neither section disappears entirely.
- [x] R4: The split persists across page reloads via `localStorage`.
- [x] R5: On window resize, the stored height is re-clamped to new bounds.
- [x] R6: The handle uses the existing `.resize-handle` class from `ds.css` —
  no new CSS needed.

## Acceptance Criteria

- [x] AC 1: A `.resize-handle` element exists between `#tool-detail-scroll` and
  `#tool-response-section` in `index.html`.
- [x] AC 2: Dragging the handle down shrinks the response section; dragging up
  grows it.
- [x] AC 3: Response section height is never less than 150px or more than
  (container height − 150px).
- [x] AC 4: After dragging and reloading, the response section opens at the
  saved height.
- [x] AC 5: The localStorage key is `shipyard_tool_response_height`.
- [x] AC 6: On `window.addEventListener('resize', ...)`, the stored height is
  re-clamped.
- [x] AC 7: The handle is visible and has `cursor:row-resize` (from
  `.resize-handle` in ds.css — no new CSS required).
- [x] AC 8: No inline style is added to the handle element itself — styling
  comes entirely from the `.resize-handle` class.
- [x] AC 9: Layout tests assert the presence and position of the handle element
  (between scroll section and response section in DOM order).
- [x] AC 10: `.shipyard-dev/verify-spec-032.sh` exits 0.
- [x] AC 11: `go test ./...` passes.
- [x] AC 12: `go vet ./...` passes.
- [x] AC 13: `go build ./...` passes.

## Verification Script

Create `.shipyard-dev/verify-spec-032.sh` that:
1. Asserts a `class="resize-handle"` element exists between
   `id="tool-detail-scroll"` and `id="tool-response-section"` in `index.html`
   (check DOM order by string index)
2. Asserts the JS contains `shipyard_tool_response_height`
3. Asserts the JS contains `mousedown` handler wired to the handle
4. Asserts the JS contains `mousemove` and `mouseup` document listeners
5. Asserts no inline style on the handle element (no `style=` attribute)
6. Runs `go test ./...`
7. Prints PASS/FAIL per check with summary

## Context

### Target files

- `internal/web/ui/index.html`:
  - HTML: add `<div class="resize-handle"></div>` between `#tool-detail-scroll`
    closing `</div>` (line ~203) and `#tool-response-section` opening tag (line 206)
  - JS: add drag logic in the Tool Browser section (~line 1450+)
  - JS: on tool detail show, apply saved height from localStorage
- `internal/web/ui_layout_test.go` — add test asserting handle DOM position
- `.shipyard-dev/verify-spec-032.sh` — new verification script

### JS pattern (vanilla — no async/await, use var)

```javascript
// Init: apply saved height
var savedToolResponseHeight = localStorage.getItem('shipyard_tool_response_height');
if (savedToolResponseHeight) {
  toolResponseSection.style.height = savedToolResponseHeight + 'px';
}

// Drag logic
var toolResizeHandle = toolDetail.querySelector('.resize-handle');
var toolResizeDragging = false;
var toolResizeStartY = 0;
var toolResizeStartHeight = 0;

toolResizeHandle.addEventListener('mousedown', function(e) {
  e.preventDefault();
  toolResizeDragging = true;
  toolResizeStartY = e.clientY;
  toolResizeStartHeight = toolResponseSection.offsetHeight;
});

document.addEventListener('mousemove', function(e) {
  if (!toolResizeDragging) return;
  var delta = toolResizeStartY - e.clientY;
  var containerH = toolDetail.offsetHeight;
  var newH = Math.min(Math.max(toolResizeStartHeight + delta, 150), containerH - 150);
  toolResponseSection.style.height = newH + 'px';
});

document.addEventListener('mouseup', function() {
  if (!toolResizeDragging) return;
  toolResizeDragging = false;
  localStorage.setItem('shipyard_tool_response_height', toolResponseSection.offsetHeight);
});

window.addEventListener('resize', function() {
  var saved = parseInt(localStorage.getItem('shipyard_tool_response_height'), 10);
  if (!saved) return;
  var containerH = toolDetail.offsetHeight;
  var clamped = Math.min(Math.max(saved, 150), containerH - 150);
  toolResponseSection.style.height = clamped + 'px';
  localStorage.setItem('shipyard_tool_response_height', clamped);
});
```

### Important notes

- `toolResizeHandle` must be queried AFTER `#tool-detail` is in the DOM — query
  it at the top of the Tool Browser JS init block where other element refs live
  (~line 1450)
- The drag delta formula: dragging DOWN (increasing Y) = user wants more form
  space = response shrinks → `delta = startY - currentY`
- Dragging UP (decreasing Y) = response grows → same formula, delta is negative
- Do NOT call `e.preventDefault()` on mousemove — only on mousedown (prevents
  text selection during drag)
- `toolResponseSection.style.height` overrides the CSS `flex:0 0 300px` basis
  because explicit `height` takes priority over `flex-basis` when both are set

## Out of Scope

- Resize handle in Timeline detail panel (separate spec if desired)
- Touch/pointer events (mouse only for v1)
- Per-tool saved heights (one global height for all tools)
- Animated transitions during drag

## Gap Protocol

- Research-acceptable gaps: none — implementation is fully specified above
- Stop-immediately gaps: response section disappears after resize; drag doesn't
  work; saved height not restored on reload
- Max research subagents before stopping: 0
