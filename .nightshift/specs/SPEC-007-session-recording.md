---
id: SPEC-007
priority: 7
type: feature
status: done
after: [SPEC-004]
created: 2026-04-06
---

# Session Recording & Export

## Problem

Developers debugging MCP integrations need to capture a full debug session (multiple requests/responses) as a replayable unit. Currently, individual requests can be replayed, but there is no way to group, name, export, or bulk-replay a sequence of captured traffic.

## Goal

Add session recording: start/stop capture windows, name them, persist in SQLite, export as JSON cassettes, and replay entire sessions.

## Architecture

```
User clicks "Record" → POST /api/sessions/start
  Manager sets recordingSession on matching server(s)
  All traffic captured with session_id FK
User clicks "Stop" → POST /api/sessions/{id}/stop
  Session marked complete, duration computed
Export → GET /api/sessions/{id}/export
  Returns self-contained JSON cassette
Replay → POST /api/sessions/{id}/replay
  Re-executes each request sequentially via Manager.SendRequest
```

## Key Changes

### 1. SQLite Schema (internal/capture/store.go)

Add `sessions` table:

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL DEFAULT '',
  server     TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'recording',  -- recording|complete|partial
  started_at TEXT NOT NULL,
  stopped_at TEXT,
  duration_ms INTEGER,
  request_count INTEGER NOT NULL DEFAULT 0,
  size_bytes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_server ON sessions(server);
```

Add `session_id` column to `traffic` table:
```sql
ALTER TABLE traffic ADD COLUMN session_id INTEGER REFERENCES sessions(id);
CREATE INDEX IF NOT EXISTS idx_traffic_session ON traffic(session_id);
```

### 2. Store Methods (internal/capture/store.go)

```go
func (s *Store) StartSession(name, server string) (int64, error)
func (s *Store) StopSession(id int64) error
func (s *Store) GetSession(id int64) (*Session, error)
func (s *Store) ListSessions(server, status string) ([]Session, error)
func (s *Store) DeleteSession(id int64) error
func (s *Store) ExportSession(id int64) (*SessionCassette, error)
```

`InsertTraffic` must accept an optional `sessionID` parameter. When a session is recording for a given server, all traffic for that server gets tagged with the session ID.

### 3. HTTP Endpoints (internal/web/server.go)

```
POST   /api/sessions/start          → handleSessionStart
POST   /api/sessions/{id}/stop      → handleSessionStop
GET    /api/sessions                → handleSessionList
GET    /api/sessions/{id}           → handleSessionDetail
GET    /api/sessions/{id}/export    → handleSessionExport
POST   /api/sessions/{id}/replay   → handleSessionReplay
DELETE /api/sessions/{id}           → handleSessionDelete
```

### 4. Manager Integration

`Manager` needs a `activeSession` map (`map[string]int64` — server name → session ID). When recording:
- `InsertTraffic` calls include the session ID
- `request_count` increments on the session row
- WebSocket broadcasts `session_update` events with current count/duration

### 5. Cassette Export Format

```json
{
  "version": 1,
  "name": "debug-auth-flow",
  "server": "filesystem",
  "recorded_at": "2026-04-06T15:42:00Z",
  "duration_ms": 25200,
  "requests": [
    {
      "method": "tools/call",
      "params": { "name": "read_file", "arguments": { "path": "/tmp/test.txt" } },
      "response": { "content": [{ "type": "text", "text": "..." }] },
      "latency_ms": 45,
      "offset_ms": 0
    }
  ]
}
```

### 6. UI (internal/web/ui/index.html)

Add Sessions sub-view under History tab (hash route: `#/history/sessions`):
- Sub-nav: `Requests | Sessions | Performance` (Sessions active)
- Action bar: Record/Stop toggle button, session name input, server filter dropdown, Export All button
- Table: Status, Name, Server, Requests, Duration, Started, Size, Actions (export/replay/delete)
- Pagination with prev/next controls
- Empty state: disc icon + "No sessions recorded" + Record Session CTA

WebSocket listener for `session_update` events to live-update the recording row.

## Acceptance Criteria

- [x] AC-1: `POST /api/sessions/start` creates a session row and returns `{id, name, server, status}`
- [x] AC-2: All traffic for the matching server is tagged with `session_id` while recording
- [x] AC-3: `POST /api/sessions/{id}/stop` sets status to `complete`, computes duration and size
- [x] AC-4: `GET /api/sessions` returns paginated list, filterable by `?server=` and `?status=`
- [x] AC-5: `GET /api/sessions/{id}/export` returns a self-contained JSON cassette
- [x] AC-6: `POST /api/sessions/{id}/replay` re-executes each request via Manager.SendRequest
- [x] AC-7: `DELETE /api/sessions/{id}` removes the session and unlinks traffic rows
- [x] AC-8: WebSocket broadcasts `session_update` events during recording
- [x] AC-9: UI shows session list with Record/Stop toggle, server filter, and pagination
- [x] AC-10: Delete and Replay actions require confirmation (DS.modal)
- [x] AC-11: All tests pass (`go test ./...`)

## Out of Scope

- Cassette format compatibility with other VCR tools
- Recording across multiple servers simultaneously (record one server at a time)
- Cloud sync or remote session sharing
- Session diff/comparison

## Notes for Implementation

- Follow the existing `InsertTraffic` dual-write pattern (SQLite + JSONL). Session metadata is SQLite-only.
- Use `Manager.mu` for thread-safe `activeSession` map access.
- Replay should execute requests sequentially with their original `offset_ms` delays (configurable: with or without delays).
- The `size_bytes` field is computed as the sum of payload lengths in the session's traffic rows.
- Use `DS.modal()` for delete/replay confirmations in the UI.
- Route: `#/history/sessions` — add sub-nav to the History view.
- Test the recording state machine: start → stop, start → server crash (partial), double-start (error).

## Target Files

- `internal/capture/store.go` — schema migration, session CRUD
- `internal/capture/store_test.go` — session store tests
- `internal/web/server.go` — 7 new handlers
- `internal/web/server_test.go` — handler tests
- `internal/proxy/manager.go` — activeSession tracking
- `internal/proxy/manager_test.go` — session recording tests
- `internal/web/ui/index.html` — Sessions sub-view UI
