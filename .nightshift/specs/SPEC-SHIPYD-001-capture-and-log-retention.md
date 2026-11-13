---
id: SPEC-SHIPYD-001
template_version: 7
priority: 1
layer: 2
type: feature
status: in_progress
after: []
nfrs:
- SPEC-NFR-001
created: 2026-11-13
stack: go
devkb_required:
- go.md
- testing.md
- macos.md
---

# Capture and log retention policy

## Problem

Shipyard keeps every captured MCP message forever. Measured on 2026-11-13 on the live install (`~/Library/Application Support/Shipyard/`, capture running since 2026-08-07):

| File | Size | Notes |
|---|---|---|
| `shipyard.jsonl` | 8.75 GB | Opened `O_APPEND` in `internal/capture/store.go`; written by `Insert`/`InsertWithSession`; nothing in the codebase reads it. The README calls it an "append-only backup". |
| `shipyard.db` | 8.0 GB (+435 MB WAL) | The `traffic` table is 7.5 GB and its indexes another ~100 MB. Nothing ever deletes from it. |
| `~/Library/Logs/Shipyard/shipyard-launchd.{out,err}.log` | ~29 MB | launchd stdout/stderr of `com.argo.shipyard.app.canonical`. The directory was deleted externally, so the gateway keeps writing to unlinked inodes. `com.argo.shipyard.logcap` exits 127 because its script lived inside the deleted log directory. |

Disk growth is unbounded, about 160 MB per day.

## Policy (owner decision, 2026-11-13)

- **Traffic DB:** keep 60 days. That covers the dashboard's longest range (`30d`) plus its previous-period comparison (`doubleDuration`). Rows linked to a recorded session (`traffic.session_id IS NOT NULL`) are never pruned by age. Do not prune `sessions`, `schema_snapshots` or `schema_changes`. Pruning frees pages for reuse and returns them to the OS (incremental vacuum).
- **JSONL backup:** size-capped rotation at 100 MB per file, keeping 3 rotated files (`shipyard.jsonl.1` … `.3`). Total capped at about 400 MB.
- **launchd stdout/stderr:** rotate at 10 MB, keeping 3. The rotation tooling lives in the repo, not in the log directory.
- All limits are configurable. The values above are the defaults. 0 or a negative value disables that limit; document this.

## Requirements

- [ ] R1: Traffic retention in `internal/capture`. A prune deletes `traffic` rows older than the retention window where `session_id IS NULL`. It runs at startup and then periodically (default every 6h) on a goroutine that stops cleanly on `Close`. Deletes run in bounded batches (for example 5,000 rows per transaction) so the single-connection store (`SetMaxOpenConns(1)`) never blocks capture inserts for long.
- [ ] R2: Space reclamation. Convert the DB to `auto_vacuum=INCREMENTAL` through a schema migration (this requires a one-time `VACUUM` when the DB is not already incremental). Run `PRAGMA incremental_vacuum` after each prune and `PRAGMA wal_checkpoint(TRUNCATE)` after a prune that deleted rows. The one-time migration VACUUM must log its start, end and duration. It must check free disk space first (it needs roughly the DB size). If space is insufficient, skip the migration with a logged warning; never fail startup.
- [ ] R3: JSONL rotation. The JSONL writer rotates by size: close, rename `.N`→`.N+1` (dropping anything past the keep count), rename the current file to `.1`, reopen. A size check runs on each write, against a byte counter initialised from the file's size at open. A first run against an existing file larger than the cap must not keep it as `.1`. Keep only its last `max` bytes, starting from a line boundary, or discard it, so the legacy 8.75 GB file is actually freed. Rotation closes the file before deleting the oldest one. Space is freed only once no fd holds the inode, so the writer must never keep a handle to a dropped file.
- [ ] R4: Configuration. Retention days, prune interval, JSONL max bytes and JSONL keep count can be set through Shipyard's existing configuration mechanism (follow the established pattern, whether config file, flags or env). Defaults are as in Policy.
- [ ] R5: Observability. `PerformanceStats` (or the existing performance endpoint) also reports the JSONL total bytes and the last prune result (time and rows deleted).
- [ ] R6: launchd log rotation. Add a repo-owned script (for example `scripts/rotate-launchd-logs.sh`) that rotates `shipyard-launchd.{out,err}.log` at 10 MB, keeping 3, using copy-truncate. launchd holds the fd with `O_APPEND`, so a truncate in place frees space without a restart. The script must create the log directory if it is missing. Add a launchd plist template for a daily job under the repo (for example `scripts/launchd/com.argo.shipyard.logcap.plist`) that points at the repo script. Document install and uninstall in the README or docs, next to the existing launchd deploy notes.
- [ ] R7: Docs. Document the retention policy, defaults and knobs in README.md (replacing the "append-only backup" wording) and add a CHANGELOG entry.

## Acceptance Criteria

- [ ] AC1: Unit test: a store seeded with traffic rows at ages 10d, 59d, 61d and 90d, with and without `session_id`, keeps exactly the rows that are under 60d or session-linked after a prune. `sessions`, `schema_snapshots` and `schema_changes` row counts are unchanged. Non-vacuity check: setting retention to 100d makes the same test keep every row, and the test asserts this.
- [ ] AC2: Unit test: after inserting a large number of rows, pruning most of them and running the R2 reclamation, the DB file is measurably smaller than before the prune. Asserts `PRAGMA auto_vacuum` = 2 (incremental) after migration of a fresh DB and of a pre-existing non-incremental DB.
- [ ] AC3: Unit test: with a small max-bytes value (for example 1 KB) and keep=3, writing enough entries produces `shipyard.jsonl` plus exactly `.1`, `.2` and `.3`. No `.4` exists. Every file except the current one is ≤ max + one line. The newest entry is in the current file. A pre-existing file 10× the cap, opened by a new store, leaves a total JSONL size ≤ (keep+1) × max.
- [ ] AC4: Unit test: concurrent `Insert` calls during a running prune complete without error or a data race (`go test -race`). The prune goroutine exits on `Close` (no goroutine leak).
- [ ] AC5: `scripts/rotate-launchd-logs.sh` test (shell test or Go test invoking it, against a temp dir): an 11 MB log becomes a ≤ 10 MB-capped set with at most 3 rotated copies, the live file is truncated to 0 bytes in place (same inode), and a missing directory is created. `shellcheck` is clean if available.
- [ ] AC6: The full repo gates pass: `go build ./...`, `go vet ./...`, `go test -race ./...`, plus the repo's Taskfile/Makefile check target if one exists.
- [ ] AC7: Live (parent-owned, after restart): on the real install, the first prune completes, `shipyard.db` shrinks substantially (target < 3.5 GB), the JSONL total is ≤ ~400 MB, the gateway serves MCP tools normally (`shipyard__status` works), and `com.argo.shipyard.logcap` exits 0.

## Out of Scope

- Changing what gets captured, redacting payloads, or compressing rotated files.
- The `access_log` table. It is not a size problem today, and its retention is a separate spec if needed.
- Migrating capture data off-machine.

## Live Execution Checklist

- [ ] LE1: Announce the Shipyard restart on the local coordinator. Back up nothing (8 GB): the owner accepted loss of capture data older than 60 days.
- [ ] LE2: Rebuild and restart under launchd per the repo's deploy notes. Watch the startup log for the migration VACUUM and the first prune.
- [ ] LE3: Record before/after sizes for `shipyard.db`, `shipyard.db-wal` and `shipyard.jsonl*`, plus `df -h /`.
- [ ] LE4: Install the logcap plist from the repo and verify `launchctl list | grep logcap` shows exit 0.

## Documentation Impact

- README.md (capture/retention section, launchd log rotation install).
- CHANGELOG.md.

## State rationale

```yaml
schema_version: 1
status: in_progress
reason: Delegating to two worktree workers (capture store; launchd log rotation)
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261113T081701Z-status-transition-ready-in-progress-delegating-to-two-work.json
```
