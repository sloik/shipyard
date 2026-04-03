---
id: SPEC-026-002
priority: 2
layer: 3
type: feature
status: done
after: [SPEC-026-003]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# Manifest Cutover and Importer

## Problem

Shipyard currently discovers child MCPs from two sources: `manifest.json` files in watched directories (legacy) and `mcps.json` config entries (SPEC-019). For the public release, `mcps.json` must be the sole mechanism. Existing users who have MCPs configured via manifest.json need a seamless one-time import that migrates their configurations to mcps.json without losing any data.

## Requirements

- [ ] Implement one-time importer that reads all discovered manifest.json MCPs and writes equivalent entries to mcps.json
- [ ] Importer runs automatically on first launch after update (detects "never imported" state)
- [ ] After successful import, write a marker (e.g., `.manifest-imported` file or flag in mcps.json) to prevent re-import
- [ ] If import fails partway, original manifest.json files remain untouched and import retries on next launch
- [ ] Log every imported MCP to system log with name, source path, and status (success/skip/fail)
- [ ] After import, manifest.json discovery becomes read-only (display in UI as "legacy — migrate to config")
- [ ] New MCPs can only be added via mcps.json (manifest.json is no longer writable from the UI)
- [ ] Add UI indicator showing import status (imported N MCPs, or "import pending", or "no legacy MCPs found")

## Acceptance Criteria

- [ ] AC 1: Given 3 MCPs in manifest.json directories, after import all 3 appear in mcps.json with correct name, command, args, and env
- [ ] AC 2: Running the app a second time does not re-import (marker prevents duplicate entries)
- [ ] AC 3: If mcps.json write fails (disk full simulation), manifest.json files are unchanged and import retries next launch
- [ ] AC 4: System log contains one line per imported MCP with format: `[Import] Migrated {name} from {path}/manifest.json`
- [ ] AC 5: After import, attempting to add a new MCP via manifest directory has no effect (directory watcher ignores new manifests)
- [ ] AC 6: Legacy MCPs show a visual indicator in the sidebar distinguishing them from config MCPs
- [ ] AC 7: Config MCPs imported from manifests include a `migratedFrom` field preserving the original manifest path

## Context

- `MCPRegistry.swift` handles manifest discovery via `DirectoryWatcher`
- `MCPConfig.swift` defines the `mcps.json` format (SPEC-019)
- The importer needs PathManager (SPEC-026-003) to resolve where mcps.json lives
- Import must handle: duplicate names (manifest MCP already has a mcps.json entry), missing binaries, relative vs absolute command paths
- `mcps.json` format from SPEC-019: `{ "mcps": { "name": { "command": "...", "args": [...], "env": {...} } } }`

## Scenarios

1. User with 3 manifest MCPs updates Shipyard → app launches → importer detects no marker → reads manifests → writes 3 entries to mcps.json → writes marker → sidebar shows all 3 MCPs → user sees "Imported 3 MCPs from legacy config" in system log
2. User with 1 manifest MCP and 1 existing config MCP → importer detects manifest MCP already in mcps.json (same name) → skips it → logs "Skipped {name}: already in config" → imports remaining
3. User kills app during import → next launch detects no marker → re-runs import → succeeds → no duplicate entries (idempotent write)

## Out of Scope

- Deleting manifest.json files (they remain as read-only backups)
- Migrating manifest.json format itself (it stays as-is, just unused)
- UI for editing legacy manifest MCPs (they become read-only)
- Reverse migration (mcps.json back to manifest.json)

## Notes for the Agent

- Study `MCPRegistry.swift` for current manifest discovery flow
- Study `MCPConfig.swift` for mcps.json read/write patterns
- The importer should be a standalone service (`ManifestImporter.swift`) called once at app startup before registry initialization
- Idempotency is critical: the importer must produce the same result regardless of how many times it runs
