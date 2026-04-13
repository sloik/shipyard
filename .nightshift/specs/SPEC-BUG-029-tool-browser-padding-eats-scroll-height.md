---
id: SPEC-BUG-029
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-028]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Tool Browser: padding on outer flex container eats scroll height, hiding response section

## Problem

Selecting a tool with many parameters (e.g. `lmstudio → lm_stateful_chat`) leaves
the user unable to scroll the form to reach lower fields, and the response section
is not visible at all.

SPEC-BUG-028 fixed scroll *ownership* by introducing `#tool-detail-scroll` with
`overflow-y:auto`. However, the `padding:24px` remains on `#tool-detail` — the
outer flex container — not on the scroll region. Because CSS padding is part of
the container's own box, it reduces the height available for flex children. With a
long enough schema, the scroll region and response section together exceed the
reduced height, and the browser has no scroll path to show the overflowing content.

## Reproduction

1. Open the Tools tab
2. Select `lmstudio → lm_stateful_chat` (has many parameters)
3. **Actual:** form fields below the fold are unreachable; the response section
   is not visible at all
4. **Expected:** the form scrolls to expose all fields; the response section is
   always visible below the form

## Root Cause

`internal/web/ui/index.html` line 161:

```html
<div id="tool-detail"
     style="... padding:24px; flex-direction:column; overflow:hidden;">
  <div id="tool-detail-scroll"
       style="flex:0 1 auto; min-height:0; overflow-y:auto;">
    <!-- form content -->
  </div>
  <div id="tool-response-section"
       style="flex:1; min-height:0; ...">
    <!-- response -->
  </div>
</div>
```

`padding:24px` belongs to `#tool-detail`'s own box. The two flex children
(`#tool-detail-scroll` and `#tool-response-section`) share the remaining height
after the padding is subtracted from all four sides. With `#tool-detail-scroll`
set to `flex:0 1 auto`, it sizes to content first — a large schema makes it
very tall, crowding `#tool-response-section` (which has `flex:1` but no minimum
height guarantee). The response section can be reduced to zero or pushed below
the padded boundary with no scroll path.

Fix: move padding *inside* each region so `#tool-detail` itself has no padding,
keeping the full `height:100%` available to the flex children.

## Requirements

- [x] R1: All form fields for `lm_stateful_chat` (and any tool with many
  parameters) must be reachable by scrolling.
- [x] R2: The response section must always be visible and accessible,
  regardless of form length.
- [x] R3: The fix must not regress the scroll behavior introduced by
  SPEC-BUG-028 (`lms_load_model` still scrollable).
- [x] R4: Visual padding around the form content and response header must
  remain unchanged from the approved Phase 1 design.

## Acceptance Criteria

- [x] AC 1: `lm_stateful_chat` — scrolling the form reaches all fields and
  the Submit button.
- [x] AC 2: The response section header and body are visible without scrolling
  the page even when the form is long.
- [x] AC 3: `lms_load_model` (SPEC-BUG-028 reference tool) still scrolls
  correctly — no regression.
- [x] AC 4: Visual spacing around form content matches the pre-fix appearance
  (padding moved, not removed).
- [x] AC 5: Regression tests cover the padding-isolation contract (padding not
  on outer container, inner regions have padding).
- [x] AC 6: `go test ./...` passes.
- [x] AC 7: `go vet ./...` passes.
- [x] AC 8: `go build ./...` passes.

## Context

### Target files

- `internal/web/ui/index.html` — lines 161–225: `#tool-detail`,
  `#tool-detail-scroll`, `#tool-response-section`
- `internal/web/ui_layout_test.go` — add/update scroll contract tests

### Key lines

```
161: <div id="tool-detail" style="... padding:24px; ...">   ← padding moves OUT of here
162:   <div id="tool-detail-scroll" ...>                    ← padding goes IN here
206:   <div id="tool-response-section" ...>                 ← padding on header child only
```

### Intended layout after fix

```
#tool-detail          height:100%; flex-direction:column; overflow:hidden;
                      NO padding — full height given to children

  #tool-detail-scroll flex:0 1 auto; min-height:0; overflow-y:auto;
                      padding:24px 24px 0 24px  (top/sides only, no bottom gap)

  #tool-response-section flex:1; min-height:0; flex-direction:column;
                      padding:0 24px 24px 24px  (sides/bottom only)
                      — or keep padding on the response *header* child
```

Exact padding split can be adjusted as long as the visual result matches
the approved design and all ACs pass.

### Related specs

- SPEC-BUG-028 — introduced `#tool-detail-scroll`; fix must not regress it
- UX-002 — approved Phase 1 design (nodes `d1yZ4`, `ncART`, `Mh6pJ`, `HqBpj`)

## Out of Scope

- Changes to schema field generation or the form rendering logic
- Changes to any view other than the Tool Browser detail pane
- Redesigning the information architecture of the Tool Browser

## Gap Protocol

- Research-acceptable gaps: exact padding split between scroll region and
  response section header
- Stop-immediately gaps: any change that hides or clips the response section;
  any change that breaks `lms_load_model` scrolling
- Max research subagents before stopping: 0
