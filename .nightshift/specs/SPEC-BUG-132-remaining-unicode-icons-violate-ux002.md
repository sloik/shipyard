---
id: SPEC-BUG-132
template_version: 3
priority: 2
layer: 2
type: bugfix
status: done
after: [UX-002, SPEC-BUG-049, SPEC-BUG-058, SPEC-BUG-059]
violates: [UX-002]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Remaining Unicode and HTML Entity Icons Violate UX-002 Lucide Icon Contract

## Problem

Several visible dashboard controls and states still use Unicode or HTML entity
glyphs for icons even after the UX-002 icon cleanup specs replaced the header,
search, clear, empty-state, and row-chevron icons with Lucide SVGs.

This creates inconsistent rendering across platforms and breaks the design
system rule that recognizable UI actions use familiar icon glyphs from the
design source rather than emoji/entity text.

**Violated spec:** UX-002 (Dashboard Design)

**Violated criteria:** UX-002 defines dashboard icons as design-system icon
nodes. Prior UX-002 bug specs establish the concrete contract: use Lucide SVG
icons for visible controls and state markers instead of Unicode/emoji/entity
glyphs.

## Reproduction

1. Open the dashboard source or live UI.
2. Inspect these visible surfaces:
   - global schema-change alert
   - Tool Browser conflict warning and Execute button
   - History no-results empty state
   - Sessions empty/record controls
   - Performance empty state and sort indicator
   - Servers action bar and warning banners
   - Schema empty state and modal close buttons
   - Tokens empty/create/stats/scope controls
   - toast icons from `ds.js`
3. **Actual:** multiple controls render icons using `&#...;` entities or
   Unicode text glyphs such as warning, plus, down arrow, red dot, chart, shield,
   lock/key, close, and play.
4. **Expected:** visible iconography uses Lucide SVGs or established design
   system components with stable sizing, stroke color, spacing, and accessible
   labels.

## Root Cause

Dashboard icon cleanup happened in focused UX-002 passes, but several later or
less-central surfaces still used inline entity text in static markup and dynamic
HTML strings. The design-system toast helper also kept prefixing messages with
Unicode status glyphs instead of leaving notification state to styling.

## Requirements

- [x] R1: Replace remaining visible Unicode/HTML entity icons in dashboard UI
  surfaces with Lucide SVG icons or existing design-system icon helpers.
- [x] R2: Icon size, color, and gap must match nearby UX-002-backed component
  patterns.
- [x] R3: Buttons with icons must keep stable text/icon alignment and must not
  rely on emoji/entity text for meaning.
- [x] R4: Empty states must use Lucide icons, not emoji code points.
- [x] R5: Warning/alert banners must use Lucide warning/alert icons, not
  `&#9888;`.
- [x] R6: Sort indicators and direction arrows must use SVG icons where the
  current design requires icons, not raw arrow entities.
- [x] R7: Existing behavior of all affected buttons, filters, modals, and
  toasts must remain unchanged.

## Acceptance Criteria

- [x] AC 1: No visible dashboard icon uses emoji or HTML entity code points for
  warning, plus/add, import/download, close, play/execute, red-dot record,
  chart/performance, shield/schema, lock/key/token, or sort direction.
- [x] AC 2: Global schema alert and all warning banners use Lucide warning/alert
  icons.
- [x] AC 3: Add/Create/Import/Close/Execute/Record buttons use SVG icons with
  stable icon+text spacing.
- [x] AC 4: History no-results, Sessions empty, Performance empty, Schema empty,
  and Tokens empty states use Lucide icons.
- [x] AC 5: `DS.toast()` no longer prefixes toast text with Unicode icons.
- [x] AC 6: Structural tests fail if new visible `&#...;` icon entities are
  added to `internal/web/ui/index.html` or `internal/web/ui/ds.js` outside
  text/content examples where an entity is semantically required.
- [x] AC 7: Existing UX-002 icon specs remain passing: SPEC-BUG-049,
  SPEC-BUG-058, SPEC-BUG-059, SPEC-BUG-079, SPEC-BUG-080, SPEC-BUG-081, and
  SPEC-BUG-122.
- [x] AC 8: `go test ./...`, `go vet ./...`, and `go build ./...` pass.

## Context

- Confirmed source scan: `internal/web/ui/index.html` still contains visible
  icon entities including `&#9888;`, `&#9654;`, `&#128269;`, `&#10005;`,
  `&#128308;`, `&#128202;`, `&#9881;`, `&#43;`, `&#8681;`, `&#128737;`,
  `&#128274;`, and `&#128273;`.
- `internal/web/ui/ds.js` prefixes toast messages with Unicode icon text.
- Prior UX-002 specs already replaced the same class of issue in header/search
  and empty-state areas.

## Out of Scope

- Changing the product information architecture
- Replacing textual arrows inside prose examples or code samples
- Adding an external icon dependency
- Reworking all inline SVG duplication into a shared runtime helper unless the
  implementation agent chooses that as the smallest maintainable route

## Code Pointers

- `internal/web/ui/index.html` - visible UI markup and dynamic HTML strings
- `internal/web/ui/ds.js` - toast rendering
- `internal/web/ui/ds.css` - icon/button spacing styles
- `internal/web/ui_layout_test.go` - structural UI regression tests
- `.nightshift/specs/SPEC-BUG-049-logo-unicode-not-lucide.md`
- `.nightshift/specs/SPEC-BUG-058-clear-button-missing-x-icon.md`
- `.nightshift/specs/SPEC-BUG-059-search-icon-unicode-emoji.md`

## Gap Protocol

- Research-acceptable gaps:
  - Choosing the nearest Lucide equivalent for each remaining state icon
  - Distinguishing decorative icons from semantically meaningful text
- Stop-immediately gaps:
  - Any replacement that removes accessible names from buttons
  - Any replacement that introduces external network-loaded assets
- Max research subagents before stopping: 1
