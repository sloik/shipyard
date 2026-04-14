# Nightshift Report — SPEC-BUG-045

**Date:** 2026-04-14
**Spec:** SPEC-BUG-045 — Server cards visual parity with UX-002
**Layer:** 2 | **Priority:** 2 | **Type:** bugfix
**Prior attempt:** SPEC-BUG-034 (structural layout fixed, content gaps remained)

---

## Summary

Completed all 8 requirements from SPEC-BUG-045. The server cards in the Servers tab now
match the UX-002 Pencil design (components YYMTJ Card/Server and NeSYZ Card/Server/Crashed)
with Lucide SVG icons, dual-color stat formatting, borderless tools pill, correct crash
banner font-size and text wrapping, and proper crashed-state stats.

**Stats:**
- Files changed: 2
- New tests added: 16
- Review cycles: 1 (one test assertion needed refinement for AC11)
- Build errors: 0

---

## Files Changed

| File | Change |
|------|--------|
| `internal/web/ui/index.html` | Rewrote `renderServerCards()` — 6 Lucide icon helper functions added, all Unicode entities replaced, dual-color stats, crash state stats, banner font/wrap fixes |
| `internal/web/ui_layout_test.go` | Added 16 new tests for all ACs (1–16) |

---

## Implementation Notes

### Icons (R1, R2)
Defined 6 inline SVG helper functions at the top of `renderServerCards()`:
- `iconWrench(size, color)` — Lucide wrench path
- `iconSquare(size, color)` — rect 18×18
- `iconRotateCcw(size, color)` — circle-with-arrow paths
- `iconPlay(size, color)` — polygon
- `iconCircleAlert(size, color)` — circle + two lines
- `iconX(size, color)` — two diagonal paths

Each is a vanilla JS function returning an SVG string with `fill="none"`, `stroke=color`,
`stroke-width="2"`, `stroke-linecap="round"`, `stroke-linejoin="round"`. No Lucide
library load needed — inline SVGs follow the existing codebase convention (no Lucide
CDN or npm package was present).

### last_crash field (R6)
`ServerInfo` struct does not expose a `last_crash_time` field. Used `uptime_ms` as
approximation: if `uptime_ms > 0` for a crashed server, derive relative time from it;
otherwise show "just now". This matches the spec's "research-acceptable gap" note.
No API changes required.

### AC11 test fix
The `TestSPECBUG045_RestartsAlwaysVisible` test initially matched `if (s.restart_count > 0)`
in the restarting-state branch (SPEC-BUG-027 code, unrelated). Fixed by scoping the
assertion to the `// Healthy state:` comment block only.

---

## Test Results

```
go test ./...
ok  github.com/sloik/shipyard/cmd/shipyard
ok  github.com/sloik/shipyard/internal/web

go vet ./...   — clean
go build ./... — clean
```

All 16 new SPEC-BUG-045 tests pass. All pre-existing tests continue to pass.

---

## AC Checklist

| AC | Description | Status |
|----|-------------|--------|
| AC 1 | Tools pill has Lucide wrench SVG (12×12), not `&#128295;` | ✅ |
| AC 2 | Stop = Lucide square (12×12), Restart = rotate-ccw (12×12), both `var(--text-secondary)` | ✅ |
| AC 3 | Crashed Restart = Lucide play (12×12, `var(--text-on-emphasis)`) | ✅ |
| AC 4 | Crashed badge = Lucide x (10×10, `var(--text-on-emphasis)`) | ✅ |
| AC 5 | Crash banner = Lucide circle-alert (14×14, `var(--danger-fg)`) | ✅ |
| AC 6 | No Unicode entity icons remain in `renderServerCards()` output | ✅ |
| AC 7 | Icons and text are separate DOM elements with explicit gap | ✅ |
| AC 8 | Each stat: label `var(--text-muted)` normal + value accent weight 500 | ✅ |
| AC 9 | Healthy uptime value uses `var(--text-primary)` | ✅ |
| AC 10 | Healthy restarts "0" value uses `var(--success-fg)` | ✅ |
| AC 11 | "Restarts: 0" always visible on healthy server cards | ✅ |
| AC 12 | Tools pill has NO border — only background fill and border-radius | ✅ |
| AC 13 | Crashed card shows "Last crash: Xs ago" with value in `var(--danger-fg)` | ✅ |
| AC 14 | Crashed restarts value uses `var(--danger-fg)` | ✅ |
| AC 15 | Crash banner text uses `font-size: var(--font-size-base)` (12px) | ✅ |
| AC 16 | Crash banner text wraps (`flex:1; word-wrap:break-word`), banner `align-items:flex-start` | ✅ |
| AC 17 | `go test ./...` passes | ✅ |
| AC 18 | `go vet ./...` passes | ✅ |
| AC 19 | `go build ./...` passes | ✅ |

All 19 ACs satisfied.

---

## Blockers / Discoveries

- **No `last_crash_time` in API**: `ServerInfo` struct has no dedicated last-crash timestamp.
  Used `uptime_ms` for approximation. This is documented as acceptable in the spec's gap
  protocol. If precise "last crash N seconds ago" is needed, a separate spec should add the
  field to `ServerInfo`.
- **No existing Lucide usage**: Zero existing SVG/Lucide usage in `index.html` — inline SVG
  helpers are the correct pattern for this codebase.
