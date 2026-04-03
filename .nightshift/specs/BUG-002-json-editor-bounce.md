---
id: BUG-002
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-012]
prior_attempts: []
created: 2026-03-26
---

# JSON Editor Bounces When Validation Error Appears/Disappears

## Problem

In the Tool Execution Sheet's JSON tab (SPEC-010/012), the text editor area resizes vertically when the validation error message ("Invalid JSON: ...") appears or disappears. This causes the content to jump/bounce, making it hard to type. The error message is in a VStack below the editor, and its appearance pushes the editor smaller or the sheet taller.

**Violated spec:** SPEC-012 (JSON Editor & Response Viewer)
**Violated criteria:** AC 6 — "Validation is debounced (doesn't fire on every keystroke — waits 300ms after last edit)". While debouncing may work, the visual effect of the error appearing/disappearing still causes layout instability. Also implicit in AC 3 — the editor should be usable without jarring layout shifts.

## Requirements

- [x] R1: The validation message area must have **fixed reserved space** — it never changes the editor's size
- [x] R2: When no error is present, the reserved space shows empty (not collapsed)
- [x] R3: When an error appears, it fills the reserved space — no layout change above it
- [x] R4: The editor frame must not shrink or grow when validation state changes

## Acceptance Criteria

- [x] AC 1: Typing valid JSON → invalid JSON → valid JSON does NOT cause the editor to resize/bounce
- [x] AC 2: Validation error area has a fixed height (recommend 24–30pt) that is always reserved
- [x] AC 3: Error text appears/disappears within the reserved area using opacity or conditional text, not conditional view insertion
- [x] AC 4: Editor `TextEditor` / `NSTextView` frame height is stable regardless of validation state
- [x] AC 5: Build succeeds with zero errors; all existing tests pass

## Context

**File to modify:** `Shipyard/Views/JSONEditorView.swift`

The issue is in the VStack layout: the error message is conditionally inserted (`if !errors.isEmpty { ... }`), which changes the VStack's total height, causing the editor to shrink.

**Fix approach:** Replace conditional view insertion with a fixed-height container that's always present. Use opacity or conditional text content inside it.

```swift
// BAD — causes bounce:
VStack {
    editor
    if !errors.isEmpty {
        Text(errors.first!)  // This insertion changes VStack height
    }
}

// GOOD — fixed space:
VStack {
    editor
    HStack {
        if let error = errors.first {
            Text(error).foregroundColor(.red)
        }
    }
    .frame(height: 24)  // Always reserved, never collapses
}
```

## Notes for the Agent

- Read JSONEditorView.swift to find the exact validation display code
- The fix is purely layout — don't change validation logic
- Use `.frame(height: 24)` or `.frame(minHeight: 24)` on the error container
- Test by typing alternating valid/invalid JSON — the editor area should not move at all
- Build after the change
