---
id: SPEC-BUG-166
priority: 2
layer: 1
type: refactor
status: in_progress
after: []
nfrs: [SPEC-NFR-001]
technologies: [go, shell]
created: 2026-08-08
---

# One canonical Shipyard runtime binary

## Problem

`bin/` currently contains five unrelated executables: the active
`shipyard-fixed`, legacy backup `shipyard.bak-jun7`, smoke harness binaries,
and an aborted local build. This makes the settings/runtime chooser ambiguous
and obscures which binary launchd actually runs.

## Requirements

- [ ] R1: `bin/shipyard` is the only executable retained in `bin/` and is the
  documented, launchd-managed runtime artifact.
- [ ] R2: Smoke harness output is built in a separate ignored directory outside
  `bin/` (for example `build/smoke/`) and never appears as a runtime choice.
- [ ] R3: The active launchd service is migrated to `bin/shipyard` only after a
  replacement binary passes its smoke/health checks.
- [ ] R4: Legacy binaries are moved to a recoverable archive location only after
  launchd and Shipyard health prove the canonical binary is live.
- [ ] R5: Build, smoke, and deployment documentation name the same canonical
  runtime path.

## Acceptance Criteria

- [ ] AC-1: `bin/` contains exactly one executable: `shipyard`.
- [ ] AC-2: `make smoke` and `make smoke-full` pass while writing no executable
  under `bin/`.
- [ ] AC-3: `launchctl print` shows the active Shipyard service executing
  `bin/shipyard`.
- [ ] AC-4: Shipyard is online and its managed child tool counts are populated
  after migration.
- [ ] AC-5: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 ./...` pass.

## Context

- Current active service: `com.argo.shipyard.app` runs `bin/shipyard-fixed`.
- macOS launch constraints reject a rebuilt binary under an existing
  ad-hoc-signed label; the implementation must use the project’s established
  safe migration/deployment mechanism rather than overwrite in place.
- Current smoke target writes `shipyard-smoke` and `stubchild-smoke` into `bin/`.

## Out of Scope

- Changing Shipyard functionality or child-MCP configuration.
- Deleting backups before the replacement has live evidence.
