# `mcps.json` Reference

Shipyard stores child MCP definitions in `mcps.json`.

Installed builds:

```text
~/.shipyard/config/mcps.json
```

Development builds:

```text
<repo>/.shipyard-dev/config/mcps.json
```

## Top-Level Structure

```json
{
  "mcpServers": {
    "server-name": {
      "transport": "stdio",
      "command": "/absolute/path/to/executable",
      "args": [],
      "cwd": "/absolute/path/to/working-directory",
      "env": {}
    }
  }
}
```

## Entry Types

### stdio MCP

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "/opt/homebrew/bin/node",
      "args": ["$HOME/mcp/filesystem/dist/index.js"],
      "cwd": "$HOME/mcp/filesystem",
      "env": {
        "LOG_LEVEL": "info"
      },
      "env_secret_keys": ["API_TOKEN"],
      "timeout": 30
    }
  }
}
```

### HTTP MCP

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

## Field Reference

| Field | Type | Applies to | Notes |
| --- | --- | --- | --- |
| `transport` | string | stdio, http | `stdio` or `http` |
| `command` | string | stdio | Absolute path recommended |
| `args` | array | stdio | Optional command arguments |
| `cwd` | string | stdio | Working directory |
| `env` | object | stdio | Non-secret environment variables |
| `env_secret_keys` | array | stdio | Secret env keys resolved from Keychain |
| `url` | string | http | Full MCP endpoint URL |
| `headers` | object | http | Non-secret headers |
| `headers_secret_keys` | array | http | Secret headers resolved from Keychain |
| `timeout` | integer | stdio, http | Request timeout in seconds |
| `disabled` | boolean | stdio, http | Keep the entry but do not run or expose it |
| `override` | boolean | stdio, http | Optional conflict-resolution flag |
| `health_check` | object | stdio, http | Optional health-check settings |
| `migrated_from` | string | stdio, http | Migration metadata for imported entries |

## Client Config

Claude Desktop and Claude Code do not read `mcps.json` directly. They only need one bridge entry that launches `ShipyardBridge`.

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

## Validation Checklist

After editing `mcps.json`:

1. Confirm the JSON parses.
2. Confirm paths are absolute and exist.
3. Restart or refresh Shipyard.
4. Confirm the MCP appears in the app.
5. Confirm its tools appear through the bridge.
