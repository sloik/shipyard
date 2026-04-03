---
id: SPEC-026-009
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

# lmstudio: Manifest to JSON Migration

## Problem

The lmstudio MCP is currently discovered via manifest.json in its directory. After the manifest cutover (SPEC-026-002), it needs a proper mcps.json entry. This spec validates that lmstudio works correctly when configured solely through mcps.json, with no manifest.json dependency.

## Requirements

- [ ] Create a verified mcps.json entry for lmstudio with correct command, args, and env
- [ ] Verify lmstudio starts successfully from mcps.json config (no manifest.json present)
- [ ] Verify all lmstudio tools are discoverable through the gateway after migration
- [ ] Verify tool execution works end-to-end (call a lmstudio tool via gateway, get correct result)
- [ ] Document the mcps.json entry in the per-MCP migration log

## Acceptance Criteria

- [ ] AC 1: lmstudio entry exists in mcps.json with command, args, and any required env vars
- [ ] AC 2: Removing lmstudio's manifest.json directory from the watch list does not affect lmstudio availability
- [ ] AC 3: `shipyard_gateway_discover` lists lmstudio tools with correct `lmstudio__` prefix
- [ ] AC 4: Calling a lmstudio tool via `shipyard_gateway_call` returns a valid result
- [ ] AC 5: lmstudio appears in the Shipyard sidebar as a config MCP (not legacy/manifest)
- [ ] AC 6: System log shows lmstudio starting from config source, not manifest source

## Context

- lmstudio is an LM Studio integration MCP — check its manifest.json for the exact command and arguments
- Location: likely in `ManagedProjects/Tools/mcp/lmstudio-mcp/`
- The mcps.json format: `{ "mcps": { "lmstudio": { "command": "...", "args": [...], "env": {...} } } }`
- SPEC-026-002 provides the importer that creates the initial entry; this spec verifies and validates it

## Scenarios

1. Shipyard launches with lmstudio in mcps.json only (no manifest directory) → lmstudio starts → tools appear in gateway → tool execution works
2. User calls a lmstudio tool via Claude → request routes through gateway → lmstudio processes it → result returned to Claude

## Out of Scope

- Modifying lmstudio's internal code
- Adding new lmstudio features
- lmstudio's own documentation

## Notes for the Agent

- Read lmstudio's manifest.json first to extract the exact command, args, and env
- Test by temporarily removing the manifest.json watch path and relying solely on mcps.json
- This is a validation spec — the importer (SPEC-026-002) does the heavy lifting, this confirms it worked for this specific MCP
