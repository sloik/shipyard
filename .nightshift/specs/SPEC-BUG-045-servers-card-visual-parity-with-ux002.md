---
id: SPEC-BUG-045
template_version: 2
priority: 2
layer: 2
type: bugfix
status: ready
after: []
violates: [UX-002]
prior_attempts: [SPEC-BUG-034]
created: 2026-04-14
---

# Server cards still diverge from UX-002 design after BUG-034 fix

## Problem

SPEC-BUG-034 addressed the structural layout of the Servers tab (action bar stats, card
sections, grid padding). Those structural fixes landed, but a side-by-side comparison
of the live UI against the UX-002 Pencil file (`UX-002-dashboard-design.pen`, card-grid
frame `bP9gn`, components `YYMTJ` Card/Server and `NeSYZ` Card/Server/Crashed) reveals
**8 remaining visual discrepancies** — icons, stat formatting, color tokens, and one
spurious border that don't match the approved design.

These gaps are immediately visible when comparing the running app to the design.

## Root Cause Analysis

BUG-034 focused on structural/layout fixes (section padding, justify-content, border
separators). It used Unicode HTML entities as a pragmatic icon strategy and rendered
stats as single-color spans. The UX-002 design system specifies Lucide icons via
`icon_font` nodes, a dual-color label/value stat pattern using `$text-muted` and
`$text-primary`/`$success-fg`/`$danger-fg` tokens, and tools pills without a border
stroke. These content-level details were outside BUG-034's structural scope.

## Exact Differences

All color references below use design system token names from `UX-002-dashboard-design.pen`.
Dark-mode resolved values are in parentheses for clarity.

### 1. Icons — Unicode entities instead of Lucide icon font

**Is:** All icons rendered as Unicode HTML entities:
- Tools pill: `&#128295;` (wrench emoji)
- Stop button: `&#9635;` (square)
- Restart button: `&#8635;` (counterclockwise arrow)
- Start button: `&#9654;` (right-pointing triangle)
- Crash banner: `&#9888;` (warning sign)
- Crashed badge: `&#10005;` (multiplication sign)
- Uptime stat: `&#9202;` (timer icon prefix)
- Restarts stat: `&#8635;` (refresh icon prefix)

**Should be (from design components `YYMTJ` and `NeSYZ`):** Lucide `icon_font` nodes
rendered as separate elements at specified sizes and colors:
- Tools pill: `wrench` 12×12px, fill `$text-muted` (#8b949e)
- Stop button: `square` 12×12px, fill `$text-secondary` (#b1bac4)
- Restart button: `rotate-ccw` 12×12px, fill `$text-secondary` (#b1bac4)
- Start button (crashed): `play` 12×12px, fill `$text-on-emphasis` (#ffffff)
- Crash banner: `circle-alert` 14×14px, fill `$danger-fg` (#f85149)
- Crashed badge: `x` 10×10px, fill `$text-on-emphasis` (#ffffff)

**Note:** The design does NOT use icons for stats — it uses text labels ("Uptime:",
"Restarts:", "Last crash:"). The current `&#9202;` and `&#8635;` prefixes on stats
should be replaced with text labels.

### 2. Icon + text structure — inline concatenation instead of separate elements

**Is:** Icons and labels are concatenated as a single string inside one element:
```html
<div>&#128295; 8 tools</div>
<button>&#9635; Stop</button>
```

**Should be:** Separate icon element + text element with explicit gap, matching the
design component structure (e.g., tools pill node `9WXIN` has `gap: 4`, children:
`icon_font` + `text`):
```html
<div style="gap:4px;">
  <svg class="lucide" width="12" height="12">...</svg>
  <span>8 tools</span>
</div>
```

This is required for correct icon sizing — Unicode entities inherit text font-size and
can't be independently sized, but Lucide SVGs/icon-fonts have explicit width/height.

### 3. Stats formatting — single-color text instead of dual-color label/value

**Is:** Stats rendered as a single `<span>` with uniform `var(--text-secondary)` color:
```html
<span style="color:var(--text-secondary);">&#9202; Uptime: 2h 14m</span>
```

**Should be (from design node `buonI` scUptime):** Two separate text elements per stat
with different colors and weights:
```
"Uptime:" → $font-size-sm (11px), $text-muted (#8b949e), normal weight
"2h 14m"  → $font-size-sm (11px), $text-primary (#e6edf3), weight 500
```
```
"Restarts:" → $font-size-sm (11px), $text-muted (#8b949e), normal weight
"0"         → $font-size-sm (11px), $success-fg (#3fb950), weight 500
```

Each stat is in a frame with `gap: 4`. The stat row has `gap: 16`.

### 4. Restarts stat hidden when count is zero

**Is:** `if (s.restart_count > 0)` — restarts stat only shown when > 0.

**Should be:** Always visible. Design component `YYMTJ` shows "Restarts: 0" with value
in `$success-fg` (#3fb950). This is a data-completeness signal.

### 5. Tools pill has a spurious border

**Is (line 3313):** Tools pill rendered with `border:1px solid var(--border-default)`.

**Should be:** NO border. The design component `9WXIN` (scTools) has `fill: $surface-raised`
(#1c2128) and `cornerRadius: 100` but NO `stroke` property. The pill's visual separation
comes from its `$surface-raised` fill against the card's `$bg-surface` background — no
border needed.

BUG-034 added this border in its implementation notes, but it doesn't exist in the
approved Pencil design.

### 6. Crashed server stats show wrong labels

**Is:** Crashed cards use the same stat template as healthy cards (Uptime + Restarts,
both conditional).

**Should be (from design node `K4GuS` ccStats):**
- "Last crash:" label `$text-muted` + relative time value `$danger-fg` (#f85149), weight 500
- "Restarts:" label `$text-muted` + count value `$danger-fg` (#f85149), weight 500

No uptime stat for crashed servers — replaced by "Last crash:" stat.

### 7. Crash banner font size wrong

**Is (line 3329):** Crash banner uses `font-size:var(--font-size-sm)` (11px).

**Should be:** The crash message text node `4OtGY` (ccMsgTxt) specifies `fontSize: 12`
which maps to `$font-size-base` (12px), not `$font-size-sm` (11px).

### 8. Crash banner text does not wrap

**Is:** Error message rendered as inline text in a flex row with `align-items:center` —
long messages overflow or truncate.

**Should be:** Message text wraps within the banner. Design node `4OtGY` specifies
`textGrowth: "fixed-width"` with `width: "fill_container"` — the text fills available
width and wraps to multiple lines. The banner should use `align-items: flex-start` (not
center) so the icon aligns to the top when text wraps.

## Requirements

- [ ] R1: Replace all Unicode HTML entity icons with Lucide glyphs at the sizes and
  colors specified in UX-002 design components `YYMTJ` and `NeSYZ` (see §1).
- [ ] R2: Render each icon + label as separate elements (icon element with explicit
  width/height + text element) with the gap specified in the design (see §2).
- [ ] R3: Render each stat as two elements: label in `$text-muted` + value in the
  appropriate accent color, matching the design's dual-color pattern (see §3).
- [ ] R4: Always show "Restarts:" stat, even when count is 0 (value in `$success-fg`).
- [ ] R5: Remove `border` from the tools pill — only `fill: $surface-raised` and
  `border-radius: 100px`, no stroke (see §5).
- [ ] R6: Crashed server stats show "Last crash:" + relative time (in `$danger-fg`)
  instead of "Uptime:" (see §6).
- [ ] R7: Crash banner uses `$font-size-base` (12px) for message text, not
  `$font-size-sm` (11px) (see §7).
- [ ] R8: Crash banner error text wraps within the banner width, icon aligns to top
  (see §8).

## Acceptance Criteria

- [ ] AC 1: Tools pill contains a Lucide `wrench` SVG/icon (12×12px, `$text-muted`),
  not `&#128295;`.
- [ ] AC 2: Stop button contains Lucide `square` (12×12px), Restart contains
  `rotate-ccw` (12×12px), both in `$text-secondary`.
- [ ] AC 3: Crashed Restart button contains Lucide `play` (12×12px, `$text-on-emphasis`).
- [ ] AC 4: Crashed badge contains Lucide `x` (10×10px, `$text-on-emphasis`).
- [ ] AC 5: Crash banner contains Lucide `circle-alert` (14×14px, `$danger-fg`).
- [ ] AC 6: No Unicode entity icons (`&#128295;`, `&#9635;`, `&#8635;`, `&#9654;`,
  `&#9888;`, `&#10005;`, `&#9202;`) remain in `renderServerCards()` output.
- [ ] AC 7: Icons and text are separate DOM elements within a container with explicit
  gap, not concatenated strings in a single text node.
- [ ] AC 8: Each stat contains two `<span>` elements: label (`$text-muted`, normal weight)
  and value (accent color, weight 500).
- [ ] AC 9: Healthy server uptime value uses `$text-primary` (#e6edf3).
- [ ] AC 10: Healthy server restarts value "0" uses `$success-fg` (#3fb950).
- [ ] AC 11: "Restarts: 0" is visible on a healthy server card (not conditionally hidden).
- [ ] AC 12: Tools pill has NO `border` property — only background fill and border-radius.
- [ ] AC 13: Crashed server card shows "Last crash: Xs ago" stat with value in `$danger-fg`.
- [ ] AC 14: Crashed server restarts value uses `$danger-fg` (#f85149).
- [ ] AC 15: Crash banner message text has `font-size: var(--font-size-base)` (12px).
- [ ] AC 16: Crash banner text wraps to a second line when the message string exceeds
  ~40 characters (roughly the card width at 380px min-width).
- [ ] AC 17: `go test ./...` passes.
- [ ] AC 18: `go vet ./...` passes.
- [ ] AC 19: `go build ./...` passes.

## Verified: What already matches the design

The following were verified against design system tokens and are NOT gaps:

- **Server name font-size:** `.server-name` uses `var(--font-size-lg)` = 14px, matching
  design `fontSize: 14`. ✅
- **Crashed card border:** Child server cards use `class="server-card is-crashed"` (no
  inline border override), and CSS `.server-card.is-crashed { border-color: var(--danger-fg) }`
  applies correctly. ✅
- **Card border-radius:** `var(--radius-l)` = 8px, matching design `cornerRadius: 8`. ✅
- **Card background:** `var(--bg-surface)` = #161b22, matching design `fill: $surface`. ✅
- **Header padding:** `12px 16px` with bottom border `$border-muted`. ✅
- **Body padding:** `16px` with `gap: 8px`. ✅
- **Actions padding:** `8px 16px 12px 16px` with top border `$border-muted`. ✅
- **Command block:** `$font-mono`, `$font-size-sm`, `$text-secondary`, `$bg-inset`,
  padding `6px 10px`, `$radius-s`. ✅
- **Grid padding:** `24px`. ✅
- **Grid gap:** `16px`. ✅
- **btn-primary color:** `var(--btn-primary-bg)` = #238636, matching design `$success-emphasis`. ✅

## Context

### Design system token mapping

These are the design system variables from `UX-002-dashboard-design.pen` with their
`ds.css` CSS variable equivalents:

| Token | CSS Variable | Dark value | Used in |
|-------|-------------|------------|---------|
| `$text-muted` | `var(--text-muted)` | #8b949e | Stat labels, tools pill icon |
| `$text-primary` | `var(--text-primary)` | #e6edf3 | Uptime value, server name |
| `$text-secondary` | `var(--text-secondary)` | #b1bac4 | Tools pill text, button icons/labels |
| `$text-on-emphasis` | `var(--text-on-emphasis)` | #ffffff | Crashed badge, primary button text |
| `$success-fg` | `var(--success-fg)` | #3fb950 | Restarts value (healthy), status dot |
| `$danger-fg` | `var(--danger-fg)` | #f85149 | All crashed values, crash banner |
| `$danger-emphasis` | `var(--danger-emphasis)` | #da3633 | Crashed badge background |
| `$danger-subtle` | `var(--danger-subtle)` | #f8514926 | Crash banner background |
| `$surface-raised` | `var(--bg-raised)` | #1c2128 | Tools pill background (NO border) |
| `$btn-default-bg` | `var(--btn-default-bg)` | #21262d | Default button background |
| `$btn-primary-bg` | `var(--btn-primary-bg)` | #238636 | Primary button background |
| `$border-default` | `var(--border-default)` | #30363d | Card border, button border |
| `$border-muted` | `var(--border-muted)` | #21262d | Section dividers |
| `$font-size-sm` | `var(--font-size-sm)` | 11px | Stats, pill text, command |
| `$font-size-base` | `var(--font-size-base)` | 12px | Button text, crash banner text |
| `$font-size-lg` | `var(--font-size-lg)` | 14px | Server name |
| `$radius-s` | `var(--radius-s)` | 4px | Command block, crash banner |
| `$radius-m` | `var(--radius-m)` | 6px | Buttons |
| `$radius-l` | `var(--radius-l)` | 8px | Card |

### Target files

- `internal/web/ui/index.html`:
  - `renderServerCards()` (~line 3299): replace Unicode entities with Lucide SVGs/icons;
    restructure into separate icon + text elements; split stats into label + value spans;
    remove tools pill border; add "Last crash:" stat for crashed state; fix crash banner
    font size and text wrapping.
  - Check `<head>` section for existing Lucide loading — grep for `lucide`.

- `internal/web/ui/ds.css`:
  - No CSS changes needed for server cards — all changes are in the JS-generated HTML.
  - `.server-name` font-size is already correct (`var(--font-size-lg)` = 14px).

- `internal/web/ui_layout_test.go`:
  - May have assertions about card HTML structure — check and update if needed.

### Lucide icon strategy

Check the existing codebase for how Lucide icons are used. Grep `index.html` and `ds.js`
for `lucide`, `svg`, or `data-lucide`. Follow the existing pattern. If none exists:
- Simplest: inline SVGs from https://lucide.dev (6 icons needed: `wrench`, `square`,
  `rotate-ccw`, `play`, `circle-alert`, `x`)
- Each is a single `<svg>` element with `width`, `height`, `stroke`, and `stroke-width`
  attributes — lightweight and self-contained

### Design reference

- Pencil file: `.nightshift/specs/UX-002-dashboard-design.pen`
- Card/Server component: node `YYMTJ` (reusable, 3 sections: header/body/actions)
- Card/Server/Crashed component: node `NeSYZ` (reusable, red border variant)
- Card grid (in-context with 4 cards): node `bP9gn`
- Full page (Phase 3 — Server Dashboard): node `t7hu7`
- Action bar: node `WZNfH`

## Scenarios

1. User opens Servers tab with 2 healthy servers → each card shows server name at
   `$font-size-lg` (14px), Lucide wrench icon (12px) in borderless tools pill with
   `$surface-raised` fill, "Uptime:" in `$text-muted` + value in `$text-primary`,
   "Restarts: 0" in `$text-muted` + "0" in `$success-fg` → matches UX-002 Card/Server
   component `YYMTJ`.

2. User has a crashed server → card border is `$danger-fg`, header shows red dot +
   "Crashed" badge (Lucide `x` 10px, `$danger-emphasis` bg), body shows crash banner
   with Lucide `circle-alert` 14px and wrapped message text at `$font-size-base`,
   stats show "Last crash: 12s ago" + "Restarts: 5" both with values in `$danger-fg`,
   action has green Restart button with Lucide `play` 12px → matches UX-002
   Card/Server/Crashed component `NeSYZ`.

3. User has a mix of healthy and crashed servers → all icons are consistent Lucide
   glyphs with explicit sizing, no Unicode entities visible anywhere, tools pills have
   no border, stats use dual-color label/value pattern → pixel-level match with `bP9gn`
   card grid.

## Out of Scope

- Action bar stat indicators (colored dots match design intent, not changing)
- Conflicts count in action bar (separate data source, not in card design)
- Gateway-disabled card state (SPEC-BUG-035)
- Restarting card state (SPEC-BUG-027)
- "Add Server" modal content
- Responsive grid breakpoints (grid layout matches design intent)
- Light mode (design is dark-mode-first; light mode values exist in tokens but are
  not being audited in this spec)

## Research Hints

- Files to study: `internal/web/ui/index.html` (renderServerCards ~L3299),
  `internal/web/ui/ds.css` (~L1599 server card section, ~L50 CSS variables)
- Patterns to look for: existing Lucide icon usage anywhere in index.html or ds.js;
  how other tabs render icons (tool browser may already use SVGs)
- Cortex tags: servers, ui, design-parity, lucide, UX-002
- DevKB: N/A (HTML/CSS work)

## Gap Protocol

- Research-acceptable gaps: exact Lucide icon markup pattern (inline SVG vs icon font —
  check existing usage first); `last_crash` field availability in API response (may need
  server-side addition)
- Stop-immediately gaps: Lucide not loadable and no fallback strategy; `go test` failures;
  API doesn't expose last-crash timestamp (would need separate spec)
- Max research subagents before stopping: 1

## Notes for the Agent

- BUG-034 established the card section structure (header/body/actions with borders and
  padding). This spec preserves that structure — only changes content within sections.
- **Use CSS variable names**, not hardcoded hex values. Every color in the design maps
  to a CSS variable already defined in `ds.css` (see token mapping table above). The
  implementation should reference `var(--text-muted)` not `#8b949e`.
- The `last_crash` field may or may not exist in the API response. Check
  `internal/web/server.go` for the `ServerInfo` struct. If the field doesn't exist,
  compute it from `uptime_ms` or add it as a simple server-side change.
- For crash banner text wrapping, change the text element from inline to a `<span>` with
  `flex: 1; word-wrap: break-word;` or similar, and change the parent from
  `align-items:center` to `align-items:flex-start` so the icon stays at the top.
- The tools pill border removal is a single deletion — remove
  `border:1px solid var(--border-default);` from the tools pill inline style on line 3313.
- `ui_layout_test.go` may have assertions about card HTML structure — check and update
  if any assertions reference Unicode entities or inline border on the tools pill.
