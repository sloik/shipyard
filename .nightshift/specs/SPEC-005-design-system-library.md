---
id: SPEC-005
priority: 1
type: main
status: done
after: [UX-002]
created: 2026-04-04
---

# SPEC-005: Design System Runtime Library

## Principle

**Every UI element on every screen comes from the design system library. Zero custom components in screens.** If a screen needs something that doesn't exist in the library, the library gets extended first — the screen never invents its own.

## Architecture

The design system is two files served by the Go HTTP server:

- `internal/web/ui/ds.css` — all tokens, all component classes, all states
- `internal/web/ui/ds.js` — interactive behavior (toggles, modals, toasts, copy-to-clipboard, theme switching, resize handles)

Both are `go:embed`'d and served at `/ds.css` and `/ds.js`. Every page includes:

```html
<link rel="stylesheet" href="/ds.css">
<script src="/ds.js" defer></script>
```

This is the ONE exception to the "all inline" rule from UX-002. The design system is a shared dependency, not page-specific code.

## Consumption API

Components are **CSS classes**. Screens are pure HTML that references these classes. No page writes its own styles for any design system component.

```html
<!-- Buttons -->
<button class="btn btn-primary"><span class="btn-icon">▶</span> Execute</button>
<button class="btn btn-default"><span class="btn-icon">⊘</span> Filter</button>
<button class="btn btn-danger">Delete</button>
<button class="btn btn-ghost">Copy</button>

<!-- Badge -->
<span class="badge badge-success"><span class="badge-dot"></span> 200 OK</span>

<!-- Direction -->
<span class="dir dir-req">→ REQ</span>
<span class="dir dir-res">← RES</span>

<!-- Input -->
<div class="input-group">
  <label class="input-label">Server</label>
  <div class="input input-default">
    <span class="input-icon">🔍</span>
    <input type="text" placeholder="All servers">
  </div>
</div>
```

JS is only for interactive components. Static components are pure CSS.

## Source of Truth

The `.pen` design file (`UX-002-dashboard-design.pen`) is the spec for every component's visual design. Implementation must match it exactly. When in doubt, read the `.pen` file via Pencil MCP tools.

All CSS variable values come from the `.pen` file's variable definitions. Do not invent colors, spacing, or typography — extract from the design.

## Design Tokens (ds.css — Part 1)

### Color Tokens

All colors are CSS custom properties with dark/light theme support via `[data-theme]` attribute and `prefers-color-scheme` fallback.

```css
:root, [data-theme="dark"] { /* dark is default */ }
[data-theme="light"] { /* light overrides */ }
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) { /* auto-detect */ }
}
```

**Backgrounds:** `--bg`, `--bg-surface`, `--bg-raised`, `--bg-inset`, `--bg-overlay`
**Text:** `--text-primary`, `--text-secondary`, `--text-muted`, `--text-link`, `--text-on-emphasis`
**Border:** `--border-default`, `--border-muted`, `--border-accent`
**Accent:** `--accent-fg`, `--accent-emphasis`, `--accent-subtle`
**Success:** `--success-fg`, `--success-emphasis`, `--success-subtle`
**Danger:** `--danger-fg`, `--danger-emphasis`, `--danger-subtle`
**Warning:** `--warning-fg`, `--warning-emphasis`, `--warning-subtle`
**Buttons:** `--btn-primary-bg`, `--btn-primary-hover`, `--btn-default-bg`, `--btn-default-hover`, `--btn-danger-bg`, `--btn-danger-hover`
**Input:** `--input-bg`, `--input-border`, `--input-focus-border`
**JSON:** `--json-key`, `--json-string`, `--json-number`, `--json-boolean`, `--json-bracket`
**Traffic:** `--traffic-req-bg`, `--traffic-req-fg`, `--traffic-res-bg`, `--traffic-res-fg`
**Rows:** `--row-alt`, `--row-hover`, `--row-selected`

### Typography Tokens

```css
--font-sans: 'Inter', system-ui, sans-serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
--font-size-xs: 10px;
--font-size-sm: 11px;
--font-size-base: 12px;
--font-size-md: 13px;
--font-size-lg: 14px;
--font-size-xl: 16px;
--font-size-2xl: 20px;
```

### Spacing & Radius Tokens

```css
--radius-s: 4px;
--radius-m: 6px;
--radius-l: 8px;
--radius-full: 100px;
--radius-scrollbar: 2px;
```

## Components (ds.css — Part 2)

### Component Index — All 68 Components

Every component listed below MUST be implemented. The class names are the contract — screens reference these classes.

#### 1. Buttons (6)

| Class | Pen Component | Description |
|---|---|---|
| `.btn.btn-primary` | Btn/Primary | Green fill, white text, icon + label |
| `.btn.btn-default` | Btn/Default | Outlined, border, icon + label |
| `.btn.btn-danger` | Btn/Danger | Red outlined, icon + label |
| `.btn.btn-ghost` | Btn/Ghost | No background, icon + label |
| `.btn.btn-copy` | Btn/Copy | Small outlined copy button |
| `.btn.btn-copied` | Btn/Copied | Green success state after copy |

Modifiers: `.btn-sm` (compact padding), `.btn-icon-only` (no label)

#### 2. Inputs (3)

| Class | Pen Component | Description |
|---|---|---|
| `.input.input-default` | Input/Default | Search input with icon |
| `.input.input-focused` | Input/Focused | Blue focus border (2px) |
| `.input-group` | InputGroup/Labeled | Label + field + optional chevron |

#### 3. Search (2)

| Class | Pen Component | Description |
|---|---|---|
| `.search-bar` | Search/Bar | Wide search with icon, placeholder, clear btn |
| `.search-bar.is-active` | Search/BarActive | Focused with result count + clear visible |

#### 4. Badges (6)

| Class | Pen Component | Description |
|---|---|---|
| `.badge.badge-success` | Badge/Success | Green dot + label |
| `.badge.badge-error` | Badge/Error | Red dot + label |
| `.badge.badge-warning` | Badge/Warning | Amber dot + label |
| `.badge.badge-info` | Badge/Info | Blue dot + label |
| `.badge.badge-neutral` | Badge/Neutral | Outlined, label only |
| `.badge.badge-crashed` | Badge/Crashed | Red fill, white text, X icon |

#### 5. Direction Badges (2)

| Class | Pen Component | Description |
|---|---|---|
| `.dir.dir-req` | Dir/Request | Blue bg, arrow-right, "REQ" |
| `.dir.dir-res` | Dir/Response | Green bg, arrow-left, "RES" |

#### 6. Status Indicators (3)

| Class | Pen Component | Description |
|---|---|---|
| `.status.status-online` | Status/Online | Green dot + "Connected" |
| `.status.status-offline` | Status/Offline | Red dot + "Disconnected" |
| `.status.status-idle` | Status/Idle | Amber dot + "Starting..." |

#### 7. WebSocket Indicators (3)

| Class | Pen Component | Description |
|---|---|---|
| `.ws-indicator.ws-live` | Indicator/Live | Green dot + "Live" |
| `.ws-indicator.ws-disconnected` | Indicator/Disconnected | Red dot + "Disconnected" |
| `.ws-indicator.ws-reconnecting` | Indicator/Reconnecting | Amber dot + "Reconnecting..." |

#### 8. Navigation (4)

| Class | Pen Component | Description |
|---|---|---|
| `.app-bar` | Header/AppBar | Full header with logo, tabs, indicators |
| `.tab.tab-default` | Tab/Default | Inactive tab with icon + label |
| `.tab.tab-active` | Tab/Active | Active with blue bottom border |
| `.tab.tab-count` | Tab/WithCount | Tab with count badge |

#### 9. Toggles (4)

| Class | Pen Component | Description |
|---|---|---|
| `.seg-toggle` | Toggle/Segmented | Container for segments |
| `.seg-toggle .seg-active` | Seg/Active | Blue filled active segment |
| `.seg-toggle .seg-inactive` | Seg/Inactive | Muted inactive segment |
| `.switch` / `.switch.is-on` | Switch/On, Switch/Off | Toggle switch with knob |

#### 10. Data Display (5)

| Class | Pen Component | Description |
|---|---|---|
| `.pill.pill-fast` | Pill/Latency/Fast | Green latency (<100ms) |
| `.pill.pill-moderate` | Pill/Latency/Moderate | Amber latency (100-500ms) |
| `.pill.pill-slow` | Pill/Latency/Slow | Red latency (>500ms) |
| `.pill.pill-timeout` | Pill/Latency/Timeout | Muted "—" for N/A |
| `.timestamp` | Timestamp/Relative | Clock icon + relative time |

#### 11. Code (4)

| Class | Pen Component | Description |
|---|---|---|
| `.code-block` | Code/Block | Block with header (lang + copy), body |
| `.code-inline` | Code/Inline | Inline code span |
| `.btn.btn-show-more` | Btn/ShowMore | Expand truncated content |
| `.btn.btn-show-less` | Btn/ShowLess | Collapse expanded content |

#### 12. Table (5)

| Class | Pen Component | Description |
|---|---|---|
| `.table-header` | Table/HeaderRow | Column headers with sort indicator |
| `.table-row` | Table/DataRow | Default data row |
| `.table-row.row-alt` | Table/DataRowAlt | Alternating background row |
| `.table-row.row-expanded` | Table/DataRowExpanded | Selected row with blue left border |
| `.table-row.row-ui` | Table/DataRowUI | UI-initiated marker |

#### 13. Row Controls (2)

| Class | Pen Component | Description |
|---|---|---|
| `.row-chevron` / `.row-chevron.is-expanded` | Chevron/Collapsed, Chevron/Expanded | Expand/collapse chevron |
| `.row-actions` | Table/RowActions | Replay + Edit & Replay hover buttons |

#### 14. Panels (2)

| Class | Pen Component | Description |
|---|---|---|
| `.split-view` | Panel/SplitView | Dual-pane request/response layout |
| `.diff-view` | Diff/SideBySide | Diff with line-added / line-removed |

#### 15. JSON Viewer (1)

| Class | Description |
|---|---|
| `.json-viewer` | Scrollable JSON panel with syntax highlighting via token classes (`.jt-key`, `.jt-string`, `.jt-number`, `.jt-boolean`, `.jt-bracket`) |

#### 16. JSON Controls (3)

| Class | Pen Component | Description |
|---|---|---|
| `.json-filter` | JSON/FilterBar | Search input for filtering JSON content |
| `.json-filter.panel-filter` | Per-panel variant | Compact filter above each panel |
| `.mode-toggle` | Toggle/TextJQ | Text/JQ mode switcher |

#### 17. Forms — Schema-Driven (7)

| Class | Pen Component | Description |
|---|---|---|
| `.field.field-text` | Field/Text | Labeled text input with help text |
| `.field.field-number` | Field/Number | Number input |
| `.field.field-boolean` | Field/Boolean | Switch + label |
| `.field.field-enum` | Field/Enum | Dropdown select |
| `.field.field-error` | Field/TextError | Error state with red border + message |
| `.field.field-array` | Field/Array | Repeating items with add/remove |
| `.field .field-required` | Required asterisk | Red asterisk on label |

#### 18. Feedback (5)

| Class | Pen Component | Description |
|---|---|---|
| `.empty-state` | State/Empty | Icon, title, description, optional CTA |
| `.toast.toast-success` | Toast/Success | Green check + message |
| `.toast.toast-error` | Toast/Error | Red alert + message |
| `.toast.toast-info` | Toast/Info | Blue info + message |
| `.spinner` | Spinner/Default | Loading icon + optional label |

#### 19. Overlays (2)

| Class | Pen Component | Description |
|---|---|---|
| `.modal` | Modal/Confirm | Overlay dialog with header, body, actions |
| `.tooltip` | Tooltip | Hover label with shadow |

#### 20. Pagination (3)

| Class | Pen Component | Description |
|---|---|---|
| `.pagination` | Pagination/Bar | Full pagination bar |
| `.page-num.is-active` | Page/Active | Blue filled current page |
| `.page-num` | Page/Default | Inactive page number |

#### 21. Server Cards (2)

| Class | Pen Component | Description |
|---|---|---|
| `.server-card` | Card/Server | Server with status, stats, actions |
| `.server-card.is-crashed` | Card/Server/Crashed | Red border, crash message, restart CTA |

#### 22. Settings (2)

| Class | Pen Component | Description |
|---|---|---|
| `.settings-section` | Settings/Section | Title + description + rows |
| `.settings-row` | Settings/Row | Label + help + control (input or toggle) |

#### 23. Tool List (4)

| Class | Pen Component | Description |
|---|---|---|
| `.tool-group` | ToolList/Group | Collapsible header with status + count |
| `.tool-item.is-active` | ToolList/ItemActive | Selected tool with accent bg |
| `.tool-item` | ToolList/ItemDefault | Default tool item |
| `.tool-item.has-conflict` | ToolList/ItemConflict | Warning + "also in" label |

#### 24. Onboarding (2)

| Class | Pen Component | Description |
|---|---|---|
| `.onboard-step` | Onboard/Step | Numbered step with code block |
| `.onboard-step.is-done` | Onboard/StepDone | Green checkmark, completed |

#### 25. Time Range (2)

| Class | Pen Component | Description |
|---|---|---|
| `.time-presets` | TimeRange/Presets | Segmented time range selector |
| `.time-custom` | TimeRange/Custom | From/To date inputs with calendar icons |

#### 26. Resize Handle (1)

| Class | Pen Component | Description |
|---|---|---|
| `.resize-handle` | Handle/Resize | Draggable grip bar for panel resizing |

## Interactive Behavior (ds.js)

### Theme Switching
- Read `data-theme` from `<html>`, default to system preference via `prefers-color-scheme`
- Toggle via `.theme-toggle` button
- Persist choice to `localStorage`

### Toast System
- `DS.toast(message, type)` — type: `success` | `error` | `info`
- Auto-dismiss after 3s, stack vertically at bottom-right
- Dismiss on click

### Modal
- `DS.modal(title, body, actions)` — returns Promise resolving to clicked action
- Escape key dismisses, backdrop click dismisses
- Focus trap inside modal

### Copy to Clipboard
- `[data-copy]` attribute on any element — copies `data-copy` value or sibling `.json-viewer` content
- Swaps button to `.btn-copied` state for 2s

### Segmented Toggle
- `.seg-toggle` — clicking a segment sets `.seg-active`, removes from siblings
- Dispatches `change` event with selected value

### Switch Toggle
- `.switch` — click toggles `.is-on` class
- Dispatches `change` event with boolean value

### Row Expand/Collapse
- `.row-chevron` — click toggles `.is-expanded` on the chevron and `.row-expanded` on the parent row
- Shows/hides sibling `.detail-panel`

### Resize Handle
- `.resize-handle` — mousedown initiates drag
- Resizes sibling panel height, clamped to min 100px / max 80vh
- `cursor: row-resize` on drag

### Tool Group Collapse
- `.tool-group` header click — toggles visibility of child `.tool-item` list
- Rotates chevron icon

### JSON Filter
- `.json-filter input` — filters JSON viewer content in real-time
- Text mode: highlights matching substrings
- JQ mode: evaluates JQ expression, shows filtered result
- Per-panel filters override combined filter when active

### Search Bar
- `.search-bar input` — shows clear button and result count when value is non-empty
- Clear button resets input and hides count

## Target Files

- `internal/web/ui/ds.css` — all tokens + all component styles (~68 components)
- `internal/web/ui/ds.js` — interactive behavior (~10 behaviors)
- `internal/web/server.go` — add routes for `/ds.css` and `/ds.js` via `go:embed`

## Acceptance Criteria

### Tokens
- [x] AC-1: All color tokens from the `.pen` file are CSS variables with dark/light values
- [x] AC-2: `prefers-color-scheme` auto-detection works
- [x] AC-3: `[data-theme="dark"]` / `[data-theme="light"]` manual override works
- [x] AC-4: Theme toggle persists to localStorage

### Components
- [x] AC-5: All 68 components are implemented as CSS classes
- [x] AC-6: Every component visually matches its `.pen` design counterpart
- [x] AC-7: Components use ONLY token variables — no hardcoded hex/rgb values
- [x] AC-8: Components work in both dark and light themes

### API Contract
- [x] AC-9: Screens can build any Phase 0-3 UI using only classes from ds.css
- [x] AC-10: No screen needs to define its own component styles
- [x] AC-11: Adding a new screen requires ZERO changes to ds.css (unless a new component type is needed, which triggers a design system extension first)

### Interactive
- [x] AC-12: Theme switching works (toggle + system preference)
- [x] AC-13: Toast system works (show, auto-dismiss, stack)
- [x] AC-14: Modal system works (show, actions, dismiss, focus trap)
- [x] AC-15: Copy-to-clipboard works with `.btn-copied` feedback
- [x] AC-16: Segmented toggles and switches dispatch change events
- [x] AC-17: Row expand/collapse works with chevron rotation
- [x] AC-18: Resize handle works with drag + min/max constraints
- [x] AC-19: JSON filter works in both Text and JQ modes
- [x] AC-20: Per-panel JSON filters override combined filter

### Integration
- [x] AC-21: `/ds.css` and `/ds.js` are served via go:embed
- [x] AC-22: `index.html` includes ds.css and ds.js, uses only design system classes
- [x] AC-23: No visual regression — existing Phase 0 UI looks identical after migration

## Design System Gate (from UX-002)

Before any future screen spec starts implementation, verify that every UI element it needs exists in ds.css. If a component is missing:

1. Extend the design system first (add component to `.pen` file)
2. Implement it in ds.css/ds.js
3. Only then build the screen

This is a blocker, not a nice-to-have.
