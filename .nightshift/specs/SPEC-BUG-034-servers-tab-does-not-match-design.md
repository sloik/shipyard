---
id: SPEC-BUG-034
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-13
---

# Servers tab visual rendering does not match UX-002 design

## Problem

The Servers tab (`#view-servers`) renders correctly in terms of functionality but does not
match the "Phase 3 — Server Dashboard" design in the UX-002 Pencil file (`t7hu7`). Five
structural areas are wrong.

## Root Cause Analysis

The server card rendering was implemented before the Phase 3 design was finalised. The
differences are structural (card section layout, header space-between, action icons) not
just cosmetic overrides.

## Exact Differences

### 1. Action bar — wrong padding, plain-text summary, missing Add Server button

**Is:** `padding:8px 16px`, single `<span id="servers-summary">` with plain text like
"3 online, 1 crashed, 19 tools"

**Should be:** `padding:12px 24px`, individual stat indicators with colored dot/icon +
label, plus an "Add Server" (primary) button beside "Auto-Import".

Design stat layout (from WZNfH):
- Green 8px dot + "N online" (success-fg color)
- Red 8px dot + "N crashed" (danger-fg color, only shown when crashed > 0)
- Wrench icon 12px + "N tools" (text-secondary color)
- Spacer (flex:1)
- "Auto-Import" button (btn-default, download icon)
- "Add Server" button (btn-primary, plus icon)

### 2. Card header — flat row instead of space-between with left/right groups

**Is:** `display:flex; align-items:center; gap:8px` — dot + name + tools pill all in
one flat row, no space-between.

**Should be:** `display:flex; align-items:center; justify-content:space-between;
padding:12px 16px; border-bottom:1px solid var(--border-muted)`:
- **Left group** (gap 8): status dot (8px circle) + server name
- **Right group**: tools pill OR crashed badge

Tools pill (healthy servers): wrench icon + "N tools", filled with `var(--bg-raised)`,
border `1px solid var(--border-default)`, border-radius full, padding `2px 8px`, gap 4.

Crashed badge (crashed servers): ✕ icon + "Crashed" text, filled with
`var(--danger-emphasis)`, color `var(--text-on-emphasis)`, border-radius full, padding
`2px 8px`, gap 4.

### 3. Card body — no distinct body section, missing icons, command block not full-width

**Is:** Everything in flat flex column inside `.server-card` which has `padding:16px`.

**Should be:** A distinct body `<div>` with `padding:16px; display:flex; flex-direction:column; gap:8px`:
- Command block: same styling but `width:100%; box-sizing:border-box` so it fills the body
- Stats row (gap 16): each stat is icon + label in a flex row (gap 4):
  - Uptime: timer icon (12px, text-muted) + "Uptime: Xh Ym"
  - Restarts: refresh-cw icon (12px, text-muted) + "N restarts"
- Crash banner (crashed only): circle-alert icon (14px, danger-fg) + message text,
  both in a `gap:8px` flex row inside the danger-subtle banner

### 4. Card actions — no top border, no padding, missing icons on buttons

**Is:** `.server-actions { display:flex; gap:8px }` — no border, no padding.

**Should be:** `display:flex; gap:8px; padding:8px 16px 12px 16px; border-top:1px solid var(--border-muted)`.

Button icons (from design):
- Stop button: square icon (12px)
- Restart button: rotate-ccw icon (12px)
- Start/Restart (crashed): play icon (12px), btn-primary style

### 5. Card-level padding must be removed (padding moves to per-section)

**Is:** `.server-card { padding:16px }` — uniform padding across the whole card.

**Should be:** `.server-card { padding:0 }` — each section (header, body, actions) has
its own padding as described above. The card itself has no padding.

### 6. Grid padding

**Is:** `padding:16px` on `#servers-grid`.

**Should be:** `padding:24px`.

## Requirements

- [ ] R1: Action bar has `padding:12px 24px` and shows online/crashed/tools as
  individual stat indicators with colored dots/icons.
- [ ] R2: Action bar has an "Add Server" (primary) button beside "Auto-Import".
- [ ] R3: Server card header uses `justify-content:space-between` with name group on
  left and tools pill (or crashed badge) on right, with `padding:12px 16px` and bottom border.
- [ ] R4: Server card body is a distinct section with `padding:16px; gap:8px` and stat
  rows include icon + label.
- [ ] R5: Server card actions section has a top border and `padding:8px 16px 12px 16px`.
- [ ] R6: Action buttons have icons (square for Stop, rotate-ccw for Restart, play for Start).
- [ ] R7: `.server-card` has no card-level padding (`padding:0`).
- [ ] R8: `#servers-grid` has `padding:24px`.

## Acceptance Criteria

- [ ] AC 1: `#servers-action-bar` has `padding:12px 24px` in `index.html`.
- [ ] AC 2: The action bar stat area renders individual inline indicators (not plain text)
  via JS — green dot for online count, red dot for crashed, icon for tools count.
- [ ] AC 3: "Add Server" button (btn-primary) exists in the action bar HTML.
- [ ] AC 4: `renderServerCards` header row has `justify-content:space-between`.
- [ ] AC 5: Tools pill renders on the RIGHT side of the header (inside right group).
- [ ] AC 6: Crashed badge uses danger-emphasis background and text-on-emphasis color.
- [ ] AC 7: Body section div wraps command + stats, with `padding:16px` and `gap:8px`.
- [ ] AC 8: Stats render with icons (timer/refresh-cw) not bare text.
- [ ] AC 9: `.server-actions` in `ds.css` has `border-top:1px solid var(--border-muted)`
  and `padding:8px 16px 12px 16px`.
- [ ] AC 10: `.server-card` in `ds.css` has `padding:0`.
- [ ] AC 11: `#servers-grid` has `padding:24px`.
- [ ] AC 12: `.shipyard-dev/verify-spec-034.sh` exits 0.
- [ ] AC 13: `go test ./...` passes.
- [ ] AC 14: `go vet ./...` passes.
- [ ] AC 15: `go build ./...` passes.

## Verification Script

Create `.shipyard-dev/verify-spec-034.sh` that checks:
1. `#servers-action-bar` contains `padding:12px 24px`
2. "Add Server" btn-primary exists in the action bar HTML
3. `renderServerCards` contains `justify-content:space-between`
4. `renderServerCards` renders tools pill in right group (check for `justify-content:space-between` AND tools pill rendered inside a separate right group, i.e. two separate div wrappers in the header)
5. `.server-card` in `ds.css` has `padding:0` (not `padding:16px`)
6. `.server-actions` in `ds.css` has `border-top`
7. `#servers-grid` has `padding:24px`
8. `go test ./...`

## Context

### Target files

- `internal/web/ui/index.html`:
  - Line 509: change action bar `padding:8px 16px` → `padding:12px 24px`
  - Line 510: replace `<span id="servers-summary">` with individual stat elements:
    ```html
    <span id="servers-stat-online" style="display:none; align-items:center; gap:6px; font-size:var(--font-size-sm);">
      <span style="width:8px; height:8px; border-radius:50%; background:var(--success-fg); flex-shrink:0;"></span>
      <span id="servers-stat-online-lbl" style="color:var(--success-fg); font-weight:500;"></span>
    </span>
    <span id="servers-stat-crashed" style="display:none; align-items:center; gap:6px; font-size:var(--font-size-sm);">
      <span style="width:8px; height:8px; border-radius:50%; background:var(--danger-fg); flex-shrink:0;"></span>
      <span id="servers-stat-crashed-lbl" style="color:var(--danger-fg); font-weight:500;"></span>
    </span>
    <span id="servers-stat-tools" style="display:none; align-items:center; gap:6px; font-size:var(--font-size-sm);">
      <span style="font-size:12px; color:var(--text-muted);">⚙</span>
      <span id="servers-stat-tools-lbl" style="color:var(--text-secondary);"></span>
    </span>
    ```
    Use Unicode wrench (⚙ U+2699) or the existing icon font pattern `&#128295;` — whichever is already used in the codebase. Keep it simple.
  - Line 511-512: add "Add Server" btn-primary after auto-import button, wire it to `openAddServerModal()`
  - Line 528: change `padding:16px` → `padding:24px` on `#servers-grid`
  - `loadServers()` function (~line 2718): update summary logic to populate the new stat elements instead of setting plain text
  - `renderServerCards()` function (~line 2742): restructure card HTML (see below)

- `internal/web/ui/ds.css` (`23. Server Cards` section, ~line 1578):
  - `.server-card`: change `padding:16px` → `padding:0`
  - `.server-card .server-actions`: add `border-top:1px solid var(--border-muted)` and `padding:8px 16px 12px 16px`

### Card HTML structure (target)

```html
<div class="server-card [is-crashed|is-restarting]" data-server="NAME">
  <!-- Header -->
  <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-bottom:1px solid var(--border-muted);">
    <!-- Left: dot + name -->
    <div style="display:flex; align-items:center; gap:8px;">
      <span style="width:8px; height:8px; border-radius:50%; background:var(--success-fg); flex-shrink:0;"></span>
      <span class="server-name">NAME</span>
    </div>
    <!-- Right: tools pill (healthy) or crashed badge -->
    <!-- Healthy: -->
    <div style="display:flex; align-items:center; gap:4px; background:var(--bg-raised); border:1px solid var(--border-default); border-radius:100px; padding:2px 8px; font-size:var(--font-size-sm); color:var(--text-secondary);">
      &#128295; N tools
    </div>
    <!-- Crashed: -->
    <div style="display:flex; align-items:center; gap:4px; background:var(--danger-emphasis); border-radius:100px; padding:2px 8px; font-size:var(--font-size-sm); color:var(--text-on-emphasis); font-weight:600;">
      &#10005; Crashed
    </div>
  </div>

  <!-- Body -->
  <div style="display:flex; flex-direction:column; gap:8px; padding:16px;">
    <!-- Command -->
    <div style="font-family:var(--font-mono); font-size:var(--font-size-sm); color:var(--text-secondary); background:var(--bg-inset); padding:6px 10px; border-radius:var(--radius-s); width:100%; box-sizing:border-box; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
      COMMAND
    </div>
    <!-- Crash banner (crashed only) -->
    <div style="display:flex; align-items:center; gap:8px; background:var(--danger-subtle); padding:8px 12px; border-radius:var(--radius-s);">
      &#9888; ERROR_MESSAGE
    </div>
    <!-- Stats row -->
    <div style="display:flex; gap:16px;">
      <span style="display:flex; align-items:center; gap:4px; font-size:var(--font-size-sm); color:var(--text-secondary);">
        &#9202; Uptime: Xh Ym
      </span>
      <span style="display:flex; align-items:center; gap:4px; font-size:var(--font-size-sm); color:var(--text-secondary);">
        &#8635; N restarts
      </span>
    </div>
  </div>

  <!-- Actions -->
  <div class="server-actions">
    <button class="btn btn-default btn-sm">&#9635; Stop</button>
    <button class="btn btn-default btn-sm">&#8635; Restart</button>
  </div>
</div>
```

Use `&#9635;` (square) for Stop icon, `&#8635;` (counterclockwise arrow) for Restart,
`&#9654;` (right-pointing triangle) for Start/restart from crashed.

### Notes on icon strategy

The codebase uses HTML entities throughout (e.g. `&#128295;` for wrench, `&#9654;` for
execute). Stick to the same pattern — no SVG, no external icon fonts in JS-generated HTML.

### `loadServers()` stat display

Replace the single `serversSummary.textContent = summary` with:
```javascript
// Show online stat
var onlineStat = document.getElementById('servers-stat-online');
var onlineLbl  = document.getElementById('servers-stat-online-lbl');
if (onlineStat && onlineLbl) {
  onlineLbl.textContent = online + ' online';
  onlineStat.style.display = online > 0 ? 'inline-flex' : 'none';
}
// Show crashed stat
var crashedStat = document.getElementById('servers-stat-crashed');
var crashedLbl  = document.getElementById('servers-stat-crashed-lbl');
if (crashedStat && crashedLbl) {
  crashedLbl.textContent = crashed + ' crashed';
  crashedStat.style.display = crashed > 0 ? 'inline-flex' : 'none';
}
// Show tools stat
var toolsStat = document.getElementById('servers-stat-tools');
var toolsLbl  = document.getElementById('servers-stat-tools-lbl');
if (toolsStat && toolsLbl) {
  toolsLbl.textContent = totalTools + ' tools';
  toolsStat.style.display = totalTools > 0 ? 'inline-flex' : 'none';
}
```

The existing `servers-summary` span can be removed from HTML or left hidden — remove it.

## Out of Scope

- Conflicts count in action bar (requires separate data source, separate spec)
- Gateway policy toggles on server cards (separate bug SPEC-BUG-035)
- Restarting card state changes
- "Add Server" modal content (already implemented, just wire the new button)

## Gap Protocol

- Research-acceptable gaps: exact HTML entity codes to use for icons (wrench, timer,
  restart) — use whatever is closest to what the rest of the codebase uses
- Stop-immediately gaps: cards not rendering; action bar missing; go test failures
- Max research subagents before stopping: 0
