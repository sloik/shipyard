---
id: SPEC-BUG-033
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-032]
violates: []
prior_attempts: []
created: 2026-04-13
---

# Tool Browser: resize handle drag does nothing

## Problem

After SPEC-032, the resize handle element exists and passes all verification checks, but
dragging the handle has no visible effect. The response section stays at its fixed height.

## Root Cause

Two bugs in the SPEC-032 JS implementation:

### Bug 1: IIFE corrupts height on page load

Lines 1476-1483 of `index.html`: the IIFE that restores saved height runs at page init when
`#tool-detail` is `display:none`. This means `toolDetail.offsetHeight = 0`. The clamp
math produces `-150`, setting `toolResponseSection.style.height = '-150px'` — an invalid
CSS value. Depending on WebKit's behaviour, this either:
- Sets height to 0 (overriding the CSS `flex:0 0 300px`), making the section invisible
- Silently fails, leaving a corrupt style value that interferes with later offset reads

### Bug 2: `offsetHeight` returns 0 on a `height:100%` flex item

Lines 1495 and 1509: `var containerH = toolDetail.offsetHeight`

`#tool-detail` uses `height:100%` on an element that is a flex item of `#tools-main`
(`flex:1; flex-direction:column`). In CSS, `height:100%` only resolves to a pixel value
when the parent has a *definite* height. A flex container whose height is determined by
its own flex layout (via `flex:1`) does NOT establish a "definite" height for this
purpose in WebKit/WKWebView.

Result: `toolDetail.offsetHeight = 0` during drag. Then:
```
containerH - 150 = -150
Math.min(newH, -150) = -150      // min wins regardless of newH
Math.max(-150, 150) = 150        // clamp back to minimum
```
Every drag snaps to exactly 150px, which appears as "nothing happening".

`getBoundingClientRect().height` always returns the actual rendered pixel height,
regardless of how the height was established (flex, percentage, etc.). It is the
correct API here.

## Fix

**In `mousemove` handler (line ~1495):**
Replace `toolDetail.offsetHeight` with `toolDetail.getBoundingClientRect().height`

**In `window resize` handler (line ~1509):**
Replace `toolDetail.offsetHeight` with `toolDetail.getBoundingClientRect().height`

**In IIFE (lines ~1479-1480):**
Do not clamp the restored height against `toolDetail.offsetHeight` at init time (the
element is hidden and offsetHeight is 0). Instead, apply the saved value directly without
clamping — the drag and resize handlers will clamp it correctly when the user interacts:

```javascript
// Before:
var containerH = toolDetail.offsetHeight;
var clamped = Math.min(Math.max(saved, 150), containerH - 150);
toolResponseSection.style.height = clamped + 'px';

// After:
toolResponseSection.style.height = saved + 'px';
```

## Requirements

- [x] R1: Dragging the handle up grows the response section in real time.
- [x] R2: Dragging the handle down shrinks the response section in real time.
- [x] R3: Height is clamped to [150px, containerH − 150px] during drag using the actual rendered height.
- [x] R4: Saved height is restored on page load without corruption.
- [x] R5: Window resize re-clamps using the actual rendered height.

## Acceptance Criteria

- [x] AC 1: Dragging the handle up by 50px grows the response section.
- [x] AC 2: Dragging the handle down by 50px shrinks the response section (or clamps at 150px min).
- [x] AC 3: The JS uses `getBoundingClientRect().height` (not `offsetHeight`) for `containerH` in both `mousemove` and `window resize` handlers.
- [x] AC 4: The IIFE that restores saved height does NOT call `toolDetail.offsetHeight` — it applies the saved value directly.
- [x] AC 5: After drag + reload, the saved height is restored correctly.
- [x] AC 6: `.shipyard-dev/verify-spec-033.sh` exits 0.
- [x] AC 7: `go test ./...` passes.
- [x] AC 8: `go vet ./...` passes.
- [x] AC 9: `go build ./...` passes.

## Verification Script

Create `.shipyard-dev/verify-spec-033.sh` that:
1. Asserts `getBoundingClientRect` appears at least twice in `index.html` (once in mousemove, once in window resize)
2. Asserts the IIFE block does NOT call `toolDetail.offsetHeight` (i.e., no `toolDetail.offsetHeight` appears between the `localStorage.getItem('shipyard_tool_response_height')` call and the closing `})()`)
3. Asserts `mousemove` handler still uses `toolResizeDragging`
4. Asserts `window.addEventListener('resize'` still exists
5. Runs `go test ./...`
6. Prints PASS/FAIL per check with summary

## Context

### Target files

- `internal/web/ui/index.html` — JS section, Tool Browser init block (~lines 1475-1513):
  - IIFE: remove `containerH` / `clamped` lines; replace with direct `saved + 'px'`
  - `mousemove` handler: change `toolDetail.offsetHeight` → `toolDetail.getBoundingClientRect().height`
  - `window resize` handler: same change

### Exact changes

**IIFE block (lines ~1476-1483) — before:**
```javascript
(function() {
  var saved = parseInt(localStorage.getItem('shipyard_tool_response_height'), 10);
  if (saved && toolResponseSection) {
    var containerH = toolDetail.offsetHeight;
    var clamped = Math.min(Math.max(saved, 150), containerH - 150);
    toolResponseSection.style.height = clamped + 'px';
  }
})();
```

**IIFE block — after:**
```javascript
(function() {
  var saved = parseInt(localStorage.getItem('shipyard_tool_response_height'), 10);
  if (saved && toolResponseSection) {
    toolResponseSection.style.height = saved + 'px';
  }
})();
```

**mousemove handler (line ~1495) — before:**
```javascript
var containerH = toolDetail.offsetHeight;
```

**mousemove handler — after:**
```javascript
var containerH = toolDetail.getBoundingClientRect().height;
```

**window resize handler (line ~1509) — before:**
```javascript
var containerH = toolDetail.offsetHeight;
```

**window resize handler — after:**
```javascript
var containerH = toolDetail.getBoundingClientRect().height;
```

### No other files need changes

`ui_layout_test.go` does not test the JS runtime logic — no changes needed.
`.shipyard-dev/verify-spec-032.sh` — no changes needed.

## Out of Scope

- Changes to the handle's visual appearance
- Touch/pointer events
- Any other resize handle behaviour not broken

## Gap Protocol

- Research-acceptable gaps: none — three exact line changes specified above
- Stop-immediately gaps: drag still does nothing after fix; `getBoundingClientRect` not present in JS
- Max research subagents before stopping: 0
