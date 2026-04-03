---
id: BUG-019
priority: 1
layer: 3
type: bugfix
status: done
after: []
violates: [SPEC-024]
prior_attempts: [BUG-018]
created: 2026-03-31
---

# ShipyardBridge Crashes 3ms After Connecting — Shipyard Completely Unusable

## Symptom

ShipyardBridge starts, connects to Shipyard's socket, then exits immediately. Every connection attempt fails the same way:

```
19:40:35.033Z — Server started and connected successfully
19:40:35.036Z — Server transport closed unexpectedly, this is likely due to the process exiting early
19:40:35.037Z — Server disconnected
```

**3ms between connect and crash.** No stderr output (no Swift error printed, no panic message). Reproducible on every connection attempt. Shipyard is completely unusable — no tools reachable from Claude/Cowork.

BUG-018 (notification storm) was fixed by Nightshift but did not resolve this crash. This is a distinct failure mode.

## Root Cause Hypothesis

SPEC-024 added Shipyard's own entry to `GatewayRegistry`. The most likely crash trigger: when ShipyardBridge connects, Shipyard's discovery code immediately tries to call `shipyard_tools` **via the newly opened socket connection** — effectively sending a request to itself through the client that just connected. ShipyardBridge receives an unexpected inbound message during its own startup handshake (before it has sent `initialize`), hits an unhandled state, and exits cleanly (no panic, just `exit(0)` or equivalent).

Alternative: something in SPEC-024's `SocketServer.dispatchRequest` changes introduced a regression in the normal request/response handling path that crashes on the first real message.

## Investigation Steps

**Step 1 — Add stderr logging to ShipyardBridge startup**

Add `fputs("ShipyardBridge: step X\n", stderr)` at each stage of ShipyardBridge's startup (connect to socket, send initialize, receive response, enter run loop). This will show exactly which step fails. The log will appear in Claude Desktop logs under the `[shipyard]` section.

**Step 2 — Check what Shipyard sends immediately on new connection**

In `SocketServer`, find the handler for new client connections. Does it send anything to the client immediately on connect (before the client sends a request)? After SPEC-024, does it trigger any discovery or notification on connect? If yes — this is the bug. ShipyardBridge expects to be the first speaker (it sends `initialize`); receiving an unexpected message first will crash it.

Key question: does SPEC-024's code call `discoverTools()` or `broadcastToolsChanged()` synchronously inside the new-connection handler?

**Step 3 — Check `dispatchRequest` for regressions**

Review all changes made to `SocketServer.dispatchRequest` by SPEC-024. Look for any new code path that could `exit()`, `fatalError()`, `preconditionFailure()`, or throw an unhandled error on the first request (which would be ShipyardBridge's `initialize`).

**Step 4 — Bisect if needed**

If the above doesn't find it: temporarily revert SPEC-024's changes to `SocketServer.swift` and `GatewayRegistry.swift` one file at a time to identify which change introduced the crash.

## Fix

Once the cause is identified, the fix will be one of:

- **If Shipyard sends on connect**: remove any proactive send/broadcast triggered by a new connection. Shipyard's socket is server-only — it speaks only in response to client requests.
- **If dispatchRequest regression**: fix the specific code path that causes the exit.
- **If self-referential `shipyard_tools` call**: the builtin Shipyard entry must never call back into the socket server for its own tool discovery. Tool list must be hardcoded/static, not fetched via socket.

## Acceptance Criteria

- [ ] ShipyardBridge stays connected for more than 1 second after startup
- [ ] ShipyardBridge successfully completes MCP `initialize` handshake with Shipyard
- [ ] `shipyard_gateway_discover` returns a tool list when called from Claude/Cowork
- [ ] Cowork can call at least one Shipyard tool end-to-end (e.g. `shipyard_status`)
- [ ] Build succeeds with zero errors; all existing tests pass

## Key Files

- `ShipyardBridgeLib/SocketServer.swift` — new-connection handler; `dispatchRequest`; any code added by SPEC-024
- `Shipyard/Models/GatewayRegistry.swift` — `discoverTools()`; any code triggered on new client connection
- `ShipyardBridge/` — startup and run loop; add stderr logging to identify crash point

## References

- SPEC-024: introduced Shipyard self-discovery (root change)
- BUG-018: notification storm fix (done, did not resolve this crash)
