---
id: SPEC-006
priority: 1
layer: 2
type: feature
status: done
after: []
prior_attempts:
  - "2026-03-26: Backend complete (registry, persistence, socket, tests). UI gap: Shipyard shows only in detail pane when nothing selected — NOT in sidebar. Must appear as sidebar entry above child MCPs with tool controls."
created: 2026-03-26
---

# Expose Shipyard as First-Class Server in Gateway Sidebar

## Problem

Shipyard runs as an MCP server itself — listening on a Unix domain socket and exposing tools like `shipyard_status`, `shipyard_health`, `shipyard_logs`, `shipyard_gateway_call`. The backend is fully implemented: tools are registered in GatewayRegistry, per-tool enable/disable persists to UserDefaults, disabled tools return `tool_unavailable` errors.

**However, Shipyard is invisible in the Gateway sidebar.** The `shipyardCardView` only appears as the detail pane fallback when no child MCP is selected. Users don't know it exists because there's no sidebar entry for it — they must deselect all servers to stumble upon it.

The user's explicit requirement: **Shipyard must appear in the sidebar, above child MCPs, with the same controls child MCPs have** (tool count, per-tool enable/disable in detail pane). The only difference: no MCP-level Gateway toggle (Shipyard can't be disabled wholesale — it's the orchestrator).

## What Already Works (DO NOT REWRITE)

These are complete and tested — do not touch unless a bug is found:

- `GatewayRegistry.isShipyardServer()` — identifies Shipyard as special
- `shipyard__` tool namespacing in registry
- `shipyard.tool.shipyard.{tool_name}.enabled` UserDefaults persistence
- `handleShipyardTools()` in SocketServer — socket method returning tool catalog
- Per-tool enable/disable toggles in `shipyardCardView`
- Disabled tools return `tool_unavailable` error via `dispatchRequest`
- `discover()` registers hardcoded Shipyard tools in GatewayRegistry
- Tests: GatewayIntegrationTests, SystemLogMetadataIntegrationTests, LogMetadataHelperTests

## Requirements (UI changes only)

- [ ] R1: Add Shipyard as a **permanent entry at the top of the Gateway sidebar**, visually separated from child MCPs
- [ ] R2: Shipyard sidebar row shows: status indicator (green dot), "Shipyard" label, tool count (e.g., "6 tools")
- [ ] R3: Shipyard sidebar row does NOT have a Gateway toggle (no MCP-level disable — only tool-level)
- [ ] R4: Clicking Shipyard in sidebar shows its tool catalog in the detail pane (reuse existing `shipyardCardView` or `toolCatalogView`)
- [ ] R5: Shipyard row is **always visible** — it doesn't depend on `registry.registeredServers` (it's not a child MCP)
- [ ] R6: Shipyard row is visually distinct from child MCPs (e.g., section header, separator, or subtle accent)
- [ ] R7: When Shipyard is selected, detail pane shows per-tool toggles (already implemented in `shipyardCardView`)
- [ ] R8: Selection state: user can click Shipyard OR a child MCP — standard `NavigationSplitView` selection behavior

## Acceptance Criteria

- [x] AC 1: Gateway sidebar shows "Shipyard" entry **above** all child MCP rows, always visible
- [x] AC 2: Shipyard row displays green status dot + "Shipyard" label + "{N} tools" count
- [x] AC 3: Shipyard row has NO Gateway toggle (child MCPs still have theirs)
- [x] AC 4: Clicking Shipyard row shows tool catalog in detail pane with per-tool enable/disable toggles
- [x] AC 5: Shipyard row is visually separated from child MCPs (Section header, divider, or distinct styling)
- [x] AC 6: Shipyard selection works alongside child MCP selection (clicking a child MCP deselects Shipyard and vice versa)
- [x] AC 7: If no servers exist, Shipyard row still appears in sidebar (it's always present)
- [x] AC 8: Shipyard tools auto-discover on Gateway tab appear (extracted `registerShipyardTools()` called in `.task` on tab appear — no click required)
- [x] AC 9: Build succeeds with zero errors; all existing tests pass

## Context

**Key Files (read these first):**
- `Shipyard/Views/GatewayView.swift` — ALL changes go here. Contains:
  - `serverListView` (line ~56): sidebar List of `registry.registeredServers` — add Shipyard above this
  - `detailView` (line ~87): shows `shipyardCardView` when nothing selected OR `toolCatalogView` when child MCP selected — refactor to also show Shipyard detail when Shipyard is selected
  - `shipyardCardView` (line ~204): existing Shipyard tool catalog — reuse for Shipyard detail
  - `GatewayServerRow` (line ~467): existing row component for child MCPs — reference for Shipyard row styling
- `Shipyard/Models/GatewayRegistry.swift` — has `isShipyardServer()`, tool storage, enable/disable logic

**Architecture constraint:** `selectedServer` binding is `MCPServer?`. Shipyard is NOT an MCPServer. Options:
1. Change selection to an enum: `.shipyard | .childMCP(MCPServer)` — cleanest
2. Use a separate `@State var isShipyardSelected: Bool` and deselect `selectedServer` when Shipyard tapped
3. Create a synthetic MCPServer for Shipyard — not recommended (leaky abstraction)

Option 1 (enum) is preferred. Option 2 is acceptable if simpler.

**Visual reference (what the sidebar currently looks like):**
```
[ cortex          Gateway [toggle] ]   ← child MCP
[ lmac-run        Gateway [toggle] ]   ← child MCP
[ hear-me-say     Gateway [toggle] ]   ← child MCP
[ lmstudio        Gateway [toggle] ]   ← child MCP
```

**What it should look like:**
```
  Shipyard                               ← NEW: always-present, no toggle
  ● Running · 6 tools
─────────────────────────────────────
[ cortex          Gateway [toggle] ]
[ lmac-run        Gateway [toggle] ]
[ hear-me-say     Gateway [toggle] ]
[ lmstudio        Gateway [toggle] ]
```

## Scenarios

1. **User opens Gateway tab** → Sidebar shows Shipyard at top + child MCPs below. Nothing selected by default → detail pane shows Shipyard tool catalog (existing behavior preserved).

2. **User clicks Shipyard in sidebar** → Shipyard row highlighted. Detail pane shows Shipyard tool catalog with per-tool toggles. Child MCPs deselected.

3. **User clicks a child MCP** → Child MCP highlighted, Shipyard deselected. Detail pane shows child MCP's tool catalog (existing behavior).

4. **No child MCPs registered** → Sidebar shows only Shipyard row. Detail pane shows Shipyard tools. No "empty state" confusion.

5. **User toggles a Shipyard tool** → Toggle updates GatewayRegistry + UserDefaults immediately. Already implemented.

## Out of Scope

- Uptime display (deferred — needs ProcessStats tracking)
- Restart/Logs buttons on Shipyard card (deferred — restart semantics unclear for orchestrator)
- Visual distinction beyond section separator (no special colors/borders needed — placement is enough)
- Any backend/model changes — this is UI-only
- Changes to SocketServer, GatewayRegistry model logic, or test files (unless build requires it)

## Implementation Notes

**Changes completed 2026-03-26:**

1. **Auto-register Shipyard tools on tab appear** — `registerShipyardTools()` was extracted from `discover()` and called in `.task` on `GatewayView` appear. Shipyard now shows 6 tools immediately without requiring a manual Discover click.

2. **Removed "Gateway" label from GatewayServerRow** — The redundant "Gateway" text label next to the toggle in child MCP rows has been removed, leaving only the toggle itself.

3. **Removed "Shipyard Running" header from shipyardCardView** — The detail pane no longer shows a redundant header (name + green dot + "Running" text + background). The tool list now starts directly in the detail pane.

## Notes for the Agent

- **Read GatewayView.swift completely** before making changes — understand the NavigationSplitView structure
- **The selection binding is the key challenge.** Currently `@Binding var selectedServer: MCPServer?`. You need to handle Shipyard selection separately since it's not an MCPServer. Enum approach preferred.
- **Reuse `shipyardCardView`** for the detail pane — it already has the right tool list and toggles
- **Don't break existing child MCP selection** — this is the most important constraint
- **Run `BuildProject` after changes** — zero errors required
- **Run existing tests** — they must still pass (especially GatewayIntegrationTests, GatewayRegistryTests)
