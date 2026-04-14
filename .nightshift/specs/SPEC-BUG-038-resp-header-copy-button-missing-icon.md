---
id: SPEC-BUG-038
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002]
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Response header Copy button is text-only — design requires icon + label

## Problem

The response header Copy button (`#tool-response-copy`) renders as plain text "Copy"
with no icon. The approved design (`Q9lu4 / respHeader → Eurmv / respMeta → zWObG / respCopy`)
specifies an inline icon + label pair: a copy icon (12×12, muted colour) followed by
the "Copy" text label.

**Violated spec:** UX-002 (dashboard design)
**Violated criteria:** respCopy (zWObG) — button must contain an icon element before the label

## Reproduction

1. Open the Tools tab
2. Select any tool and execute it
3. Observe the Copy button in the response header

4. **Actual:** button shows only the text "Copy"
5. **Expected:** button shows a small copy icon (≈12×12) followed by "Copy"

## Root Cause

(To be filled by agent.)

The current HTML is:

```html
<button class="btn btn-copy btn-sm" id="tool-response-copy">Copy</button>
```

No icon element is present.

## Requirements

- [ ] R1: The Copy button contains an icon element (inline SVG or equivalent)
  rendered at 12×12 px in the muted text colour before the "Copy" label.
- [ ] R2: The icon and label are separated by a gap consistent with the design
  (4px — matches `--gap-xs` or inline style).
- [ ] R3: The icon must convey "copy" semantics (copy/duplicate glyph).
- [ ] R4: The icon must not break the existing copy-to-clipboard behaviour wired
  to `#tool-response-copy`.

## Acceptance Criteria

- [ ] AC 1: The Copy button contains an icon element followed by the text "Copy".
- [ ] AC 2: The icon renders at approximately 12×12 px in a muted/secondary colour.
- [ ] AC 3: The button gap between icon and label is 4 px.
- [ ] AC 4: Clicking the button still triggers copy-to-clipboard (no regression on
  existing copy wiring).
- [ ] AC 5: `ui_layout_test.go` contains a test verifying the button contains both
  an icon child and the "Copy" text.
- [ ] AC 6: `go test ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.

## Context

- Design frame: `Q9lu4` (respHeader) → `Eurmv` (respMeta) → `zWObG` (respCopy)
  - Design node IDs: respCopyIcon `5GyTO` (icon, 12×12, fill: #b1bac4), respCopyLbl `73kEk` ("Copy", fill: #b1bac4, 11px)
  - Design gap: 4px between icon and label
- Implementation: `internal/web/ui/index.html` line ~216
- Test file: `internal/web/ui_layout_test.go`
- CSS: `.btn-copy` in `internal/web/ui/ds.css` — padding 3px 8px, colour --text-secondary

## Notes for the Agent

- The project does **not** use Lucide font. Use an inline SVG for the copy icon
  (two overlapping rectangles is the standard copy glyph). Keep it minimal —
  one `<svg>` with a `<path>` or `<rect>` elements, `currentColor` fill,
  `width="12" height="12"`.
- The `--text-secondary` / `--text-muted` CSS variable covers the `#b1bac4` colour
  from the design — use that variable rather than a hardcoded hex.
- Do NOT restructure the button's existing JavaScript wiring. The `id` attribute
  and `btn-copy` class must remain in place.
- The JS conventions for this project: `var`, `.then()`, no `async/await`, no
  `let`/`const`.

## Out of Scope

- Changing copy-to-clipboard behaviour or feedback states
- Adding icons to other Copy buttons in the UI (traffic detail panel, etc.)
- Updating icon size/colour for the non-response-header copy buttons

## Gap Protocol

- Research-acceptable gaps: exact SVG path for the copy glyph
- Stop-immediately gaps: any change to clipboard JS wiring
- Max research subagents before stopping: 0
