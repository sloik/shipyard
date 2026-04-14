---
id: SPEC-006
template_version: 2
priority: 6
layer: 2
type: main
status: ready
children:
  - SPEC-006-001
  - SPEC-006-002
  - SPEC-006-003
implementation_order:
  - SPEC-006-001
  - SPEC-006-002
  - SPEC-006-003
after: [SPEC-004]
prior_attempts: []
created: 2026-04-06
---

# Phase 4: Advanced — Sessions, Profiling, Schema Detection

## Problem

Developers debugging MCP integrations need to record and replay full sessions (not just individual requests), understand latency patterns across tools and servers, and be alerted when MCP server schemas change unexpectedly. These capabilities turn Shipyard from a debugging tool into a developer workflow tool.

## Goal

Three features that deepen Shipyard's value beyond request-level inspection:

1. **Session Recording & Export** — VCR-like cassettes for CI and reproducibility
2. **Latency Profiling** — per-tool/server performance stats with percentiles
3. **Schema Change Detection** — alert when `tools/list` responses change

## Feature 1: Session Recording & Export

Record all traffic during a session, name it, and export as a portable cassette file (JSON) for CI replay or sharing.

### Key Features

- **Record/Stop controls** — red "Record Session" button with optional session name
- **Session list** — table showing status (recording/complete/partial), name, server, request count, duration, started time, file size
- **Export** — download individual sessions as JSON cassette files; "Export All" for bulk
- **Replay** — re-execute a recorded session's requests against the current server
- **Delete** — remove sessions with confirmation

### Acceptance Criteria

- [ ] AC-1: "Record Session" button starts capture; "Stop" button ends it
- [ ] AC-2: Session list shows all sessions with status indicators (recording=red, complete=green, partial=yellow)
- [ ] AC-3: Sessions persist in SQLite across restarts
- [ ] AC-4: Export produces a self-contained JSON file with all request/response pairs and metadata
- [ ] AC-5: Exported cassettes can be replayed via `POST /api/sessions/{id}/replay`
- [ ] AC-6: Session can be filtered by server

## Feature 2: Latency Profiling

Aggregate latency statistics per tool and per server over configurable time ranges.

### Key Features

- **Summary cards** — total calls, avg latency, P95 latency, error rate (with delta from prior period)
- **Per-tool table** — tool name, server, call count, min/avg/P50/P95/max latency, error rate
- **Color-coded values** — green (<100ms), yellow (100-500ms), red (>500ms) for latency cells
- **Time range filter** — last hour, 24h, 7d, 30d, custom
- **Server filter** — all servers or specific server

### Acceptance Criteria

- [ ] AC-7: Stats cards display aggregate metrics for selected time range
- [ ] AC-8: Latency table shows all tools sorted by P95 desc (configurable)
- [ ] AC-9: Latency values use semantic colors based on thresholds
- [ ] AC-10: Time range and server filters update all data in real-time
- [ ] AC-11: Stats computed from existing SQLite traffic history (no new data collection)

## Feature 3: Schema Change Detection

Detect when an MCP server's `tools/list` response changes and alert the developer.

### Key Features

- **Alert banner** — warning banner when schema change detected, showing which server, what changed, when
- **Change history sidebar** — chronological list of all detected changes with timestamps and badges (+N added, -N removed, ~N modified)
- **Schema diff detail** — for each change event, show added tools (with full schema), removed tools, and modified parameters
- **Acknowledge** — dismiss alerts for reviewed changes

### Acceptance Criteria

- [ ] AC-12: Shipyard periodically polls `tools/list` (configurable interval, default 60s)
- [ ] AC-13: Schema changes produce a dismissible alert banner
- [ ] AC-14: Change history persists in SQLite with full before/after snapshots
- [ ] AC-15: Diff view shows added tools in green, removed in red, modified parameters highlighted
- [ ] AC-16: WebSocket pushes schema change events to the dashboard in real-time

## New Navigation

Phase 4 adds two new tabs to the main navigation:
- **Sessions** — session recording and management (tab 5)
- **Profiling** — latency statistics dashboard (tab 6)

Schema Changes is accessible from:
- Alert banner (appears on any tab when schema changes)
- "Schema" tab or sub-navigation (tab 7, or accessible from Servers view)

## API Endpoints

### Sessions
- `POST /api/sessions/start` — start recording (body: `{name?, server?}`)
- `POST /api/sessions/{id}/stop` — stop recording
- `GET /api/sessions` — list sessions (query: `?server=&status=`)
- `GET /api/sessions/{id}` — get session detail with all requests
- `GET /api/sessions/{id}/export` — download cassette JSON
- `POST /api/sessions/{id}/replay` — replay session
- `DELETE /api/sessions/{id}` — delete session

### Profiling
- `GET /api/profiling/summary` — aggregate stats (query: `?range=24h&server=`)
- `GET /api/profiling/tools` — per-tool latency breakdown (query: `?range=&server=&sort=p95&order=desc`)

### Schema
- `GET /api/schema/changes` — list schema change events
- `GET /api/schema/changes/{id}` — get change detail with diff
- `POST /api/schema/changes/{id}/acknowledge` — acknowledge a change
- `GET /api/schema/current/{server}` — get current schema for a server

## Design

All screens designed in `UX-002-dashboard-design.pen`:
- **Phase 4 — Sessions** — session list with recording state, export actions
- **Phase 4 — Profiling** — stats cards + per-tool latency table with color coding
- **Phase 4 — Schema Changes** — alert banner, change history sidebar, schema diff detail

## Out of Scope

- Cassette format compatibility with other VCR tools (custom JSON format)
- Remote session sharing / cloud sync
- Alerting integrations (email, Slack, webhooks) for schema changes
- Custom latency threshold configuration (hardcoded green/yellow/red bands)
