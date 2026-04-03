# Monitor Logs

Shipyard writes logs to a stable runtime directory so you can inspect problems outside the UI.

## Log Files

- Bridge logs: `~/.shipyard/logs/bridge.jsonl`
- App logs: `~/.shipyard/logs/app.jsonl`
- Child MCP logs: `~/.shipyard/logs/mcp/<name>/`

## What To Check First

### Bridge problems

Look at `bridge.jsonl` when Claude cannot connect or when no tools appear.

### App problems

Look at `app.jsonl` when Shipyard fails to load config, bind the socket, or manage child MCPs.

### Child MCP problems

Look in `logs/mcp/<name>/` when one specific MCP fails to start or crashes after launch.

## Useful Workflow

1. Reproduce the issue.
2. Check `bridge.jsonl` and `app.jsonl`.
3. If only one MCP is affected, inspect that MCP's log directory.
4. Correlate timestamps between the three log sources.

## Related Docs

- [troubleshoot.md](troubleshoot.md)
- [debug-stuck-server.md](debug-stuck-server.md)
