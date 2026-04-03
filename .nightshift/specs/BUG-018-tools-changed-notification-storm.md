---
id: BUG-018
priority: 1
layer: 3
type: bugfix
status: done
after: []
violates: [SPEC-024]
prior_attempts: []
created: 2026-03-31
---

# tools_changed Notification Storm — Shipyard Self-Discovery Feedback Loop

## Symptom

After SPEC-024 (Shipyard self-exposure), a rapid burst of ~30+ `tools_changed` notifications fires within a single millisecond:

```
[notif] Received tools_changed notification
[notif] Emitted notifications/tools/list_changed to Claude
[notif] Received tools_changed notification
[notif] Emitted notifications/tools/list_changed to Claude
... (×30 in ~2ms)
```

Followed by ShipyardBridge crashing 4ms after connecting:

```
19:28:26.199Z - Server started and connected successfully
19:28:26.203Z - Server transport closed unexpectedly (process exiting early)
```

Result: Shipyard MCP is permanently broken in Cowork/Claude Desktop — ShipyardBridge dies before it can serve any requests.

## Root Cause

SPEC-024 added Shipyard itself to `GatewayRegistry` as a managed server. This created a circular feedback loop:

1. Shipyard starts → discovers its own tools via `shipyard_tools`
2. Tool discovery triggers a `tools_changed` notification
3. ShipyardBridge (connected client) receives `tools_changed` → calls `tools/list` on Shipyard
4. `tools/list` in Shipyard re-runs discovery → discovers its own tools again
5. → fires `tools_changed` again → go to step 3

Each cycle fires another notification. The loop saturates within milliseconds, generating ~30+ notifications before something (likely a write buffer overflow or assertion) kills ShipyardBridge.

This is the circular self-reference risk flagged in `docs/specs/006-shipyard-self-exposure.md` § Unknowns & Risks, point 1: "Risk: Shipyard disables the gateway_discover or gateway_call tools, breaking the gateway."

## Fix

The loop must be broken at the source. **Two complementary fixes:**

### Fix 1 — Don't fire `tools_changed` for Shipyard's own tools (preferred)

Shipyard's tool list is **static** (hardcoded in `shipyard_tools`). It never changes at runtime. There is no reason to fire `tools_changed` when Shipyard's builtin tools are "discovered" — they're always the same.

In `GatewayRegistry` (or wherever `tools_changed` is broadcast after discovery):
- Guard: skip the `tools_changed` broadcast when the only change is the builtin Shipyard entry
- Or: during discovery, if the incoming tools for `name == "shipyard"` / `isBuiltin == true` are identical to what's already cached, suppress the notification

### Fix 2 — Debounce `tools_changed` broadcasts (defensive)

Even if Fix 1 is applied, rapid successive notifications from child MCPs can still cause bursts. Add a short debounce (e.g. 100–200ms) to the `tools_changed` broadcast so that multiple rapid changes coalesce into a single notification.

Find where `tools_changed` is broadcast (grep for `tools_changed`, `notifyToolsChanged`, `broadcastToolsChanged`, or the relevant Combine publisher/notification post) and wrap it with a debounce.

### Fix 3 — Guard `tools/list` against re-triggering discovery

When Shipyard handles an incoming `tools/list` request from a connected client, it should NOT re-run `GatewayRegistry.discoverTools()`. Discovery is a proactive operation (triggered by MCP start/stop events and manual refresh). Serving `tools/list` is a read — it should only read the already-cached registry, not re-discover.

Verify that the `gateway_discover` / `tools/list` handler in `SocketServer` reads from the cache and does NOT call `discoverTools()` or any method that triggers a `tools_changed` broadcast.

## Acceptance Criteria

- [ ] No `tools_changed` notification burst on Shipyard startup (≤1 notification per actual tool change event)
- [ ] ShipyardBridge stays connected after startup — does not crash within seconds of connecting
- [ ] Cowork / Claude Desktop can call Shipyard tools successfully after the fix
- [ ] Adding or removing a real child MCP still correctly fires a single `tools_changed` notification
- [ ] Shipyard's own tool list change (builtin) does NOT fire `tools_changed`
- [ ] Build succeeds with zero errors; all existing tests pass

## Implementation Order

1. **Grep first**: find where `tools_changed` is broadcast and where `discoverTools()` is called. Map the full trigger chain before touching anything.
2. Apply Fix 3: verify `tools/list` handler is read-only (does not trigger discovery)
3. Apply Fix 1: suppress `tools_changed` for builtin Shipyard entry when tools are unchanged
4. Apply Fix 2 (optional but defensive): add debounce to `tools_changed` broadcast
5. Test: start Shipyard → verify ≤1 notification → verify ShipyardBridge stays connected

## Key Files

- `Shipyard/Models/GatewayRegistry.swift` — where discovery runs and `tools_changed` is published
- `ShipyardBridgeLib/SocketServer.swift` — `tools/list` / `gateway_discover` handler; verify it's read-only
- `ShipyardTests/GatewayRegistryTests.swift` — add test: discover builtin → no notification fired when tools unchanged

## References

- SPEC-024: introduced Shipyard self-discovery (root cause of this bug)
- docs/specs/006-shipyard-self-exposure.md § Unknowns & Risks — circular dependency risk was documented but not mitigated in SPEC-024
