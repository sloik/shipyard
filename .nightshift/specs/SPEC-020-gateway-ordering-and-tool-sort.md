---
id: SPEC-020
priority: 2
layer: 2
type: feature
status: done
after: [BUG-014]
prior_attempts: []
created: 2026-03-29
---

# Gateway Tab — Sidebar Ordering and Tool Alphabetical Sort

## Problem

Two ordering requirements are absent from the Gateway tab:

1. **Gateway sidebar has no authoritative ordering spec.** The Servers tab sidebar ordering is defined in BUG-014 (Shipyard → manifest MCPs alpha → JSON MCPs alpha). The same ordering rule must apply to the Gateway tab sidebar, but no spec mandates it — leaving it fragile and vulnerable to regression.

2. **Tools in the detail view are displayed in discovery order.** When a user selects an MCP in the Gateway tab, its tools are shown in whatever order the child MCP returned them during discovery. For MCPs with many tools this makes the list hard to scan. Tools should be sorted alphabetically.

## Requirements

### R1: Gateway sidebar follows the canonical server ordering

The Gateway tab's server sidebar MUST display servers in the same three-group order as the Servers tab:

1. **Shipyard** — always first
2. **Manifest MCPs** — servers sourced from `manifest.json` files, sorted A→Z by name (case-insensitive)
3. **JSON MCPs** — servers sourced from `mcps.json` / Claude Desktop config, sorted A→Z by name (case-insensitive)

This is the same ordering rule that `MCPRegistry.sortedServers` implements and that the Servers tab already uses.

### R2: Tools in the Gateway detail view are sorted alphabetically

When a user selects a server in the Gateway sidebar, the tool list in the detail pane MUST be displayed sorted A→Z by tool name (case-insensitive, un-namespaced name).

## Acceptance Criteria

### Sidebar Ordering (R1)

- [ ] AC 1: Shipyard is the first entry in the Gateway sidebar, above all child MCPs
- [ ] AC 2: Manifest MCPs appear after Shipyard, sorted A→Z by name (case-insensitive)
- [ ] AC 3: JSON MCPs appear after all manifest MCPs, sorted A→Z by name (case-insensitive)
- [ ] AC 4: When a manifest MCP and a JSON MCP share the same initial letter, the manifest MCP appears first
- [ ] AC 5: Server selection works correctly — selecting any server in the ordered list opens its tool detail

### Tool Sorting (R2)

- [ ] AC 6: Tools in the detail view are displayed A→Z by original (un-namespaced) tool name (case-insensitive)
- [ ] AC 7: A server with tools discovered in order `["zebra_tool", "alpha_tool", "middle_tool"]` displays them as: `alpha_tool`, `middle_tool`, `zebra_tool`
- [ ] AC 8: Toggling a tool's enabled state does NOT change the display order
- [ ] AC 9: Re-discovering tools (Discover button) re-sorts the updated tool list correctly
- [ ] AC 10: A server with 0 tools shows the "No Tools Discovered" empty state without errors

### Regression

- [ ] AC 11: All existing Gateway tests pass
- [ ] AC 12: Build succeeds with zero errors

## Context

### Key Files

- **`Shipyard/Views/GatewayView.swift`** — Gateway tab view. Contains the server sidebar list and the tool detail view for a selected server.
- **`Shipyard/Services/MCPRegistry.swift`** — `sortedServers` computed property implements the three-group canonical ordering. Already used by the Servers tab.
- **`Shipyard/Models/MCPServer.swift`** — `MCPSource` enum: `.synthetic` (Shipyard), `.manifest`, `.config`. Drives group assignment.
- **`GatewayTool`** (wherever defined) — has `originalName` (un-namespaced) and `prefixedName` (namespaced). `originalName` is the sort key for R2.

## Scenarios

### Scenario 1: User opens Gateway tab with mixed MCPs

Given: cortex (manifest), lmac-run (manifest), hear-me-say (manifest), jcodemunch (JSON), pencil (JSON), xcode (JSON).

Expected Gateway sidebar order:
1. Shipyard
2. cortex
3. hear-me-say
4. lmac-run
5. jcodemunch
6. pencil
7. xcode

User clicks each server — selection works, detail view opens.

### Scenario 2: User selects a server with many tools

User selects "jcodemunch" (15+ tools discovered in arbitrary order). Expected: tools appear A→Z. User finds `search_symbols` without hunting through a random list.

### Scenario 3: User re-discovers tools

User clicks Discover after a child MCP was restarted. Expected: updated tool list is still sorted A→Z.

### Scenario 4: Only Shipyard registered

No child MCPs. Gateway sidebar shows Shipyard only. Selecting it shows its tools sorted A→Z (or empty state if no tools discovered).

## Out of Scope

- User-configurable sort order (A→Z, Z→A, by frequency) — future spec
- Grouping tools by category — future spec
- Changing the Shipyard-first / manifest-before-config rule — governed by SPEC-008 and BUG-014
- Any changes to Servers tab ordering — addressed by BUG-014
