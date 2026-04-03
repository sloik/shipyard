# ADR 0004: Mandatory Three-Channel Logging

**Status**: Accepted
**Date**: 2026-03-13 (Session 55)
**Deciders**: project maintainer, AI assistant

---

## Context

ShipyardBridge originally had a "debug" stderr dual-write that was planned for removal. The project decision was that all logging channels must remain active because logging visibility is a core requirement, not a debug feature.

## Decision

**All logging must write to three channels simultaneously. No channel may be disabled or removed.**

The three channels:
1. **JSONL file** (`~/.shipyard/logs/bridge.jsonl` / `app.jsonl`) — persistent, rotated, structured
2. **stderr** — visible in the app's System Logs tab + fallback when app is not running
3. **Socket forwarding** — real-time delivery to Shipyard app's LogStore (info+ level, fire-and-forget)

## Rationale

- **Visibility is a core value.** Users must always be able to see what's happening.
- **stderr is dual-purpose**: the Shipyard app captures it for the System Logs tab, and when the app isn't running, the parent process (Claude Desktop) still receives the output.
- **JSONL persists across restarts** — can always investigate after the fact.
- **Socket forwarding enables real-time display** in the app's log viewer.

Removing any channel reduces observability. The cost of writing to all three is negligible compared to the value of guaranteed visibility.

## Consequences

### Positive
- Logs are always visible, everywhere, in every running state
- No "silent failure" possible — something will capture the output
- System Logs tab always has content to show

### Negative
- Slightly more stderr noise (acceptable trade-off)
- All three channels must be maintained in both BridgeLogger and AppLogger

---

*Established as invariant in Session 55. Added to Logging Architecture section of MCP-Manager-App.md.*
