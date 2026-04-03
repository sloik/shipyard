---
id: UX-002
priority: 2
layer: 3
type: feature
status: done
after: [UX-001, BUG-012]
created: 2026-03-28
---

# Config MCP Context Menu — Edit Config Sheet + Reveal in Finder

## Problem

Config-sourced MCPs (from `mcps.json`) have the same context menu as manifest-sourced MCPs: Start/Stop/Restart + log actions. There's no way to edit a config-sourced MCP's configuration or find its config file from the UI. Users must manually locate and edit `~/.config/shipyard/mcps.json`.

## Requirements

### R1: "Edit Configuration" context menu item

Add a new context menu item **"Edit Configuration…"** (with `pencil.line` icon) to MCPRowView's context menu. Visible ONLY for `server.source == .config`.

When clicked, opens a **sheet** containing:
- The full `mcps.json` content in `SimpleJSONTextEditor` (the existing NSTextView-based editor from JSONEditorView)
- The editor cursor positioned at the beginning of the JSON object that defines THIS MCP (scroll to and select the `"server-name": {` line)
- A validation bar at the bottom (reuse the JSONEditorView pattern — debounced JSON parsing, error/warning display)
- **Save** button — writes the edited JSON back to `MCPConfig.defaultPath`, then triggers `MCPRegistry.reloadConfig()`
- **Cancel** button — dismisses without saving

### R2: "Reveal Config in Finder" context menu item

Add **"Reveal Config in Finder"** (with `doc.text.magnifyingglass` icon) to MCPRowView's context menu. Visible ONLY for `server.source == .config`.

Action: `NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: MCPConfig.defaultPath)])`

### R3: Context menu ordering

Updated context menu order for config-sourced MCPs:

```
▶ Start / ⏹ Stop / 🔄 Restart     (existing, if not disabled)
───────────────────────────────
✏️ Edit Configuration…              (NEW — config only)
📄 Reveal Config in Finder          (NEW — config only)
───────────────────────────────
🔍 Reveal Log in Finder             (existing)
📁 Open Logs Folder                 (existing)
```

### R4: ConfigEditorSheet view

New file: `Shipyard/Views/ConfigEditorSheet.swift`

```
┌─────────────────────────────────────────────────┐
│  Edit MCP Configuration                    ✕    │
│─────────────────────────────────────────────────│
│                                                 │
│  {                                              │
│    "mcpServers": {                              │
│      "cortex": { ... },                         │
│  ▶   "lldb-mcp": {           ← cursor here     │
│        "command": "/usr/local/bin/lldb-mcp",    │
│        "transport": "stdio"                     │
│      },                                         │
│      ...                                        │
│    }                                            │
│  }                                              │
│                                                 │
│─────────────────────────────────────────────────│
│  ✓ Valid JSON                    [Cancel] [Save]│
└─────────────────────────────────────────────────┘
```

**Key behaviors:**
- Load: Read raw file content from `MCPConfig.defaultPath` (not re-encode — preserve user formatting)
- Cursor positioning: Find `"<server-name>"` in the text, set NSTextView selection to that range, scroll so the matched line appears near the top (~3rd line). Use `SimpleJSONTextEditor`'s `scrollToText` parameter.
- Save: Write string content to file. Then call `await registry.reloadConfig()` on dismiss.
- Sheet size: `.frame(minWidth: 600, minHeight: 500)`
- Reuse `SimpleJSONTextEditor` (existing NSTextView wrapper with syntax highlighting)

### R6: SimpleJSONTextEditor scroll-to support

Add an optional `scrollToText: String? = nil` parameter to `SimpleJSONTextEditor`. In `makeNSView`, after setting the initial text and creating the scroll view:

1. Search for `scrollToText` in `textView.string` (e.g., `"lldb-mcp"` including the quotes)
2. If found, set `textView.setSelectedRange(range)` to place the cursor
3. Scroll so the match line is near the top: calculate the line's rect via `textView.layoutManager`, then scroll the NSScrollView so that line appears ~3 lines from the top of the visible area
4. Use `DispatchQueue.main.async` to defer the scroll until after layout completes

ConfigEditorSheet passes `scrollToText: "\"\(serverName)\""` (with escaped quotes to match the JSON key).

### R5: Error handling

- If `mcps.json` doesn't exist → show empty `{}` with a note "Config file will be created on save"
- If file read fails → show error alert, don't open sheet
- If save fails → show error in the validation bar, don't dismiss
- If JSON is invalid on save → show validation error, prevent save (Save button disabled)

## Acceptance Criteria

- AC1: Right-clicking a config-sourced MCP in the sidebar shows "Edit Configuration…" and "Reveal Config in Finder" items.
- AC2: Right-clicking a manifest-sourced MCP does NOT show these items.
- AC3: "Edit Configuration…" opens a sheet with the full mcps.json, cursor at the selected MCP's entry.
- AC4: Editing and saving writes back to mcps.json and triggers config reload.
- AC5: "Reveal Config in Finder" selects mcps.json in Finder.
- AC6: Invalid JSON disables the Save button and shows validation error.
- AC7: Build passes with zero Swift 6 concurrency warnings.

## Target Files

- `Shipyard/Views/ConfigEditorSheet.swift` — NEW (the editor sheet)
- `Shipyard/Views/MCPRowView.swift` — add context menu items + sheet trigger
- `Shipyard/Views/JSONEditorView.swift` — reference for SimpleJSONTextEditor + validation pattern

## Test Files

- Manual testing (sheet UI). No automated tests for sheets currently.

## Dependencies

- `SimpleJSONTextEditor` from JSONEditorView.swift (NSTextView wrapper with highlighting)
- `MCPConfig.defaultPath` for file location
- `MCPRegistry.reloadConfig()` for live reload after save
