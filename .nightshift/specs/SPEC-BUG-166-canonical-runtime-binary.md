---
id: SPEC-BUG-166
priority: 2
layer: 1
type: refactor
status: done
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

- [x] R1: `bin/shipyard` is the only executable retained in `bin/` and is the
  documented, launchd-managed runtime artifact.
- [x] R2: Smoke harness output is built in a separate ignored directory outside
  `bin/` (for example `build/smoke/`) and never appears as a runtime choice.
- [x] R3: The active launchd service is migrated to `bin/shipyard` only after a
  replacement binary passes its smoke/health checks.
- [x] R4: Legacy binaries are moved to a recoverable archive location only after
  launchd and Shipyard health prove the canonical binary is live.
- [x] R5: Build, smoke, and deployment documentation name the same canonical
  runtime path.

## Acceptance Criteria

- [x] AC-1: `bin/` contains exactly one executable: `shipyard`.
- [x] AC-2: `make smoke` and `make smoke-full` pass while writing no executable
  under `bin/`.
- [x] AC-3: `launchctl print` shows the active Shipyard service executing
  `bin/shipyard`.
- [x] AC-4: Shipyard is online and its managed child tool counts are populated
  after migration.
- [x] AC-5: `go test ./...`, `go vet ./...`, `go build ./...`, and
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

## Resolved Blocker

**Resolution:** Łukasz authorized the parent operator on 2026-08-08 to merge the
worker branch and run the canonical live deployment/evidence gate from `main`.

The worker completed its implementation and focused unblock pass in the isolated
worktree. The remaining acceptance criteria require an authorized live deployment
from the canonical main checkout; that parent-side validation was prohibited for
this kickoff. The preserved worker report and branch contain the exact rerun.
