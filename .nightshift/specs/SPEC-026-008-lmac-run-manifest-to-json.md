---
id: SPEC-026-008
priority: 3
layer: 3
type: feature
status: done
after: [SPEC-026-002]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# lmac-run: Manifest to JSON Migration

## Problem

The lmac-run MCP is currently discovered via manifest.json in its directory. After the manifest cutover (SPEC-026-002), it needs a proper mcps.json entry. This spec validates that lmac-run works correctly when configured solely through mcps.json, with no manifest.json dependency.

## Requirements

- [ ] Create a verified mcps.json entry for lmac-run with correct command, args, and env
- [ ] Verify lmac-run starts successfully from mcps.json config (no manifest.json present)
- [ ] Verify all lmac-run tools are discoverable through the gateway after migration
- [ ] Verify tool execution works end-to-end (call a lmac-run tool via gateway, get correct result)
- [ ] Document the mcps.json entry in the per-MCP migration log

## Acceptance Criteria

- [ ] AC 1: lmac-run entry exists in mcps.json with command, args, and any required env vars
- [ ] AC 2: Removing lmac-run's manifest.json directory from the watch list does not affect lmac-run availability
- [ ] AC 3: `shipyard_gateway_discover` lists lmac-run tools with correct `lmac-run__` prefix
- [ ] AC 4: Calling a lmac-run tool via `shipyard_gateway_call` returns a valid result
- [ ] AC 5: lmac-run appears in the Shipyard sidebar as a config MCP (not legacy/manifest)
- [ ] AC 6: System log shows lmac-run starting from config source, not manifest source

## Context

- lmac-run is a command execution MCP — check its manifest.json for the exact command and arguments
- Location: likely in `ManagedProjects/Tools/mcp/lmac-run-mcp/`
- The mcps.json format: `{ "mcps": { "lmac-run": { "command": "...", "args": [...], "env": {...} } } }`
- SPEC-026-002 provides the importer that creates the initial entry; this spec verifies and validates it

## Scenarios

1. Shipyard launches with lmac-run in mcps.json only (no manifest directory) → lmac-run starts → tools appear in gateway → tool execution works
2. User calls a lmac-run tool via Claude → request routes through gateway → lmac-run processes it → result returned to Claude

## Out of Scope

- Modifying lmac-run's internal code
- Adding new lmac-run features
- lmac-run's own documentation

## Notes for the Agent

- Read lmac-run's manifest.json first to extract the exact command, args, and env
- Test by temporarily removing the manifest.json watch path and relying solely on mcps.json
- This is a validation spec — the importer (SPEC-026-002) does the heavy lifting, this confirms it worked for this specific MCP
