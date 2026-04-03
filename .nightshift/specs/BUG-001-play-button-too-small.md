---
id: BUG-001
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-010]
prior_attempts: []
created: 2026-03-26
---

# Play Button Too Small on Tool Rows

## Problem

The ▶ play button added by SPEC-010 (Tool Execution Sheet) on each tool row in the Gateway detail pane is too small. Users can barely see it and it's hard to click. This violates **SPEC-010 AC 1**: "Each tool row in Gateway detail pane shows a ▶ button (SF Symbol: `play.circle` or `play.fill`)" — the button exists but is not practically usable due to size.

**Violated spec:** SPEC-010 (Tool Execution Sheet)
**Violated criteria:** AC 1 — button must be visible and clickable. Implied by the requirement that this is a primary interaction trigger.

## Requirements

- [ ] R1: Play button uses a larger SF Symbol (at minimum `.font(.title3)`, recommend `.font(.title2)`)
- [ ] R2: Play button has adequate padding for hit target (minimum 44×44pt clickable area per Apple HIG)
- [ ] R3: Consider using `play.circle.fill` instead of `play.fill` for better visibility against the dark background
- [ ] R4: Button should be visually balanced with the enable/disable toggle on the same row

## Acceptance Criteria

- [ ] AC 1: Play button is clearly visible on each tool row without straining
- [ ] AC 2: Play button hit target is at minimum 44×44pt (macOS HIG minimum tap target)
- [ ] AC 3: Play button is visually balanced with other row elements (toggle, text)
- [ ] AC 4: Build succeeds with zero errors; all existing tests pass

## Context

**File to modify:** `Shipyard/Views/GatewayView.swift` — find the play button in the tool row rendering section.

Look for the Button with `play.fill` or `play.circle` SF Symbol. Increase its font size and padding.

## Notes for the Agent

- Read GatewayView.swift and find the exact play button code
- Apple HIG minimum touch target: 44×44pt on macOS
- Use `.font(.title2)` or `.font(.title3)` — test both visually
- Add `.padding(4)` or `.contentShape(Rectangle())` for larger hit area
- Build after the change
