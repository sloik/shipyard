---
id: BUG-004
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-010]
violates: [SPEC-010]
prior_attempts: []
created: 2026-03-26
completed: 2026-03-26
---

# Tool Execution Sheet Opens Blank — Content Not Rendering

## Problem

When clicking ▶ on a tool (e.g., `list_voices` from hear-me-say MCP), the sheet opens but shows a blank dark rectangle with no content — no title, no JSON/Form tabs, no Cancel/Execute buttons. The sheet frame renders but the content inside is empty.

**Violated spec:** SPEC-010 (Tool Execution Sheet)
**Violated criteria:** AC 2 — "Clicking ▶ opens the Tool Execution Sheet as a .sheet modal" (sheet opens but with no content). AC 3 — "Sheet title shows the tool name". AC 10 — "Execute button is always enabled".

## Root Cause

GatewayView used `.sheet(isPresented: $showExecutionSheet)` with an `if let tool = sheetTool` inside the content closure. SwiftUI evaluates the sheet content at presentation time, and the `@State var sheetTool: GatewayTool?` was not yet unwrappable when the sheet rendered, producing an empty view.

```swift
// BROKEN — sheetTool may not unwrap in time:
.sheet(isPresented: $showExecutionSheet) {
    if let tool = sheetTool {
        ToolExecutionSheet(tool: tool)  // Never reached
    }
}
```

## Fix Applied

Switched to `.sheet(item:)` pattern which guarantees the item is non-nil when the sheet renders:

```swift
// FIXED — tool is guaranteed non-nil:
.sheet(item: $sheetTool) { tool in
    ToolExecutionSheet(tool: tool)
}
```

Also added `Identifiable` conformance to `GatewayTool` (required by `.sheet(item:)`), using `prefixedName` as the id.

Removed the now-unnecessary `showExecutionSheet` boolean state variable.

## Files Modified

- `Shipyard/Shipyard/Models/GatewayRegistry.swift` — added `Identifiable` to `GatewayTool`
- `Shipyard/Views/GatewayView.swift` — switched to `.sheet(item:)`, removed `showExecutionSheet`
