---
id: SPEC-BUG-175
template_version: 3
priority: 3
layer: 3
type: bugfix
status: done
after: [SPEC-BUG-171]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
parent: UX-002
created: 2026-09-24
---

# Traffic filter bar deviates from the UX-002 design

## Problem

Found during the UX-002 acceptance-criteria audit (AC-2 / AC-10). Measured
in headless Chromium at 1440×900 against the design frame
`Phase 0 — Traffic Timeline` → `Filter Bar`:

| Element                 | Design (`.pen`)                    | Implementation                         |
|-------------------------|------------------------------------|----------------------------------------|
| Server select width     | 160 px (`fServer`)                 | 103 px (shrinks to content)            |
| Method select width     | 160 px (`fMethod`)                 | 110–168 px (varies with option text)   |
| Filter label font size  | 11 px, weight 500                  | 12 px                                  |
| Label baseline          | Server/Method/Direction aligned    | Direction label 3 px lower (y 49 vs 46) |
| Entry count badge       | not in filter bar                  | `#traffic-count` "N entries" badge     |
| Select vertical fit     | inside bar                         | selects overflow the 48 px bar by 1 px |

The `N entries` badge is an element not in the design (UX-002 AC-10). It
can also disagree with the footer: one run showed the badge at
`19 entries` while the footer read `Showing 17 of 17 entries` after live
rows arrived.

Pagination vs infinite scroll is **not** part of this spec: SPEC-BUG-113
deliberately replaced the design's paginated footer.

## Requirements

- [x] R1: Server and Method controls are a fixed 160 px wide, per design.
- [x] R2: Filter labels use 11 px / 500 and share one baseline.
- [x] R3: Controls fit inside the filter bar with the design's 8/16 padding.
- [x] R4: Remove the filter-bar entry badge, or keep a single entry count
  that stays consistent with the footer, and record which in the run report.

## Acceptance Criteria

- [x] AC1: Headless measurement: `#filter-server` and `#filter-method` widths
  are 160 px regardless of option text.
- [x] AC2: All three `#filter-bar .input-label` elements have the same `y`
  and computed `font-size: 11px`.
- [x] AC3: No filter control's bounding box extends past `#filter-bar`.
- [x] AC4: At most one visible entry count, which matches the rows loaded
  after live events arrive.
- [x] AC5: `go test ./...` (including `internal/web/ui_layout_test.go`) passes.

## Code Pointers

- `internal/web/ui/index.html` — `#filter-bar` markup (~110–135),
  `trafficCount` / `timelineScrollInfo` updates (~2035–2050, ws handler ~2118)
- `internal/web/ui/ds.css` — `.app-bar`, `.input-group`, `.input-label`
- `.nightshift/specs/UX-002-dashboard-design.pen` — frame `rRx2E` → `Filter Bar`

## Resolution — 2026-09-24

- `ds.css`: `#filter-bar` uses a content-sized height with the design's 8/16
  padding, `align-items: flex-start` (so the three labels share a baseline)
  and a centred Clear button. `#filter-bar .input-label` is 11px, and
  `#filter-server`/`#filter-method` are fixed at 160px. The rules are scoped
  to `#filter-bar`, so History and the other views are unchanged.
- R4 decision: removed the `#traffic-count` badge, which is not in the design.
  The footer "Showing N of M entries" (the design's own count) is now the
  single count. `updateTimelineCount()` refreshes it after every page load and
  every live insert, not only once all pages have loaded.
- Measured at 1440×900: selects 160/160px; labels 11px on one baseline; no
  control extends past the bar; one visible count, which matched the rows
  after live inserts.
- Tests: `TestSPECBUG175_FilterBarMatchesDesign` (fails on the pre-fix UI)
  and a filter-bar + live-count section in `test/smoke/traffic_smoke.mjs`.
