---
id: SPEC-008
priority: 1
layer: 2
type: feature
status: done
after: [SPEC-006]
prior_attempts: []
created: 2026-03-26
---

# Shipyard as First Server on the Servers Tab — Full MCP Parity

## Problem

Shipyard (the orchestrator) is invisible on the Servers tab. Only child MCPs appear. Users expect to see Shipyard itself listed as the first server with **identical** presentation and controls to any child MCP: name, description, status, PID, memory, Start/Stop/Restart, detail pane with logs, and all other controls.

Shipyard IS an MCP server (it listens on a Unix domain socket). It should be treated as one everywhere in the UI — no special cases, no "always running" labels, no missing controls.

## Requirements

- [ ] R1: Shipyard appears as the **first entry** in the Servers tab sidebar, above all child MCPs
- [ ] R2: Shipyard's row uses **MCPRowView** (the same component child MCPs use) — identical layout, fonts, spacing
- [ ] R3: Shipyard row shows: name ("Shipyard"), description ("MCP orchestrator — manages child servers via gateway"), green status dot, PID (of the Shipyard.app process), memory usage, "Running" label
- [ ] R4: Clicking Shipyard in sidebar shows the **same detail pane** as child MCPs: LogViewer + toolbar with Start/Stop/Restart/Auto-Restart controls
- [ ] R5: Shipyard detail pane toolbar has Start/Stop/Restart buttons (Stop quits the socket listener or shows "Cannot stop orchestrator" — implementation choice for agent)
- [ ] R6: Shipyard has a context menu matching child MCPs: Stop/Restart (when running), Start (when stopped), Reveal Log in Finder, Open Logs Folder
- [ ] R7: Shipyard logs are visible in the LogViewer when selected (pull from AppLogger or system log entries)

## Acceptance Criteria

- [ ] AC 1: Servers tab sidebar shows "Shipyard" as the first entry above all child MCPs
- [ ] AC 2: Shipyard row is rendered by MCPRowView (not a custom component)
- [ ] AC 3: Shipyard row displays: name, description, green status dot, PID, memory, "Running"
- [ ] AC 4: Clicking Shipyard shows LogViewer in the detail pane (matching child MCP behavior)
- [ ] AC 5: Detail pane toolbar shows Start/Stop/Restart/Auto-Restart controls (Start/Stop may be disabled for orchestrator — agent's choice)
- [ ] AC 6: Right-clicking Shipyard shows the same context menu as child MCPs
- [ ] AC 7: Shipyard is always first in the list (above all child MCPs), regardless of sort order
- [ ] AC 8: Build succeeds with zero errors; all existing tests pass
- [ ] AC 9: If no child MCPs are registered, Shipyard still appears in the sidebar

## Context

**Key Files (read ALL before coding):**

### MainWindow.swift — Primary target for Servers tab changes
- `serversView` (line ~81): NavigationSplitView with `List(registry.registeredServers, ...)` — Shipyard needs to be injected above this list
- Detail pane (line ~130): shows LogViewer when server selected, empty state when not — must also handle Shipyard selection
- Selection binding: `@Binding var selectedServer: MCPServer?` — Shipyard must work with this OR use a similar pattern to SPEC-006's Gateway approach

### MCPRowView.swift — Row component (DO NOT MODIFY unless absolutely necessary)
- Takes `MCPServer` as parameter — displays name, description, status, PID, memory, dep issues
- Context menu: Start/Stop/Restart, Reveal Log, Open Logs Folder
- **The challenge:** MCPRowView requires an MCPServer object. Shipyard needs a synthetic MCPServer instance.

### MCPServer model — Check its structure
- Find the MCPServer class definition (likely in Models/)
- Understand required properties: manifest, state, processStats, healthStatus, restartCount, dependencyResults, etc.
- Determine if a synthetic MCPServer can be created for Shipyard (with hardcoded manifest, always-running state, real PID/memory stats)

### GatewayView.swift — Reference for SPEC-006 approach
- SPEC-006 already added Shipyard to the Gateway sidebar — look at how selection was handled there
- The Servers tab should use a consistent approach

## Implementation Strategy

**Recommended approach: Create a synthetic MCPServer for Shipyard**

1. Create a static/singleton `MCPServer` representing Shipyard itself:
   - `manifest.name = "Shipyard"`
   - `manifest.description = "MCP orchestrator — manages child servers via gateway"`
   - `state = .running` (always, while app is alive)
   - `processStats` = real stats from `ProcessInfo.processInfo` (PID, memory)
   - `dependencyResults` = empty (no deps to check)

2. Insert it at position 0 in the server list, or render it above the `List(registry.registeredServers, ...)` in a separate section

3. Handle selection: when Shipyard is clicked, show its detail pane (LogViewer with Shipyard's own logs from AppLogger)

**Alternative approach: Separate section above the list**
- Add a dedicated Section for Shipyard above the `List`
- Still uses MCPRowView (pass the synthetic MCPServer)
- Selection requires the same enum pattern as SPEC-006

**The agent should choose whichever approach integrates most naturally with the existing code.**

## Scenarios

1. **User opens Servers tab** → Sidebar shows Shipyard at top, child MCPs below. Shipyard shows green dot, "Shipyard", description, PID, memory, "Running".

2. **User clicks Shipyard** → Detail pane shows LogViewer with Shipyard's own log entries. Toolbar shows Start/Stop/Restart controls.

3. **User right-clicks Shipyard** → Context menu: Restart, Reveal Log in Finder, Open Logs Folder. (Stop may show but be disabled, or show "Quit Shipyard".)

4. **No child MCPs registered** → Sidebar shows only Shipyard. No "empty state" overlay.

5. **User clicks "Start All"** → Should NOT affect Shipyard (it's already running). Only starts child MCPs.

6. **User clicks "Stop All"** → Should NOT stop Shipyard. Only stops child MCPs.

## Out of Scope

- Changing MCPRowView component structure (reuse as-is)
- Shipyard auto-restart logic (it's the app itself)
- Shipyard health checks (defer to later)
- LogViewer changes (reuse existing component)
- Any Gateway tab changes (covered by SPEC-006)

## Notes for the Agent

- **Read MCPServer class definition first** — understand all required properties
- **Read MCPRowView.swift** — understand what it expects from MCPServer
- **Read MainWindow.swift serversView** — understand the NavigationSplitView structure
- **The synthetic MCPServer for Shipyard must have real PID and memory** — use `ProcessInfo.processInfo.processIdentifier` for PID, use `task_info` or similar for memory
- **Start All / Stop All must skip Shipyard** — add a check like `server !== shipyardServer` or `server.manifest.name != "Shipyard"`
- **LogViewer for Shipyard** — if LogViewer requires process-specific logs, you may need to feed it Shipyard's AppLogger entries or create a minimal log view
- **Build after every change** — zero errors required
- **Run existing tests** — they must still pass
