# Changelog

## Unreleased

### Changed
- Capture retention policy (SPEC-SHIPYD-001): `traffic` rows older than 60 days are pruned at startup and every 6 hours in bounded batches; session-linked rows, `sessions`, `schema_snapshots` and `schema_changes` are never pruned.
- `shipyard.jsonl` is no longer append-only forever: it rotates at 100 MiB keeping 3 rotated files. An existing oversized file is trimmed to its tail on first start.
- The database is converted once to `auto_vacuum=INCREMENTAL` (one-time `VACUUM`, skipped with a warning if disk space is short). Prunes return space to the OS via `incremental_vacuum` and `wal_checkpoint(TRUNCATE)`.
- New optional `capture` config block (`retention_days`, `prune_interval_hours`, `jsonl_max_bytes`, `jsonl_keep`); `0` or negative disables the limit.
- launchd log rotation: repo-owned `scripts/rotate-launchd-logs.sh` (10 MB, keep 3, copy-truncate) plus `scripts/launchd/` plist template and installer for `com.argo.shipyard.logcap` (SPEC-SHIPYD-001 R6).
- `/api/performance/runtime` store stats now include `jsonl_total_bytes`, `last_prune_at` and `last_prune_rows_deleted`.

### Tests
- `cmd/shipyard` tests now run with an isolated home directory so they can never open the real Shipyard data directory.
