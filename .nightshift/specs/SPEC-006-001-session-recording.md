---
id: SPEC-006-001
template_version: 2
priority: 1
layer: 2
type: feature
status: done
parent: SPEC-006
after: [SPEC-004]
nfrs: [SPEC-NFR-001]
prior_attempts: []
created: 2026-04-14
---

# Session Recording & Export

## Problem

Developers debugging MCP integrations often need to capture full traffic sessions (not
just individual requests) so they can replay, share, or use them in CI. Currently
Shipyard captures traffic per-request but has no concept of a recording session that
groups related requests, persists them as a unit, and exports them as a portable file.

## Requirements

- [ ] R1: "Record Session" button starts a named recording session; "Stop" button ends it.
- [ ] R2: Session list table shows all sessions with status (recording / complete / partial),
  name, server, request count, duration, started time, and file size.
- [ ] R3: Sessions persist in a new SQLite table across Shipyard restarts.
- [ ] R4: Export produces a self-contained JSON cassette file containing all request/response
  pairs and session metadata.
- [ ] R5: Replay endpoint re-executes a recorded session's requests against the current server.
- [ ] R6: Delete endpoint removes a session with all its captured data.
- [ ] R7: Session list supports filtering by server.

## Acceptance Criteria

- [ ] AC 1: Clicking "Record Session" in the Sessions tab starts capture; a red recording
  indicator is visible; clicking "Stop" ends the session and updates status to "complete".
- [ ] AC 2: Session list renders columns: status (color-coded — recording=red,
  complete=green, partial=yellow), name, server, request count, duration, started, size.
- [ ] AC 3: Sessions survive Shipyard restart — `GET /api/sessions` returns previously
  recorded sessions after process restart.
- [ ] AC 4: `GET /api/sessions/{id}/export` returns a JSON file with Content-Disposition
  header; the file contains all request/response pairs with timestamps and session metadata.
- [ ] AC 5: `POST /api/sessions/{id}/replay` re-sends the recorded requests to the
  original server and returns a summary of results.
- [ ] AC 6: `DELETE /api/sessions/{id}` removes the session and all associated data;
  subsequent `GET /api/sessions/{id}` returns 404.
- [ ] AC 7: `GET /api/sessions?server=<name>` returns only sessions for that server.
- [ ] AC 8: `go test -race -count=1 -timeout 5m ./...` passes with zero race warnings.
- [ ] AC 9: `go vet ./...` passes clean.
- [ ] AC 10: `go build ./...` compiles without errors.

## API Endpoints

- `POST /api/sessions/start` — start recording (body: `{name?, server?}`)
- `POST /api/sessions/{id}/stop` — stop recording
- `GET /api/sessions` — list sessions (query: `?server=&status=`)
- `GET /api/sessions/{id}` — get session detail with all requests
- `GET /api/sessions/{id}/export` — download cassette JSON
- `POST /api/sessions/{id}/replay` — replay session
- `DELETE /api/sessions/{id}` — delete session

## Context

### Target files

- `internal/session/store.go` — new: SQLite table, CRUD operations for sessions
- `internal/session/recorder.go` — new: recording state machine (idle → recording → stopped)
- `internal/session/cassette.go` — new: JSON cassette export/import format
- `internal/session/handler.go` — new: HTTP handlers for session API endpoints
- `internal/web/ui/index.html` — add Sessions tab with recording controls and session table
- `internal/web/routes.go` — register session API routes

### Test files

- `internal/session/store_test.go` — SQLite CRUD tests
- `internal/session/recorder_test.go` — state machine tests
- `internal/session/cassette_test.go` — export/import round-trip tests
- `internal/session/handler_test.go` — HTTP handler tests
- `internal/web/ui_layout_test.go` — UI tab presence and structure

### Design reference

`UX-002-dashboard-design.pen` → "Phase 4 — Sessions" screen:
- Header with nav tabs (Sessions is a new tab)
- SessionActionBar: Record/Stop buttons, server filter
- SessionsTable: session list with status, name, server, request count, duration,
  started, size columns

## Scenarios

1. Developer opens Sessions tab → clicks "Record Session" → enters name "auth-flow" →
   performs 5 tool calls in Tool Browser → clicks "Stop" → sees session with status
   "complete", 5 requests, and correct duration.
2. Developer records a session → restarts Shipyard → opens Sessions tab → sees the
   previously recorded session with all data intact.
3. Developer exports a session → opens the JSON file → sees structured request/response
   pairs with timestamps → shares file with a colleague.
4. Developer replays a session → sees replay results showing which requests succeeded
   and which failed (e.g., server changed schema since recording).
5. Developer filters sessions by server "my-mcp" → sees only sessions recorded for that
   server → clears filter → sees all sessions.

## Out of Scope

- Cassette format compatibility with other VCR tools (custom JSON format)
- Remote session sharing / cloud sync
- Session diff (comparing two sessions)
- Automatic session naming based on tool calls
- Session annotations or comments

## Research Hints

- Files to study: `internal/capture/store.go` (existing SQLite pattern for traffic),
  `internal/web/routes.go` (route registration pattern), `internal/web/ui/index.html`
  (tab structure and vanilla JS patterns)
- Patterns to look for: how existing tabs are added to navigation, how SQLite tables
  are created/migrated, how HTTP handlers are structured
- DevKB: DevKB/go.md, DevKB/javascript.md

## Gap Protocol

- Research-acceptable gaps: existing tab structure in index.html, SQLite migration pattern
- Stop-immediately gaps: unclear cassette format requirements, unclear session-to-traffic
  linkage mechanism
- Max research subagents before stopping: 2

---

## Notes for the Agent

- **Vanilla JS only**: use `var` declarations, `.then()` callbacks — no `async/await`,
  no `let/const`. This matches the project convention in all existing UI code.
- **New SQLite table**: follow the pattern in `internal/capture/store.go` for table
  creation and query structure. Use `internal/session/` as the package.
- **New navigation tab**: Sessions is tab 5 in the main nav. Follow the existing tab
  pattern in `index.html`.
- **Recording state**: the recorder needs to hook into the existing traffic capture
  pipeline to associate requests with the active session. Study how
  `internal/capture/store.go` stores traffic.
- **Status indicators**: use DS classes for color-coded status badges (red=recording,
  green=complete, yellow=partial).
- **Cassette JSON format**: include session metadata (name, server, started, ended,
  request count) plus an array of request/response pairs, each with timestamp, method,
  params, result, and latency.
