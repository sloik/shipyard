---
id: SPEC-BUG-033
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-032]
violates: []
prior_attempts:
  - "Attempt 1 (2026-04-13): Fixed offsetHeight→getBoundingClientRect and IIFE clamping bug. Verified 5/5 with script. User confirmed still broken — wrong diagnosis."
created: 2026-04-13
---

# Tool Browser: resize handle drag does nothing

## Problem

After SPEC-032, the resize handle element exists and passes all verification checks, but
dragging the handle has no visible effect. The response section stays at its fixed height.

## Prior Attempt (failed)

**Attempt 1** diagnosed two bugs:
1. IIFE calling `toolDetail.offsetHeight` while element is hidden → produced `-150px`
2. `mousemove` using `toolDetail.offsetHeight` → might return 0 on `height:100%` flex item

Fixes applied: IIFE now applies saved value directly; both handlers use
`getBoundingClientRect().height` for container. Verify script 5/5 green.

**Still broken.** Attempt 1 fixed real bugs but did NOT fix the root cause of the drag
having no effect. Read section below carefully before implementing.

## Root Cause: `style.height` does not override `flex-basis` in WebKit

`#tool-response-section` has `flex:0 0 300px` in its inline style:
```html
<div id="tool-response-section" style="display:flex; flex:0 0 300px; ...">
```

`flex:0 0 300px` is shorthand for `flex-grow:0; flex-shrink:0; flex-basis:300px`.

The SPEC-032 drag logic sets height via `toolResponseSection.style.height = newH + 'px'`.

**The problem:** In the CSS Flexible Box spec, when `flex-basis` is an explicit length (not
`auto`), it determines the main-axis size directly — it takes precedence over the `height`
property. Setting `style.height = '350px'` does NOT change `flex-basis`, so the rendered
size remains 300px. The drag fires, the JS runs, but the visual size never changes.

This is spec-compliant behaviour. Chrome/Blink is lenient and may honour `style.height`
anyway, but WebKit (WKWebView in Wails) follows the spec: `flex-basis` wins.

**Key evidence:** `offsetHeight` in the mouseup handler saves `toolResponseSection.offsetHeight`
which is 300px on every drag (flex-basis overrides the ignored `style.height`) → the same
300px value gets restored on next load → perpetual no-change loop.

## Fix

Replace every `toolResponseSection.style.height = X + 'px'` with
`toolResponseSection.style.flexBasis = X + 'px'`. Inline `style.flexBasis` directly
overrides the CSS rule's `flex-basis`, which IS the property controlling the rendered height.

Also fix height reading in the `mousedown` handler: `toolResponseSection.offsetHeight`
reliably returns the current rendered height, so it can stay as-is — but the value it
returns (currently always 300 because height changes were silently ignored) will now
correctly reflect the `flexBasis`-set size after first drag.

### Current state of the file (post Attempt 1, before this fix)

Lines 1475-1511:
```javascript
// Apply saved response section height on init
(function() {
  var saved = parseInt(localStorage.getItem('shipyard_tool_response_height'), 10);
  if (saved && toolResponseSection) {
    toolResponseSection.style.height = saved + 'px';          // ← BUG: height ignored by flex
  }
})();

toolResizeHandle.addEventListener('mousedown', function(e) {
  e.preventDefault();
  toolResizeDragging = true;
  toolResizeStartY = e.clientY;
  toolResizeStartHeight = toolResponseSection.offsetHeight;   // ← reads flex-basis value, OK
});

document.addEventListener('mousemove', function(e) {
  if (!toolResizeDragging) return;
  var delta = toolResizeStartY - e.clientY;
  var containerH = toolDetail.getBoundingClientRect().height;
  var newH = Math.min(Math.max(toolResizeStartHeight + delta, 150), containerH - 150);
  toolResponseSection.style.height = newH + 'px';            // ← BUG: height ignored by flex
});

document.addEventListener('mouseup', function() {
  if (!toolResizeDragging) return;
  toolResizeDragging = false;
  localStorage.setItem('shipyard_tool_response_height', toolResponseSection.offsetHeight); // OK
});

window.addEventListener('resize', function() {
  var saved = parseInt(localStorage.getItem('shipyard_tool_response_height'), 10);
  if (!saved || !toolDetail) return;
  var containerH = toolDetail.getBoundingClientRect().height;
  var clamped = Math.min(Math.max(saved, 150), containerH - 150);
  toolResponseSection.style.height = clamped + 'px';         // ← BUG: height ignored by flex
  localStorage.setItem('shipyard_tool_response_height', clamped);
});
```

### Target state (what to change TO)

Only the three lines marked `← BUG` need to change. Replace `style.height` with
`style.flexBasis` on `toolResponseSection` in all three places:

```javascript
// IIFE: apply saved height
toolResponseSection.style.flexBasis = saved + 'px';

// mousemove: update during drag
toolResponseSection.style.flexBasis = newH + 'px';

// window resize: re-clamp
toolResponseSection.style.flexBasis = clamped + 'px';
```

No other changes. `toolResizeStartHeight = toolResponseSection.offsetHeight` stays as-is
(reads rendered height correctly). The `localStorage.setItem(...)` in mouseup stays as-is.

## Requirements

- [ ] R1: Dragging the handle up visibly grows the response section in real time.
- [ ] R2: Dragging the handle down visibly shrinks the response section in real time.
- [ ] R3: Height is clamped to [150px, containerH − 150px] during drag.
- [ ] R4: Saved height is restored on page load.
- [ ] R5: Window resize re-clamps the saved height.

## Acceptance Criteria

- [ ] AC 1: All three `toolResponseSection.style.height` assignments are replaced with
  `toolResponseSection.style.flexBasis`.
- [ ] AC 2: No NEW occurrences of `toolResponseSection.style.height` are introduced.
- [ ] AC 3: `style.flexBasis` appears at least 3 times in the Tool Browser JS block.
- [ ] AC 4: `getBoundingClientRect` still appears in `mousemove` and `window resize`.
- [ ] AC 5: `.shipyard-dev/verify-spec-033.sh` is updated to check for `flexBasis` and exits 0.
- [ ] AC 6: `go test ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.

## Verification Script

Update `.shipyard-dev/verify-spec-033.sh` to check:
1. `toolResponseSection.style.flexBasis` appears at least 3 times in `index.html`
2. No `toolResponseSection.style.height` assignments remain (grep for
   `toolResponseSection.style.height\s*=`)
3. `getBoundingClientRect` still appears at least 2 times
4. `toolResizeDragging` still present in mousemove handler
5. `window.addEventListener('resize'` still exists
6. `go test ./...`
7. Print PASS/FAIL + summary

## Context

### Target files

- `internal/web/ui/index.html` — three line changes (~lines 1479, 1495, 1509):
  - IIFE: `style.height` → `style.flexBasis`
  - mousemove: `style.height` → `style.flexBasis`
  - window resize: `style.height` → `style.flexBasis`
- `.shipyard-dev/verify-spec-033.sh` — update checks (flexBasis, no style.height)

### Why flexBasis works and height doesn't

CSS Flexbox Level 1, Section 9.2 ("Determine the flex base size and hypothetical main size"):
> If the item has a definite flex basis, it is the flex base size.

`flex:0 0 300px` gives `flex-basis:300px`. This is the definite value controlling size in
the main axis (height in a column flex container). `height` is a separate property that
flex-basis overrides. Setting `style.flexBasis = '350px'` directly changes the value that
the flex algorithm uses.

WebKit (WKWebView used by Wails on macOS) follows the spec. Chrome/Blink may be lenient.
This explains why the Attempt 1 fix appeared correct logically but didn't work in the app.

### Investigation guidance for the agent

Before making changes, verify the current code matches the "Current state" block above.
If the file has diverged, read lines 1475-1515 first and adjust accordingly.

Do NOT change `toolResizeStartHeight = toolResponseSection.offsetHeight` — this reads the
rendered height correctly after `flexBasis` is set (offsetHeight always reflects the
final rendered size).

Do NOT add `style.height = ''` to clear the old height — the previous height assignments
used `style.height` which WebKit ignored (flex-basis won), so there is no inline height
to clear. The inline style on the element in HTML only has `flex:0 0 300px` — no `height`.

## Out of Scope

- Changes to the handle's visual appearance
- Touch/pointer events
- Any other resize handle behaviour

## Gap Protocol

- Research-acceptable gaps: verifying that `toolResponseSection.offsetHeight` correctly
  reflects flexBasis-set size (it should — offsetHeight is always the rendered value)
- Stop-immediately gaps: drag still does nothing; `style.flexBasis` assignments not present
- Max research subagents before stopping: 1 (only for looking up WebKit flex spec behaviour)
