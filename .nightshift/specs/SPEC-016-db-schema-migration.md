---
id: SPEC-016
priority: 16
type: bugfix
status: done
after: [SPEC-006]
created: 2026-04-06
---

# Database Schema Migration

## Problem

Users running Shipyard with an existing `shipyard.db` from Phase 0-3 will get errors when Phase 4 code tries to access new columns/tables (`session_id` on `traffic`, `sessions` table, `schema_snapshots` table, `schema_changes` table). The current `initDB()` uses `CREATE TABLE IF NOT EXISTS` which doesn't handle column additions to existing tables.

## Goal

Add schema versioning and migration logic so existing databases are upgraded automatically when Shipyard starts.

## Architecture

```
initDB() →
  1. Check PRAGMA user_version
  2. If version < current:
     Run migrations sequentially (v0→v1, v1→v2, etc.)
     Update PRAGMA user_version
  3. Continue with existing CREATE TABLE IF NOT EXISTS
```

## Key Changes

### 1. Version Tracking

Use SQLite's built-in `PRAGMA user_version` to track schema version:
- v0: Phase 0-3 schema (traffic table without session_id)
- v1: Phase 4 schema (sessions table, session_id column, schema_snapshots, schema_changes)

### 2. Migration Functions (internal/capture/store.go)

```go
const currentSchemaVersion = 1

func (s *Store) migrate() error {
    var version int
    err := s.db.QueryRow("PRAGMA user_version").Scan(&version)
    if err != nil {
        return err
    }

    if version < 1 {
        if err := s.migrateToV1(); err != nil {
            return fmt.Errorf("migrate to v1: %w", err)
        }
    }

    _, err = s.db.Exec(fmt.Sprintf("PRAGMA user_version = %d", currentSchemaVersion))
    return err
}

func (s *Store) migrateToV1() error {
    // Add session_id column to traffic (if not exists)
    // CREATE TABLE IF NOT EXISTS sessions (...)
    // CREATE TABLE IF NOT EXISTS schema_snapshots (...)
    // CREATE TABLE IF NOT EXISTS schema_changes (...)
    // CREATE INDEX IF NOT EXISTS idx_traffic_session (...)
}
```

### 3. Column Existence Check

SQLite doesn't support `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Check first:
```go
func (s *Store) columnExists(table, column string) (bool, error) {
    rows, err := s.db.Query(fmt.Sprintf("PRAGMA table_info(%s)", table))
    // scan rows, check if column name matches
}
```

### 4. Call migrate() in initDB()

Add `s.migrate()` call at the beginning of `initDB()`, before CREATE TABLE statements. The CREATE TABLE IF NOT EXISTS statements remain as a safety net for fresh databases.

## Acceptance Criteria

- [x] AC-1: Fresh database creates all tables and sets `user_version = 1`
- [x] AC-2: Existing v0 database (no sessions/schema tables) is migrated automatically on startup
- [x] AC-3: Migration adds `session_id` column to existing `traffic` table
- [x] AC-4: Migration creates `sessions`, `schema_snapshots`, `schema_changes` tables
- [x] AC-5: Migration is idempotent (running twice doesn't error)
- [x] AC-6: `PRAGMA user_version` reflects current schema version after migration
- [x] AC-7: All existing tests continue to pass

## Out of Scope

- Downgrade migrations (one-way only)
- Migration CLI command (migrations run automatically on startup)
- Backup before migration (user's responsibility)

## Notes for Implementation

- SQLite `ALTER TABLE ... ADD COLUMN` doesn't support constraints or defaults that reference other tables. The `session_id` column should be `INTEGER` with no FK constraint (add FK in application logic).
- Test with a pre-Phase-4 database: create a DB with only the traffic table, run migration, verify new tables exist.
- `PRAGMA user_version` defaults to 0 for new databases — this is our v0 baseline.
- Keep migrations in sequential functions (`migrateToV1`, `migrateToV2`, etc.) for future extensibility.

## Target Files

- `internal/capture/store.go` — migrate(), migrateToV1(), columnExists()
- `internal/capture/store_test.go` — migration tests (fresh DB, v0→v1 upgrade, idempotency)
