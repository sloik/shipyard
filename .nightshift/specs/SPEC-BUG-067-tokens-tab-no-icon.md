---
id: SPEC-BUG-067
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

# Tokens tab has no Lucide icon while all other tabs do

## Problem

The Tokens tab (`<a class="tab" data-route="tokens">Tokens</a>`) is the only tab without a Lucide SVG icon. Timeline has `activity`, Tools has `wrench`, History has `history`, Servers has `server` — all 14px icons. The Tokens tab is text-only, breaking visual consistency.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** While Tokens is not in the 4-tab design (Timeline, Tools, History, Servers), all tabs that exist must follow the Tab/Default and Tab/Active component patterns (`3wZYe`/`ae085`) which include a 14px Lucide icon + text. The Tokens tab was added without an icon.

## Reproduction

1. Open any page in Shipyard UI
2. Look at the nav tabs in the header
3. **Actual:** Tokens tab shows only text "Tokens" with no icon
4. **Expected:** Tokens tab should have a Lucide icon (e.g., `key-round`) at 14px before the text, matching other tabs

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: Tokens tab has a Lucide SVG icon (suggest `key-round`) at 14px before the text
- [ ] R2: Icon style matches other tab icons (14×14px, `stroke="currentColor"`, `stroke-width="2"`)

## Acceptance Criteria

- [ ] AC 1: Tokens tab `<a>` element contains a Lucide SVG icon before the text "Tokens"
- [ ] AC 2: Icon is 14×14px with `stroke="currentColor"`
- [ ] AC 3: Icon inherits color from `.tab` / `.tab-active` CSS (muted when inactive, primary when active)
- [ ] AC 4: `go build ./...` passes

## Context

- Bug location: `internal/web/ui/index.html`, line ~22 — `<a class="tab tab-default" href="#tokens" data-route="tokens">Tokens</a>`
- Other tabs use inline SVGs from Lucide icon set at 14px
- Suggested icon: `key-round` (represents tokens/API keys) — but any appropriate Lucide icon is acceptable

## Out of Scope

- Whether Tokens tab should exist at all (design has 4 tabs)
- Tab styling or layout changes

## Code Pointers

- `internal/web/ui/index.html` — `<a ... data-route="tokens">Tokens</a>` (line ~22)

## Gap Protocol

- Research-acceptable gaps: which Lucide icon best represents "Tokens" — check other tab icons for precedent
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
