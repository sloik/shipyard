---
id: SPEC-BUG-030
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-029]
violates: [UX-002]
prior_attempts:
  - "SPEC-BUG-029 moved padding but left the flex roles unchanged — scroll still broken"
created: 2026-04-13
---

# Tool Browser: wrong flex roles cause response section to collapse to 0px on long forms

## Problem

Selecting a tool with many parameters (e.g. `lmstudio → lm_stateful_chat`) makes
it impossible to scroll the form and hides the response section entirely. The bug
persists after SPEC-BUG-029 because the real cause is the **flex roles**, not
the padding.

## Root Cause

`internal/web/ui/index.html` lines 162 and 206:

```
#tool-detail-scroll:    flex:0 1 auto   ← content-sized, can shrink, CANNOT grow
#tool-response-section: flex:1          ← expands to flex:1 1 0 (flex-basis: 0)
```

CSS flex shrink distributes overflow proportional to `flex-shrink × flex-basis`:

| Element | flex-shrink | flex-basis | shrink weight |
|---------|-------------|------------|---------------|
| `#tool-detail-scroll` | 1 | content (~1200px) | **1200** |
| `#tool-response-section` | 1 | 0 | **0** |

When the form is taller than the container, 100% of shrinkage goes to the scroll
section and 0% to the response section. The response section stays at **0px**.
The scroll section IS constrained in height — but `overflow-y:auto` never fires
because the element has `flex:0 1 auto` (no grow), so it only fills its shrunken
content size. The result: the form is clipped, the response is invisible, nothing
scrolls.

## Correct Flex Contract

```
#tool-detail            height:100%; flex-direction:column; overflow:hidden;
  #tool-detail-scroll   flex:1 1 0; min-height:0; overflow-y:auto;
                        ← grows to fill ALL available space; shrinks when needed;
                          content scrolls within its allocated height
  #tool-response-section flex:0 0 auto; min-height:200px;
                        ← always takes its natural height; never grows or shrinks;
                          guaranteed visible regardless of form length
```

With `flex:1 1 0` on the scroll section:
- `flex-basis:0` → both children start from 0, making shrink math symmetric
- `flex-grow:1` → scroll section takes all space not consumed by response section
- `overflow-y:auto` → content longer than allocated height scrolls

With `flex:0 0 auto` + `min-height:200px` on response:
- Always renders at its natural height (≥200px)
- Never shrinks to 0 regardless of form length
- Response section is always accessible

## Requirements

- [x] R1: `#tool-detail-scroll` must use `flex:1 1 0` so it fills available
  space and scrolls when content overflows.
- [x] R2: `#tool-response-section` must use `flex:0 0 auto` with
  `min-height:200px` so it is always visible and never collapses.
- [ ] R3: The fix must not regress SPEC-BUG-021 (response JSON body fills
  remaining response section height).
- [ ] R4: Visual appearance for short-form tools must be unchanged — response
  section appears at its natural height below the form.

## Acceptance Criteria

- [x] AC 1: `lm_stateful_chat` — the form scrolls and all fields are reachable.
- [x] AC 2: The response section is visible at all times, even when the form
  is longer than the viewport.
- [x] AC 3: `lms_load_model` still scrolls (SPEC-BUG-028 regression check).
- [x] AC 4: Short-form tool (e.g. `read_file` with 1-2 params) — form and
  response both visible without scrolling; layout unchanged.
- [x] AC 5: `#tool-detail-scroll` has `flex:1 1 0` in `index.html`.
- [x] AC 6: `#tool-response-section` has `flex:0 0 auto` and `min-height:200px`
  in `index.html`.
- [x] AC 7: All layout tests updated to assert the new flex contract — no tests
  left asserting the old broken values (`flex:0 1 auto` on scroll,
  `flex:1` on response).
- [x] AC 8: `go test ./...` passes.
- [x] AC 9: `go vet ./...` passes.
- [x] AC 10: `go build ./...` passes.
- [x] AC 11: `.shipyard-dev/verify-bug-030.sh` exits 0 (see below).

## Verification Script

A shell script at `.shipyard-dev/verify-bug-030.sh` must be created as part of
this fix. It is the canonical way to verify the fix before merge. It must:

1. Assert `#tool-detail-scroll` contains `flex:1 1 0` in `index.html`
2. Assert `#tool-detail-scroll` does NOT contain `flex:0 1 auto`
3. Assert `#tool-response-section` contains `flex:0 0 auto` in `index.html`
4. Assert `#tool-response-section` contains `min-height:200px` in `index.html`
5. Assert `#tool-response-section` does NOT contain `flex:1;` (the broken value)
6. Assert `#tool-detail` does NOT have `padding:` directly on it
7. Run `go test ./...` and exit non-zero if any test fails
8. Print PASS/FAIL per check with a final summary

The script must be executable and work from the repo root.

## Context

### Target files

- `internal/web/ui/index.html` — lines 162 and 206: flex values on scroll and
  response sections
- `internal/web/ui_layout_test.go` — update ALL assertions that check the old
  broken flex values:
  - `TestSPECBUG028` (line ~516): asserts `flex:0 1 auto` → update to `flex:1 1 0`
  - `TestSPECBUG028` (line ~527): asserts `flex:1` on response → update to `flex:0 0 auto`
  - `TestSPECBUG021` (line ~1049): asserts `flex:1` on response → update
  - `TestSPECBUG022` (line ~1081): exact-match string with `flex:1` on response → update
  - `TestSPECBUG023` (line ~1182): exact-match string with `flex:1` on response → update
  - `TestSPECBUG029` (line ~1014): asserts `flex:1` on response → update
- `.shipyard-dev/verify-bug-030.sh` — new verification script

### Current broken values (what to change FROM)

```
line 162: flex:0 1 auto   → change to: flex:1 1 0
line 206: flex:1           → change to: flex:0 0 auto; min-height:200px
```

The `min-height:0` on line 206 becomes redundant with `flex:0 0 auto` — remove it.

## Out of Scope

- Changes to any other view (History, Servers, Timeline)
- Changes to the response JSON body scroll behavior (SPEC-BUG-021)
- Redesigning the Tool Browser information architecture

## Gap Protocol

- Research-acceptable gaps: exact `min-height` value for response section
  (200px is the floor — adjust if visual testing shows a better value)
- Stop-immediately gaps: response section not visible for `lm_stateful_chat`;
  regression in `lms_load_model` scrolling; `go test` failures
- Max research subagents before stopping: 0
