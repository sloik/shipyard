---
id: SPEC-042
priority: 3
layer: 2
type: feature
status: done
after: [SPEC-040]
prior_attempts: []
created: 2026-04-14
---

# JSON keys sorted alphabetically in the viewer

## Problem

When a tool returns a JSON object, the keys are displayed in whatever order
the server sent them. This makes it hard to visually scan repeated responses,
and when a developer saves tool output and diffs it across runs (e.g. in git),
key reordering causes noisy diffs even when values haven't changed.

Sorting keys alphabetically at render time makes the viewer output deterministic
and easier to read.

## Requirements

- [ ] R1: When `highlightJSON()` renders a JSON object, keys are sorted
  alphabetically (case-insensitive, ascending) before rendering.
- [ ] R2: Sorting is applied recursively — nested objects have their keys
  sorted too.
- [ ] R3: JSON arrays preserve their original element order (arrays are
  ordered by definition; only object keys are sorted).
- [ ] R4: The raw captured JSON stored in the database is never modified —
  sorting is display-only.
- [ ] R5: Sorting applies consistently in all JSON viewers: Tool Browser
  response panel, traffic timeline REQUEST and RESPONSE panels.

## Acceptance Criteria

- [ ] AC 1: `{"z": 1, "a": 2, "m": 3}` renders as `a`, `m`, `z` (alphabetical).
- [ ] AC 2: Nested objects have their keys sorted too.
- [ ] AC 3: Arrays render in original order.
- [ ] AC 4: The raw JSON stored in `data-raw` / capture store is unmodified.
- [ ] AC 5: `ui_layout_test.go` contains a test verifying that `highlightJSON`
  produces keys in sorted order for a mixed-key input object.
- [ ] AC 6: `go test -race -count=1 -timeout 5m ./...` passes.
- [ ] AC 7: `go vet ./...` passes.
- [ ] AC 8: `go build ./...` passes.

## Context

- Implementation: `highlightJSON()` in `internal/web/ui/index.html`. This
  function takes a raw JSON string and returns an HTML string of `.json-line`
  elements. The sort must happen after JSON.parse() and before the line-by-line
  render walk.
- Test file: `internal/web/ui_layout_test.go`

## Notes for the Agent

- Vanilla JS only: `var`, `.then()`, no `async/await`, no `let`/`const`.
- `JSON.parse()` already handles the parsing step — after parsing, walk the
  resulting object tree and sort keys before rendering. A recursive helper
  function is appropriate.
- Case-insensitive sort: `a.localeCompare(b, undefined, {sensitivity: 'base'})`.
- Do NOT sort before storing `data-raw` — raw must remain unsorted.
- Do NOT use `JSON.stringify(parsed, Object.keys(parsed).sort(), ...)` as a
  shortcut — it does not recurse and breaks nested objects.

## Out of Scope

- Sorting keys in the captured / stored JSON
- User-configurable sort order (reverse, by value, etc.)
- Sorting array elements
