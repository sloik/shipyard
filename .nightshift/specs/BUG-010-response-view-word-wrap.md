---
id: BUG-010
priority: 1
layer: 3
type: bug
status: ready
after: []
created: 2026-03-27
---

# Response View: Garbled Text Layout and Misaligned Line Numbers

## Problem

In `CodeBlockView` (the read-only JSON response viewer in ExecutionDetailView), long lines cause two visual bugs:

1. **Garbled/overlapping text when wrapping**: Each line of highlighted JSON is rendered in a `Text` view with a fixed height of `fontSize + 5` (~16pt). When word wrap causes a line to span multiple visual lines, the extra content overflows its fixed frame and overlaps the next line, producing unreadable garbled text.

2. **Line numbers misaligned**: Line numbers in the left gutter also use `fontSize + 5` fixed height. Since they don't grow when the adjacent content line wraps, line numbers drift out of sync with the actual text.

Both bugs are clearly visible when viewing responses with long string values (e.g. `list_voices` returning a large JSON array on one line).

## Root Cause

`CodeBlockView.swift` lines 77-88: each highlighted line is rendered as an individual `Text` view inside a `VStack` with `.frame(height: fontSize + 5)`. This fixed height does not accommodate word-wrapped content. The line number gutter (lines 63-69) uses the same fixed height and cannot stay in sync.

## Requirements

- [ ] R1: Long lines in the response view must word-wrap correctly without overlapping adjacent lines.
- [ ] R2: Line numbers must remain vertically aligned with their corresponding content lines, even when content wraps to multiple visual lines.
- [ ] R3: The response view must use word wrap (not horizontal scrolling) for long lines.
- [ ] R4: Syntax highlighting (JSON colors) must continue to work correctly with wrapped lines.
- [ ] R5: Search highlighting must continue to work correctly.
- [ ] R6: Text selection (`.textSelection(.enabled)`) must continue to work.
- [ ] R7: The copy-to-clipboard button must continue to work.

## Acceptance Criteria

- [ ] AC 1: Viewing a response with long lines (e.g. `list_voices` output) shows properly word-wrapped text with no overlapping or garbled rendering.
- [ ] AC 2: Line numbers stay aligned with their corresponding content lines when content wraps.
- [ ] AC 3: JSON syntax highlighting renders correctly on wrapped lines.
- [ ] AC 4: Search still works (find, highlight, navigate matches).
- [ ] AC 5: Text is selectable and copy-to-clipboard works.
- [ ] AC 6: Build succeeds with zero errors.
- [ ] AC 7: Short JSON responses (no wrapping needed) still look correct — no regression.

## Context

### Key file:
- **`Shipyard/Views/CodeBlockView.swift`** — the entire bug and fix are in this single file.

### Current broken layout (lines 60-96):
```swift
ScrollView(.vertical) {
    HStack(spacing: 0) {
        // Line numbers — fixed height per line
        VStack(alignment: .trailing, spacing: 0) {
            ForEach(1...lineCount, id: \.self) { line in
                Text("\(line)")
                    .frame(height: fontSize + 5)  // BUG: fixed height
            }
        }

        // Code lines — fixed height per line
        VStack(alignment: .leading, spacing: 0) {
            ForEach(...) { _, lineAttrString in
                Text(swiftAttr)
                    .frame(height: fontSize + 5, alignment: .leading)  // BUG: fixed height
            }
        }
    }
}
```

### Fix approach:
The core problem is using fixed `.frame(height:)` on each line. The fix should allow each content line to have dynamic height (growing when it wraps) and keep the corresponding line number aligned.

One proven approach: use a `GeometryReader` or preference key to measure each content line's actual height and apply it to the corresponding line number. Another approach: use a single `NSTextView`-based approach (like `JSONEditorView` does) for the read-only viewer. A third approach: render each line as an HStack `[lineNumber | content]` so they naturally align.

The simplest correct approach is likely the HStack-per-line pattern:
```swift
ForEach(lines) { index, line in
    HStack(alignment: .top, spacing: 0) {
        Text("\(index + 1)")  // line number
            .frame(width: gutterWidth, alignment: .trailing)
        Text(attributedLine)  // content — wraps naturally
            .fixedSize(horizontal: false, vertical: true)  // allow vertical growth
    }
}
```

The agent should evaluate which approach works best with SwiftUI's layout system while preserving search, highlighting, and selection.

## Out of Scope

- Changes to JSONEditorView (the editable editor — that's a separate component)
- Changes to ExecutionDetailView layout
- Pretty-printing the JSON content itself

## Notes for the Agent

- **Read DevKB/swift.md** before writing code
- The key insight is replacing the dual-VStack layout (separate line numbers and content columns) with a per-line HStack layout where line number and content are siblings — this guarantees vertical alignment.
- `.fixedSize(horizontal: false, vertical: true)` on the content Text allows it to grow vertically for word wrap while respecting the container width.
- Watch out for `lineLimit` — do NOT set it, as it would re-introduce truncation.
- The `highlightedLines` computed property already splits the attributed string into per-line `NSAttributedString` — reuse this.
- Test with both short JSON (e.g. `{"ok": true}`) and very long JSON (e.g. `list_voices` output with 100+ character lines).
- **Build after every change** — use `mcp__xcode__BuildProject`
- **Do NOT create new .swift files**
