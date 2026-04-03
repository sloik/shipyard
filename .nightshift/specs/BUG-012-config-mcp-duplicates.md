---
id: BUG-012
priority: 1
layer: 3
type: bug
status: done
after: [SPEC-019]
created: 2026-03-28
---

# Config-Sourced MCPs Appear as Broken Duplicates in Registry

## Problem

After SPEC-019 (Standard MCP Registration), MCPs imported from Claude Desktop config into `mcps.json` appear as duplicate, broken entries in Shipyard's menu bar and server list. Six config-sourced MCPs (lldb-mcp, shipyard, xcode, jcodemunch, mcp-obsidian-argo, pencil) show `Error: Server manifest has no root directory set` because they are stdio MCPs without a `rootDirectory` on their synthesized manifest.

### Symptoms

1. **"shipyard" (lowercase) duplicates the synthetic "Shipyard" (uppercase)** — loadConfig doesn't check against synthetic-sourced servers, only manifest-sourced ones.
2. **Config-sourced stdio MCPs fail to start** — `ProcessManager.start()` requires `manifest.rootDirectory`, but config-sourced manifests are synthesized from mcps.json entries which don't provide a root directory.
3. **Error-state MCPs clutter the UI** — 6 error entries alongside 4 healthy ones makes the menu bar noisy and confusing.

### Root Cause

`MCPRegistry.loadConfig()` (lines 265–365) creates `MCPManifest` objects from `MCPConfig.ServerEntry` but:

1. **Never sets `rootDirectory`** on the synthesized manifest. For stdio MCPs, `ProcessManager.start()` at line 68 throws `ProcessManagerError.noRootDirectory`.
2. **Name collision check is case-sensitive** and only checks `registeredByName` (manifest-sourced servers). The synthetic Shipyard server (SPEC-008) is NOT in `registeredServers` — it's a `@State` in MainWindow — so "shipyard" from config slips through.
3. **`configCwd` is set but not used as fallback** — `server.configCwd = entry.cwd` is stored but `ProcessManager.start()` doesn't fall back to it when `rootDirectory` is nil.

### Broken SPEC-019 Acceptance Criteria

- **R8** ("Name collision: manifest wins unless override=true") — partially broken. Dedup works for manifest-vs-config but NOT for synthetic-vs-config.
- **R11** ("Config MCPs appear in all UI views with correct source badge") — technically met, but the error state makes them useless. Config-sourced stdio MCPs should either work or not be registered.

## Requirements

### R1: Config stdio MCPs use `cwd` or command path as rootDirectory fallback

When `loadConfig()` creates a synthesized manifest for a stdio MCP:
- If `entry.cwd` is set → use it as `rootDirectory`
- Else if `entry.command` is an absolute path → use `dirname(command)` as `rootDirectory`
- Else → use home directory as fallback

### R2: Name collision check includes synthetic-sourced servers

`loadConfig()` must check `registeredByName` against ALL sources (manifest + synthetic + existing config), not just manifest. The check should be case-insensitive on the name.

### R3: `reloadConfig()` applies the same rootDirectory and dedup fixes

Same logic as R1 and R2 applied to `reloadConfig()`.

### R4: Config-sourced MCPs with unresolvable commands show "disabled" not "error"

If a config-sourced stdio MCP's command cannot be found on PATH and no cwd is set, mark it `disabled = true` with a descriptive reason rather than letting it fail with a cryptic rootDirectory error at start time.

## Acceptance Criteria

- AC1: Config-sourced stdio MCP with `cwd` set starts successfully using `cwd` as working directory.
- AC2: Config entry named "shipyard" (any case) is skipped when synthetic Shipyard server exists. Log message: "Name collision (synthetic wins)".
- AC3: Config entry named same as a manifest server (case-insensitive) is skipped. Existing test for case-sensitive still passes.
- AC4: `reloadConfig()` applies same dedup and rootDirectory logic.
- AC5: All existing MCPRegistry tests pass. No regressions in SPEC-019 test suite.

## Target Files

- `Shipyard/Services/MCPRegistry.swift` — `loadConfig()` and `reloadConfig()`
- `Shipyard/Services/ProcessManager.swift` — `start()` rootDirectory fallback
- `Shipyard/Models/MCPManifest.swift` — check if `rootDirectory` is settable or needs a new init path

## Test Files

- `ShipyardTests/MCPRegistryConfigTests.swift` — add tests for R1–R4
- `ShipyardTests/BridgeProtocolTests.swift` — verify no regression

## Context

- SPEC-019 implementation: `MCPRegistry.loadConfig()` lines 261–365
- ProcessManager start: `ProcessManager.start()` line 68 (`guard let rootDir = manifest.rootDirectory`)
- Synthetic Shipyard: `MainWindow.initShipyardServer()` — NOT in `registeredServers`
- MCPManifest: check `rootDirectory` computed property
