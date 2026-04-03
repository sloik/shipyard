---
id: SPEC-026-007
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

# hear-me-say: Manifest to JSON Migration

## Problem

The hear-me-say MCP is currently discovered via manifest.json in its directory. After the manifest cutover (SPEC-026-002), it needs a proper mcps.json entry. This spec validates that hear-me-say works correctly when configured solely through mcps.json, with no manifest.json dependency.

## Requirements

- [ ] Create a verified mcps.json entry for hear-me-say with correct command, args, and env
- [ ] Verify hear-me-say starts successfully from mcps.json config (no manifest.json present)
- [ ] Verify all hear-me-say tools are discoverable through the gateway after migration
- [ ] Verify tool execution works end-to-end (call a hear-me-say tool via gateway, get correct result)
- [ ] Document the mcps.json entry in the per-MCP migration log

## Acceptance Criteria

- [ ] AC 1: hear-me-say entry exists in mcps.json with command, args, and any required env vars
- [ ] AC 2: Removing hear-me-say's manifest.json directory from the watch list does not affect hear-me-say availability
- [ ] AC 3: `shipyard_gateway_discover` lists hear-me-say tools with correct `hear-me-say__` prefix
- [ ] AC 4: Calling a hear-me-say tool via `shipyard_gateway_call` returns a valid result
- [ ] AC 5: hear-me-say appears in the Shipyard sidebar as a config MCP (not legacy/manifest)
- [ ] AC 6: System log shows hear-me-say starting from config source, not manifest source

## Context

- hear-me-say is a speech/audio MCP — check its manifest.json for the exact command and arguments
- Location: likely in `ManagedProjects/Tools/mcp/hear-me-say/`
- The mcps.json format: `{ "mcps": { "hear-me-say": { "command": "...", "args": [...], "env": {...} } } }`
- SPEC-026-002 provides the importer that creates the initial entry; this spec verifies and validates it

## Scenarios

1. Shipyard launches with hear-me-say in mcps.json only (no manifest directory) → hear-me-say starts → tools appear in gateway → tool execution works
2. User calls a hear-me-say tool via Claude → request routes through gateway → hear-me-say processes it → result returned to Claude

## Out of Scope

- Modifying hear-me-say's internal code
- Adding new hear-me-say features
- hear-me-say's own documentation

## Notes for the Agent

- Read hear-me-say's manifest.json first to extract the exact command, args, and env
- Test by temporarily removing the manifest.json watch path and relying solely on mcps.json
- This is a validation spec — the importer (SPEC-026-002) does the heavy lifting, this confirms it worked for this specific MCP
