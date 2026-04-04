---
id: UX-002
priority: 2
type: main
status: in-progress
supersedes: UX-001
after: [BUG-001, SPEC-001]
created: 2026-04-04
---

# UX-002: Dashboard Design — Pencil Source of Truth

## Principle

**The Pencil design file is the spec.** All dashboard UI must match `UX-002-dashboard-design.pen` exactly. No implementation detail is invented outside the design — if it's not in the `.pen` file, it doesn't get built. If there's a discrepancy between the design and the implementation, the design wins.

## Design File

**Location:** `.nightshift/specs/UX-002-dashboard-design.pen`

This file is the single source of truth for all Shipyard web dashboard UI. It is maintained in Pencil and covers all phases.

## Scope — Full Dashboard (All Phases)

The design covers all four phases of the dashboard, designed together for visual consistency:

### Phase 0: Traffic Timeline
- Header with branding, connection status, server count
- Filter bar: server dropdown, method filter, direction toggle, clear button
- Traffic table: timestamp, direction, server, method, status badge, latency
- Row expansion: detail panel with full JSON payload (syntax highlighted)
- Correlated view: request + matched response side by side
- Copy-to-clipboard on payloads
- Pagination
- Empty state with getting-started guidance

### Phase 1: Tool Browser + Invocation (SPEC-002)
- Sidebar: tool list grouped by server, search/filter
- Tool detail: name, description, input schema
- Schema-driven form: auto-generated fields from JSON Schema
- Execute button + response display
- Execution appears in traffic timeline

### Phase 2: Replay + History (SPEC-003)
- Replay button on any traffic entry
- Edit-and-replay: opens form with pre-filled arguments
- Search bar: free text across payloads, method, server
- Time range filter
- Response diff: side-by-side comparison of two executions

### Phase 3: Multi-Server Dashboard (SPEC-004)
- Server status cards: name, status indicator (green/red/yellow), tool count
- Health monitoring: uptime, last crash, restart count
- Per-server controls: start/stop/restart buttons
- Server config display: command, args, env

## Implementation Rules

1. **Read the .pen file** via Pencil MCP tools before writing any HTML/CSS/JS
2. **Match the design pixel-for-pixel** — colors, spacing, typography, layout
3. **No external dependencies** — all CSS/JS inline in `internal/web/ui/index.html`
4. **JSON syntax highlighting** uses the existing `highlightJSON()` from BUG-001
5. **Dark theme** — the design defines the color palette; implementation uses CSS variables
6. **Responsive** — dashboard should work at 1024px+ width (no mobile needed)

## Target Files

- `internal/web/ui/index.html` — full implementation of the design
- Additional HTML files if the design requires multiple pages (unlikely for Phase 0)

## Acceptance Criteria

- [ ] AC-1: Design file (`UX-002-dashboard-design.pen`) is complete and covers all four phases
- [ ] AC-2: Phase 0 traffic timeline matches the design exactly
- [ ] AC-3: Traffic rows have alternating backgrounds and clear visual hierarchy
- [ ] AC-4: Relative timestamps ("2s ago") with absolute on hover
- [ ] AC-5: Detail panel shows request + matched response side by side with JSON highlighting
- [ ] AC-6: Copy-to-clipboard button on JSON payloads
- [ ] AC-7: Server filter populated dynamically from actual traffic data
- [ ] AC-8: Direction toggle (all / client→server / server→client) works
- [ ] AC-9: Empty state matches design
- [ ] AC-10: No visual element exists in the implementation that isn't in the design
- [ ] AC-11: No external dependencies — all CSS/JS inline in single HTML file
- [ ] AC-12: Phase 1-3 designs are present in the .pen file (implementation deferred to their respective specs)

## Workflow

1. Design all phases in Pencil (this session)
2. Implement Phase 0 UI to match the design
3. When SPEC-002/003/004 are built, their UI implementation must also match this design
