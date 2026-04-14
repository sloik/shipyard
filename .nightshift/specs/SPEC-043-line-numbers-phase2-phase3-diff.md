---
id: SPEC-043
priority: 2
layer: 2
type: feature
status: ready
after: [SPEC-040]
prior_attempts: []
created: 2026-04-14
---

# Line numbers in Phase 2, Phase 3, and Diff JSON views

## Problem

SPEC-040 added line numbers to the Phase 1 tool browser JSON viewer. Three other
views also display JSON with syntax highlighting but were not updated:

1. **Phase 2 History — request body** — the scrollable JSON panel showing the
   original request in the "State — Edit & Replay" screen. Absolutely positioned
   lines with a decorative scrollbar, clipped at 160px. Uses `$json-bracket`,
   `$json-key`, `$json-string` token colours.
   Design frame: `rJHR1` (name: `srBody`, parent screen: "State — Edit & Replay").

2. **Phase 2 History — response body** — the expanded-row detail panel that shows
   the full JSON response for a historical traffic entry. Located inside the
   "State — Edit & Replay" screen. Same JSON token colour variables.
   Design frame: `kyYV1` (name: `resBody`, parent screen: "State — Edit & Replay").

3. **Phase 2 Response Diff — left panel body** — the "before" panel in the
   side-by-side response diff screen. Shows JSON with danger-highlighted lines
   (lines 4, 5, 8 have `$danger-subtle` background, `$danger-fg` text). Uses
   `$font-mono` / `$font-size-base`.
   Design frame: `L67nP` (name: `panLBody`, parent screen: "State — Response Diff").

4. **Phase 2 Response Diff — right panel body** — the "after" panel in the
   side-by-side response diff screen. Shows JSON with success-highlighted lines
   (lines 4, 5, 8 have `$success-subtle` background, `$success-fg` text).
   Design frame: `QAJcZ` (name: `panRBody`, parent screen: "State — Response Diff").

5. **Phase 3 Server Detail — error response body** — the code block inside the
   error-state server detail view showing the raw JSON-RPC error. Uses `$font-mono`
   / `$font-size-base` and the same JSON token colour variables.
   Design frame: `WLWZQ` (name: `codeBody`, parent screen: "State — Error Response").

6. **Diff/SideBySide component** — the reusable side-by-side diff viewer used by
   Phase 2's "Response Diff" screen. Both the "before" and "after" panels show
   JSON-like content (unchanged / removed / added lines).
   Design component: `2VMoF` (name: `Diff/SideBySide`, reusable). Contains
   reusable sub-components `DJh0f` (name: `line-removed`) and `W5lJJ`
   (name: `line-added`) — these must keep their `reusable: true` status.

All three views now have line numbers in the UX-002 design file
(`UX-002-dashboard-design.pen`, updated 2026-04-14). The implementation must
match the updated design.

## Pattern

Follow the same row structure established by SPEC-040:

- Each logical JSON line is wrapped in a horizontal flex row
- First child: line-number cell — fixed width (20–24px), right-aligned,
  `--text-muted` colour, monospace font matching JSON content
- Second child: JSON content cell — `flex: 1` / `fill_container`, inherits
  existing syntax-highlighting classes
- Row gap: 2px between rows
- Word wrapping: content cell uses `word-wrap: break-word`; line number stays
  top-aligned while wrapped content flows below

### Diff-specific notes

- Unchanged lines: line number in `--text-muted`
- Removed lines (`line-removed`): line number in `--danger-fg` at reduced opacity
- Added lines (`line-added`): line number in `--success-fg` at reduced opacity
- Line numbers represent the file position (not sequential from 1) — they may
  start mid-file to show context around a change

## Requirements

- [ ] R1: Phase 2 History request body (`srBody`) renders line numbers using the
  SPEC-040 row pattern.
- [ ] R2: Phase 2 History response body (`resBody`) renders line numbers using
  the SPEC-040 row pattern.
- [ ] R3: Phase 2 Response Diff left panel (`panLBody`) renders line numbers;
  danger-highlighted lines use `--danger-fg` for line numbers at reduced opacity.
- [ ] R4: Phase 2 Response Diff right panel (`panRBody`) renders line numbers;
  success-highlighted lines use `--success-fg` for line numbers at reduced opacity.
- [ ] R5: Phase 3 error response body (`codeBody`) renders line numbers using
  the SPEC-040 row pattern.
- [ ] R6: Diff/SideBySide component (`Diff/SideBySide`) "before" and "after"
  panels render line numbers with colour matching the line type (muted for
  unchanged, danger for removed, success for added).
- [ ] R7: Existing JSON syntax highlighting and token colours are unchanged.
- [ ] R8: The `line-removed` and `line-added` reusable components in
  Diff/SideBySide are preserved (not replaced with non-reusable frames).

## Acceptance Criteria

- [ ] AC-1: Phase 2 History request body shows a line number for each JSON line.
- [ ] AC-2: Phase 2 History response body shows a line number for each JSON line.
- [ ] AC-3: Phase 2 Response Diff left panel shows line numbers; danger-highlighted
  lines use `--danger-fg` for the number at reduced opacity.
- [ ] AC-4: Phase 2 Response Diff right panel shows line numbers; success-highlighted
  lines use `--success-fg` for the number at reduced opacity.
- [ ] AC-5: Phase 3 error response body shows a line number for each JSON line.
- [ ] AC-6: Diff/SideBySide component before-panel shows line numbers; removed
  lines use `--danger-fg` for the number.
- [ ] AC-7: Diff/SideBySide component after-panel shows line numbers; added
  lines use `--success-fg` for the number.
- [ ] AC-8: Long JSON values wrap at word boundaries; line number stays
  top-aligned.
- [ ] AC-9: `go test ./...` passes.
- [ ] AC-10: `go vet ./...` passes.
- [ ] AC-11: Visual output matches the UX-002 design for each affected view.

## Target Files

- `internal/web/ui/index.html` — JSON rendering functions (grep for
  `highlightJSON`, `renderJSON`, `buildJsonHtml`, or the function that produces
  JSON viewer rows — verify exact name before editing)
- `internal/web/ui/ds.css` — line-number and diff-line styles if not already
  present from SPEC-040

## Design Reference

All design frames are in `UX-002-dashboard-design.pen`. If a frame ID listed
above no longer exists, search by the frame **name** (given in parentheses) —
IDs may change across design iterations but names are stable.
