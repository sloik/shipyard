---
id: SPEC-004
priority: 4
type: main
status: ready
after: [SPEC-003]
created: 2026-04-04
---

# Phase 3: Multi-Server Management

## Problem

Most developers run multiple MCP servers. Managing them individually (separate proxy instances) is cumbersome. They need a single dashboard showing all servers, their health, and their tools.

## Goal

Support multiple child MCP servers from one Shipyard instance with config-based management, health monitoring, and auto-discovery from existing client configurations.

## Key Features

1. **Config-based multi-server** — JSON config file listing all servers to manage
2. **Health monitoring** — running/crashed/unreachable status per server, auto-detection
3. **Auto-import** — read existing configs from Claude Desktop, Claude Code, Cursor and offer to proxy them
4. **Tool conflict detection** — flag duplicate tool names across servers
5. **Per-server controls** — start/stop/restart individual servers from the dashboard

## Acceptance Criteria

- [ ] AC-1: Config file supports multiple server entries with command, args, env, cwd
- [ ] AC-2: Dashboard shows all servers with status indicators (green/red/yellow)
- [ ] AC-3: Server crash is detected and surfaced in the UI within 2 seconds
- [ ] AC-4: "Restart" button kills and respawns a specific server
- [ ] AC-5: Auto-import discovers servers from `~/.claude/settings.json` and `claude_desktop_config.json`
- [ ] AC-6: Duplicate tool names across servers are flagged in the tool browser
- [ ] AC-7: Traffic timeline shows server name for each entry, filterable

## Out of Scope

- Remote server management (always local)
- Server installation / package management
