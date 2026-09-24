---
id: SPEC-BUG-171
template_version: 3
priority: 1
layer: 3
type: bugfix
status: ready
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
parent: UX-002
created: 2026-09-24
---

# Segmented toggle "All" option filters every row out (Traffic + History)

## Problem

Found during the UX-002 acceptance-criteria audit (AC-8, "Direction toggle
(all / client→server / server→client) works").

Clicking **All** in the Traffic view's Direction toggle empties the table.
Runtime-confirmed in headless Chromium against a current `-tags server` build
with the `teststubchild` server and 13 captured entries:

| Action                     | Rows shown | Scroll info             |
|----------------------------|-----------:|-------------------------|
| initial load               | 13         | Showing 13 of 13        |
| click **All** (already on) | **0**      | Showing 0 of 11         |
| click **REQ →**            | 5          | Showing 0 of 11         |
| click **All**              | **0**      | Showing 0 of 13         |
| click **← RES**            | 6          | Showing 0 of 13         |
| click **Clear**            | 13         | Showing 13 of 13        |

The only way back to an unfiltered table is the **Clear** button.

### Root cause

`handleSegToggle()` in `internal/web/ui/ds.js` emits:

```js
detail: { value: target.getAttribute('data-value') || target.textContent.trim() }
```

The "All" buttons use `data-value=""`. Empty string is falsy, so the event
value falls back to the button label `"All"`. The Traffic handler then sets
`dirFilter = "All"` and keeps only items whose `direction === "All"` — none.

The same markup (`data-value=""` on an "All" button) exists on three toggles
in `internal/web/ui/index.html`:

- `#dir-toggle` (Traffic direction) — client-side filter → 0 rows
- `#history-dir-toggle` (History direction) — sends `direction=All` to the API
- `#history-time-toggle` (History time range) — "All" becomes `"All"` instead of
  "no time bound"

### Secondary defect (same code path)

Because the direction filter is applied client-side *after* paging,
`loadPage()` advances `timelineOffset` by the **filtered** item count and
prints `Showing <timelineOffset> of <timelineTotal>` using the unfiltered
server total. With a direction filter active the footer reads e.g.
"Showing 0 of 11 entries" while 5 rows are visible.

## Reproduction

1. `CGO_ENABLED=0 go build -tags server -o build/shipyard ./cmd/shipyard`
   and `go build -o build/stubchild ./internal/teststubchild`.
2. Launch via the smoke harness (`test/smoke/lib/harness.mjs`), generate a few
   `POST /api/tools/call` requests against the stub `echo` tool.
3. Open the Traffic view, click **All** in the Direction toggle.
4. **Actual:** table is empty. **Expected:** all rows are shown.

## Requirements

- [ ] R1: A segmented-toggle button with an explicitly empty `data-value`
  emits `""` as its value (use `hasAttribute('data-value')`, not truthiness).
- [ ] R2: Traffic Direction "All" shows every row, including after switching
  from REQ/RES back to All.
- [ ] R3: History Direction "All" and History time-range "All" apply no
  direction / no time bound (no `direction=All` or NaN window reaches the API).
- [ ] R4: With a Traffic direction filter active, the "Showing N of M" footer
  and paging offset are consistent with the rows actually displayed and do
  not stall infinite scroll.

## Acceptance Criteria

- [ ] AC1: Headless check: after load, clicking All / REQ → / All / ← RES /
  All in `#dir-toggle` yields row counts N / req / N / res / N where N is the
  unfiltered count and req + res = N.
- [ ] AC2: Clicking History's direction "All" and time "All" after another
  option returns the unfiltered history list; no request carries
  `direction=All`.
- [ ] AC3: With REQ → active, the footer never reports fewer shown entries
  than rows visible.
- [ ] AC4: A regression test covers `handleSegToggle` emitting `""` for
  `data-value=""` (UI layout/unit test or smoke script).
- [ ] AC5: `go test ./...`, `go vet ./...`, `go build ./...` pass.

## Out of Scope

- Moving the direction filter server-side (acceptable if it is the simplest
  way to satisfy R4, but not required).
- Visual restyling of the toggle.

## Code Pointers

- `internal/web/ui/ds.js` — `handleSegToggle()` (~line 220)
- `internal/web/ui/index.html` — `#dir-toggle` (~126), `#history-time-toggle`
  (~321), `#history-dir-toggle` (~338); `dirToggle` change handler and
  `loadPage()` (~1910–2060); `historyDirToggle` handler (~3313)
