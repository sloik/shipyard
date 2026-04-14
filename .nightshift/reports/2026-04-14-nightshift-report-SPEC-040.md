# Nightshift Report — SPEC-040

**Date:** 2026-04-14
**Spec:** SPEC-040 — JSON viewer line numbers per row
**Agent:** Claude Sonnet 4.6 (subagent)
**Duration:** ~15 min
**Status:** COMPLETE ✅

---

## Summary Stats

| Metric | Value |
|--------|-------|
| Files changed | 2 |
| Lines added | +18 CSS, +61 Go test |
| Lines removed | -5 CSS |
| Build errors | 0 |
| Test failures | 0 (new test passes) |
| Pre-existing failures | 2 data races (unrelated packages) |
| Review cycles | 0 |
| Fix iterations | 0 |

---

## Files Changed

1. **`internal/web/ui/ds.css`** — 3 CSS rule adjustments:
   - `.json-viewer`: `padding: 12px` → `padding: 12px 12px 12px 0` (left-0 per spec)
   - `.json-line`: added `gap: 12px` (replaces old `padding-right: 12px` on `.ln`), added `margin-bottom: 2px`
   - `.json-line .ln`: `width/min-width: 32px` → `24px`, added `max-width: 24px`, removed `padding-right: 12px`

2. **`internal/web/ui_layout_test.go`** — Added `TestSPEC040_JSONViewerLineNumbers` (61 lines)
   - Reads embedded `index.html` and `ds.css`
   - Verifies JS emits `<span class="ln">` with `(i + 1)` counter
   - Verifies CSS has `--text-muted`, `gap: 12px`, `width: 24px`, `max-width: 24px`, `align-items: flex-start`, `padding: 12px 12px 12px 0`, `margin-bottom: 2px`

**Note:** `index.html` was NOT changed — the JS already had the correct line-number generation (`highlightJSON` with `<span class="ln">' + (i + 1)`) from prior specs.

---

## Test Results

```
go build ./...      → PASS (exit 0)
go vet ./...        → PASS (exit 0)
go test ./internal/web/... -race -count=1 -timeout 5m → PASS (10.5s)
  TestSPEC040_JSONViewerLineNumbers → PASS
```

Pre-existing failures (not caused by SPEC-040):
- `internal/proxy: TestChildInputWriter_WriteLineRetriesAfterNewlineFailure` — data race in proxy_more_test.go:77 (present on clean main)
- `cmd/shipyard: TestRunProxy_HeadlessTrue_DoesNotCallDesktop` — data race in desktop_test.go:225 (present on clean main)

---

## AC Checklist

| AC | Description | Status |
|----|-------------|--------|
| AC 1 | JSON response panel renders a line number for each logical JSON line | ✅ |
| AC 2 | Line numbers use `--text-muted` colour, right-aligned, monospace | ✅ |
| AC 3 | Gap between number cell and content is 12px | ✅ |
| AC 4 | Number column is 24px wide (fixed) | ✅ |
| AC 5 | Continuation visual lines show a 24px blank spacer (flex layout) | ✅ |
| AC 6 | Row gap 2px; padding-left 0 | ✅ |
| AC 7 | `ui_layout_test.go` test with incrementing line-number verification | ✅ |
| AC 8 | `go test -race` passes | ✅ (for SPEC-040 packages) |
| AC 9 | `go vet ./...` passes | ✅ |
| AC 10 | `go build ./...` passes | ✅ |

---

## Discoveries

### Pre-existing state (important context)
The spec description implies this was a greenfield implementation, but previous specs (SPEC-039 or earlier) had already added:
- `.json-line` flex row structure
- `<span class="ln">` with `(i + 1)` counter in `highlightJSON`
- `<span class="lc">` for content

SPEC-040 was therefore a CSS adjustment spec, not a JS implementation spec. The only JS-level work was confirming no changes were needed. This explains the small diff.

### Gap implementation choice
The 12px gap between `.ln` and `.lc` was previously implemented as `padding-right: 12px` on `.ln`, which put padding INSIDE the number cell (reducing number text area to 20px out of 32px). SPEC-040 corrected this by:
1. Moving the gap to `gap: 12px` on the flex container (`.json-line`)
2. Removing `padding-right` from `.ln`
3. Making `.ln` a clean 24px box for the number text itself

This is semantically more correct: the gap is between items, not inside an item.

### Diff viewer isolation
The diff viewer at lines 2752-2762 also uses `.json-line` class without `.ln`/`.lc` children. The `gap: 12px` and `margin-bottom: 2px` changes apply there too, but have no negative effect (single-child flex items are unaffected by gap).

### Pre-existing data races
Two data races exist on clean `main` (verified via `git stash`):
- `internal/proxy/proxy_more_test.go:77` — failSecondWriteCloser race
- `cmd/shipyard/desktop_test.go:225` — cleanup race

These should be logged as BUG specs if not already tracked.

---

## Pattern Notes

**Pattern: CSS gap vs padding for flex item spacing**
When a flex item (`.ln`) needs a fixed width AND a gap to the next sibling, use `gap` on the flex CONTAINER rather than padding on the item. Padding shrinks the item's content area; gap is clean space between items.

**Pattern: CSS-only specs can masquerade as JS specs**
If a spec says "implement X in JS", grep first — it may already exist. SPEC-040 required no JS changes despite describing JS behavior. Always grep before writing.

---

Generated: 2026-04-14
