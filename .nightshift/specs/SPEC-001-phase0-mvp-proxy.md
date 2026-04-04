---
id: SPEC-001
priority: 1
type: main
status: draft
children:
  - SPEC-001-001
  - SPEC-001-002
  - SPEC-001-003
created: 2026-04-04
---

# Phase 0: MVP Proxy — Traffic Capture + Web Dashboard

## Problem

MCP developers cannot see what JSON-RPC messages flow between their clients and servers. Testing a tool requires crafting an LLM prompt and hoping it picks the right tool. There is no "Network tab" for MCP.

## Goal

Build a minimal proxy that sits between an MCP client and one or more MCP servers, captures all JSON-RPC traffic, and displays it in a browser.

## Success Criteria

A developer should be able to:
1. Point their MCP client (Claude Code, Cursor, etc.) at `shipyard` instead of their MCP server
2. Shipyard spawns the real server as a child process
3. All JSON-RPC traffic flows through Shipyard transparently
4. Open `localhost:9417` in a browser and see every request/response in real time
5. Historical traffic persists across proxy restarts

## Architecture

```
MCP Client ←stdio→ Shipyard Proxy ←stdio→ Child MCP Server
                        │
                   localhost:9417
                   (web dashboard)
```

## Components

### SPEC-001-001: Stdio Proxy Core
- Read config file listing child MCP servers (command, args, env, cwd)
- Spawn child process with piped stdin/stdout/stderr
- Proxy stdin→child and child→stdout bidirectionally
- Tap both directions through a capture channel
- Handle child crash/exit (log, optionally restart)
- Graceful shutdown on SIGTERM/SIGINT

### SPEC-001-002: Traffic Capture & Storage
- Parse tapped bytes as newline-delimited JSON-RPC 2.0
- Extract: method, id, direction (client→server / server→client), timestamp
- Correlate requests with responses by JSON-RPC id
- Store in SQLite (schema: id, ts, direction, server_name, method, message_id, payload, latency_ms)
- Also write JSONL file as append-only log
- Calculate latency by matching request/response pairs

### SPEC-001-003: Web Dashboard (Bare MVP)
- HTTP server on localhost:9417
- Embedded static HTML/JS/CSS via `go:embed`
- GET / → traffic timeline page
- WebSocket /ws → push new traffic events in real time
- GET /api/traffic → paginated historical traffic (from SQLite)
- Traffic table: timestamp, direction, server, method, status, latency
- Click row → expand to show full JSON payload
- Filter by server name, method, direction

## Tech Stack

| Component | Library |
|-----------|---------|
| Runtime | Go 1.22+ |
| Async I/O | goroutines + channels |
| Child process | `os/exec` |
| JSON | `encoding/json` |
| SQLite | `github.com/ncruces/go-sqlite3` (pure Go, no CGO) |
| HTTP server | `net/http` (stdlib) |
| WebSocket | `github.com/coder/websocket` |
| Static embed | `embed` (stdlib) |
| Config | JSON file |
| CLI | `flag` (stdlib) |
| Logging | `log/slog` (stdlib) |

## Config Format

```json
{
  "servers": {
    "my-mcp": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": { "NODE_ENV": "development" }
    }
  },
  "web": {
    "port": 9417
  }
}
```

## Usage

```bash
# Wrap a single MCP server (inline mode)
shipyard wrap -- npx -y @modelcontextprotocol/server-filesystem /tmp

# Run with config file (multi-server mode)
shipyard --config servers.json
```

The client's MCP config points at `shipyard` instead of the real server:
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "shipyard",
      "args": ["wrap", "--", "npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
```

## Acceptance Criteria

- [ ] AC-1: `shipyard wrap -- <command>` spawns child, proxies stdio, client works normally
- [ ] AC-2: All JSON-RPC messages captured to SQLite with timestamp, direction, method
- [ ] AC-3: Request/response pairs correlated by JSON-RPC id with latency calculated
- [ ] AC-4: `localhost:9417` shows traffic timeline updating in real time via WebSocket
- [ ] AC-5: Traffic table shows: time, direction, server, method, status badge, latency
- [ ] AC-6: Clicking a row shows full JSON payload (request and matched response)
- [ ] AC-7: Filter by server name and method works
- [ ] AC-8: Traffic persists in SQLite — refreshing the page shows historical data
- [ ] AC-9: Child crash is logged; proxy remains running
- [ ] AC-10: SIGTERM/SIGINT triggers graceful shutdown (kill child, close DB, exit)
- [ ] AC-11: Single static binary with no runtime dependencies
- [ ] AC-12: Builds for macOS arm64 and Linux amd64 via cross-compilation

## Out of Scope (deferred to Phase 1+)

- Tool invocation from the web UI (Phase 1)
- Request replay (Phase 2)
- Multi-server config file mode (Phase 3 — start with `wrap` single-server mode)
- Auto-import from Claude/Cursor configs (Phase 3)
- Session recording export (Phase 4)

## Notes for Implementation

- Use `bufio.Scanner` with enlarged buffer (`scanner.Buffer(buf, 10*1024*1024)`) — MCP responses can be large
- Always drain child stderr in a separate goroutine to prevent deadlock
- The web UI for Phase 0 can be minimal: a single HTML file with vanilla JS, no React needed
- Port 9417 chosen to avoid conflicts with common dev ports (3000, 8080, etc.)
