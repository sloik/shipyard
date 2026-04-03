---
id: BUG-007
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-011, SPEC-012]
violates: [SPEC-011, SPEC-012]
prior_attempts: [BUG-007-attempt-1-formatjson]
created: 2026-03-26
---

# JSON Content Invisible in CodeBlockView — NSTextView Has Zero Width

## Problem

In the ExecutionDetailView, both Request and Response sections show line numbers but **no visible text content**. The JSON data is correctly formatted (confirmed by line count going from 1 to 12 after the formatJSON fix), but the `AttributedStringView` (NSViewRepresentable wrapping NSTextView) renders at zero width, making all text invisible.

This affects EVERY use of CodeBlockView — request args, response JSON, and the JSON editor read-only mode.

**Violated spec:** SPEC-011 AC 6 (View shows request + response), SPEC-012 (JSON viewer with syntax highlighting)
**Violated criteria:** AC 6 — content must be visible and readable, not just present in the DOM

## Reproduction

1. Open Gateway tab → click ▶ on `hear-me-say` → `list_voices` → Execute
2. Wait for completion → click [View] in the queue panel
3. **Actual (Request):** Shows line numbers 1, 2, 3 but the JSON content area to the right is blank
4. **Actual (Response):** Shows line numbers 1-12 but the JSON content area to the right is blank
5. **Expected:** Pretty-printed, syntax-highlighted JSON text visible next to line numbers

## Root Cause

`CodeBlockView.swift` — the `AttributedStringView` (NSViewRepresentable, lines 155-173) wraps an `NSTextView` but has critical sizing issues:

1. **No intrinsic content size communication.** The NSTextView doesn't tell SwiftUI how much space it needs. SwiftUI gives it zero width.

2. **No `sizeThatFits` implementation.** `NSViewRepresentable` can implement `sizeThatFits(_:usingNSView:)` (macOS 13+) to communicate the view's ideal size to SwiftUI. This is missing.

3. **No width constraint on text container.** The NSTextView's `textContainer` has no width set, so it can't perform line wrapping or width-based layout.

4. **Layout structure:** The code uses `HStack { lineNumbers, VStack { AttributedStringView }, Spacer }` inside a `ScrollView([.horizontal, .vertical])`. The NSTextView gets no width proposal from the horizontal ScrollView.

```swift
// Current broken code:
func makeNSView(context: Context) -> NSTextView {
    let textView = NSTextView()
    textView.isEditable = false
    textView.isSelectable = true
    textView.backgroundColor = .clear
    textView.textContainerInset = NSSize(width: 0, height: 0)
    textView.textContainer?.lineFragmentPadding = 0
    // ← No width constraint, no sizing override, no intrinsic size
    return textView
}
```

## Requirements

- [ ] R1: JSON text content is visible next to line numbers in CodeBlockView
- [ ] R2: Text renders with correct syntax highlighting colors
- [ ] R3: Long lines are scrollable horizontally (not clipped)
- [ ] R4: Multi-line JSON is scrollable vertically
- [ ] R5: Works for both small (`{}`) and large (50+ line) JSON payloads

## Acceptance Criteria

- [ ] AC 1: Executing `list_voices` and clicking View shows visible, readable JSON text in both Request and Response
- [ ] AC 2: JSON is syntax-highlighted (keys bold, strings green, numbers blue, etc.)
- [ ] AC 3: Line numbers align with corresponding text lines
- [ ] AC 4: Empty args `{}` is visible as text, not just line numbers
- [ ] AC 5: AC 6 from SPEC-011 now passes (View shows readable request + response)
- [ ] AC 6: Build succeeds with zero errors; all existing tests pass
- [ ] AC 7: Copy button copies the actual JSON text to clipboard (verify with copy)

## Context

**Key files:**
- `Shipyard/Views/CodeBlockView.swift` — the broken view (lines 1-190). Contains `AttributedStringView` NSViewRepresentable (lines 155-173)
- `Shipyard/Views/JSONHighlighter.swift` — produces the NSAttributedString (works correctly, issue is display)
- `Shipyard/Views/ExecutionDetailView.swift` — consumer of CodeBlockView

**Fix approaches (pick the most robust):**

### Option A: Replace NSViewRepresentable with SwiftUI native Text
The simplest and most robust fix. SwiftUI's `Text` can display `AttributedString` (Swift struct). Convert the `NSAttributedString` from JSONHighlighter to `AttributedString`:

```swift
// Replace AttributedStringView entirely with:
if let attrString = try? AttributedString(highlightedJSON, including: \.appKit) {
    Text(attrString)
        .font(.system(size: 11, design: .monospaced))
        .textSelection(.enabled)
} else {
    Text(jsonString)
        .font(.system(size: 11, design: .monospaced))
        .textSelection(.enabled)
}
```

This eliminates the NSViewRepresentable sizing problem entirely. SwiftUI Text handles its own layout.

### Option B: Fix NSTextView sizing
If NSTextView must be kept (for features like text selection across the whole block):

```swift
func makeNSView(context: Context) -> NSTextView {
    let textView = NSTextView()
    textView.isEditable = false
    textView.isSelectable = true
    textView.backgroundColor = .clear
    textView.textContainerInset = NSSize(width: 0, height: 0)
    textView.textContainer?.lineFragmentPadding = 0
    textView.isVerticallyResizable = true
    textView.isHorizontallyResizable = true
    textView.textContainer?.widthTracksTextView = false
    textView.textContainer?.containerSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    textView.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    return textView
}
```

And add a `GeometryReader` or explicit frame to give the NSTextView a proposed width.

### Option C: Use SwiftUI Text per line (simplest, most reliable)
Split the JSON into lines and render each as a SwiftUI Text:

```swift
VStack(alignment: .leading, spacing: 0) {
    ForEach(Array(jsonString.split(separator: "\n", omittingEmptySubsequences: false).enumerated()), id: \.offset) { _, line in
        Text(/* highlighted line */)
            .font(.system(size: 11, design: .monospaced))
            .frame(height: 16)
    }
}
```

This keeps line numbers and content perfectly aligned (same 16pt frame height).

**Recommendation:** Option A or C. Avoid keeping the broken NSViewRepresentable unless there's a specific feature requirement for NSTextView.

## Out of Scope

- Search highlight scrolling (can be added later with SwiftUI `.id()` + `ScrollViewReader`)
- Performance for 10,000+ line JSON (not a current use case)
- The formatJSON logic (already fixed in prior attempt)
- The response wrapper unwrapping (already fixed in prior attempt)

## Notes for the Agent

- **Read DevKB/swift.md** before coding — especially NSViewRepresentable patterns
- The prior attempt fixed `formatJSON` and `formatResponseJSON` correctly — those changes should be preserved
- The JSONHighlighter punctuation color was already fixed to `labelColor.withAlphaComponent(0.6)` — preserve that
- The core issue is ONLY in `CodeBlockView.swift` — specifically `AttributedStringView`
- If using Option A (SwiftUI Text), note that `AttributedString(nsAttributedString, including: \.appKit)` can throw
- If using Option C (per-line Text), you lose cross-line text selection but gain perfect layout
- The search functionality (match highlighting) needs to work with whatever approach is chosen
- **Build after every change** — zero errors required
- **Test visually** — the fix must produce visible text, not just compile
