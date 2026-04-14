---
id: SPEC-BUG-003
priority: 2
type: bugfix
status: done
after: [SPEC-001]
created: 2026-04-04
---

# SPEC-BUG-003: Config File Mode Not Implemented

## Problem

SPEC-001 defines a `--config servers.json` mode for managing multiple servers. The current implementation only supports `wrap` (single inline server). The config file mode needs to work for Phase 3 multi-server support, but even for Phase 0 it's a cleaner way to configure a single server.

## Current Behavior

`cmd/shipyard/main.go` only parses the `wrap` subcommand. No `--config` flag.

## Expected Behavior

```bash
# Config mode
shipyard --config servers.json

# servers.json
{
  "servers": {
    "my-mcp": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "env": {"NODE_ENV": "development"},
      "cwd": "/some/path"
    }
  },
  "web": {
    "port": 9417
  }
}
```

For Phase 0, only the first server in the config is proxied via stdio. Multi-server support comes in Phase 3.

## Target Files

- `cmd/shipyard/main.go` — add `--config` flag, parse JSON config
- `internal/proxy/proxy.go` — accept env and cwd from config

## Acceptance Criteria

- [ ] AC-1: `shipyard --config servers.json` starts proxy with first server from config
- [ ] AC-2: Config supports command, args, env, cwd per server
- [ ] AC-3: Web port configurable via config file
- [ ] AC-4: Missing config file produces a clear error message
- [ ] AC-5: `wrap` mode still works unchanged
