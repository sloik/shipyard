# ADR-002: Go as Implementation Language

**Status:** Accepted
**Date:** 2026-04-04
**Deciders:** Project maintainer, AI assistant

## Context

Shipyard v2 needs a language for a cross-platform MCP proxy with an embedded web dashboard. Three candidates were evaluated via parallel research spikes:

| Factor | Go | Rust | Node/TypeScript |
|--------|-----|------|-----------------|
| Phase 0 effort | 10-16h | 20-40h | 12-19h |
| Binary size | ~12 MB | ~8 MB | 50-90 MB |
| Startup time | ~5-10ms | ~1ms | 8-50ms |
| Memory (RSS) | ~15 MB | ~5 MB | 30-50 MB |
| Cross-compile | Trivial (pure Go) | Medium (needs cross-linkers) | Bun compile or Node SEA |
| MCP ecosystem | Official SDK + 8.5k star community SDK | Official SDK (rmcp) + 4 proxies | Official SDK (reference impl) |
| Learning curve | Medium | High | Low |

## Decision

Use **Go** for Shipyard v2.

## Rationale

**Distribution is the deciding factor.** A 12 MB static binary with zero runtime dependencies, cross-compiled via `GOOS=X GOARCH=Y go build`, installable via `brew install` or GitHub Releases download. For a developer tool that needs adoption, frictionless installation is everything.

**Why not Rust:** Produces a marginally smaller binary nobody would notice. 20-40 hour MVP estimate (vs 10-16 for Go) due to async Rust ramp-up and compile times. The performance advantages (1ms startup, 5MB RSS) solve problems Shipyard doesn't have — it's a traffic inspector, not a database engine.

**Why not Node/TypeScript:** The MCP ecosystem being TypeScript-native is seductive but irrelevant — Shipyard proxies JSON-RPC, it doesn't need deep SDK integration. A 50-90 MB binary is embarrassing for a lightweight dev tool. Requiring a Node/Bun runtime is adoption friction.

**Go-specific advantages for this use case:**
- Goroutines are purpose-built for the stdio proxy pattern (two concurrent pipe readers)
- `go:embed` bakes the web dashboard into the binary at compile time
- CGO-free SQLite via `ncruces/go-sqlite3` eliminates cross-compilation pain
- `net/http` stdlib is sufficient for the dashboard server
- Most learnable language for open-source contributors

## Consequences

- The project maintainer learns Go (medium ramp, simple language)
- CI builds produce 6 binaries (macOS arm64/amd64, Linux arm64/amd64, Windows amd64/arm64)
- Web UI is developed as a separate frontend (HTML/JS/CSS) embedded at build time
- No native GUI — the dashboard is always a web page in a browser

## References

- Go MCP SDK: `github.com/modelcontextprotocol/go-sdk`
- mcp-go community SDK: `github.com/mark3labs/mcp-go` (8.5k stars)
- CGO-free SQLite: `github.com/ncruces/go-sqlite3`
- WebSocket: `github.com/coder/websocket`
