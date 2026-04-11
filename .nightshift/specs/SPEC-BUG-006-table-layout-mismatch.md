---
id: SPEC-BUG-006
priority: 1
type: bug
status: done
after: [SPEC-006]
created: 2026-04-05
---

# SPEC-BUG-006: Traffic Table Layout Does Not Match Design

## Screenshots

- Actual: `docs/phase_1_feedback/003-table-layout.png`
- Design: Phase 0 — Traffic Timeline frame in `UX-002-dashboard-design.pen` (node `rRx2E`)

## Problems

Comparing the live implementation against the .pen design, the following mismatches are visible:

### 1. Direction column — all rows show "REQ →"

Every row displays a blue "REQ →" badge regardless of traffic direction. The design shows:
- **Requests:** blue `REQ →` badge
- **Responses:** green `← RES` badge

The implementation renders all entries as requests. Either the `direction` field from the API is not differentiating, or the `dirBadge()` function isn't matching response patterns correctly.

### 2. No alternating row backgrounds

The design uses `$row-alt` background on every other row for visual rhythm. The implementation shows all rows with identical dark backgrounds. The CSS class `.row-alt` exists in ds.css but may not be applied correctly.

### 3. Column widths don't match design proportions

Design column widths (from .pen frame):
- Time: **90px** fixed
- Dir: **55px** fixed
- Server: **110px** fixed
- Method: **fill** (flex grow)
- Status: **90px** fixed
- Latency: **70px** fixed (right-aligned)
- Chevron: **14px** fixed

The implementation appears to use roughly equal column widths, making the table feel cramped on the left (Time, Dir) and too wide on the right (Status, Latency).

### 4. Status badge shows "request" as a status

Some rows display `● request` (blue) as their status value. The design only defines these status states:
- `● ok` — green (`$success-fg`)
- `● error` — red (`$danger-fg`)
- `● pending` — blue/info (`$info`)

"request" is not a valid status — it appears the capture layer may be storing the direction as the status for request-type messages, or the UI is falling through to a default badge.

### 5. Latency pill styling

Some latency pills show "5ms" with what appears to be the correct green/fast styling, but "577ms" uses the same green instead of the moderate/yellow tier. Design thresholds:
- Fast (< 100ms): green (`$success-fg` / `$success-subtle`)
- Moderate (100-999ms): yellow (`$warning-fg` / `$warning-subtle`)
- Slow (1000-4999ms): red (`$danger-fg` / `$danger-subtle`)
- Timeout (5000ms+): gray/muted

### 6. Header row styling

The table header (TIME, DIR, SERVER, METHOD, STATUS, LATENCY) should have:
- Uppercase text, `$font-size-xs` (10px), `$text-muted` color
- Bottom border separator
- Same column widths as data rows

The implementation header looks correct in styling but column widths don't align with data rows.

### 7. Row padding

Design specifies consistent row padding of `[8, 16]` (8px vertical, 16px horizontal). Rows in the implementation may have different padding values.

## Acceptance Criteria

- [ ] AC-1: Request rows show blue "REQ →", response rows show green "← RES"
- [ ] AC-2: Alternating rows use `$row-alt` background
- [ ] AC-3: Column widths match design: Time 90px, Dir 55px, Server 110px, Method fill, Status 90px, Latency 70px, Chevron 14px
- [ ] AC-4: Status badges show only valid states (ok, error, pending) — not "request"
- [ ] AC-5: Latency pill colors use correct threshold tiers (green/yellow/red/gray)
- [ ] AC-6: Row padding is [8, 16] consistently
- [ ] AC-7: Table header column widths align with data row column widths

## Target Files

- `internal/web/ui/index.html` — `renderRow()`, `dirBadge()`, `statusBadge()`, `latencyPill()`
- `internal/web/ui/ds.css` — `.table-header`, `.table-row`, `[data-col]` widths, `.row-alt`
- `internal/capture/store.go` — verify `direction` and `status` field values
