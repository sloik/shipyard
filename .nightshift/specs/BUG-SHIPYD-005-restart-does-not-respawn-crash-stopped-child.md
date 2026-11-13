---
id: BUG-SHIPYD-005
template_version: 3
priority: 1
layer: 1
type: bugfix
status: draft
after: []
violates:
- SPEC-004
nfrs:
- SPEC-NFR-001
prior_attempts: []
attachments: []
created: 2026-11-13
stack: go
devkb_required:
- go.md
- testing.md
scope:
  write:
  - internal/proxy/**
  - cmd/shipyard/**
---

# Restart does not respawn a child whose supervisor stopped after repeated crashes

## Problem

When a managed child crashes five times within one minute, its supervisor logs
`fatal: child crashed 5 times within 1m0s; stopping restarts` and gives up. From then on a restart
request for that child (MCP tool `shipyard__restart`, and the same manager call behind the UI)
answers `{"status":"restarting"}`, bumps `restart_count`, and nothing else happens: no process is
started and no log line is written. The child shows `restarting` with `tool_count: 0` indefinitely.

The only way to bring such a child back is to restart the whole gateway, which interrupts every
other child and every connected session. That defeats the purpose of a per-child restart exactly
in the case where it is needed most: after the operator has fixed whatever made the child crash.

**Violated spec:** SPEC-004 (multi-server management)
**Violated criteria:** restarting a named server stops and starts that server.

## Reproduction

Observed on the live gateway on 2026-11-13 (launchd pid 35609, build b528862):

1. `lmstudio` crashed at start five times at 10:58 (a stale virtualenv); the log shows
   "stopping restarts".
2. The virtualenv was repaired at about 13:10; `python -c "import server"` succeeds.
3. `shipyard__restart lmstudio` returned `{"server":"lmstudio","status":"restarting"}`.
4. **Actual:** `shipyard__status` still reports `lmstudio` as `restarting`, `restart_count: 2`,
   `tool_count: 0`, `uptime_ms: 0` minutes later. The gateway log has no `lmstudio` line after
   10:58. `slack-mcp-server` is in the same state.
5. **Expected:** the child process is started again; it comes online or, if it still fails, the
   failure is logged and reported with status `crashed`.

## Root Cause

(Agent fills in during run.)

## Requirements

- [ ] R1: A restart request for a child whose supervisor has stopped after the crash limit starts
      that child again, with a fresh crash window.
- [ ] R2: A restart request for a running child keeps its current behaviour.
- [ ] R3: A child never stays in status `restarting` without a process being started or a failure
      being recorded; if the respawn fails, status and error message say so.
- [ ] R4: The restart is logged (child name and outcome).

## Acceptance Criteria

- [ ] AC1 (R1): A test drives a child past the crash limit, then requests a restart with the child
      now healthy, and observes the child running and reporting tools again.
- [ ] AC2 (R1): After such a restart the crash counter starts from zero: one further crash does not
      immediately stop restarts.
- [ ] AC3 (R2): Existing restart tests for a running child pass unchanged.
- [ ] AC4 (R3): If the respawned child crashes again past the limit, status becomes `crashed` with
      an error message, never a permanent `restarting`.
- [ ] AC5 (R4): The gateway log contains a line for the restart request and its outcome.
- [ ] AC6: `go test -race -count=1 ./...` passes (SPEC-NFR-001); the violated SPEC-004 behaviour
      holds for crash-stopped children.

## Context

- Found while repairing lmstudio-mcp on 2026-11-13.
- Related operational rule: `SHIPYARD_HEALTH_ALLOW_EMPTY` exists because such children cannot be
  brought back without a gateway restart.

## Out of Scope

- Changing the crash limit or the backoff schedule.
- Automatic recovery without an explicit restart request.

## Code Pointers

- `internal/proxy/manager.go` (`RestartServer`, about line 221)
- `internal/proxy/proxy.go` (crash limit, about line 279)
- The run loop that owns each proxy in `cmd/shipyard/main.go`

## State rationale

```yaml
schema_version: 1
status: draft
reason: Observed on the live gateway on 2026-11-13; needs a Nightshift run and a gateway redeploy, not an inline fix
reconsider_when: The owner schedules the next Shipyard run or the next gateway deploy
evidence: []
provenance: authored
record: artifacts/20261113T121814Z-decision-state-rationale-authored-draft-observed-.json
```
