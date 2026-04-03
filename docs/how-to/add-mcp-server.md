# Add a New MCP to Shipyard

Shipyard loads child MCPs from `~/.shipyard/config/mcps.json`.

## Workflow

1. Add or update an entry in `mcps.json`.
2. Restart or refresh Shipyard.
3. Start the child MCP in Shipyard if needed.
4. Verify that its tools appear through the gateway.

## File Location

Installed builds:

```text
~/.shipyard/config/mcps.json
```

Development builds:

```text
<repo>/.shipyard-dev/config/mcps.json
```

## File Shape

The managed file is named `mcps.json`. The top-level object follows the standard MCP-style `mcpServers` map:

```json
{
  "mcpServers": {
    "name-of-server": {
      "transport": "stdio",
      "command": "/absolute/path/to/executable",
      "args": [],
      "cwd": "/absolute/path/to/working-directory",
      "env": {}
    }
  }
}
```

## Example 1: stdio child MCP

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "/opt/homebrew/bin/node",
      "args": [
        "$HOME/mcp/filesystem-server/dist/index.js"
      ],
      "cwd": "$HOME/mcp/filesystem-server",
      "env": {
        "LOG_LEVEL": "info"
      },
      "env_secret_keys": ["API_TOKEN"],
      "timeout": 30
    }
  }
}
```

## Example 2: HTTP child MCP

```json
{
  "mcpServers": {
    "local-http-mcp": {
      "transport": "http",
      "url": "http://127.0.0.1:8080/mcp",
      "headers": {
        "X-Client": "shipyard"
      },
      "headers_secret_keys": ["AUTHORIZATION"],
      "timeout": 30
    }
  }
}
```

## Common Fields

- `transport`: `stdio` or `http`
- `command`: executable for stdio MCPs
- `args`: argument array for stdio MCPs
- `cwd`: working directory for stdio MCPs
- `env`: non-secret environment variables
- `env_secret_keys`: environment variables resolved from Keychain
- `url`: endpoint for HTTP MCPs
- `headers`: non-secret HTTP headers
- `headers_secret_keys`: headers resolved from Keychain
- `timeout`: request timeout in seconds
- `disabled`: keep the entry present but inactive

## Add A Server

1. Open `mcps.json`.
2. Add a new entry under `mcpServers`.
3. Save the file.
4. Restart or refresh Shipyard.
5. Start the new MCP if it is not already running.

## Verify The New MCP

1. Check the server list in Shipyard.
2. Open the Gateway view and confirm the tools appear.
3. Open Claude and confirm the tools are exposed through the single `shipyard` bridge entry.

## Secrets

If you declare `env_secret_keys` or `headers_secret_keys`, store the secret values in Shipyard instead of hardcoding them into `mcps.json`.

Reference: [configure-secrets.md](configure-secrets.md)
