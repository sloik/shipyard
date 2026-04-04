# ADR-004: MCP Tooling Competitive Landscape (April 2026)

**Status:** Accepted (snapshot — will need refreshing)
**Date:** 2026-04-04
**Deciders:** Project maintainer, AI assistant

## Context

Before deciding Shipyard v2's direction, we surveyed the MCP developer tooling ecosystem. This ADR captures the landscape as of April 2026 for future reference.

## Landscape Summary

### Development Frameworks
| Tool | Stars | Language | What it does |
|------|-------|----------|--------------|
| FastMCP (Python) | 24.3k | Python | High-level MCP server framework, ~70% of MCP servers |
| FastMCP (TypeScript) | - | TypeScript | TypeScript equivalent, Zod validation |
| Speakeasy | Commercial | - | Auto-generates MCP servers from OpenAPI specs |

### Debugging & Inspection
| Tool | Stars | Platform | What it does | Gap |
|------|-------|----------|--------------|-----|
| MCP Inspector | 9.3k | Web (Node) | Official testing tool, single-server, no persistence | No traffic recording, no multi-server |
| Context | 785 | macOS native | SwiftUI debugger, auto-imports client configs | No process management, no recording, no gateway |
| Reticle | 118 | Desktop (Rust/Tauri) | "Wireshark for MCP" — traffic inspection, latency profiling | No replay, no tool invocation, no management |
| TRMX Playground | - | Desktop (Electron) | "Postman for MCPs" with LLM integration | Newer, less mature |

### Traffic Recording & Replay
| Tool | Stars | What it does | Gap |
|------|-------|--------------|-----|
| mcp-recorder | 8 | VCR-like record/replay/verify with cassettes | Very new, CLI-only, no UI |
| mcp-debug | 0 | Hot-swap servers + session recording (Go) | No community, TUI only |
| Microsoft Dev Proxy | - | General API proxy with MCP stdio mocking | MCP is secondary use case |

### Gateways & Proxies
| Tool | Stars | Focus |
|------|-------|-------|
| Microsoft MCP Gateway | 560 | Enterprise Kubernetes routing |
| IBM ContextForge | 3.5k | Multi-protocol federation, admin UI |
| Lasso Security Gateway | 363 | Security-focused (PII detection, injection prevention) |
| Traefik Hub | Commercial | Enterprise traffic management |

### Package Management
| Tool | What it does |
|------|--------------|
| MCPM (mcpm.sh) | CLI package manager for MCP servers |
| mcp.run | Registry + control plane with profiles |
| PulseMCP | Directory of 14,000+ MCP servers |

## Unfilled Niches (Shipyard v2's Opportunity)

1. **No mature multi-server dashboard for developers** — enterprise gateways are overkill, single-server tools are insufficient
2. **No integrated traffic capture + replay + tool invocation** in one tool
3. **No cross-platform native-feel developer console** — Inspector is web-only, Context is macOS-only
4. **No battle-tested VCR-like record/replay** — mcp-recorder has 8 stars
5. **No "always-on passive capture"** in the Browser DevTools sense

## Decision

This landscape confirms the positioning chosen in ADR-003. Shipyard v2 targets the gap between single-server debuggers (Inspector, Context) and enterprise gateways (Microsoft, IBM) — a lightweight, cross-platform developer console with traffic visibility.

## References

Full competitive analysis with URLs available in the research sprint archive (2026-04-04 session).
