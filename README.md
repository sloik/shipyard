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

Release artifacts are built as Wails v3 `.app` bundles. A local unsigned app can
be created from source with:

```bash
make package-macos
```

The package command runs the Wails v3 raw desktop build first and writes
`bin/Shipyard.app`. This is useful for local testing, but it is not a
Gatekeeper-ready distribution artifact.

**First launch for unsigned local builds:** Apple will block the app because it
is not code-signed with an Apple Developer ID. To allow it:

1. Try to open `Shipyard.app` -- macOS will block it
2. Open **System Settings → Privacy & Security**
3. Scroll down to the **Security** section -- you'll see a message about Shipyard being blocked
4. Click **Open Anyway** and confirm

macOS remembers your choice -- subsequent launches work normally. Alternatively, remove the quarantine attribute from the terminal:
```bash
xattr -d com.apple.quarantine /Applications/Shipyard.app
```

Maintainer release builds should be signed and notarized:

```bash
export SHIPYARD_MACOS_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)"
make sign-macos
```

For notarization, first store Apple credentials in the keychain:

```bash
xcrun notarytool store-credentials "shipyard-notary" \
  --apple-id "apple-id@example.com" \
  --team-id "TEAMID" \
  --password "app-specific-password"
export SHIPYARD_MACOS_NOTARY_PROFILE="shipyard-notary"
make notarize-macos
```

`SHIPYARD_MACOS_SIGN_IDENTITY` is required for signing. `SHIPYARD_MACOS_NOTARY_PROFILE`
is required for notarization. The commands fail before signing or submitting if
those values are missing. `SIGN_IDENTITY` and `KEYCHAIN_PROFILE` are also
accepted for compatibility with Wails v3 Taskfile variable names. The ordinary
raw development build remains unchanged:

```bash
make wails-build
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

### Tool Browser Smoke (headless browser)

The Go tests above are source-scan assertions over the embedded UI — they
verify strings exist, not that the UI behaves. A headless-browser smoke harness
(SPEC-BUG-149) drives real clicks against a live ephemeral Shipyard instance to
catch DOM/runtime regressions in the Tool Browser (group collapse toggling,
collapse retention across tool selection, persistence across reload).

```bash
npm install   # first run only — pulls playwright-core (no browser download)
make smoke
```

`make smoke` builds its throwaway binaries under `build/smoke/`, launches a throwaway Shipyard on an ephemeral
port, and drives the system Google Chrome via `playwright-core`. It is
intentionally **not** part of `make test`, so a missing browser never blocks the
Go suite. It skips gracefully (exit 0) when `node` or Chrome is unavailable.
Override the browser path with `CHROME_BIN=/path/to/chrome make smoke`.

### Lint

```bash
make quality
```

`make quality` is the repository's blocking local and CI contract: canonical
Go formatting, pinned Staticcheck analysis, `go vet`, GitHub Actions workflow
validation, JavaScript (including inline UI scripts) and zsh syntax checks,
builds, ordinary tests, and the race suite. The analyzer binaries are built
into `.tools/bin/` from exact versions recorded in `tools/go.mod` and
`tools/go.sum`; no global installation is required.

Run `make quality-self-test` to prove every static gate rejects its committed
invalid fixture. Staticcheck has no exclusions. Any future narrow exception
must identify the rule and exact location, explain why it is safe, and state
when it will be reviewed or removed in `.staticcheck.conf`.

### macOS Wails GUI Smoke

After native desktop changes, run the repeatable macOS Wails v3 smoke:

```bash
scripts/macos-wails-gui-smoke.sh
```

The script builds Shipyard with `wails3 task build`, launches the native app,
checks the local HTTP server, records process/window evidence, and writes a
Markdown artifact under `reports/gui-smoke/`. The menu-bar tray steps are a
structured manual checklist because macOS menu-bar extras are brittle to inspect
without Accessibility permissions.

The checklist covers tray visibility, tray click show/toggle behavior, the
right-click menu items `Show Dashboard` and `Quit`, close-to-tray behavior, and
detaching a panel tab with `Open in New Window`.

### macOS Packaging and Release

### Canonical launchd runtime

`bin/shipyard` is the sole launchd-managed runtime binary. Smoke-harness
binaries are intentionally kept in ignored `build/smoke/` and never appear as
runtime choices. To replace the running service safely, run this from the
canonical checkout after its tests have passed:

```bash
make deploy-runtime
```

The deployment script runs the full browser smoke first, builds a temporary
replacement, migrates the LaunchAgent to the fresh
`com.argo.shipyard.app.canonical` label (avoiding the old label's code-hash
cache), verifies its active program path and child tool counts, and only then
archives former binaries under `archive/runtime/`. On failure it reboots the
previous `com.argo.shipyard.app` service and retains legacy binaries.

Shipyard uses Wails v3 packaging tasks for the desktop `.app` and GoReleaser for
the cross-platform headless CLI binaries.

| Command | Output | Credential behavior |
|---------|--------|---------------------|
| `make wails-build` | raw desktop-capable binary at `bin/shipyard` | no signing credentials required |
| `make package-macos` | unsigned `.app` bundle at `bin/Shipyard.app` | no signing credentials required |
| `make sign-macos` | signed `bin/Shipyard.app` | requires `SHIPYARD_MACOS_SIGN_IDENTITY` or `SIGN_IDENTITY` |
| `make notarize-macos` | signed, notarized, stapled `bin/Shipyard.app` | requires signing identity and `SHIPYARD_MACOS_NOTARY_PROFILE` or `KEYCHAIN_PROFILE` |
| `make snapshot` / `make release` | cross-platform CLI archives from GoReleaser | independent of macOS `.app` signing |

To inspect local signing prerequisites:

```bash
security find-identity -v -p codesigning
```

The macOS app package is produced by `wails3 task darwin:package`. Signing uses
`wails3 sign GOOS=darwin`, which runs `darwin:sign`. Notarization is explicit
through `wails3 task darwin:sign:notarize`.

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
