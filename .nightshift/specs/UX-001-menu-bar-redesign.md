---
id: UX-001
priority: 2
layer: 3
type: feature
status: done
after: [BUG-012]
created: 2026-03-28
---

# Menu Bar Popover — Full UX Redesign

## Problem

The current MenuBarView popover is 280px wide, uses flat typography, and shows all MCPs in a single list split only by Running/Stopped. With SPEC-019 adding config-sourced MCPs, the list is now longer and mixes manifest, config, and error-state servers without visual distinction. Key issues:

1. **Too narrow** — 280px truncates MCP names and status labels. Error messages are invisible.
2. **No source grouping** — manifest-sourced and config-sourced MCPs are interleaved. No visual hierarchy to distinguish managed vs. external MCPs.
3. **Error states not distinct** — a red 10px dot is the only indicator. No error message visible in the menu bar view. Users see "Error" but not WHY.
4. **Typography is flat** — section headers ("Running", "Stopped") use `.caption2` which is too small. Server names and status compete for attention.
5. **No disabled state visualization** — disabled MCPs look the same as idle ones.
6. **Control buttons cramped** — "Start All" / "Stop All" / "Open Shipyard" are stacked tightly.

## Design Principles

Based on macOS menu bar extra conventions (1Password, Docker Desktop, Raycast):

- **Width**: 360–400px for comfortable reading
- **Sections**: Clear visual grouping with headers
- **Density**: Compact but not cramped — 8px padding minimum
- **Hierarchy**: Server name > status > metadata (source, error, PID)
- **Error visibility**: Error messages shown inline with red styling
- **Interactivity**: Hover states, tooltips for truncated text

## Requirements

### R1: Wider popover (380px)

Change `MenuBarView` frame width from 280 to 380. Validate that it looks good on both 13" and 27" displays (macOS handles menu bar extra sizing).

### R2: Source-grouped sections

Replace the Running/Stopped split with a three-section layout:

```
┌──────────────────────────────────────┐
│  ● cortex          Running    ⏸      │
│  ● lmac-run        Running    ⏸      │
│  ● hear-me-say     Running    ⏸      │
│  ● lmstudio        Running    ⏸      │
│ ─────────────────────────────────── │
│  Config-sourced                      │
│  ○ remote-api  [JSON]  Idle    ▶     │
│ ─────────────────────────────────── │
│  ⚠ Issues (2)                        │
│  ✕ xcode  [JSON]  No root dir       │
│  ✕ pencil [JSON]  No root dir       │
│ ─────────────────────────────────── │
│  [Start All]  [Stop All]             │
│  [     Open Shipyard     ]           │
└──────────────────────────────────────┘
```

Section order:
1. **Healthy servers** (running + idle manifest-sourced) — no section header needed, these are the default
2. **Config-sourced** (running + idle config MCPs) — section header "Config" with JSON badge
3. **Issues** (any server in error state, regardless of source) — section header with warning icon and count
4. **Disabled** (collapsed by default, expand on click) — section header "Disabled (N)"

### R3: Error messages visible in menu

For servers in `.error(message)` state:
- Show the error message as a second line in `.caption` red text
- Truncate to 60 chars with `...` and full text in tooltip (`.help()`)
- Use `exclamationmark.triangle.fill` icon instead of the colored circle

### R4: Disabled servers styled distinctly

For `server.disabled == true`:
- Gray out the entire row (`.opacity(0.5)`)
- Show "Disabled" badge instead of play/pause button
- No start/stop toggle — just "Open Shipyard" context menu item

### R5: Typography hierarchy

- Section headers: `.caption.weight(.semibold)` + `.foregroundStyle(.secondary)` + uppercase
- Server name: `.callout.weight(.medium)` (keep current)
- Status label: `.caption2` (keep current)
- Error message: `.caption` + `ShipyardColors.error`
- Source badge (menu bar): `doc.text` SF Symbol (8pt, blue) with `.help("Configured via mcps.json")` tooltip. Text badge truncated at menu width — replaced with icon.
- Source badge (MCPRowView sidebar): `Text("JSON")` at 9pt medium weight, 4px horizontal / 2px vertical padding, blue tint background, `.fixedSize()` to prevent truncation. Replaced original `Label("JSON", systemImage: "doc.json")` which had misaligned icon+text and excessive padding.

### R6: Hover effect on server rows

Add subtle hover state:
- `.background(Color.primary.opacity(0.04))` on hover
- `RoundedRectangle(cornerRadius: 6)` clip shape (already present)
- Use `@State private var hoveredServer: MCPServer.ID?` + `.onHover`

### R7: "Start All" / "Stop All" as icon-only buttons

Compact the control bar:
- Replace text labels with icon-only buttons in a horizontal group
- `play.fill` for Start All, `stop.fill` for Stop All, `arrow.clockwise` for Restart All
- Keep "Open Shipyard" as a full-width text button below
- Add `.help()` tooltips on each icon button

### R8: Server count in section headers

Show counts: "Running (4)", "Config (2)", "Issues (3)", "Disabled (1)"

## Acceptance Criteria

- AC1: Popover width is 380px.
- AC2: Servers are grouped by source/state: healthy first, then config, then errors, then disabled.
- AC3: Error-state servers show the error message as red text below the name.
- AC4: Disabled servers are visually distinct (dimmed, no toggle).
- AC5: Section headers show server counts.
- AC6: Hover effect visible on server rows.
- AC7: Control buttons are compact with tooltips.
- AC8: No regressions — Start/Stop/Open Shipyard still work.
- AC9: Menu bar view renders correctly with 0 servers, 1 server, and 10+ servers.

## Target Files

- `Shipyard/Views/MenuBarView.swift` — primary redesign target

## Test Files

- Manual testing via menu bar. No automated UI tests for MenuBarView currently.

## Design Reference

The MCPRowView in MainWindow sidebar already has:
- Source badges (`[JSON]` for config)
- Error message display
- Health status indicators
- Process stats

The menu bar version should be a compact variant of the same information hierarchy.
