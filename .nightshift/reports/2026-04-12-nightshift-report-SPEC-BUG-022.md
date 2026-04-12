# Nightshift Report

**Date:** 2026-04-12
**Spec:** SPEC-BUG-022
**Status:** completed

## Summary

SPEC-BUG-022 fixed the Tool Browser detail-pane response flow so the response
section is always present after a tool is selected. Shipyard now shows an idle
placeholder before first execution and renders loading inside that same
response region instead of removing the section from layout.

## Root Cause

The Tool Browser modeled response state by hiding and showing whole layout
regions. `selectTool()` hid `#tool-response-section`, and `executeTool()`
swapped to a separate loading block outside the response section. That caused
layout pop-in and drifted from the approved Phase 1 design, which treats the
response region as a stable pane-level surface with internal idle/loading/
success/error substates.

## Fix

- Kept `#tool-response-section` mounted in `internal/web/ui/index.html`.
- Added an explicit idle placeholder inside `#tool-response-json`.
- Added helper functions to reset response metadata and render idle/loading
  inside the existing response body.
- Changed `selectTool()` to reset into the idle state instead of hiding the
  response section.
- Changed `executeTool()` to render loading inside the same response region.
- Added layout regression coverage in `internal/web/ui_layout_test.go`.

## Validation Results

- `go test ./internal/web -run 'SPECBUG021|SPECBUG022|BUG007' -v` ✅
- `go test ./...` ✅
- `go vet ./...` ✅
- `go build ./...` ✅

## Files Changed

- `internal/web/ui/index.html`
- `internal/web/ui_layout_test.go`
- `.nightshift/specs/SPEC-BUG-022-tool-browser-response-section-hidden-until-first-execution.md`
- `.nightshift/reports/2026-04-12-nightshift-report-SPEC-BUG-022.md`

## Remaining Risk

The current idle/loading body uses lightweight inline markup inside the JSON
viewer container. If the response area later gains richer non-JSON modes, that
substate rendering may need to move into a dedicated reusable component rather
than stay inline in `index.html`.
