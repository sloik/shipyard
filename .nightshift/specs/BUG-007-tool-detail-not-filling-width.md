---
id: BUG-007
priority: 2
type: bug
status: done
after: [SPEC-002]
created: 2026-04-05
---

# BUG-007: Tool Detail Panel Does Not Fill Available Width

## Screenshots

- Actual: `docs/phase_1_feedback/004-tool-does-not-fill-width.png`
- Design: Phase 1 — Tool Browser frame in `UX-002-dashboard-design.pen` (node `d1yZ4`)

## Problem

The tool detail panel (form + response) is constrained to a narrow column (~720px) instead of filling the entire area right of the sidebar. A large empty dark region is visible on the right side of the viewport.

## Design Reference (.pen nodes)

In the design, the layout hierarchy is:

- `e6zcZ` (body) — `width: fill_container`, horizontal flex
  - `dsx1Y` (sidebar) — `width: 260`, fixed
  - `ncART` (main-content) — `width: fill_container`, `height: fill_container`, `padding: 24`, `gap: 20`
    - `Dd1pJ` (tool-header) — `width: fill_container`
    - `Mh6pJ` (form-section) — `width: fill_container`
      - `mO03J` (field1) — `width: 400` (individual fields are 400px, but the section fills)
    - `HqBpj` (response-section) — `width: fill_container`, `height: fill_container`
      - `NdYmB` (respBody) — `width: fill_container`, `height: fill_container`

**Key design rules:**
- Main content fills all horizontal space right of the sidebar
- Form fields are 400px wide within the full-width section
- Response section (JSON viewer) fills both remaining width AND height
- 24px padding on the main content area

## Root Cause

The `#tool-detail` element has `style="max-width:720px"` which caps the content width. This should be removed — the main content container (`#tools-main`) already has `flex:1` which handles the width correctly.

## Fix

Remove `max-width:720px` from `#tool-detail`. The form fields already have their own `width:400` constraint. The response section should fill the available space.

## Acceptance Criteria

- [ ] AC-1: Tool detail panel fills the full width between sidebar (260px) and viewport edge
- [ ] AC-2: Form fields remain 400px wide (not stretched to full width)
- [ ] AC-3: Response JSON viewer fills the full available width
- [ ] AC-4: Response section grows vertically to fill remaining viewport height
- [ ] AC-5: 24px padding maintained around the main content area

## Target Files

- `internal/web/ui/index.html` — `#tool-detail` inline style
