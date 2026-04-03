---
id: SPEC-025
priority: 2
layer: 3
type: feature
status: done
after: [SPEC-024]
prior_attempts: []
created: 2026-03-31
---

# Shipyard Restart Control — Same Controls as Any Other MCP

## Problem

After SPEC-024, Shipyard appears in the server sidebar exactly like any other MCP. However it still lacks the Restart button that all other running MCPs have. The goal is full control parity: Shipyard's row should show the same controls as any other running MCP server, with two exceptions driven by its builtin nature:

- **No Stop button** — stopping Shipyard would terminate the entire app (all child MCPs go down). This is destructive and unrecoverable from within the app. Hide it.
- **No Start button** — Shipyard is always running; there is no idle/stopped state for it. Hide it.
- **Restart button** — restarts the Unix domain socket listener (stop + rebind). Fast, safe, useful when the socket gets into a bad state. **Show it.**

## Requirements

### Restart Action for Shipyard

- [ ] Clicking Restart on the Shipyard row calls a `restartSocketListener()` method on `SocketServer`
  - Sequence: close existing socket → unbind → rebind → start listening again
  - All child MCP processes remain running during the restart (socket restart only, not process restart)
  - Connected clients (e.g. Claude) will need to reconnect — this is acceptable and expected
  - Restart completes synchronously or with a brief async wait; update Shipyard state to `.running` when done
  - See `ShipyardBridgeLib/SocketServer.swift` — understand the existing start/stop/bind flow before implementing

- [ ] `restartSocketListener()` is exposed so the app layer can call it
  - If `SocketServer` is already accessible from the view model layer, add the method there
  - Do not add a new dependency chain — follow the existing pattern for how child MCP restart is wired

### UI — Control Visibility for Builtin Entries

- [ ] Shipyard row shows **Restart button only** among the start/stop/restart controls
  - Stop button: hidden for `isBuiltin == true` entries
  - Start button: hidden for `isBuiltin == true` entries (never idle)
  - Restart button: **visible** for `isBuiltin == true` entries
  - Grep for where Stop/Start/Restart buttons are conditionally rendered in the existing server row component — add the `isBuiltin` guard there, touching only the minimum needed

- [ ] No new view components. Modify only the conditional rendering logic in the existing server row.

- [ ] Restart button behaviour matches child MCPs visually:
  - Same icon, same placement, same disabled/active states
  - Brief spinner or state change while socket is restarting (if child MCPs do this — match them)

### Tests

- [ ] `SocketServer.restartSocketListener()`: socket is unbound and rebound; new connections succeed after restart; in-flight connections during restart receive an appropriate error
- [ ] UI: Restart button is visible for Shipyard entry; Stop and Start buttons are hidden
- [ ] UI: tapping Restart triggers `restartSocketListener()` (mock the call, verify it fires)
- [ ] Build succeeds with zero errors; all existing tests pass

## Implementation Order

1. **Read first**: grep for how Restart is wired for child MCPs (button → action → ProcessManager or equivalent). Understand the full call chain before writing anything.
2. Add `restartSocketListener()` to `SocketServer` — stop, unbind, rebind, listen
3. Wire the Shipyard entry's Restart action to `restartSocketListener()`
4. Update server row conditional rendering: hide Stop + Start for `isBuiltin`, show Restart
5. Tests

## Key Files

- `ShipyardBridgeLib/SocketServer.swift` — add `restartSocketListener()`; understand existing bind/listen flow
- `Shipyard/Views/` — find the server row component; add `isBuiltin` guard for Stop/Start visibility
- `Shipyard/Models/MCPServer.swift` (or equivalent) — `isBuiltin` computed property (may already exist from SPEC-024)
- `ShipyardTests/` or `ShipyardBridgeTests/` — socket restart tests, UI control visibility tests

## References

- SPEC-024: established Shipyard as first-in-list builtin entry using existing row components
- Existing Restart wiring for child MCPs — grep and follow that pattern exactly
