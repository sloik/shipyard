---
id: SPEC-013
priority: 2
layer: 2
type: feature
status: done
after: [SPEC-005]
prior_attempts: []
created: 2026-03-27
---

# Settings Catalog — Centralized App Preferences

## Problem

Shipyard's Settings window (Cmd+,) only has "Server Auto-Start" settings. As features grow (tool execution, JSON viewer, etc.), new settings need a home. There's no single spec defining what settings exist and how they're organized — leading to ad-hoc additions that lack consistency.

This spec establishes the Settings window as the canonical place for all user preferences, adds new settings sections, and ensures a consistent UX pattern for future additions.

## Requirements

- [ ] R1: Settings window organized in sections with clear headers
- [ ] R2: Existing "Server Auto-Start" section preserved as-is
- [ ] R3: New section: "JSON Viewer" with font size setting (9-18pt, default 11pt)
- [ ] R4: Font size persisted via @AppStorage and applied to all CodeBlockView and JSONEditorView instances
- [ ] R5: Settings window has a reasonable minimum size and looks good with multiple sections

## Acceptance Criteria

- [ ] AC 1: Settings window (Cmd+,) shows sections: "Server Auto-Start", "JSON Viewer"
- [ ] AC 2: "JSON Viewer" section has a font size stepper (9-18pt range)
- [ ] AC 3: Default font size is 11pt (current hardcoded value)
- [ ] AC 4: Changing font size immediately updates all open CodeBlockView instances
- [ ] AC 5: Font size persists across app restarts (UserDefaults key: `jsonViewer.fontSize`)
- [ ] AC 6: Existing auto-start settings continue to work unchanged
- [ ] AC 7: Build succeeds with zero errors; all existing tests pass
- [ ] AC 8: No SwiftUI runtime faults (NFR-001)

## Context

**Key files:**
- `Shipyard/Views/SettingsView.swift` — current settings UI (Form with grouped style, one section)
- `Shipyard/Services/AutoStartManager.swift` — current persistence pattern
- `Shipyard/Views/CodeBlockView.swift` — JSON viewer (hardcoded `size: 11`)
- `Shipyard/Views/JSONEditorView.swift` — JSON editor (hardcoded font size)
- `Shipyard/App/ShipyardApp.swift` — Settings scene definition (lines 119-123)

**Persistence approach:**
Use `@AppStorage("jsonViewer.fontSize")` directly — simpler than creating a new manager for a single setting. CodeBlockView and JSONEditorView read from the same key.

**Implementation:**
1. In `SettingsView.swift`, add a new section "JSON Viewer" below the auto-start section
2. Add a Stepper for font size (same pattern as auto-start delay stepper)
3. In `CodeBlockView.swift`, replace hardcoded `size: 11` with `@AppStorage("jsonViewer.fontSize") private var fontSize: Double = 11`
4. In `JSONEditorView.swift`, same change
5. The JSONHighlighter's font sizes also need to respect this setting — either pass font size as a parameter or read from @AppStorage

## Out of Scope

- Settings search/filter
- Settings import/export
- Per-tool or per-MCP settings
- Keyboard shortcuts customization

## Notes for the Agent

- **Read DevKB/swift.md** before coding
- The existing stepper pattern in SettingsView is the model — follow it for font size
- `@AppStorage` triggers SwiftUI view updates automatically — no manual refresh needed
- JSONHighlighter uses `NSFont.monospacedSystemFont(ofSize: 11, weight: ...)` — this needs to accept a configurable size. Consider passing the font size as a parameter to `highlight(_:fontSize:)`
- The SettingsView uses `@Environment(AutoStartManager.self)` — the new font size setting can use `@AppStorage` directly (simpler)
- **Build after every change** — zero errors required
