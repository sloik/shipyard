---
id: SPEC-BUG-153
template_version: 3
priority: 1
layer: 3
type: bugfix
status: done
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-07
---

# run-local-app.sh can leave two Shipyard desktop windows running

## Problem

Running `.shipyard-dev/run-local-app.sh` can result in two Shipyard app
instances and two desktop windows. Runtime inspection showed two
`bin/shipyard --config /Users/ed/servers.json` processes alive at the same
time, one orphaned under PID 1 and one attached to a terminal.
Further inspection showed the orphaned process was managed by the
`com.argo.shipyard` LaunchAgent with `KeepAlive=true`, so killing it during a
local run caused launchd to respawn it.

## Reproduction

1. Run `.shipyard-dev/run-local-app.sh`.
2. Interrupt or relaunch while a prior Wails desktop instance is still alive,
   or start two script invocations close together.
3. **Actual:** more than one `bin/shipyard --config ...` process can remain
   alive and multiple desktop windows appear.
4. **Expected:** the script keeps at most one local Shipyard app instance alive.

## Requirements

- [x] R1: A second launch cannot keep a second
  Shipyard app instance.
- [x] R2: Existing Shipyard app processes are terminated before a new instance
  launches.
- [x] R3: Stuck or orphaned app processes are escalated from `TERM` to `KILL`
  after a bounded wait.
- [x] R4: Stale launcher state does not permanently block future launches.
- [x] R5: Shipyard desktop mode enforces Wails single-instance behavior so a
  second app process exits instead of opening another window.
- [x] R6: Shipyard desktop mode rejects duplicate processes before starting the
  localhost web server or child MCP processes.
- [x] R7: The local launcher temporarily stops the `com.argo.shipyard`
  LaunchAgent before starting a foreground dev instance, then restores it on
  exit.

## Acceptance Criteria

- [x] AC1: Desktop mode uses an app-level lock that survives the Wails raw-binary
  relaunch behavior.
- [x] AC2: A second direct desktop launch exits with a clear duplicate-instance
  log instead of keeping another app process alive.
- [x] AC3: Releasing the app-level lock allows a later launch.
- [x] AC4: Existing `bin/shipyard` or legacy Wails app processes are terminated
  with `TERM`, then `KILL` if they remain after a bounded wait.
- [x] AC5: Desktop mode configures Wails `SingleInstance` with a stable unique
  ID and a callback that raises the existing dashboard.
- [x] AC6: Desktop mode acquires an app-level lock before `runMultiServer`
  starts child servers.
- [x] AC7: `run-local-app.sh` bootouts the launchd Shipyard agent before local
  launch and bootstraps it again during cleanup.
- [x] AC8: The script passes `zsh -n`.
- [x] AC9: `go test ./...` passes.

## Resolution

Desktop mode now acquires an app-level file lock before starting the web server
or child MCP processes. The Wails app also configures `SingleInstance`, so later
desktop launches exit cleanly and focus the existing dashboard. The local
launcher temporarily stops the `com.argo.shipyard` LaunchAgent, keeps bounded
cleanup for stale app processes, restores the LaunchAgent on exit, and uses
exact executable matching instead of `pgrep -f`.

## Context

The local launcher lives at `.shipyard-dev/run-local-app.sh`. The app entry
point is `cmd/shipyard/main.go`; desktop mode blocks in Wails while the local
server and child MCP processes run in the background.

## Out of Scope

- Changing Wails desktop window behavior.
- Packaging or notarization changes.
- Changing Shipyard's HTTP server port or config format.
