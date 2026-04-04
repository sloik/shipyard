---
id: UX-001
priority: 3
type: main
status: draft
after: [BUG-001]
created: 2026-04-04
---

# UX-001: Dashboard Design Pass

## Problem

The Phase 0 dashboard is functional but minimal. For Shipyard to be taken seriously as "DevTools for MCP," the UI needs polish: better layout, clearer information hierarchy, and a design that feels professional.

## Scope

This spec covers visual polish, NOT new features. No tool invocation, no replay — those are SPEC-002 and SPEC-003.

## Design Process

1. Create a Pencil design file (`.pen`) with the dashboard layout
2. Define component patterns: traffic row, detail panel, filter bar, status indicator
3. Implement the approved design in `index.html`

## Key Improvements

### Header
- Connection status with server count and uptime
- Clear branding without clutter

### Traffic Timeline
- Alternating row backgrounds for readability
- Relative timestamps ("2s ago") with absolute on hover
- Method column with monospace font and icon prefix (→ for request, ← for response)
- Latency color bands: green (<100ms), yellow (100-1000ms), red (>1000ms)
- Status column: request/ok/error with distinct icons

### Detail Panel
- Split view: request on left, matched response on right (if correlated)
- JSON syntax highlighting (from BUG-001)
- Copy-to-clipboard button for payloads
- Metadata row: message ID, timestamp, latency, server name

### Filter Bar
- Dropdown for server (populated from actual traffic)
- Dropdown or autocomplete for method
- Direction toggle (all / client→server / server→client)
- Clear filters button

### Empty State
- Helpful getting-started message with example command

## Target Files

- `internal/web/ui/index.html` — complete rewrite of HTML/CSS/JS
- Pencil design file for reference

## Acceptance Criteria

- [ ] AC-1: Pencil design created and approved before implementation
- [ ] AC-2: Traffic rows have alternating backgrounds and clear visual hierarchy
- [ ] AC-3: Relative timestamps with absolute tooltip
- [ ] AC-4: Detail panel shows request + matched response side by side
- [ ] AC-5: Copy-to-clipboard on JSON payloads
- [ ] AC-6: Server filter populated from actual traffic data
- [ ] AC-7: Direction toggle works
- [ ] AC-8: No external dependencies — all CSS/JS inline in single HTML file
