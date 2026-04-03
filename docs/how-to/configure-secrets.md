# Configure Secrets

Keep API keys, bearer tokens, and private headers out of `mcps.json`. Shipyard resolves them from macOS Keychain at runtime.

## Declare Secret Keys

For stdio MCPs, declare secret environment variables with `env_secret_keys`:

```json
{
  "mcpServers": {
    "anthropic-tools": {
      "command": "/opt/homebrew/bin/node",
      "args": ["$HOME/mcp/anthropic-tools/dist/index.js"],
      "env": {
        "LOG_LEVEL": "info"
      },
      "env_secret_keys": ["ANTHROPIC_API_KEY"]
    }
  }
}
```

For HTTP MCPs, declare secret headers with `headers_secret_keys`:

```json
{
  "mcpServers": {
    "private-http-mcp": {
      "transport": "http",
      "url": "https://example.com/mcp",
      "headers": {
        "X-Client": "shipyard"
      },
      "headers_secret_keys": ["AUTHORIZATION"]
    }
  }
}
```

## Store The Values

1. Open Shipyard.
2. Go to the secrets UI.
3. Select the MCP and the secret key name.
4. Paste the value and save it.

Shipyard stores the secret in macOS Keychain and injects it when the child MCP starts.

## Verify

1. Start the MCP in Shipyard.
2. Check the logs for missing-secret or auth errors.
3. If needed, restart the MCP after changing a secret.

## Troubleshooting

- If a secret is missing at runtime, confirm the key name in `env_secret_keys` or `headers_secret_keys` matches exactly.
- If an MCP still fails authentication, delete and re-enter the secret.
- If you accidentally committed a secret, rotate it and remove it from git history.
