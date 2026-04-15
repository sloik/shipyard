---
id: SPEC-BUG-073
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

# Dir badge text uses Inter font, design specifies JetBrains Mono

## Problem

The direction badge text ("REQ"/"RES") renders in Inter (sans-serif). The UX-002 design specifies `fontFamily: "JetBrains Mono"` for the dir badge label.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Dir badge text node `ABlQv` (r1DirLbl) has `fontFamily: "JetBrains Mono", fontSize: 10, fontWeight: 600`.

## Reproduction

1. Open the Timeline tab with traffic data
2. Inspect a direction badge (REQ or RES)
3. **Actual:** Badge text uses Inter (sans-serif)
4. **Expected:** Badge text should use JetBrains Mono (monospace)

## Root Cause

The `.dir` rule in `internal/web/ui/ds.css` had no explicit `font-family`, so it inherited the page default (Inter/sans-serif). Fix: added `font-family: var(--font-mono)` to the `.dir` rule.

## Requirements

- [ ] R1: Dir badge text uses `font-family: var(--font-mono)`

## Acceptance Criteria

- [ ] AC 1: `.dir` badge text renders in JetBrains Mono (monospace)
- [ ] AC 2: `go build ./...` passes

## Context

- Design reference: UX-002 Pencil file, node `ABlQv` — `fontFamily: "JetBrains Mono"`
- Bug location: `internal/web/ui/ds.css` — `.dir` class, or inline in JS
- Live computed: `fontFamily: "Inter, system-ui, sans-serif"`

## Out of Scope

- Dir badge icon (SPEC-BUG-072)
- Dir badge font-size (SPEC-BUG-074)
- Dir badge color or background

## Code Pointers

- `internal/web/ui/ds.css` — `.dir` class rules (grep for `.dir`)
- `internal/web/ui/index.html` — JS dir badge creation

## Gap Protocol

- Research-acceptable gaps: none expected
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 0
