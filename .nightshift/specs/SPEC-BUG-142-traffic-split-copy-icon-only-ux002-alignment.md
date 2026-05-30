---
id: SPEC-BUG-142
template_version: 3
priority: 5
layer: 3
type: bugfix
status: in_progress
after: [SPEC-BUG-141]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Split-View Copy Controls Use Text Buttons Instead of Icon-Only Actions

## Problem

The Traffic request/response split-view currently renders `Copy` as a text
button inside each panel header. In UX-002, the split-view panel headers use a
single muted copy icon at the far right, not a bordered text button.

This differs from the generic `Btn/Copy` component, which intentionally has an
icon plus label for broader code-block contexts. The split-view panel header
uses an icon-only affordance because the REQUEST/RESPONSE header is already
compact and color-coded.

Observed implementation drift:

- `renderDetailPanel` emits `<button class="btn btn-copy">Copy</button>` for
  request and response panels.
- The copy control has button padding, text, border, and background from
  `.btn-copy`.
- UX-002 `srCopy` and `resCopy` are 12px muted Lucide copy icons with no text.

UX-002 reference:

- `srCopy` (`MEjKm`): Lucide `copy`, 12x12, fill `#8b949e`
- `resCopy` (`Ww2Ws`): Lucide `copy`, 12x12, fill `#8b949e`
- Header rows: `srHeader` (`1bzgW`), `resHeader` (`vdw4y`)

## Requirements

- [ ] R1: Traffic split-view request/response panel copy controls must render
  as icon-only actions in the panel headers.
- [ ] R2: The icon-only controls must preserve accessible labels via
  `aria-label` or equivalent title text.
- [ ] R3: The icon size and muted color must match UX-002's 12px copy icon.
- [ ] R4: Existing clipboard behavior and copied feedback must continue to work
  for request and response payloads.
- [ ] R5: Generic `.btn-copy` behavior elsewhere must not be broken; this spec
  only changes Traffic split-view panel headers.

## Acceptance Criteria

- [ ] AC 1: Request panel header copy action contains a copy icon and no visible
  `Copy` text.
- [ ] AC 2: Response panel header copy action contains a copy icon and no
  visible `Copy` text.
- [ ] AC 3: Both icon-only controls have accessible labels.
- [ ] AC 4: Clicking each copy icon copies only that panel's payload.
- [ ] AC 5: Existing copy buttons in modals, Tool Browser response, and generic
  code blocks keep their current label behavior.
- [ ] AC 6: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `srCopy` (`MEjKm`), `resCopy` (`Ww2Ws`), `Btn/Copy` (`kEmRD`)
- Current implementation:
  - `internal/web/ui/index.html` - copy buttons in `renderDetailPanel`
  - `internal/web/ui/index.html` - `wireCopyButtons`
  - `internal/web/ui/ds.css` - `.btn-copy`
- Related done spec: `SPEC-BUG-038` explicitly scoped to Tool Browser response
  header and did not cover Traffic detail panel copy controls.

## Out of Scope

- Changing Tool Browser response copy button.
- Changing token modal or add-server modal copy buttons.
- Replacing the clipboard implementation globally.

## Code Pointers

- `internal/web/ui/index.html` - request and response copy buttons in
  `renderDetailPanel`
- `internal/web/ui/index.html` - `wireCopyButtons(panelEl)`
- `internal/web/ui_layout_test.go` - source-level structure assertions

## Gap Protocol

- Research-acceptable gaps:
  - Whether icon-only copy controls should still reuse `.btn-copy` with a
    modifier class or use a dedicated traffic split copy class.
- Stop-immediately gaps:
  - Copy action becomes inaccessible to keyboard or screen-reader users.
  - Copy action copies the wrong panel payload.
- Max research subagents before stopping: 1
