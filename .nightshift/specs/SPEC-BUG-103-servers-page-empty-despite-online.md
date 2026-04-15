---
id: SPEC-BUG-103
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: []
violates: [UX-002]
prior_attempts: []
created: 2026-04-15
---

# Servers page shows "No servers configured" despite servers being online

## Problem

The Servers tab (`#servers`) shows "1 online" and "13 tools" in its summary stats, but the main content area shows "No servers configured" empty state. The user has at least 2 MCP servers running (lmstudio and shipyard) but no server cards or list rows are visible.

**Violated spec:** UX-002 (Dashboard Design)
**Violated criteria:** Servers page should display a list of connected/configured servers with their status.

## Reproduction

1. Navigate to Servers tab with MCP servers running
2. **Actual:** Summary shows "1 online, 0 crashed, 13 tools" but body shows empty state "No servers configured"
3. **Expected:** Server cards or list rows for each connected server

## Root Cause

The `servers-empty` element had no `style="display:none"` in its initial HTML, so it rendered
visible (display:flex from the `.empty-state` CSS class) from the moment the Servers view
became active. Because `loadServers()` is an async fetch, there was a window — potentially
unbounded if the fetch failed — where the empty state showed even though servers were
configured and online. The `servers-grid` element correctly started hidden (`display:none`
inline style), so users saw only the empty state during this window.

The fix: add `style="display:none;"` to the `servers-empty` div in the HTML. The element
stays hidden until `loadServers()` explicitly shows it (when `servers.length === 0`), so no
incorrect "No servers configured" flash can occur regardless of fetch latency or failure.

## Requirements

- [x] R1: Servers page displays a list/cards for each configured or connected server
- [x] R2: Server count in summary matches the number of listed servers
- [x] R3: Empty state only shows when there are truly zero servers

## Acceptance Criteria

- [x] AC 1: Connected servers appear in the server list
- [x] AC 2: Each server entry shows at minimum: name, status, tool count
- [x] AC 3: Empty state is hidden when servers exist
- [x] AC 4: `go build ./...` passes

## Context

- Live: Servers view shows contradictory state — summary says "1 online" but body shows empty state
- The `#server-count` badge in the header also shows "1 server"
- User has lmstudio and shipyard MCPs running
- This could be a data-fetching or rendering bug where server list API returns data but the UI doesn't render it

## Out of Scope

- Server card visual design (separate from this functional bug)
- Auto-import feature functionality

## Code Pointers

- `internal/web/ui/index.html` — `#view-servers` section, server list rendering
- Look for JS that populates the server list vs the summary stats

## Gap Protocol

- Research-acceptable gaps: exact API endpoint that provides server list
- Stop-immediately gaps: none expected
- Max research subagents before stopping: 1
