# ADR-003: "Browser DevTools for MCP" Product Positioning

**Status:** Accepted
**Date:** 2026-04-04
**Deciders:** Project maintainer, AI assistant

## Context

Shipyard v0.x positioned itself as an "MCP runtime manager." A 5-team research sprint evaluated four possible positionings for v2:

1. **MCP Process Manager** — manage server lifecycle (start/stop/restart)
2. **MCP Gateway / API Hub** — route and aggregate multiple MCP servers
3. **Postman for MCPs** — collections, environments, test automation
4. **Browser DevTools for MCP** — traffic visibility, direct invocation, replay

## Decision

Position Shipyard v2 as the **"Browser DevTools for MCP"** — a developer console that shows every MCP call happening on the machine and lets developers replay any of them without an LLM.

**One-line pitch:** "Shipyard shows you every MCP call happening on your machine — and lets you replay any of them without an LLM."

## Rationale

### Why this positioning wins

**Pain alignment:** The #1 MCP developer pain is "I can't call a tool without an LLM in the loop." The #2 is "I can't see what's happening on the wire." DevTools positioning directly addresses both.

**Competitive gap:** Nobody combines visibility + invocation + replay + multi-server in one tool:
- MCP Inspector (9.3k stars): web-only, single-server, no persistence
- Context.app (785 stars): macOS-only, debug-only, no traffic recording
- Reticle (118 stars): traffic capture but no replay, no tool invocation
- Enterprise gateways (Microsoft, IBM): overkill for individual developers

**Adoption model:** Browser DevTools won by being always-available and passively capturing. The proxy model gives Shipyard the same quality — it's always in the traffic path, always recording.

### Why other positionings lose

**Process Manager:** Becoming a commodity. VS Code has auto-restart. Clients will handle lifecycle natively. Nobody evangelizes a process manager.

**Gateway/API Hub:** Enterprise gateways from Microsoft, IBM, and Traefik have massive investment. Can't compete on routing, auth, or scale.

**Postman for MCPs:** Requires building collections, environments, request chaining, mock servers from scratch. Shipyard's proxy-position advantage becomes irrelevant.

## Consequences

**Core features (in priority order):**
1. Passive traffic capture of all MCP JSON-RPC messages
2. Real-time traffic timeline (the "Network tab")
3. Tool browser with schema-driven forms for direct invocation
4. One-click replay of any captured request
5. Persistent execution history

**Deferred features:**
- Collections / saved requests (Postman territory)
- Mock server capability
- Request chaining / workflows
- Environment variable templating

## User Personas Served

| Persona | Primary value |
|---------|--------------|
| MCP Builder | Direct tool invocation without LLM, schema validation |
| MCP Integrator | Multi-server health dashboard, conflict detection |
| MCP Debugger | Traffic inspection, request replay |
| MCP Tester | Session recording for test fixture generation |
