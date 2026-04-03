# Shipyard — Project Constitution

> Where MCPs are built, launched, and maintained.

## Mission

Shipyard is a native macOS application that makes managing local MCP (Model Context Protocol) servers as simple as managing any other system service. It provides lifecycle control, observability, and a gateway pattern — so any AI agent only needs one MCP dependency.

## Values

1. **Visibility first.** Every process state, every log entry, every error must be visible to the user — in the app, in the menu bar, in stderr. Never hide what's happening.
2. **Native macOS.** SwiftUI, menu bar, Keychain, system notifications. Shipyard should feel like it belongs on the Mac.
3. **Single source of truth.** One gateway, one config, one tool catalog. Agents connect to Shipyard; Shipyard handles the rest.
4. **Contract-driven.** Every managed MCP declares its interface via `manifest.json`. No snowflakes.
5. **Observable by default.** Structured JSONL logging, stderr dual-write, socket forwarding — all mandatory. Logging is never optional.

## Non-Goals

- **Not a cloud service.** Shipyard runs locally on one machine. No remote management, no SaaS.
- **Not a package manager.** Shipyard manages running servers, not installation. Use pip/npm/cargo to install; Shipyard to run.
- **Not a debugging tool.** MCP Inspector exists for protocol-level debugging. Shipyard is production monitoring.
- **Not cross-platform.** macOS only. No Linux, no Windows.

## Architecture Summary

```
Claude Desktop/Code → ShipyardBridge (Swift CLI, stdio) → Unix socket → Shipyard.app (SwiftUI) → child MCPs
```

- **Shipyard.app**: macOS SwiftUI app. Manages processes, provides UI, runs socket server.
- **ShipyardBridge**: Swift CLI binary. MCP JSON-RPC 2.0 proxy translating Claude's protocol to Shipyard's internal socket protocol.
- **Child MCPs**: Individual MCP servers (mac-runner, lmstudio, etc.) managed by Shipyard via stdio.

## Key Invariants

1. All logging goes through three channels: JSONL file, stderr, socket forwarding. Never reduce channels.
2. Every MCP must have a `manifest.json`. No exceptions.
3. Gateway tools are namespaced: `{mcp-name}__{tool-name}`.
4. Health checks run periodically. Failures trigger notifications.
5. Secrets live in macOS Keychain, never in config files.

## Tech Stack

- Swift 6.2 + SwiftUI (macOS 26 Tahoe target)
- MCP JSON-RPC 2.0 protocol
- Unix domain socket for inter-process communication
- JSONL structured logging with rotation

## Authors

- AI-assisted development with Claude
- Human maintainer — vision, decisions, validation
