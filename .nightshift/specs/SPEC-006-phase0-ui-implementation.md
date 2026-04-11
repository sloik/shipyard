---
id: SPEC-006
priority: 1
type: main
status: draft
after: [SPEC-001, SPEC-005, UX-002]
created: 2026-04-04
---

# SPEC-006: Phase 0 UI Implementation

## Principle

Rewrite `index.html` to consume the design system library (`ds.css` + `ds.js`) exclusively. Every element uses design system classes. Zero inline styles. All 4 navigation tabs are routable — Phase 1-3 are empty placeholder pages.

## Architecture

### Single-Page App with Hash Routing

The dashboard is a single `index.html` with client-side hash routing:

- `#/timeline` — Phase 0 Traffic Timeline (default)
- `#/tools` — Phase 1 Tool Browser (placeholder)
- `#/history` — Phase 2 Replay + History (placeholder)
- `#/servers` — Phase 3 Multi-Server Dashboard (placeholder)

Tab clicks update the hash. Each route shows/hides its content section. Browser back/forward works.

### File Structure

```
internal/web/ui/
├── ds.css          ← design system (SPEC-005, already exists)
├── ds.js           ← design system JS (SPEC-005, already exists)
└── index.html      ← rewritten to consume ds.css/ds.js
```

### Page Structure

```html
<!DOCTYPE html>
<html data-theme="dark">
<head>
  <link rel="stylesheet" href="/ds.css">
</head>
<body>
  <!-- App Bar (persistent) -->
  <header class="app-bar">...</header>

  <!-- Route: Timeline -->
  <main id="view-timeline" class="view">...</main>

  <!-- Route: Tools (placeholder) -->
  <main id="view-tools" class="view">...</main>

  <!-- Route: History (placeholder) -->
  <main id="view-history" class="view">...</main>

  <!-- Route: Servers (placeholder) -->
  <main id="view-servers" class="view">...</main>

  <script src="/ds.js"></script>
  <script>/* app logic: routing, WebSocket, API calls */</script>
</body>
</html>
```

## Screens to Implement

### 1. App Bar (persistent across all routes)

Uses design system class: `.app-bar`

- Shipyard logo (anchor icon) + wordmark
- 4 tabs: Timeline, Tools, History, Servers — clicking navigates via hash
- Active tab has `.tab-active` class, others `.tab-default`
- Right side: WebSocket indicator (`.ws-live` / `.ws-disconnected` / `.ws-reconnecting`), server count chip
- Tab active state updates on route change

### 2. Timeline View (`#/timeline`)

The main Phase 0 screen. Two states:

#### 2a. Empty State (no traffic)

- Centered `.empty-state` component
- Inbox icon, "No traffic yet" title
- Two `.onboard-step` cards with setup instructions
- WebSocket indicator shows "Waiting..." (`.ws-indicator.ws-reconnecting` or similar)
- No filter bar, no table, no pagination

#### 2b. Traffic State (has data)

**Filter Bar:**
- Server dropdown (`.input-group`) — populated dynamically from traffic data
- Method dropdown (`.input-group`) — populated dynamically
- Direction segmented toggle (`.seg-toggle`) — All / REQ → / ← RES
- Clear button (`.btn.btn-ghost`)

**Traffic Table:**
- Header row (`.table-header`) with columns: Time (90px), Dir (55px), Server (110px), Method (fill), Status (90px), Latency (70px), Expand chevron (24px)
- Data rows (`.table-row` / `.table-row.row-alt`) — alternating backgrounds
- Hover state (`.table-row:hover` uses `--row-hover`)
- Click to expand — row gets `.row-expanded`, chevron gets `.is-expanded`
- Direction badges (`.dir.dir-req` / `.dir.dir-res`)
- Status badges (`.badge.badge-success` / `.badge.badge-error` / `.badge.badge-info`)
- Latency pills (`.pill.pill-fast` / `.pill.pill-moderate` / `.pill.pill-slow` / `.pill.pill-timeout`)
- Timestamps (`.timestamp`) — relative with absolute in `title` attribute for hover tooltip
- Row chevron (`.row-chevron`) — dedicated column, not overlapping latency

**Detail Panel (inline, below expanded row):**
- Metadata bar: ID, absolute timestamp, latency
- Combined JSON filter (`.json-filter`) with Text/JQ mode toggle (`.mode-toggle`)
- Split view (`.split-view`):
  - REQUEST panel: per-panel filter (`.json-filter.panel-filter`), blue header, scrollable JSON body with syntax highlighting
  - RESPONSE panel: per-panel filter, green header, scrollable JSON body
  - Both have copy buttons (`.btn.btn-copy` → `.btn.btn-copied` on click)
  - Scrollbar on JSON body (fixed height, overflow-y: auto)
- Resize handle (`.resize-handle`) at the bottom

**Detail Panel — Pending State:**
- REQUEST panel shows JSON normally
- RESPONSE panel shows spinner (`.spinner`) + "Awaiting response..."

**Detail Panel — Error State:**
- REQUEST panel shows JSON normally
- RESPONSE header shows "RESPONSE — ERROR" with danger background
- RESPONSE body shows JSON-RPC error structure

**Pagination Footer:**
- `.pagination` component
- "Showing X–Y of Z entries"
- Prev/Next buttons + page numbers
- Fetches next page from `/api/traffic?page=N`

**Disconnected Banner:**
- When WebSocket drops: red banner below header with "Connection lost. Reconnecting..." + "Retry now" button
- WebSocket indicator switches to `.ws-disconnected`

### 3. Tools View (`#/tools`) — Placeholder

- `.empty-state` with wrench icon
- Title: "Tool Browser"
- Description: "Coming in Phase 1 — browse and invoke MCP tools"
- No CTA button

### 4. History View (`#/history`) — Placeholder

- `.empty-state` with history icon
- Title: "History & Replay"
- Description: "Coming in Phase 2 — search, replay, and compare executions"
- No CTA button

### 5. Servers View (`#/servers`) — Placeholder

- `.empty-state` with server icon
- Title: "Server Management"
- Description: "Coming in Phase 3 — monitor and control MCP servers"
- No CTA button

## Data Flow

### WebSocket (`/ws`)
- Connect on page load, auto-reconnect on disconnect (exponential backoff: 1s, 2s, 4s, max 30s)
- Incoming messages: new traffic entries → prepend to table, update filters
- Connection state drives WebSocket indicator

### REST API
- `GET /api/traffic?page=1&limit=25&server=X&method=Y&direction=Z` — paginated traffic list
- `GET /api/traffic/{id}` — single entry with full payload
- Server/method filter values extracted from traffic data (no separate endpoint)

### JSON Syntax Highlighting
- Reuse existing `highlightJSON()` function from SPEC-BUG-001
- Token classes: `.jt-key`, `.jt-string`, `.jt-number`, `.jt-boolean`, `.jt-bracket`
- Applied when rendering detail panel JSON

## Constraints

- ALL styling via ds.css classes — zero inline styles, zero `<style>` blocks
- ALL interactive behavior via ds.js or page-level `<script>` — ds.js handles component behavior, page script handles app logic (routing, API, WebSocket)
- No external dependencies — no frameworks, no CDN imports
- Must work at 1024px+ width
- `highlightJSON()` function can be defined in the page script (it's app logic, not a design system component)

## Target Files

- `internal/web/ui/index.html` — complete rewrite

## Acceptance Criteria

### Navigation
- [ ] AC-1: All 4 tabs (Timeline, Tools, History, Servers) are clickable and navigate to their view
- [ ] AC-2: Hash routing works — direct URL access to `#/tools` shows Tools view
- [ ] AC-3: Browser back/forward navigates between views
- [ ] AC-4: Active tab updates on route change

### Timeline — Empty State
- [ ] AC-5: When no traffic exists, shows empty state with onboarding steps
- [ ] AC-6: Empty state matches the Phase 0 — Empty State design

### Timeline — Traffic
- [ ] AC-7: Traffic table renders with correct columns and alternating row backgrounds
- [ ] AC-8: Rows show direction badges, status badges, latency pills, relative timestamps
- [ ] AC-9: Clicking a row expands it with detail panel, clicking again collapses
- [ ] AC-10: Detail panel shows split REQUEST/RESPONSE with syntax-highlighted JSON
- [ ] AC-11: JSON panels scroll with fixed height, not expand infinitely
- [ ] AC-12: Copy button copies JSON payload and shows "Copied!" feedback
- [ ] AC-13: Combined JSON filter searches both panels
- [ ] AC-14: Per-panel filters override combined filter
- [ ] AC-15: Resize handle adjusts detail panel height via drag

### Filters
- [ ] AC-16: Server dropdown populates from actual traffic data
- [ ] AC-17: Method dropdown populates from actual traffic data
- [ ] AC-18: Direction toggle filters rows (All / REQ / RES)
- [ ] AC-19: Clear button resets all filters
- [ ] AC-20: Filters update the API query and refresh the table

### WebSocket
- [ ] AC-21: New traffic appears in real-time via WebSocket
- [ ] AC-22: WebSocket indicator shows Live/Disconnected/Reconnecting
- [ ] AC-23: Auto-reconnect on disconnect with exponential backoff
- [ ] AC-24: Disconnected banner appears when WebSocket drops

### Pagination
- [ ] AC-25: Pagination shows correct page count and entry range
- [ ] AC-26: Prev/Next navigate pages via API
- [ ] AC-27: Active page is visually highlighted

### Placeholders
- [ ] AC-28: Tools, History, Servers views show placeholder empty states
- [ ] AC-29: Each placeholder has correct icon, title, and description

### Design System Compliance
- [ ] AC-30: Zero inline styles in index.html
- [ ] AC-31: Zero `<style>` blocks in index.html
- [ ] AC-32: All components use ds.css classes exclusively
- [ ] AC-33: Visual output matches the Phase 0 .pen design
