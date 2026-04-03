---
id: BUG-009
priority: 1
layer: 3
type: bugfix
status: done
violates: [SPEC-010, SPEC-012]
after: [SPEC-015]
prior_attempts:
  - attempt: 1
    approach: "In-place attribute application with save/restore selectedRange + isUpdating re-entrancy guard in updateNSView"
    result: "FAILED — cursor jump still persists. updateNSView fires after the editing transaction, so attribute changes disrupt cursor."
  - attempt: 2
    approach: "Moved highlighting from updateNSView to textDidChange() delegate callback, in-place attributes + cursor save/restore"
    result: "FAILED — textDidChange fires AFTER the editing transaction completes, so attribute changes start a new transaction that still disrupts cursor."
  - attempt: 3
    approach: "NSTextStorageDelegate.textStorage(_:didProcessEditing:range:changeInLength:) — highlighting inside the editing transaction"
    result: "FIXED — attribute changes during didProcessEditing are part of the same edit, cursor is never disrupted. @MainActor + @preconcurrency NSTextStorageDelegate for Swift 6."
created: 2026-03-27
---

# JSON Editor Cursor Jumps / Text Inserted at Wrong Position

## Bug Description

When typing inside a string value in the JSON editor, the cursor position is lost and characters are inserted at the wrong location. Example: user places cursor between `o` and `"` in `"hello"`, types `ni` — expected: `"hello ni"`, actual: `"hello "` with `}ni` appearing on the next line as garbage text.

## Root Cause

The fundamental problem is that our custom `JSONTextEditorView` (an `NSViewRepresentable` wrapping `NSTextView`) fights with SwiftUI's update cycle. On every keystroke:
1. User types → `textDidChange` → updates `@Binding text`
2. SwiftUI detects binding change → calls `updateNSView`
3. `updateNSView` modifies `textStorage` attributes → this disrupts the cursor even when we save/restore `selectedRange` and apply attributes in-place

**Attempt 1 failed** because even in-place attribute application via `beginEditing()/setAttributes()/endEditing()` with `selectedRange` save/restore does not reliably preserve cursor position. The `textStorage` modifications during `updateNSView` interfere with AppKit's internal text editing state in ways that `setSelectedRange()` cannot fully undo.

## Approach — Attempt 2: Replace with 3rd Party Editor

Instead of trying to fix the NSViewRepresentable cursor problem (which is a known category of bug with AppKit↔SwiftUI bridging), **replace the custom `JSONTextEditorView` with a 3rd party code editor component** that handles syntax highlighting internally, without going through SwiftUI's `updateNSView` cycle.

### Recommended Library: CodeEditorView

**Package:** [mchakravarty/CodeEditorView](https://github.com/mchakravarty/CodeEditorView)
- SwiftUI-native code editor view (not an NSViewRepresentable wrapper — it manages its own TextKit 2 internals)
- Built-in syntax highlighting with configurable language tokenizers and themes
- Cursor management is handled internally — no external `updateNSView` interference
- macOS 12+ (we target macOS 26 ✓)
- SPM compatible ✓
- Actively maintained (2025/2026) ✓
- Features: bracket matching, line numbers, minimap, configurable themes

**Why this fixes the bug:** CodeEditorView manages its own text storage and highlighting internally. The SwiftUI binding updates text content, but highlighting is applied by the view's own TextKit 2 layout manager — not by an external `updateNSView` call that fights with the cursor.

### Fallback: STTextView + Neon Plugin

If CodeEditorView doesn't fit (e.g., too heavy, missing JSON config, API mismatch):

**Package:** [krzyzanowskim/STTextView](https://github.com/krzyzanowskim/STTextView) + [STTextView-Plugin-Neon](https://github.com/krzyzanowskim/STTextView-Plugin-Neon)
- TextKit 2 text view built from scratch as NSTextView replacement
- Neon plugin provides TreeSitter-based syntax highlighting (JSON support included)
- Would need an NSViewRepresentable wrapper, but STTextView handles highlighting through its plugin system (not through external attribute replacement), so the cursor issue doesn't apply

## Requirements

- [ ] R1: Replace `JSONTextEditorView` (custom NSViewRepresentable) with a 3rd party editor component
- [ ] R2: Typing in the middle of a string value must insert characters at the cursor position without jumping
- [ ] R3: JSON syntax highlighting must still work (colors for keys, strings, numbers, booleans, null, punctuation)
- [ ] R4: Selection ranges (shift+arrow, mouse selection) must work correctly
- [ ] R5: The `@Binding var jsonText: String` interface in `JSONEditorView` must be preserved (callers don't change)
- [ ] R6: Font size preference (`@AppStorage("jsonViewer.fontSize")`) must still apply
- [ ] R7: The 3rd party dependency must be added to the **Xcode project** (not Package.swift — the app is built by Shipyard.xcodeproj, not SPM)
- [ ] R8: Keep `JSONHighlighter.swift` — it's still used by `CodeBlockView` (read-only viewer). Only remove its usage from the editor.

## Acceptance Criteria

- [ ] AC 1: Type `"hello"` in the JSON editor, place cursor between `o` and `"`, type ` world` — result is `"hello world"` with cursor after `d`.
- [ ] AC 2: Select a range of text, then type a replacement — the selected text is replaced correctly at the right position.
- [ ] AC 3: JSON syntax highlighting (colors for keys, strings, numbers, booleans, null, punctuation) still works.
- [ ] AC 4: Font size changes from Settings still apply correctly.
- [ ] AC 5: Build succeeds with zero errors; all existing tests pass.
- [ ] AC 6: The `JSONEditorView` public interface (`@Binding var jsonText: String`, `let inputSchema: Data`) is unchanged.
- [ ] AC 7: The 3rd party dependency is properly added to the Xcode project via SPM.
- [ ] AC 8: `CodeBlockView.swift` (read-only viewer) continues to work with `JSONHighlighter` — no regressions.

## Context

### Files to modify:
- **`Shipyard/Views/JSONEditorView.swift`** — Replace `JSONTextEditorView` (lines 89-163) with the 3rd party editor. Keep `JSONEditorView` as the public wrapper.
- **`Shipyard.xcodeproj`** — Add SPM dependency for the chosen library.

### Files to NOT modify:
- `Shipyard/Views/JSONHighlighter.swift` — still used by CodeBlockView
- `Shipyard/Views/CodeBlockView.swift` — read-only, no cursor issues
- `Package.swift` — only for ShipyardBridge, not the app

### Current structure of JSONEditorView.swift:
```
JSONEditorView (public SwiftUI view)
  ├── JSONTextEditorView (private NSViewRepresentable) ← REPLACE THIS
  ├── debounceValidation() — schema validation ← KEEP
  └── error display area ← KEEP
```

### Integration pattern:
The 3rd party editor should be used **inside** `JSONEditorView`, replacing only the `JSONTextEditorView` struct. The validation logic, error display, and public interface remain unchanged.

If using **CodeEditorView**: it provides a `CodeEditor` SwiftUI view that takes a text binding and a language configuration. You'd need to create or find a JSON language configuration for its regex-based tokenizer.

If using **STTextView**: wrap it in a minimal NSViewRepresentable, but let its Neon plugin handle highlighting (not our JSONHighlighter). The key difference from the current approach is that highlighting happens in the view's plugin system, not in `updateNSView`.

## Out of Scope

- JSON auto-formatting / pretty-print on type
- Undo/redo behavior beyond what the 3rd party provides
- Multi-cursor editing
- Changing CodeBlockView (read-only viewer)

## Notes for the Agent

- **Read DevKB/swift.md** before writing any code — especially entry #33 (NSViewRepresentable sizing) and #34 (.onChange identity)
- **Read DevKB/xcode.md** — for Xcode project file registration patterns
- The 3rd party library must be added via Xcode SPM (Project → Package Dependencies → Add). This modifies the .pbxproj file. Use `mcp__xcode__BuildProject` to verify.
- **Try CodeEditorView first.** If it doesn't work or has issues (e.g., no JSON language config, API incompatibility), fall back to STTextView + Neon.
- If CodeEditorView needs a JSON language configuration: create one using its `LanguageConfiguration` API with regex patterns for JSON tokens (strings, numbers, keywords, punctuation). Look at existing configs in the library for reference.
- **Build after every change** — zero errors required. Use `mcp__xcode__BuildProject`.
- **Do NOT modify JSONHighlighter.swift or CodeBlockView.swift**
- **Do NOT modify Package.swift** — the app uses Xcode project, not SPM
- Test by actually typing in the middle of a string value after the fix
- The `@AppStorage("jsonViewer.fontSize")` preference should still control font size in the editor
