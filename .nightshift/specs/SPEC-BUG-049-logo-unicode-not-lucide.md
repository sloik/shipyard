---
id: SPEC-BUG-049
template_version: 2
priority: 2
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-14
---

# Header logo uses Unicode anchor character instead of Lucide anchor icon in accent blue

## Problem

The app bar logo renders as a Unicode anchor character (`&#9875;` / ⚓) with no specific color styling. The UX-002 design specifies a Lucide `anchor` icon at 20×20px in accent blue (`#58a6ff`).

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Header/AppBar component (`wnzNq`) contains node `kTDSe` — a Lucide "anchor" icon_font, 20×20px, fill `#58a6ff`.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the leftmost element in the app bar (before "Shipyard" text)
3. **Actual:** A Unicode anchor character (⚓), inheriting default text color
4. **Expected:** A Lucide `anchor` icon, 20×20px, colored `var(--accent-fg)` (#58a6ff)

## Root Cause

(Agent fills in during run.)

## Requirements

- [x] R1: The header logo uses the Lucide `anchor` icon, not a Unicode character
- [x] R2: The icon is 20×20px and colored `var(--accent-fg)`

## Acceptance Criteria

- [x] AC 1: Header logo is a Lucide `anchor` icon element (not a Unicode character)
- [x] AC 2: Icon is 20px in size
- [x] AC 3: Icon color is `var(--accent-fg)` (#58a6ff)
- [x] AC 4: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `kTDSe` inside Header/AppBar — `iconFontFamily: "lucide", iconFontName: "anchor", width: 20, height: 20, fill: #58a6ff`
- Bug location: `internal/web/ui/index.html`, line 15 — `<span class="empty-icon">&#9875;</span>`

## Out of Scope

- Brand text styling (already matches design)
- Brand/tabs separator (SPEC-BUG-048)

## Code Pointers

- `internal/web/ui/index.html` — header logo element (line 15)
- `internal/web/ui/ds.css` — check how Lucide icons are loaded (look at server cards for pattern)

## Gap Protocol

- Research-acceptable gaps: how Lucide icons are referenced in the HTML (check existing usage in renderServerCards)
- Stop-immediately gaps: if Lucide font is not bundled
- Max research subagents before stopping: 1
