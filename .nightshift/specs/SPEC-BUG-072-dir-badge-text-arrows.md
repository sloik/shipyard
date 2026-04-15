---
id: SPEC-BUG-072
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Dir badge uses text arrows "REQ →/← RES" instead of Lucide arrow icons

## Problem

The direction badges in data rows use Unicode text arrows: `"REQ →"` and `"← RES"`. The UX-002 design uses a Lucide `arrow-right` icon (10px) next to the text `"REQ"` (no Unicode arrows), with `gap: 3` inside the badge. A RES variant would use a `arrow-left` icon.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Dir badge node (`pQzwV`/r1DirBadge) contains icon_font node `dhDqG` — Lucide `arrow-right`, 10×10px, fill `#58a6ff`, followed by text `"REQ"` (no arrow character). The badge uses `gap: 3`.

## Reproduction

1. Open the Timeline tab with traffic data
2. Look at the Dir column
3. **Actual:** Text badges show "REQ →" and "← RES" with Unicode arrows
4. **Expected:** Badge should contain a Lucide arrow-right/arrow-left SVG icon (10px) + text "REQ"/"RES" with no Unicode arrow characters

## Root Cause

The `dirBadge()` JS function in `index.html` built badge HTML using Unicode arrow characters (`\u2192`, `\u2190`) appended to the "REQ"/"RES" text. The `.dir` CSS class had `gap: 4px` instead of the 3px required by the design spec.

## Requirements

- [x] R1: REQ badge contains Lucide `arrow-right` SVG (10px) + text "REQ", no Unicode "→"
- [x] R2: RES badge contains Lucide `arrow-left` SVG (10px) + text "RES", no Unicode "←"
- [x] R3: Icon and text have 3px gap inside the badge

## Acceptance Criteria

- [x] AC 1: REQ badges show a Lucide arrow-right SVG (10×10px) before "REQ" text
- [x] AC 2: RES badges show a Lucide arrow-left SVG (10×10px) before "RES" text
- [x] AC 3: Badge internal gap is 3px
- [x] AC 4: No Unicode arrow characters (→/←) in dir badge text
- [x] AC 5: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `pQzwV` (r1DirBadge) — children: `dhDqG` (Lucide arrow-right 10×10, fill #58a6ff) + `ABlQv` (text "REQ", JetBrains Mono 10px 600, fill #58a6ff); `gap: 3, cornerRadius: 4, fill: #58a6ff15, padding: [2,6]`
- Bug location: `internal/web/ui/index.html` — JS that creates dir badge HTML (search for `dir-req` or `dir-res` in the script)

## Out of Scope

- Dir badge color (blue for REQ is correct per design)
- Dir badge border-radius or padding
- Dir badge font changes (SPEC-BUG-073, SPEC-BUG-074)

## Code Pointers

- `internal/web/ui/index.html` — JS function that creates row HTML (search for `dir-req`, `dir-res`, or direction badge creation)

## Gap Protocol

- Research-acceptable gaps: how dir badges are created in JS
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
