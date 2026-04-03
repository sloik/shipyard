# Troubleshooting Shipyard

Use this guide for the most common public-release setup failures.

## Bridge Not Connecting

Symptoms:

- Claude shows the Shipyard MCP as unavailable
- no Shipyard tools appear in Claude
- `ShipyardBridge` exits immediately

Checks:

1. Confirm `Shipyard.app` is running.
2. Confirm the bridge path in your Claude config points to `~/.shipyard/bin/ShipyardBridge`.
3. Confirm the socket exists at `~/.shipyard/data/shipyard.sock`.
4. Check `~/.shipyard/logs/bridge.jsonl` and `~/.shipyard/logs/app.jsonl`.

## Child MCP Not Starting

Symptoms:

- the MCP appears in Shipyard but stays stopped or errors immediately
- the tool catalog never includes that MCP

Checks:

1. Open `~/.shipyard/config/mcps.json` and validate the entry.
2. Confirm `command`, `args`, and `cwd` paths exist for stdio MCPs.
3. Run the configured command manually in Terminal.
4. Check the MCP-specific logs under `~/.shipyard/logs/mcp/<name>/`.

## Socket Errors

Symptoms:

- bridge logs mention connection refused
- Shipyard logs mention socket bind or permission failures

Checks:

1. Confirm no stale process owns the socket path.
2. Confirm `~/.shipyard/data/` exists and is writable by your user.
3. Restart Shipyard so it recreates the socket cleanly.
4. Re-check `~/.shipyard/data/shipyard.sock`.

## Log Locations

- Bridge logs: `~/.shipyard/logs/bridge.jsonl`
- App logs: `~/.shipyard/logs/app.jsonl`
- Child MCP logs: `~/.shipyard/logs/mcp/<name>/`

## Quick Recovery Order

1. Quit Claude.
2. Quit Shipyard.
3. Start Shipyard again.
4. Confirm the socket and logs exist.
5. Restart Claude.

## Still Stuck

Use these references next:

- [monitor-logs.md](monitor-logs.md)
- [socket-protocol.md](../reference/socket-protocol.md)
- [debug-stuck-server.md](debug-stuck-server.md)
