---
id: SPEC-040
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-039, UX-002]
prior_attempts: []
created: 2026-04-14
---

# JSON viewer — line numbers per row

## Problem

The current JSON response viewer renders each line as a plain text node with no
line number column. The updated UX-002 design adds a fixed-width line number
column (24px, muted, right-aligned) to every logical JSON line, paired with the
JSON content. This improves readability for large responses and makes it easier
to reference specific lines in conversation.

**Design source:** UX-002-dashboard-design.pen — JSON viewer component (updated
2026-04-14; diff committed alongside this spec)

## Requirements

- [ ] R1: The JSON viewer wraps each logical line in a horizontal flex row
  containing a line-number cell and the JSON content cell. A "logical line"
  is one entry in the rendered output array (one `<div>` / node today).
- [ ] R2: Line-number cell is 24px wide, right-aligned, font matches JSON content
  (`$font-mono` / `--font-mono`, `$font-size-base`), colour is `--text-muted`.
- [ ] R3: Gap between the line-number cell and the content cell is 12px.
- [ ] R4: For long string values that wrap onto multiple visual lines, the
  continuation row shows a 24px blank spacer in the number column (no number).
- [ ] R5: Outer row gap is 2px (changed from 1px). Container padding changes
  to `[12, 12, 12, 0]` — left padding drops to 0; the number column provides
  the visual left margin.
- [ ] R6: Line numbers are generated dynamically in JS (incrementing counter)
  as the JSON tree is rendered — not hardcoded or injected post-render.
- [ ] R7: Existing JSON syntax highlighting (colours, expand/collapse, recursive
  string expansion from SPEC-039) is unchanged.

## Acceptance Criteria

- [ ] AC 1: The JSON response panel renders a line number for each logical JSON line.
- [ ] AC 2: Line numbers use `--text-muted` colour, are right-aligned, and share
  the monospace font with JSON content.
- [ ] AC 3: The gap between the number cell and content is 12px.
- [ ] AC 4: The number column is 24px wide (fixed, not grow/shrink).
- [ ] AC 5: Continuation visual lines (wrapped long strings) show a 24px blank
  spacer instead of a number.
- [ ] AC 6: The outer container row gap is 2px and padding-left is 0.
- [ ] AC 7: `ui_layout_test.go` contains a test verifying that rendered JSON
  output contains line-number nodes with incrementing content.
- [ ] AC 8: `go test ./...` passes.
- [ ] AC 9: `go vet ./...` passes.
- [ ] AC 10: `go build ./...` passes.

## Scope

Line numbers apply to **all** JSON-displaying views across the app:
- Phase 0: Traffic detail panel (REQUEST/RESPONSE split view) — updated in UX-002
- Phase 1: Tool browser response viewer — primary target of this spec
- Phase 2: History response body (`resBody` frame in UX-002) — updated in UX-002
- Phase 3: Server detail error body (`codeBody` frame in UX-002) — updated in UX-002
- Diff/SideBySide component: both before/after panels — updated in UX-002
- Design system: Code/Block and Panel/SplitView components — updated in UX-002

## Context

- **Design frame:** UX-002 JSON viewer
  - Row structure: `KLPwR` (row1), `sp9o1` (row2), `urRFJ` (row3), `l8o0q` (row4), `i3IXJ` (row5/wrap), `e4jIR` (row6), `laeRx` (row7)
  - Line number nodes: `jS9qe` (row1 num), `N1KOR` (row2 num), `i1eaW` (row3 num), `kD3s1` (row4 num), `6GPQD` (row5 num), `4dlPO` (row6 num), `LwUM6` (row7 num)
  - Wrap spacer: `CFOyi` (width: 24, height: fit_content(0))
- **Implementation:** `internal/web/ui/index.html` — grep for `renderJSON`,
  `formatJSON`, `buildJsonHtml`, or the function that produces JSON viewer rows.
  Verify the exact function name before editing.
- **Test file:** `internal/web/ui_layout_test.go`
- **CSS:** `internal/web/ui/ds.css` — add line-number column style using DS
  classes; no inline styles except layout values.

## Notes for the Agent

- Vanilla JS only: `var`, `.then()`, no `async/await`, no `let`/`const`.
- Use `--text-muted` (CSS variable) for line number colour — not `#b1bac4`.
- The 24px number column should be a `div` with `min-width:24px; max-width:24px`
  (or equivalent DS class if one exists), `text-align:right`.
- For the wrap case, the continuation spacer is a blank div of the same width
  (24px), with no text content.
- Do NOT change the JSON highlighting logic or the SPEC-039 recursive expansion
  behaviour. Only the row wrapper structure changes.
- Grep the existing render function before writing — the row structure today is
  a single text node; you are wrapping it.

## Out of Scope

- Clickable line numbers or anchor links (`#L5`)
- Line range selection / highlighting
- Gutter annotations, decorations, or icons
- Changing line number style for non-JSON response panels
