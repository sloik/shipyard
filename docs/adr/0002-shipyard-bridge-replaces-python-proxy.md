# ADR 0002: ShipyardBridge (Swift CLI) Replaces Python Proxy

**Status**: Accepted
**Date**: 2026-03-11 (Session 35)
**Deciders**: project maintainer, AI assistant
**Supersedes**: Initial Python FastMCP proxy design (Sessions 27-28)

---

## Context

Shipyard originally used a Python FastMCP proxy (`server.py`, ~465 LOC) as the MCP-to-socket bridge. This worked but introduced friction: Python 3.10+ runtime dependency, fastmcp package, virtual environment management.

Options:
1. **Keep Python proxy** — working solution, FastMCP handles MCP protocol
2. **Swift CLI binary (ShipyardBridge)** — native, single binary, same language as app
3. **Embedded MCP in Shipyard.app** — app itself speaks MCP on stdio (no separate process)

## Decision

**Swift CLI binary — ShipyardBridge (Option 2).**

## Rationale

| Criterion | Python proxy | ShipyardBridge | Embedded in app |
|-----------|-------------|----------------|-----------------|
| Runtime deps | Python 3.10+, fastmcp, venv | None (compiled binary) | None |
| Startup time | ~500ms (Python + imports) | ~10ms | ~200ms (full app) |
| Binary size | N/A (scripts) | ~2 MB | ~15 MB |
| Maintenance | Two languages (Swift + Python) | Single language (Swift) | Single codebase |
| Separation of concerns | Good (proxy is standalone) | Good (CLI is standalone) | Poor (app must handle stdio) |
| Build complexity | pip install | Xcode target + symlink | Already built |

The key insight: ShipyardBridge is a ~1000 LOC Swift CLI that speaks full MCP JSON-RPC 2.0 on stdin/stdout and translates to the socket protocol. It's fast, dependency-free, and shares the same language as the app.

Option 3 (embedded) was rejected because the app's lifecycle (menu bar, window) conflicts with stdin/stdout expectations. A separate CLI process is cleaner.

## Consequences

### Positive
- Zero external runtime dependencies (no Python needed for MCP bridge)
- Faster startup (~10ms vs ~500ms)
- Single language codebase (Swift throughout)
- Stable binary path via symlink (`~/.shipyard/bin/ShipyardBridge`)
- Type-safe MCP protocol handling (Codable structs)

### Negative
- Lost FastMCP's automatic tool registration (reimplemented manually)
- Python proxy tests became reference-only (archived to `_archive/shipyard-mcp-python/`)
- More code to maintain in Swift (~1000 LOC for protocol handling)

## Implementation

- ShipyardBridge: `ShipyardBridge/main.swift` (later extracted to `ShipyardBridgeLib/`)
- Symlink: Run Script build phase creates `~/.shipyard/bin/ShipyardBridge` → DerivedData binary
- Config: Claude Desktop uses `~/.shipyard/bin/ShipyardBridge` as MCP command
- Python proxy archived: `_archive/shipyard-mcp-python/`

---

*Implemented across Sessions 35-38. 7 runtime bugs found and fixed. 10 DevKB lessons recorded (swift.md #17-26).*
