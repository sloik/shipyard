# Getting Started with Shipyard

This guide gets Shipyard working with one child MCP in a few minutes.

## Prerequisites

- Shipyard is installed and has been launched once
- `~/.shipyard/bin/ShipyardBridge` exists
- Claude Desktop or Claude Code is installed

## Step 1: Add one child MCP to `mcps.json`

Open `~/.shipyard/config/mcps.json` and add a single stdio server entry:

```json
{
  "mcpServers": {
    "echo-demo": {
      "command": "/opt/homebrew/bin/python3",
      "args": ["$HOME/mcp/echo-demo/server.py"],
      "cwd": "$HOME/mcp/echo-demo",
      "env": {
        "LOG_LEVEL": "info"
      }
    }
  }
}
```

If you already have other entries, merge this into the existing `mcpServers` object instead of replacing it.

## Step 2: Launch or refresh Shipyard

Open `Shipyard.app`. If it is already running, refresh or restart it after saving `mcps.json`.

You should see `echo-demo` in the Shipyard server list.

## Step 3: Point Claude at ShipyardBridge

Add Shipyard to your Claude client config.

Claude Desktop:

```json
{
  "mcpServers": {
    "shipyard": {
      "command": "$HOME/.shipyard/bin/ShipyardBridge"
    }
  }
}
```

Claude Code:

```json
{
  "mcpServers": {
    "shipyard": {
      "command": "$HOME/.shipyard/bin/ShipyardBridge"
    }
  }
}
```

## Step 4: Restart Claude and verify tools

Restart Claude Desktop or your Claude Code session. Start a new conversation and check the available tools. Shipyard should expose the tools from `echo-demo` through the bridge.

## If something does not appear

- Confirm `Shipyard.app` is still running.
- Confirm `~/.shipyard/data/shipyard.sock` exists.
- Confirm the child MCP command works outside Shipyard.
- Check [troubleshoot.md](../how-to/troubleshoot.md).

## Next Steps

- Add more servers: [add-mcp-server.md](../how-to/add-mcp-server.md)
- Configure secrets: [configure-secrets.md](../how-to/configure-secrets.md)
- Review the config schema: [config-format.md](../reference/config-format.md)
