# ADR 0003: Gateway Pattern — Single MCP Entry Point

**Status**: Accepted
**Date**: 2026-03-12 (Session 33)
**Deciders**: project maintainer, AI assistant

---

## Context

Before the gateway, every AI agent needed separate MCP entries for each server (mac-runner, lmstudio, etc.). Adding or removing an MCP meant editing every agent's config. This doesn't scale.

Options:
1. **No gateway** — agents configure each MCP individually (status quo)
2. **Gateway aggregation** — Shipyard re-exposes all child MCP tools under one namespace
3. **Config generation only** — Shipyard generates config but agents still connect directly

## Decision

**Gateway aggregation (Option 2).** Shipyard becomes a single MCP that aggregates and re-exposes all tools from managed child MCPs.

## Rationale

| Criterion | No gateway | Gateway | Config-only |
|-----------|-----------|---------|-------------|
| Agent config changes on MCP add/remove | Every agent | None (just Shipyard) | Every agent |
| Tool visibility control | None | Per-MCP + per-tool toggles | None |
| Single connection | No | Yes | No |
| Complexity | Low | High | Low |
| Runtime overhead | None | Socket + bridge | None |

The gateway pattern centralizes MCP management: agents connect to Shipyard once, and Shipyard controls which tools are available. Enable/disable toggles give fine-grained control without config changes.

## Design

- **Tool namespacing**: `{mcp-name}__{tool-name}` (double underscore, matches Claude Code convention)
- **Enable/disable**: MCP-level toggle + per-tool overrides, persisted in UserDefaults
- **Discovery**: `tools/list` on child MCPs, aggregated in GatewayRegistry
- **Forwarding**: `gateway_call` → MCPBridge → child stdin/stdout → response passthrough
- **Hot-reload**: Re-discovery on MCP start/stop/restart + manual refresh

## Consequences

### Positive
- One MCP config entry for all tools
- UI control over tool availability (Gateway tab)
- Clean tool catalog for agents (no stale entries)
- Future: can add rate limiting, logging, access control per tool

### Negative
- Additional latency (socket hop + bridge)
- Failure of Shipyard = failure of all tools
- GatewayRegistry state must stay in sync with running MCPs
- More complex protocol (gateway_discover, gateway_call, gateway_set_enabled)

## Protocol

```
gateway_discover → {tools: [{name, mcp, original_name, description, inputSchema, enabled}]}
gateway_call → {mcp, tool, args} → child MCP → result passthrough
gateway_set_enabled → {mcp, tool?, enabled} → toggle state
```

---

*Implemented in Phase 7 (Sessions 33-34). Verified end-to-end in Phase 8.2 (Session 38). T2 integration tests added (Session 46).*
