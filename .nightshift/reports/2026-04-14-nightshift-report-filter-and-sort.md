# Nightshift Report — JSON Filter + Key Sort

**Date:** 2026-04-14
**Session:** filter-and-sort
**Specs processed:** SPEC-BUG-044, SPEC-041, SPEC-042
**Commits:** 2 (d7f84c5, 0e64a31)
**Outcome:** All specs completed, all tests pass

---

## SPEC-BUG-044 — Text filter matches line-number digits

### AC Checklist

- [x] AC 1: `.lc` content used for matching, not parent `.json-line` textContent
- [x] AC 2: Matching lines visible; non-matching hidden
- [x] AC 3: Ancestor structural lines remain visible when a descendant matches (backward indent-walk via `getLineIndent()`)
- [x] AC 4: Clearing filter restores all lines
- [x] AC 5: Works in all filter contexts (Tool Browser + timeline panels) — same `filterJsonLines` function used everywhere
- [x] AC 6: `ui_layout_test.go` test: `TestSPECBUG044_FilterUsesLCNotParentTextContent` passes — verifies `.querySelector('.lc')` used, parent textContent not used, clear-query branch present, `getLineIndent` referenced
- [x] AC 7–9: `go test -race`, `go vet`, `go build` all pass

### Files Changed

- `internal/web/ui/index.html`: rewrote `filterJsonLines()` to use `.lc` child; added `getLineIndent()` helper; backward ancestor walk to keep structural context
- `internal/web/ui_layout_test.go`: added `TestSPECBUG044_FilterUsesLCNotParentTextContent`

### Key Design

`filterJsonLines` now has three phases:
1. Check each `.lc` child's `textContent` for the query
2. For each matched line, walk backward to find ancestor lines with less indentation — mark them visible
3. Apply visibility to all lines

The ancestor walk uses `getLineIndent()` which reads leading spaces from `.lc.textContent`. When a match at indent=4 is found, the walk finds lines with indent=2 and indent=0 and keeps them visible.

---

## SPEC-041 — JQ filter engine (client-side)

### AC Checklist

- [x] AC 1: `.foo` on `{"foo":1}` produces `1` — `jqEval('.foo', {foo:1})` → `{ok:true, value:1}`
- [x] AC 2: Nested path `.foo.bar` — multi-step tokeniser handles chained key segments
- [x] AC 3: Invalid expression shows inline "jq error: ..." message in viewer (not blank)
- [x] AC 4: Clearing input restores original highlighted content via `highlightJSON(rawJson)`
- [x] AC 5: JQ → Text mode switch restores original content from `data-raw-json`
- [x] AC 6: Evaluation is debounced — `debounce(fn, 200)` wraps all filter `input` listeners
- [x] AC 7: `ui_layout_test.go` tests: `TestSPEC041_JqEvalFunctionExists` verifies function exists with ok/error shape, `data-raw-json` stored on viewers, debounce used
- [x] AC 8–10: `go test -race`, `go vet`, `go build` all pass

### Files Changed

- `internal/web/ui/index.html`:
  - Added `debounce(fn, ms)` helper
  - Added `jqEval(expr, data)` — tokenises jq-like expression, supports `.`, `.foo`, `.foo.bar`, `.arr[]`, `.[N]`
  - Added `applyJqToViewer(viewer, expr)` — reads `data-raw-json`, evaluates, renders result or inline error
  - Added `getActiveMode(filterEl)` — reads active button from mode toggle
  - Updated `wireFilterInputs()` — all inputs debounced, mode-aware (text vs jq)
  - Updated `trafficBody` mode toggle handler — switches placeholder, restores/evaluates
  - Updated `toolModeToggle` handler — same
  - Updated `toolResponseBody()` — stores `data-raw-json`, resets mode to text on new response
  - Updated `renderDetailPanel()` — embeds `data-raw-json` attribute on json-viewer elements

### Implementation Notes

Used a minimal embedded jq evaluator instead of a WASM library. This avoids any network dependency, CDN risk, or WASM loading complexity. The evaluator handles the 90% case (path expressions) with < 100 lines of vanilla JS. Array iteration returns the array itself (most useful for the display purpose). Complex jq programs (pipes, filters, functions) are out of scope per the spec.

---

## SPEC-042 — JSON keys sorted alphabetically in viewer

### AC Checklist

- [x] AC 1: `{"z":1,"a":2,"m":3}` renders as `a`, `m`, `z`
- [x] AC 2: Nested objects have sorted keys — `sortKeysRecursive` recurses into object values
- [x] AC 3: Arrays render in original order — `Array.isArray()` check preserves order, only recurses into elements
- [x] AC 4: `data-raw-json` holds unsorted original — stored before `highlightJSON` renders (which sorts)
- [x] AC 5: `ui_layout_test.go` tests: `TestSPEC042_HighlightJSONSortsKeysAlphabetically` verifies `sortKeysRecursive` exists, uses `localeCompare`, is recursive, checks `Array.isArray`, and is called from `highlightJSON`
- [x] AC 6–8: `go test -race`, `go vet`, `go build` all pass

### Files Changed

- `internal/web/ui/index.html`:
  - Added `sortKeysRecursive(obj)` — case-insensitive `localeCompare` sort, recursive for nested objects, array-preserving
  - Updated `highlightJSON()` — calls `sortKeysRecursive(obj)` after `expandJSONStrings`, before `JSON.stringify`

### Key Design

The sort happens entirely in `highlightJSON` — the display path. The `data-raw-json` attribute (from SPEC-041) stores the pre-sort string, so jq evaluation operates on the original structure. The `toolResponseBody` stores `str` (unsorted) before calling `highlightJSON(str)` (which sorts). The `renderDetailPanel` embeds `escapeHtml(payload)` as `data-raw-json` before passing to `highlightJSON`.

---

## Test Results

```
ok  github.com/sloik/shipyard/cmd/shipyard          33.151s
ok  github.com/sloik/shipyard/cmd/shipyard-mcp      1.400s
ok  github.com/sloik/shipyard/internal/auth         10.321s
ok  github.com/sloik/shipyard/internal/capture      12.149s
ok  github.com/sloik/shipyard/internal/gateway       4.059s
ok  github.com/sloik/shipyard/internal/proxy        13.769s
ok  github.com/sloik/shipyard/internal/secrets       2.078s
ok  github.com/sloik/shipyard/internal/secrets/env   3.752s
ok  github.com/sloik/shipyard/internal/secrets/keychain 3.097s
ok  github.com/sloik/shipyard/internal/secrets/op    4.165s
ok  github.com/sloik/shipyard/internal/web          12.625s
```

All 11 test packages pass. Race detector clean. go vet clean. go build clean.

---

## Discoveries & Pattern Notes

### Pattern: Vanilla JS tokeniser for mini-DSL (no dependencies)

For simple expression languages (path notation, filter expressions), a character-by-character tokeniser in ~80 lines of vanilla JS is viable and produces zero runtime dependencies. Alternative WASM libs add CDN risk and async loading complexity that conflicts with the single-file convention.

### Pattern: data-raw-json attribute for reversible rendering

Storing the raw JSON as a data attribute on the viewer element makes mode switching (text/jq) trivially O(1) — no need to maintain a parallel JS variable. The attribute survives DOM re-use and is accessible from any function that has a reference to the element. Use `escapeHtml(str)` when embedding in HTML attributes.

### Pattern: Backward indent-walk for structural context preservation

When hiding non-matching lines, preserving structural context (brackets, braces) requires walking backward from each match to find ancestors at lower indentation. The key insight: only the *closest* ancestor at each indentation level matters — once indent reaches 0, stop. This is O(n²) worst case but fine for typical JSON (< 1000 lines).
