---
id: SPEC-009
priority: 9
type: feature
status: done
after: [SPEC-004]
created: 2026-04-06
---

# Schema Change Detection

## Problem

MCP servers can change their tool schemas at any time (add tools, remove tools, modify parameters). When this happens, client integrations break silently. Developers currently have no way to know a schema changed unless they manually compare `tools/list` outputs.

## Goal

Detect schema changes automatically by polling `tools/list`, persist change history, show diffs, and alert the developer via a banner and WebSocket event.

## Architecture

```
Startup:
  For each server → call tools/list → store as baseline in schema_snapshots

Polling goroutine (every 60s):
  For each online server → call tools/list → compare to last snapshot
  If different → insert schema_change row → broadcast WS event → update snapshot

UI:
  Alert banner on any tab when unacknowledged changes exist
  Schema sub-view under Servers tab with sidebar + diff detail
```

## Key Changes

### 1. SQLite Schema (internal/capture/store.go)

```sql
CREATE TABLE IF NOT EXISTS schema_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  server_name TEXT NOT NULL,
  snapshot    TEXT NOT NULL,  -- JSON: tools/list response
  captured_at TEXT NOT NULL,
  UNIQUE(server_name, captured_at)
);

CREATE TABLE IF NOT EXISTS schema_changes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  server_name     TEXT NOT NULL,
  detected_at     TEXT NOT NULL,
  tools_added     INTEGER NOT NULL DEFAULT 0,
  tools_removed   INTEGER NOT NULL DEFAULT 0,
  tools_modified  INTEGER NOT NULL DEFAULT 0,
  before_snapshot INTEGER REFERENCES schema_snapshots(id),
  after_snapshot  INTEGER REFERENCES schema_snapshots(id),
  acknowledged    INTEGER NOT NULL DEFAULT 0,
  diff_json       TEXT NOT NULL DEFAULT '{}' -- structured diff
);

CREATE INDEX IF NOT EXISTS idx_schema_changes_server ON schema_changes(server_name);
CREATE INDEX IF NOT EXISTS idx_schema_changes_ack ON schema_changes(acknowledged);
```

### 2. Schema Diff Logic (internal/capture/schema.go — new file)

```go
type SchemaDiff struct {
  Added    []ToolSchema `json:"added"`
  Removed  []ToolSchema `json:"removed"`
  Modified []ToolModification `json:"modified"`
}

type ToolSchema struct {
  Name        string          `json:"name"`
  Description string          `json:"description"`
  InputSchema json.RawMessage `json:"input_schema"`
}

type ToolModification struct {
  Name   string          `json:"name"`
  Before json.RawMessage `json:"before"`
  After  json.RawMessage `json:"after"`
}

func DiffSchemas(before, after []ToolSchema) SchemaDiff
```

Compare by tool name:
- Present in `after` but not `before` → added
- Present in `before` but not `after` → removed
- Present in both but `input_schema` differs → modified

### 3. Store Methods (internal/capture/store.go)

```go
func (s *Store) SaveSnapshot(server string, tools []ToolSchema) (int64, error)
func (s *Store) GetLatestSnapshot(server string) ([]ToolSchema, int64, error)
func (s *Store) InsertSchemaChange(server string, diff SchemaDiff, beforeID, afterID int64) (int64, error)
func (s *Store) ListSchemaChanges(server string) ([]SchemaChange, error)
func (s *Store) GetSchemaChange(id int64) (*SchemaChangeDetail, error)
func (s *Store) AcknowledgeSchemaChange(id int64) error
func (s *Store) UnacknowledgedCount() (int, error)
```

### 4. Polling Goroutine (internal/proxy/manager.go)

Add `StartSchemaWatcher(ctx, store, interval)` method on Manager:

```go
func (m *Manager) StartSchemaWatcher(ctx context.Context, store *capture.Store, interval time.Duration) {
  ticker := time.NewTicker(interval)
  defer ticker.Stop()

  // Initial baseline capture
  m.captureAllSchemas(store)

  for {
    select {
    case <-ctx.Done():
      return
    case <-ticker.C:
      m.checkSchemaChanges(store)
    }
  }
}
```

`checkSchemaChanges`:
1. For each online server, call `Manager.SendRequest(ctx, server, "tools/list", nil)`
2. Parse response as `[]ToolSchema`
3. Get latest snapshot from store
4. Run `DiffSchemas`
5. If diff is non-empty: save new snapshot, insert change, broadcast WS event

WebSocket event format:
```json
{
  "type": "schema_change",
  "server": "filesystem",
  "added": 2,
  "removed": 0,
  "modified": 0,
  "change_id": 5
}
```

### 5. HTTP Endpoints (internal/web/server.go)

```
GET    /api/schema/changes              → handleSchemaChanges
GET    /api/schema/changes/{id}         → handleSchemaChangeDetail
POST   /api/schema/changes/{id}/ack     → handleSchemaAcknowledge
GET    /api/schema/current/{server}     → handleSchemaCurrentTools
GET    /api/schema/unacknowledged-count  → handleSchemaUnackCount
```

### 6. UI (internal/web/ui/index.html)

**Alert banner** (global, appears on any tab):
- Check `/api/schema/unacknowledged-count` on page load and after each `schema_change` WS event
- If count > 0, show warning banner below the app bar: icon + message + "Review Changes →" link
- Banner navigates to `#/servers/schema`

**Schema sub-view** under Servers tab (hash route: `#/servers/schema`):
- Sub-nav: `Overview | Schema` (Schema active)
- Left sidebar (320px): "Change History" title + list of changes with timestamps, server names, and badges (+N, -N, ~N)
- Selected change highlighted with accent left border
- Right detail panel: server + timestamp header, "Acknowledge" button, sections for added/removed/modified tools
- Added tools: green background, schema params in green
- Removed tools: red background, strikethrough, params in red
- Modified tools: yellow background, before/after param diff (red for removed, green for added)
- Empty state: shield-check icon + "No schema changes detected" + "All schemas stable"

## Acceptance Criteria

- [x] AC-1: On startup, Shipyard captures a baseline schema snapshot for each server
- [x] AC-2: Polling runs every 60s (configurable via `--schema-poll` flag)
- [x] AC-3: Schema changes are detected by comparing `tools/list` responses
- [x] AC-4: `schema_changes` table stores the diff with added/removed/modified counts
- [x] AC-5: WebSocket broadcasts `schema_change` events when changes are detected
- [x] AC-6: Alert banner appears on any tab when unacknowledged changes exist
- [x] AC-7: `GET /api/schema/changes` returns change history, filterable by server
- [x] AC-8: `GET /api/schema/changes/{id}` returns full diff detail with tool schemas
- [x] AC-9: `POST /api/schema/changes/{id}/ack` marks a change as acknowledged
- [x] AC-10: UI shows change history sidebar with schema diff detail panel
- [x] AC-11: Acknowledging all changes dismisses the global alert banner
- [x] AC-12: All tests pass (`go test ./...`)

## Out of Scope

- Alerting integrations (email, Slack, webhooks)
- Schema change rollback or pinning
- Configurable poll interval from the UI (CLI flag only)
- Comparing schemas across different servers

## Notes for Implementation

- Use `Manager.SendRequest` with a short timeout (5s) for `tools/list` calls — don't block the poll loop.
- Skip servers with status != "online" during polling.
- The diff algorithm compares tools by `name`. Parameter comparison should use deep JSON equality.
- Store full `tools/list` responses in `schema_snapshots` for historical diff reconstruction.
- The poll goroutine should be started in `main.go` after all servers are registered.
- Use `slog.Info` / `slog.Warn` for schema change logging.
- Test with mock servers that return different `tools/list` responses on consecutive calls.
- Banner dismissal: banner disappears when `unacknowledged_count` reaches 0 (all changes acknowledged).

## Target Files

- `internal/capture/schema.go` — new file: DiffSchemas, ToolSchema types
- `internal/capture/schema_test.go` — diff algorithm tests
- `internal/capture/store.go` — schema tables, snapshot/change CRUD
- `internal/capture/store_test.go` — schema store tests
- `internal/web/server.go` — 5 new handlers
- `internal/web/server_test.go` — handler tests
- `internal/proxy/manager.go` — StartSchemaWatcher, checkSchemaChanges
- `internal/proxy/manager_test.go` — watcher tests with mock responses
- `internal/web/ui/index.html` — alert banner + Schema sub-view
- `cmd/shipyard/main.go` — start schema watcher, add `--schema-poll` flag
