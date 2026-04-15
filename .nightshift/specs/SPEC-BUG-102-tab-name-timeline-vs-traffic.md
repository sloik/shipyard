---
id: SPEC-BUG-102
template_version: 2
priority: 3
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# First tab labeled "Timeline" but design says "Traffic"

## Problem

The first nav tab is labeled "Timeline" in the live UI. The UX-002 design labels it "Traffic" (node `qCfG0`, text `"Traffic"`, inside tab `7cucN`). The route hash is `#timeline`.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** First tab label should be "Traffic", not "Timeline".

## Reproduction

1. Open any page, look at the first tab in the nav bar
2. **Actual:** "Timeline"
3. **Expected:** "Traffic"

## Root Cause

The tab link text in `internal/web/ui/index.html` was set to "Timeline" instead of "Traffic". The route hash `#timeline` and `data-route="timeline"` were already correct — only the visible label needed updating.

## Requirements

- [x] R1: Rename the first tab label from "Timeline" to "Traffic"
- [x] R2: Route hash can remain `#timeline` (internal route name doesn't need to match display label)

## Acceptance Criteria

- [x] AC 1: First tab displays "Traffic" as its label
- [x] AC 2: Tab still navigates to the timeline/traffic view
- [x] AC 3: `go build ./...` passes

## Context

- Design: node `qCfG0` content "Traffic", icon `activity` (Lucide)
- Live: tab text "Timeline", href="#timeline"
- The page title bar also says "Phase 0 — Traffic Timeline" — may need updating

## Out of Scope

- Route hash renaming (#timeline → #traffic)
- Page title bar text

## Code Pointers

- `internal/web/ui/index.html` — nav tab link text (line ~24 area)

## Gap Protocol

- Research-acceptable gaps: whether "Timeline" was an intentional rename
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
