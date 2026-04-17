# Shipyard

**See every MCP call happening on your machine -- and replay any of them without an LLM.**

[![Go](https://img.shields.io/badge/Go-1.22+-00ADD8?logo=go&logoColor=white)](https://go.dev)
[![License](https://img.shields.io/badge/license-TBD-lightgrey)]()
[![CI](https://github.com/sloik/shipyard/actions/workflows/ci.yml/badge.svg)](https://github.com/sloik/shipyard/actions/workflows/ci.yml)

## What is Shipyard?

Shipyard is a traffic-inspecting proxy and web dashboard for the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). It sits between your MCP client (Claude Desktop, Claude Code, Cursor) and your MCP servers, capturing every JSON-RPC message in real time. A local web dashboard lets you browse traffic, invoke tools directly, and replay past requests -- no LLM required.

```
┌─────────────┐       stdio        ┌───────────┐       stdio        ┌────────────┐
│  MCP Client │◄──────────────────►│ Shipyard  │◄──────────────────►│ MCP Server │
│  (Claude,   │                    │   Proxy   │                    │ (filesystem│
│   Cursor)   │                    │           │                    │  git, etc) │
└─────────────┘                    └─────┬─────┘                    └────────────┘
                                         │
                                         │ http://localhost:9417
                                         ▼
                                  ┌──────────────┐
                                  │ Web Dashboard│
                                  │  (embedded)  │
                                  └──────────────┘
```

## Features

- **Traffic Timeline** -- real-time request/response capture for all JSON-RPC messages
- **Tool Browser** -- schema-driven forms for direct tool invocation without an LLM
- **Replay & History** -- one-click replay of any captured request, edit-and-replay, response diff
- **Multi-Server Management** -- run multiple MCP servers from a single config file
- **Auto-Import** -- discover servers from Claude Desktop, Claude Code, and Cursor configs
- **Session Recording** -- VCR-like cassettes for CI test fixtures (start/stop/export)
- **Latency Profiling** -- P50/P95 stats per tool and server, color-coded in the dashboard
- **Schema Change Detection** -- automatic polling alerts when a server's `tools/list` changes
- **Server Lifecycle** -- start, stop, restart servers from the dashboard; auto-restart on crash
- **Tool Conflict Detection** -- identifies duplicate tool names across servers

## Quick Start

### Wrap a single server

```bash
shipyard wrap --name filesystem -- npx -y @modelcontextprotocol/server-filesystem /tmp
```

### Run multiple servers from config

```bash
shipyard --config servers.json
```

The dashboard opens automatically in a native window. Add `--headless` to skip the window and open [http://localhost:9417](http://localhost:9417) in your browser instead.

### Expose Shipyard as one MCP server to external clients

If you want Claude CLI or Codex to connect to one Shipyard entry instead of
registering every child MCP separately, run the stdio bridge:

```bash
go run ./cmd/shipyard-mcp --api-base http://127.0.0.1:9417
```

This bridge:

- speaks MCP over stdio
- discovers Shipyard-managed tools through the local HTTP API
- exposes namespaced tools like `lmstudio__chat`
- lets multiple external clients connect through separate bridge processes while
  sharing one running Shipyard backend

Example registration shape:

```json
{
  "mcpServers": {
    "shipyard": {
      "type": "stdio",
      "command": "go",
      "args": ["run", "./cmd/shipyard-mcp", "--api-base", "http://127.0.0.1:9417"]
    }
  }
}
```

### Codex note

Codex `exec` currently needs explicit per-tool approval entries for Shipyard-exposed
tools in `~/.codex/config.toml`. A server-wide setting such as
`mcp_servers.shipyard.approval_mode = "approve"` is not sufficient.

Minimal example:

```toml
[mcp_servers.shipyard]
command = "/Users/ed/Dropbox/Developer/Repos/shipyard/.shipyard-dev/bin/ShipyardBridge"
args = ["--api-base", "http://127.0.0.1:9417"]

[mcp_servers.shipyard.tools.shipyard__status]
approval_mode = "approve"

[mcp_servers.shipyard.tools.lmstudio__lms_status]
approval_mode = "approve"
```

To refresh the approval list for the currently exposed Shipyard tools:

```bash
curl -s http://127.0.0.1:9417/api/gateway/tools | jq -r '.tools[].name'
```

If you use the compiled bridge binary, rebuild it after bridge changes:

```bash
make build-mcp
```

To verify the documented Codex path end-to-end:

```bash
.shipyard-dev/verify-spec-125.sh
```

## Installation

### Desktop App (macOS)

Download `shipyard-macos.zip` from [Releases](https://github.com/sloik/shipyard/releases). Unzip and move `Shipyard.app` to your Applications folder.

**First launch on macOS:** Apple will block the app because it is not code-signed with an Apple Developer ID. To allow it:

1. Try to open `Shipyard.app` -- macOS will block it
2. Open **System Settings → Privacy & Security**
3. Scroll down to the **Security** section -- you'll see a message about Shipyard being blocked
4. Click **Open Anyway** and confirm

macOS remembers your choice -- subsequent launches work normally. Alternatively, remove the quarantine attribute from the terminal:
```bash
xattr -d com.apple.quarantine /Applications/Shipyard.app
```

### CLI Binaries

Download the binary for your platform from [Releases](https://github.com/sloik/shipyard/releases), extract, and add to your `PATH`. Use `--headless` flag to run without a desktop window.

Available binaries: macOS (arm64, amd64), Linux (arm64, amd64), Windows (amd64, arm64).

### From Source

Requires Go 1.22+:

```bash
go install github.com/sloik/shipyard/cmd/shipyard@latest
```

### Homebrew (planned)

```bash
# Coming soon
brew install sloik/tap/shipyard
```

## Configuration Reference

### JSON Config File

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {},
      "cwd": ""
    },
    "git": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git", "--repository", "/path/to/repo"]
    },
    "custom": {
      "command": "python",
      "args": ["my_server.py"],
      "env": {"DEBUG": "1"},
      "cwd": "/path/to/project"
    }
  },
  "web": {
    "port": 9417
  }
}
```

#### Server fields

| Field     | Type              | Required | Description                        |
|-----------|-------------------|----------|------------------------------------|
| `command` | string            | yes      | Executable to run                  |
| `args`    | string[]          | no       | Command-line arguments             |
| `env`     | map[string]string | no       | Extra environment variables        |
| `cwd`     | string            | no       | Working directory for the process  |

#### Web fields

| Field  | Type | Default | Description            |
|--------|------|---------|------------------------|
| `port` | int  | 9417    | Web dashboard port     |

### CLI Flags

| Flag            | Default | Description                          |
|-----------------|---------|--------------------------------------|
| `--config`      | (none)  | Path to JSON config file             |
| `--schema-poll` | `60s`   | Schema change polling interval       |
| `--name`        | `child` | Server display name (wrap mode only) |
| `--port`        | `9417`  | Web dashboard port (wrap mode only)  |

### Usage

```
shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]
shipyard --config <servers.json> [--schema-poll DURATION]
```

## Auto-Import

Shipyard can discover MCP servers already configured in your local tools. The dashboard's auto-import feature scans:

- **Claude Desktop** -- `claude_desktop_config.json`
- **Claude Code** -- `~/.claude/` project configs

Servers found in these configs appear in the dashboard with a one-click import option. Already-imported servers are marked to avoid duplicates.

Access via the dashboard UI or directly:

```
GET http://localhost:9417/api/auto-import
```

## API Endpoints

The dashboard communicates via a REST API, also available for scripting:

| Method   | Path                                  | Description                      |
|----------|---------------------------------------|----------------------------------|
| `GET`    | `/api/traffic`                        | List captured traffic            |
| `GET`    | `/api/traffic/{id}`                   | Traffic entry detail             |
| `GET`    | `/api/servers`                        | List managed servers             |
| `POST`   | `/api/servers/{name}/restart`         | Restart a server                 |
| `POST`   | `/api/servers/{name}/stop`            | Stop a server                    |
| `GET`    | `/api/auto-import`                    | Scan for importable servers      |
| `GET`    | `/api/tools`                          | List all tools across servers    |
| `GET`    | `/api/tools/conflicts`                | Detect tool name conflicts       |
| `POST`   | `/api/tools/call`                     | Invoke a tool directly           |
| `POST`   | `/api/replay`                         | Replay a captured request        |
| `POST`   | `/api/sessions/start`                 | Start a recording session        |
| `GET`    | `/api/sessions`                       | List sessions                    |
| `GET`    | `/api/sessions/{id}`                  | Session detail                   |
| `GET`    | `/api/sessions/{id}/export`           | Export session as cassette       |
| `POST`   | `/api/sessions/{id}/stop`             | Stop a recording session         |
| `POST`   | `/api/sessions/{id}/replay`           | Replay an entire session         |
| `DELETE` | `/api/sessions/{id}`                  | Delete a session                 |
| `GET`    | `/api/schema/changes`                 | List schema changes              |
| `GET`    | `/api/schema/changes/{id}`            | Schema change detail             |
| `POST`   | `/api/schema/changes/{id}/ack`        | Acknowledge a schema change      |
| `GET`    | `/api/schema/current/{server}`        | Current tool schema for a server |
| `GET`    | `/api/schema/unacknowledged-count`    | Count of unacked schema changes  |
| `GET`    | `/api/profiling/summary`              | Latency profiling summary        |
| `GET`    | `/api/profiling/tools`                | Per-tool latency stats           |
| `GET`    | `/ws`                                 | WebSocket for live updates       |

## Development

### Prerequisites

- Go 1.22+

### Build

```bash
go build ./cmd/shipyard/
```

### Test

```bash
go test ./...
```

### Lint

```bash
go vet ./...
```

### UI

The web dashboard is a single HTML file with vanilla JS, embedded into the binary at compile time via `go:embed`. To edit the UI:

1. Edit files in `internal/web/ui/`
2. Rebuild: `go build ./cmd/shipyard/`
3. The design system lives in `internal/web/ui/ds.css` and `internal/web/ui/ds.js`

## Architecture

Shipyard is built with Go stdlib-first principles:

- **Proxy** -- stdio pipe relay using goroutines, one per server
- **Capture** -- SQLite (`internal/capture/store.go`) with JSONL append-only backup
- **Web** -- `net/http` server with `go:embed` for static assets
- **Dashboard** -- vanilla JS, WebSocket for live updates, no framework dependencies
- **Schema watcher** -- periodic `tools/list` polling with diff detection

For design decisions, see the Architecture Decision Records:

- [ADR-001: Cross-Platform Pivot](docs/adr/0001-cross-platform-pivot.md) -- why Shipyard moved from SwiftUI to proxy + web
- [ADR-002: Go Language Choice](docs/adr/0002-go-language-choice.md) -- why Go over Rust and Node
- [ADR-003: DevTools Positioning](docs/adr/0003-devtools-positioning.md) -- "Browser DevTools for MCP" product strategy

## License

See [LICENSE](LICENSE) file.
