---
id: SPEC-BUG-176
template_version: 3
priority: 3
layer: 3
type: bugfix
status: draft
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
parent: UX-002
created: 2026-09-24
---

# Traffic empty state deviates from the UX-002 design

## Problem

Found during the UX-002 acceptance-criteria audit (AC-9, "Empty state
matches design"). Compared at 1440×900 with `/api/traffic` stubbed empty and
the WebSocket blocked, against design frame `Phase 0 — Empty State`
(`ApsQe`):

| Element        | Design                                                       | Implementation                                                      |
|----------------|--------------------------------------------------------------|---------------------------------------------------------------------|
| Placement      | vertically centered (`justifyContent: center`)               | top-aligned under the header                                        |
| Title          | "No traffic yet", 20 px / 600                                | "No traffic yet", ~16 px                                            |
| Description    | "Start your MCP server through Shipyard to see traffic here." | "Waiting for MCP messages. Set up servers to start capturing traffic." (with link) |
| Step 1         | "Wrap your MCP server" + code block `shipyard wrap -- npx -y @mcp/server /tmp` | "Add MCP servers" + auto-import link, no code block      |
| Step 2         | "Point your AI client at Shipyard"                           | "Traffic appears here"                                              |
| Step layout    | 480 px wide, number chip left, text left-aligned             | ~640 px wide, text centered                                         |
| Number chip    | solid `$accent-emphasis` fill, `$text-on-emphasis` label     | dark tinted fill, accent-colored label                              |

No spec in `.nightshift/specs/` records a decision to change the empty-state
copy. The implementation's copy points users to auto-import (SPEC-004, the
design's `State — Auto-Import Discovery` frame) and the Servers view instead of
`shipyard wrap`, so the **copy** may be an intentional improvement rather than
a regression.

## Open Question (blocks `ready`)

- Q1: Should the implementation follow the design's copy (wrap command +
  "Point your AI client"), or should the `.pen` design be updated to the
  current auto-import copy? UX-002 says "the design wins", so changing the
  design needs an explicit decision.

Layout and styling (centering, title size, step width/alignment, chip
style) follow the design either way.

## Requirements

- [ ] R1: Empty state is vertically centered in the content area.
- [ ] R2: Title 20 px / 600; description 14 px, `$text-secondary`, max 360 px.
- [ ] R3: Step cards 480 px wide, left-aligned content, solid accent number
  chips.
- [ ] R4: Copy per the Q1 decision; if the design is updated instead, update
  `UX-002-dashboard-design.pen` in Pencil.

## Acceptance Criteria

- [ ] AC1: Headless screenshot with `/api/traffic` stubbed empty matches the
  design frame's structure (centered block, two steps, per R1–R3).
- [ ] AC2: Copy matches whichever source Q1 selects; the other source is
  updated so the design and the implementation agree.
- [ ] AC3: `go test ./...` passes.

## Code Pointers

- `internal/web/ui/index.html` — `#timeline-empty` (~84–105)
- `internal/web/ui/ds.css` — `.empty-state`
- `.nightshift/specs/UX-002-dashboard-design.pen` — frame `ApsQe`
