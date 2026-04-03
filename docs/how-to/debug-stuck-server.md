# Debug a Stuck or Failing MCP

Use this guide when a child MCP will not start, hangs during initialization, or returns errors through Shipyard.

## Step 1: Check Shipyard Status

1. Open Shipyard and locate the MCP in the server list.
2. Note whether it is stopped, starting, or failed.
3. If the app itself is not healthy, fix that first before debugging the child MCP.

## Step 2: Check Logs

Review:

- `~/.shipyard/logs/app.jsonl`
- `~/.shipyard/logs/bridge.jsonl`
- `~/.shipyard/logs/mcp/<name>/`

Look for:

- command-not-found errors
- missing-file errors
- authentication failures
- timeout messages

## Step 3: Inspect `mcps.json`

Open `~/.shipyard/config/mcps.json` and confirm:

- the MCP exists under `mcpServers`
- `command`, `args`, and `cwd` are correct for stdio MCPs
- `url` and headers are correct for HTTP MCPs
- secret key names match the values stored in Shipyard

## Step 4: Test The Child MCP Outside Shipyard

For stdio MCPs:

1. Run the configured command directly in Terminal.
2. Confirm the process starts without immediate errors.
3. Confirm the runtime, script, and working directory all exist.

For HTTP MCPs:

1. Confirm the endpoint is reachable.
2. Confirm any required auth headers are present.

## Step 5: Restart Cleanly

1. Stop the MCP in Shipyard.
2. Quit Shipyard if needed.
3. Start Shipyard again.
4. Start the MCP again and watch the logs during startup.

## If It Still Fails

Use the broader recovery steps in [troubleshoot.md](troubleshoot.md).
