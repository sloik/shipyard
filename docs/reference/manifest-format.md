# Legacy Manifest Reference

Current public Shipyard installs use `~/.shipyard/config/mcps.json` instead of manifest-based discovery.

This page remains only as migration context for older setups that imported MCP definitions from `manifest.json` files. For all new installs and public documentation, use:

- [config-format.md](config-format.md)
- [add-mcp-server.md](../how-to/add-mcp-server.md)

## What Changed

Older Shipyard revisions discovered child MCPs from per-project `manifest.json` files. Public release builds now centralize managed MCP definitions in:

```text
~/.shipyard/config/mcps.json
```

## Migration Guidance

If you are moving from an older manifest-based setup:

1. Convert each legacy server definition into an entry under `mcpServers`.
2. Move secrets out of old manifests and into Shipyard-managed secrets.
3. Restart Shipyard and verify each MCP appears in the UI.

For new users, skip manifests entirely.
