---
id: BUG-014
priority: 2
layer: 2
type: bugfix
status: done
after: [SPEC-019]
violates: [SPEC-019, SPEC-008]
prior_attempts: []
created: 2026-03-29
---

# Sidebar Ordering and Source Badge Missing for Config MCPs

## Problem

Two SPEC-019 requirements are not implemented in MainWindow's server sidebar:

1. **No source badge on config-sourced MCPs.** Config MCPs (jcodemunch, pencil, shipyard, lldb-mcp, xcode, mcp-obsidian-argo) show "Configured via Claude Desktop" in the description but lack a visual pill/badge distinguishing them from manifest-sourced MCPs. SPEC-019 line 546 calls for "source badge (config vs manifest)" on MCPRowView. The screenshot shows config MCPs are visually identical to manifest MCPs.

2. **Sidebar is not sorted per SPEC-019 R8a.** The list renders in registry insertion order instead of the required ordering: **Shipyard (first) → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)**. In the screenshot, Shipyard appears after jcodemunch and pencil (both config-sourced), violating AC 11a.

### Affected Spec Requirements

- **SPEC-019 R8a:** "Sidebar ordering: Shipyard (first) → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)"
- **SPEC-019 AC 11a:** "Sidebar order is: Shipyard → Manifest MCPs (alphabetical) → Config MCPs (alphabetical)"
- **SPEC-019 line 546:** "MCPRowView — source badge (config vs manifest)"
- **SPEC-008 AC 7:** "Shipyard is always first in the list (above all child MCPs), regardless of sort order"

## Requirements

### R1: Source badge on MCPRowView for config-sourced MCPs

MCPRowView should display a small pill/badge indicating the source when `server.source == .config`:

- Badge text: "JSON" (matches the `mcps.json` origin)
- Style: `.font(.caption2)`, muted background (e.g. `.secondary` fill with contrasting text), rounded corners
- Position: inline after the server name or on the description line (next to "Configured via Claude Desktop")
- Manifest-sourced MCPs do NOT show a badge (they are the default/expected source)

### R2: Sidebar ordering per SPEC-019 R8a

`MainWindow.swift` `serversView` must sort `registry.registeredServers` into three groups, rendered in order:

1. **Shipyard** (synthetic server, always first — already hardcoded via SPEC-008)
2. **Manifest MCPs** (`.source == .manifest`) — sorted alphabetically by `manifest.name`
3. **Config MCPs** (`.source == .config`) — sorted alphabetically by `manifest.name`

SPEC-019 line 547 notes: "split by source, sort alphabetically, render Shipyard → Manifest → Config. **`.tag()` types must match the selection binding type**"

## Acceptance Criteria

- [ ] AC 1: Config-sourced MCPs show a "JSON" pill badge in MCPRowView
- [ ] AC 2: Manifest-sourced MCPs do NOT show a source badge
- [ ] AC 3: Shipyard is always the first entry in the sidebar
- [ ] AC 4: Manifest MCPs appear after Shipyard, sorted alphabetically by name
- [ ] AC 5: Config MCPs appear after manifest MCPs, sorted alphabetically by name
- [ ] AC 6: Existing tests pass; no compile errors
- [ ] AC 7: Selection still works after reordering (`.tag()` types match binding)

## Context

**Key Files:**

- `Shipyard/Views/MainWindow.swift` — `serversView` renders the sidebar list. Currently `List(registry.registeredServers, ...)` without sorting. Shipyard synthetic server is already prepended (SPEC-008).
- `Shipyard/Views/MCPRowView.swift` — Row component. Needs source badge addition. `server.source` is available as `MCPSource` enum (`.manifest`, `.config`, `.synthetic`).
- `Shipyard/Models/MCPServer.swift` — `MCPSource` enum at line 45: `.manifest`, `.config`, `.synthetic`. The `source` property is `nonisolated let` at line 84.
- `Shipyard/Views/GatewayView.swift` — Gateway sidebar at line 91 also uses `List(registry.registeredServers, ...)` — may need same sorting fix for consistency.

**DevKB:**
- `swift.md` #11 — mismatched `.tag()` types cause silent selection failure. Ensure sorted array maintains the same type as the selection binding.

## Test Plan

- [ ] Visual: config MCPs show "JSON" badge, manifest MCPs don't
- [ ] Visual: sidebar order is Shipyard → manifest (alpha) → config (alpha)
- [ ] Functional: clicking any server in reordered list selects it correctly
- [ ] Functional: context menu works on all servers after reorder
