---
id: UX-007
priority: 2
layer: 3
type: feature
status: done
after: [SPEC-019]
prior_attempts: []
created: 2026-03-31
---

# Right-Click "Edit in Config…" for JSON-Sourced MCP Servers

## Problem

`ConfigEditorSheet` exists and is fully functional — it opens `mcps.json` and scrolls to the named entry via `scrollToText`. However, it is not reachable from the sidebar. There is no way to open it without going to Settings. Right-clicking a config-sourced MCP row should surface an "Edit in Config…" option that opens the editor pre-scrolled to that server's entry.

## Design

Add "Edit in Config…" to the row-level `.contextMenu` in `MCPRowView`, visible only when `server.source == .config`. The menu item opens `ConfigEditorSheet(serverName: server.manifest.name, isPresented: $showConfigEditor)`.

Sheet presentation should be local to `MCPRowView` (self-contained `@State var showConfigEditor = false`) — no new callbacks needed on the parent.

```swift
// In MCPRowView (after existing Stop/Restart/Start items):

if server.source == .config {
    Divider()
    Button {
        showConfigEditor = true
    } label: {
        Label("Edit in Config…", systemImage: "square.and.pencil")
    }
}

// Sheet modifier on the row's root view:
.sheet(isPresented: $showConfigEditor) {
    ConfigEditorSheet(
        serverName: server.manifest.name,
        isPresented: $showConfigEditor
    )
}
```

## Acceptance Criteria

- [x] AC 1: Right-clicking a config-sourced MCP row shows "Edit in Config…" in the context menu
- [x] AC 2: Selecting "Edit in Config…" opens `ConfigEditorSheet`
- [x] AC 3: The editor scrolls to (and highlights) the server's entry in `mcps.json` on open
- [x] AC 4: Manifest-sourced and synthetic (Shipyard) MCPs do NOT show "Edit in Config…"
- [x] AC 5: Disabled config MCPs (server.disabled == true) DO show "Edit in Config…" — editing a disabled entry is valid
- [x] AC 6: Build succeeds with zero errors; existing tests pass

## Files

- `Shipyard/Views/MCPRowView.swift` — add `@State var showConfigEditor`, context menu item, `.sheet()` modifier
- `ConfigEditorSheet.swift` — no changes needed; already supports `serverName` + scroll

## Notes

`ConfigEditorSheet` already passes `scrollToText: "\"\(serverName)\""` to `JSONEditorView` — the scroll-to-entry behaviour is already implemented and just needs to be triggered.
