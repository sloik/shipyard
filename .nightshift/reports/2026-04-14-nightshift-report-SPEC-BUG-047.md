# Nightshift Report — SPEC-BUG-047

**Date:** 2026-04-14
**Spec:** SPEC-BUG-047 — Navigation tabs missing Lucide icons
**Status:** done
**Result:** All 9 AC green, 1 iteration

## What was done

Added inline Lucide SVG icons to the four main navigation tabs in `internal/web/ui/index.html`:

- Timeline: `activity` icon (polyline path)
- Tools: `wrench` icon (path)
- History: `history` icon (three paths)
- Servers: `server` icon (two rects + two lines)

Tokens and Settings tabs left as text-only per spec (out of scope).

## Key findings

- The `.tab` CSS class in `ds.css` already had `display:inline-flex; align-items:center; gap:6px` — no CSS changes needed.
- Using `stroke="currentColor"` on each SVG means icon color inherits from the element's `color` CSS property automatically. `.tab-active` sets `color: var(--text-primary)`, `.tab-default` inherits `color: var(--text-muted)` from `.tab` — so AC 6 and AC 7 are satisfied without additional JS or class logic.
- The tab nav is static HTML, not JS-generated, so inline SVG is the correct pattern (consistent with the server card icons which are JS helper functions for dynamic content).

## Build verification

- `go vet ./...` — clean
- `go build ./...` — clean
- `go test ./internal/web/...` — ok (2.465s)

## Files changed

- `internal/web/ui/index.html` — added SVG icons to four tab anchors
- `.nightshift/specs/SPEC-BUG-047-tabs-missing-lucide-icons.md` — status: done, all AC/R boxes checked, root cause filled in
- `.nightshift/reports/2026-04-14-nightshift-report-SPEC-BUG-047.md` — this file
