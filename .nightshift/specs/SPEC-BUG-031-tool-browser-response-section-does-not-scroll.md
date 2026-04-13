---
id: SPEC-BUG-031
template_version: 2
priority: 1
layer: 2
type: bugfix
status: ready
after: [SPEC-BUG-030]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Tool Browser: response section does not scroll — JSON expands to natural height

## Problem

After SPEC-BUG-030, the form section scrolls correctly. But when a tool returns a
large JSON response, the response section expands to its full natural height instead
of scrolling — the JSON body overflows the visible area and is unreachable.

## Root Cause

`internal/web/ui/index.html` line 206:

```html
<div id="tool-response-section"
     style="display:flex; flex:0 0 auto; min-height:200px; ...">
```

`flex:0 0 auto` means flex-basis is `auto` — the element sizes to its content.
A long JSON response → large natural height → section expands to fill it.
The inner `#tool-response-json` has `overflow:auto`, but its parent never
constrains it, so there is never a reason to scroll.

## Fix

Give `#tool-response-section` a fixed initial height (`flex:0 0 300px`) so the
JSON viewer inside gets a bounded container and can scroll. 300px is the default;
SPEC-032 will make this user-adjustable via a drag handle.

Remove `min-height:200px` (superseded by the explicit basis of 300px which is
already larger).

```
Before: flex:0 0 auto; min-height:200px
After:  flex:0 0 300px
```

`#tool-response-json` already has `overflow:auto` — no change needed there.

## Requirements

- [ ] R1: A long JSON response must be scrollable within the response section.
- [ ] R2: The response section must have a visible, usable default height even
  before any response has been received.
- [ ] R3: The fix must not break the form section scroll introduced by
  SPEC-BUG-030.

## Acceptance Criteria

- [ ] AC 1: A long JSON response (>300px of content) scrolls within the
  response section — the section does not expand to natural height.
- [ ] AC 2: The response section is visible at a usable default height
  (≥ 300px) when no response has been received.
- [ ] AC 3: Form section (`#tool-detail-scroll`) still scrolls for long forms
  (SPEC-BUG-030 not regressed).
- [ ] AC 4: `#tool-response-section` has `flex:0 0 300px` in `index.html`.
- [ ] AC 5: `#tool-response-section` does NOT have `flex:0 0 auto` or
  `min-height:200px`.
- [ ] AC 6: All layout tests updated to assert the new value.
- [ ] AC 7: `.shipyard-dev/verify-bug-031.sh` exits 0.
- [ ] AC 8: `go test ./...` passes.
- [ ] AC 9: `go vet ./...` passes.
- [ ] AC 10: `go build ./...` passes.

## Verification Script

Create `.shipyard-dev/verify-bug-031.sh` that:
1. Asserts `#tool-response-section` contains `flex:0 0 300px`
2. Asserts `#tool-response-section` does NOT contain `flex:0 0 auto`
3. Asserts `#tool-response-section` does NOT contain `min-height:200px`
4. Asserts `#tool-response-json` contains `overflow:auto`
5. Runs `go test ./...`
6. Prints PASS/FAIL per check with summary

## Context

### Target files

- `internal/web/ui/index.html` — line 206: `#tool-response-section` flex value
- `internal/web/ui_layout_test.go` — update assertions that check
  `flex:0 0 auto` or `min-height:200px` on `#tool-response-section`
- `.shipyard-dev/verify-bug-031.sh` — new verification script

### Note on SPEC-032

SPEC-032 (resize handle) will let users drag the boundary between form and
response sections. When implemented, it will override the `300px` basis by
setting an explicit pixel height on `#tool-response-section` via JS. This
spec only establishes the default static height — SPEC-032 makes it dynamic.

## Out of Scope

- Making the split user-configurable (that is SPEC-032)
- Changes to any other view

## Gap Protocol

- Research-acceptable gaps: exact default height value (300px is the minimum,
  adjust if visual testing shows a better default)
- Stop-immediately gaps: response section not visible; form scroll regressed
- Max research subagents before stopping: 0
