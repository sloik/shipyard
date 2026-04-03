# Socket Protocol Reference

Shipyard uses a newline-delimited JSON protocol over Unix domain socket for communication between ShipyardBridge and Shipyard.app.

**Socket path**: `~/.shipyard/data/shipyard.sock`

## Management Methods

### `status`
Returns state of all managed MCP servers.
```json
→ {"method": "status"}
← {"result": [{"name": "mac-runner", "state": "running", "pid": 12345, ...}, ...]}
```

### `health`
Run health checks on all servers.
```json
→ {"method": "health"}
← {"result": [{"name": "mac-runner", "healthy": true}, ...]}
```

### `logs`
Retrieve recent log lines for a server.
```json
→ {"method": "logs", "params": {"mcp_name": "mac-runner", "lines": 50, "level": "error"}}
← {"result": {"lines": ["..."]}}
```

### `restart`
Restart a specific server.
```json
→ {"method": "restart", "params": {"mcp_name": "mac-runner"}}
← {"result": {"ok": true}}
```

## Gateway Methods

### `gateway_discover`
Discover all available tools across managed MCPs.
```json
→ {"method": "gateway_discover"}
← {"result": {"tools": [
    {"name": "mac-runner__run_command", "mcp": "mac-runner", "original_name": "run_command",
     "description": "...", "inputSchema": {...}, "enabled": true},
    ...
  ]}}
```

### `gateway_call`
Forward a tool call to a child MCP.
```json
→ {"method": "gateway_call", "params": {"mcp": "mac-runner", "tool": "run_command", "arguments": {"command": "ls"}}}
← {"result": {"content": [{"type": "text", "text": "file1\nfile2"}]}}
```

Error responses:
| Condition | Error |
|-----------|-------|
| MCP disabled | `{"error": "tool_unavailable", "message": "...", "available_tools": [...]}` |
| MCP not running | `{"error": "mcp_not_running", "message": "..."}` |
| Timeout (30s) | `{"error": "timeout", "message": "mac-runner did not respond within 30s"}` |
| Child crash | `{"error": "mcp_crashed", "message": "..."}` |

### `gateway_set_enabled`
Toggle MCP-level or tool-level enabled state.
```json
→ {"method": "gateway_set_enabled", "params": {"mcp_name": "mac-runner", "enabled": false}}
← {"result": {"ok": true, "tools_changed": true}}

→ {"method": "gateway_set_enabled", "params": {"mcp_name": "mac-runner", "tool_name": "run_command", "enabled": false}}
← {"result": {"ok": true, "tools_changed": true}}
```

## Logging Methods

### `log_event`
Forward a log entry from BridgeLogger to Shipyard's LogStore (fire-and-forget).
```json
→ {"method": "log_event", "params": {"ts": "2026-03-13T...", "level": "info", "cat": "mcp", "src": "bridge", "msg": "Tool call completed"}}
← (no response expected — fire-and-forget)
```

## Protocol Notes

- All messages are single-line JSON terminated by `\n`
- Socket reads must use newline delimiter, not buffer size (DevKB swift.md #26)
- Timeout: 30s default for gateway calls, 5s for management calls
- Two-tier timeout pattern: inner tool timeout + outer socket timeout (bug #7 fix)

---

*Reference version: Session 55 (2026-03-13)*
