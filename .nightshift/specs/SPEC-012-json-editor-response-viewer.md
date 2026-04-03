---
id: SPEC-012
priority: 2
layer: 2
type: feature
status: ready
after: [SPEC-010, SPEC-011]
prior_attempts: []
created: 2026-03-26
---

# JSON Editor & Response Viewer — Syntax Highlighting, Validation, and Search

## Problem

The tool execution sheet (SPEC-010) uses a plain TextEditor for JSON input, and the execution detail view (SPEC-011) displays raw text responses. Both need syntax highlighting, pretty-printing, and the response viewer needs full-text search. Without these, large JSON payloads are unreadable and debugging tool calls is painful.

## Requirements

- [ ] R1: **CodeBlockView** — reusable SwiftUI view that renders JSON with syntax highlighting
- [ ] R2: Syntax highlighting for JSON tokens: strings (green), numbers (blue), booleans (orange), null (gray), keys (default/bold), braces/brackets (gray)
- [ ] R3: **Pretty-printing** — all JSON displayed is indented with 2-space formatting
- [ ] R4: **JSONEditorView** — editable version of CodeBlockView for use in the execution sheet's JSON tab
- [ ] R5: JSONEditorView validates input: checks for valid JSON on every keystroke (debounced 300ms). Shows inline error message below editor if invalid ("Invalid JSON: unexpected token at line 3")
- [ ] R6: JSONEditorView validates against tool's inputSchema: marks missing required fields, wrong types. Shows warnings below editor.
- [ ] R7: **Response viewer** — read-only CodeBlockView used in ExecutionDetailView to display tool responses
- [ ] R8: **Search in response** — search bar (Cmd+F or always-visible) that highlights matches in the response JSON. Shows match count ("3 of 12"). Up/Down arrows to navigate between matches.
- [ ] R9: **Copy button** — copies the entire JSON (input or response) to clipboard
- [ ] R10: Line numbers in the gutter (left side) for both editor and viewer

## Acceptance Criteria

- [ ] AC 1: `CodeBlockView` renders JSON with colored tokens (strings, numbers, booleans, null, keys, punctuation)
- [ ] AC 2: All JSON is pretty-printed with 2-space indentation
- [ ] AC 3: `JSONEditorView` is an editable text view with syntax highlighting
- [ ] AC 4: Invalid JSON shows inline error: "Invalid JSON: {description}" below the editor (red text)
- [ ] AC 5: Schema validation warnings appear below editor for missing required fields or type mismatches
- [ ] AC 6: Validation is debounced (doesn't fire on every keystroke — waits 300ms after last edit)
- [ ] AC 7: Response viewer (read-only CodeBlockView) displays tool responses with highlighting
- [ ] AC 8: Search bar in response viewer: text field + match count + Up/Down navigation
- [ ] AC 9: Search highlights all matches in the response (yellow background or similar)
- [ ] AC 10: Current match is visually distinct from other matches (orange vs yellow)
- [ ] AC 11: Copy button copies full JSON to `NSPasteboard.general`
- [ ] AC 12: Line numbers shown in left gutter for both editor and viewer
- [ ] AC 13: Handles empty JSON `{}` gracefully (no errors, correct display)
- [ ] AC 14: Handles large JSON (1MB+) without freezing the UI — use lazy rendering or truncation if needed
- [ ] AC 15: Build succeeds with zero errors; all existing tests pass

## Context

**Key Files (read ALL before coding):**

### ToolExecutionSheet.swift (from SPEC-010)
- Replace the plain TextEditor in the JSON tab with `JSONEditorView`
- Pass the tool's `inputSchema` for validation

### ExecutionDetailView.swift (from SPEC-011)
- Replace plain Text views with `CodeBlockView` for request and response display
- Add search bar to the response section

### Existing code patterns
- Check if Shipyard already has any text highlighting (e.g., in LogViewer)
- Check if there's a monospace font preference already defined

## Implementation Strategy

1. **Create `Views/CodeBlockView.swift`** — read-only JSON viewer
   - Input: `String` (raw JSON)
   - Uses `NSAttributedString` with syntax highlighting applied
   - Rendered in a `ScrollView` with `Text` (attributed string) or NSTextView wrapper
   - Line numbers via a side gutter (HStack: gutter + code)

2. **Create `Views/JSONEditorView.swift`** — editable JSON editor
   - Wraps an `NSTextView` (via NSViewRepresentable) for editable syntax highlighting
   - On text change: debounce 300ms → validate JSON → validate against schema → show errors
   - Binding: `@Binding var jsonString: String`

3. **Create `Utilities/JSONHighlighter.swift`** — the highlighting engine
   - Input: JSON string → Output: `NSAttributedString` with colored ranges
   - Parse JSON tokens using `JSONSerialization` + string scanning
   - Color map: keys (label color), strings (green/systemGreen), numbers (blue/systemBlue), booleans (orange/systemOrange), null (gray), punctuation (secondaryLabel)

4. **Create `Utilities/JSONSchemaValidator.swift`** — lightweight schema validation
   - Input: JSON payload + JSON Schema → Output: array of validation issues
   - Check: required fields present, property types match, enum values valid
   - Don't implement full JSON Schema spec — just the basics (type, required, enum, properties)

5. **Add search to response viewer:**
   - `@State var searchText = ""` + TextField
   - Compute match positions from the JSON string
   - Highlight matches using attributed string ranges
   - Up/Down buttons cycle through matches (scroll to match)

6. **Integrate:**
   - Replace TextEditor in ToolExecutionSheet JSON tab with JSONEditorView
   - Replace Text in ExecutionDetailView with CodeBlockView
   - Add search bar to ExecutionDetailView response section

## Design Reference

→ See: `docs/specs/009-tool-execution/shipyard-execution-queue-design.md` § "JSON Editor"
→ See: `docs/specs/009-tool-execution/shipyard-execution-ui-states.md` § "State 3: Response Viewer"

## Out of Scope

- Full JSON Schema validation (no $ref, oneOf, anyOf, allOf, patternProperties)
- JSON Schema draft compatibility (just handle type, required, enum, properties, description)
- Syntax highlighting for non-JSON formats (XML, YAML)
- Code folding (collapsible JSON sections) — v2
- Dark/light theme switching (use system NSColor semantic colors — they adapt automatically)

## Notes for the Agent

- **NSTextView for editing, not TextEditor** — SwiftUI's TextEditor doesn't support attributed strings or syntax highlighting. Wrap `NSTextView` in `NSViewRepresentable`.
- **NSAttributedString for highlighting** — build the attributed string from the raw JSON. Use `NSFont.monospacedSystemFont(ofSize:weight:)` as the base font.
- **Semantic colors** — use `NSColor.systemGreen`, `NSColor.systemBlue`, `NSColor.systemOrange`, `NSColor.secondaryLabelColor` — these adapt to dark/light mode automatically.
- **Debounce validation** — use `Task.sleep(for: .milliseconds(300))` pattern with cancellation to debounce. Don't validate on every single character.
- **Performance for large JSON** — if JSON > 100KB, skip character-level highlighting and use a simpler approach (just monospace + basic formatting). Test with 1MB payloads.
- **JSONSerialization for pretty-printing** — `JSONSerialization.data(withJSONObject:options:.prettyPrinted)` gives you pretty-printed JSON from any valid JSON object.
- **Search match highlighting** — compute NSRange positions for all occurrences of searchText in the JSON string. Apply background color attribute to those ranges in the attributed string. Rebuild on search text change.
- **New .swift files MUST be added via `mcp__xcode__XcodeWrite`**
- **Build after every change** — zero errors required
