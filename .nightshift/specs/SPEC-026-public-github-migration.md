---
id: SPEC-026
priority: 2
layer: 3
type: main
status: done
after: [SPEC-025]
children:
  - SPEC-026-001
  - SPEC-026-002
  - SPEC-026-003
  - SPEC-026-004
  - SPEC-026-005
  - SPEC-026-006
  - SPEC-026-007
  - SPEC-026-008
  - SPEC-026-009
implementation_order:
  - SPEC-026-001
  - SPEC-026-003
  - SPEC-026-002
  - SPEC-026-007
  - SPEC-026-008
  - SPEC-026-009
  - SPEC-026-004
  - SPEC-026-006
  - SPEC-026-005
prior_attempts: []
created: 2026-03-31
---

# Public GitHub Migration

## Problem

Shipyard is currently a private repository with personal paths, internal tooling references, and manifest-based MCP discovery that assumes a specific local directory layout. To make it a useful open-source project, it needs to be cleaned up for public consumption: no secrets, no personal paths, config-based MCP discovery as the primary mechanism, proper governance files, contributor-friendly documentation, and a narrowed public surface for the Nightshift automation layer.

## Context

- Shipyard is a native macOS SwiftUI MCP orchestrator managing child MCPs via a gateway pattern
- SPEC-019 added config-sourced MCPs from `mcps.json` alongside the existing `manifest.json` discovery
- The migration makes `mcps.json` the sole discovery mechanism for the public release
- Existing private users get a one-time import from `manifest.json` to `mcps.json`
- Child MCPs: lmac-run, lmstudio, hear-me-say, mac-runner
- Architecture: Shipyard.app (SwiftUI), ShipyardBridge (CLI stdio MCP proxy), ShipyardBridgeLib (shared library)

## Implementation Order Rationale

1. **SPEC-026-001** (baseline/governance) — must come first; ensures the repo is clean before any public-facing work
2. **SPEC-026-003** (centralized paths/binary setup) — PathManager is needed by the importer and per-MCP migrations
3. **SPEC-026-002** (manifest cutover/importer) — the import mechanism, depends on centralized paths
4. **SPEC-026-007/008/009** (per-MCP migrations) — each child MCP migrated from manifest to mcps.json
5. **SPEC-026-004** (Nightshift public surface) — narrowing happens after code changes stabilize
6. **SPEC-026-006** (GitHub issue intake) — templates depend on knowing the final spec structure
7. **SPEC-026-005** (docs/install rewrite) — last, because it documents the final state

## Out of Scope

- Rewriting ShipyardBridge in Swift (separate effort)
- Adding new child MCPs
- CI/CD pipeline setup (separate spec)
- App Store distribution
- Windows/Linux support

## Notes for the Agent

Do not implement this spec directly. Run `nightshift-dag plan SPEC-026` to generate `execution-plan.json`, then execute children in the plan's `execution_order`. All children reference NFR-003 for migration safety constraints.
