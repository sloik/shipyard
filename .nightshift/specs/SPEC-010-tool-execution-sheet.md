---
id: SPEC-010
priority: 1
layer: 1
type: feature
status: ready
after: [SPEC-009]
prior_attempts: []
created: 2026-03-26
---

# Tool Execution Sheet — Parameter Input & Confirmation

## Problem

Users need a way to provide parameters for a tool call before executing it. The Gateway tab shows tools but has no input mechanism. This spec adds the action sheet that opens when the user clicks the ▶ play button on a tool row, providing both a raw JSON editor and a dynamically generated form.

## Requirements

- [ ] R1: ▶ play button added to each tool row in the Gateway detail pane
- [ ] R2: Clicking ▶ opens a SwiftUI `.sheet` modal — the Tool Execution Sheet
- [ ] R3: Sheet has a **segmented control** (Picker) to switch between "JSON" and "Form" tabs
- [ ] R4: **JSON tab** — a text editor for raw JSON input, pre-filled with `{}` (or last used payload from recent calls)
- [ ] R5: **Form tab** — dynamically generated form fields from the tool's `inputSchema` (JSON Schema)
- [ ] R6: Form field types (basic, v1):
  - `string` → TextField
  - `number` / `integer` → numeric TextField with stepper
  - `boolean` → Toggle
  - `enum` (string with enum array) → Picker (dropdown)
  - `array` → add/remove rows (each row is the array item type)
  - `object` → nested group with indentation (max 3 levels deep)
- [ ] R7: Form fields show property name as label and `description` from schema as help text (smaller, gray)
- [ ] R8: Required fields marked with asterisk (*) or "Required" badge
- [ ] R9: **Bidirectional sync** — editing in Form updates JSON tab and vice versa. Single source of truth: a `[String: Any]` payload dictionary
- [ ] R10: **Recent calls dropdown** — in the sheet header, a "Recent" button/popover showing last 5 payloads for this tool (from ExecutionQueueManager). Selecting one pre-fills the payload.
- [ ] R11: **Confirmation dialog** — clicking "Execute" shows a confirmation alert: "Execute {tool_name}?" with [Cancel] and [Execute] buttons
- [ ] R12: After confirmation, sheet **dismisses immediately** and execution starts in the queue (via ExecutionQueueManager)
- [ ] R13: If tool has no parameters (empty schema or no `properties`), show "No parameters required" message and direct Execute button
- [ ] R14: Click outside sheet or press Esc to dismiss without executing

## Acceptance Criteria

- [ ] AC 1: Each tool row in Gateway detail pane shows a ▶ button (SF Symbol: `play.circle` or `play.fill`)
- [ ] AC 2: Clicking ▶ opens the Tool Execution Sheet as a `.sheet` modal
- [ ] AC 3: Sheet title shows the tool name (without namespace prefix, e.g., "cortex_query" not "cortex__cortex_query")
- [ ] AC 4: Segmented control switches between "JSON" and "Form" tabs
- [ ] AC 5: JSON tab shows a TextEditor pre-filled with `{}` or last-used payload
- [ ] AC 6: Form tab generates fields from inputSchema: TextField for strings, numeric input for numbers, Toggle for booleans, Picker for enums
- [ ] AC 7: Editing a form field updates the JSON tab payload; editing JSON updates form fields
- [ ] AC 8: Required fields are visually marked (asterisk or badge)
- [ ] AC 9: "Recent" dropdown shows last 5 payloads with timestamps; selecting one fills the editor
- [ ] AC 10: "Execute" button is always enabled (even with empty payload — sends `{}`)
- [ ] AC 11: Clicking "Execute" shows confirmation alert before proceeding
- [ ] AC 12: After confirmation, sheet dismisses and `ExecutionQueueManager.executeToolAsync()` is called
- [ ] AC 13: Tools with no parameters show simplified UI ("No parameters required" + Execute button)
- [ ] AC 14: Esc key or clicking outside dismisses sheet without executing
- [ ] AC 15: Form handles missing schema gracefully — falls back to JSON-only mode with a note
- [ ] AC 16: Nested objects render as indented groups (up to 3 levels; deeper shows "Use JSON editor" hint)
- [ ] AC 17: Array fields have "+" button to add rows and "−" to remove them
- [ ] AC 18: Build succeeds with zero errors; all existing tests pass

## Context

**Key Files (read ALL before coding):**

### GatewayView.swift — Add ▶ button and sheet state
- Find the tool row rendering (where tool name, description, enable toggle are shown)
- Add a ▶ Button to each row
- Add `@State var showExecutionSheet = false` and `@State var sheetTool: GatewayTool?`
- Add `.sheet(isPresented:)` modifier

### GatewayRegistry.swift / GatewayTool — Schema access
- `GatewayTool` should have `inputSchema` (JSON Schema as Data or [String: Any])
- This is the schema used to generate form fields
- Check how tools are stored — the schema comes from MCP tool discovery

### ExecutionQueueManager (from SPEC-009)
- Call `executeToolAsync()` after user confirms
- Call `getRecentCalls(for:)` to populate the Recent dropdown

### Existing UI patterns
- Look at how other sheets are used in Shipyard (e.g., Settings sheet from SPEC-005)
- Match styling: same padding, button styles, section headers

## Implementation Strategy

1. **Create `ToolExecutionSheet.swift`** — the main sheet view
   - Takes a `GatewayTool` as input
   - Has `@State var payload: [String: Any]` as single source of truth
   - Segmented Picker for JSON/Form mode
   - JSON tab: TextEditor bound to JSON-serialized payload
   - Form tab: dynamic form generated from `tool.inputSchema`

2. **Create `DynamicFormView.swift`** — recursive form generator
   - Input: JSON Schema dictionary + binding to payload
   - Generates SwiftUI form fields based on property types
   - Handles nesting up to 3 levels
   - Marks required fields

3. **Modify GatewayView.swift:**
   - Add ▶ button to each tool row
   - Add sheet state variables
   - Add `.sheet` modifier presenting `ToolExecutionSheet`

4. **Wire up confirmation + execution:**
   - Execute button → `.alert` confirmation → `queueManager.executeToolAsync()` → dismiss sheet

## Design Reference

→ See: `docs/specs/009-tool-execution/shipyard-execution-queue-design.md` § "Tool Execution Sheet"
→ See: `docs/specs/009-tool-execution/shipyard-execution-ui-states.md` § "State 1: Sheet Open"

## Out of Scope

- JSON syntax highlighting in the editor (SPEC-012 handles this; use plain TextEditor for now)
- Response display (SPEC-011 queue panel handles this)
- Smart semantic field detection (file pickers, URL validation) — v2
- Schema validation of input before execute — v2 (accept any JSON for now)

## Notes for the Agent

- **Read GatewayView.swift thoroughly** — understand the existing tool row layout before modifying
- **JSON Schema parsing**: `inputSchema` is likely `Data` or `[String: Any]`. Parse it to extract `properties`, `required`, and `type` for each property. Standard JSON Schema format.
- **Bidirectional sync is tricky** — use a single `@State var payload: [String: Any]` dictionary. JSON tab serializes/deserializes from it. Form fields bind to individual keys. When one changes, the other reflects it.
- **Don't over-engineer the form** — basic types only. If schema has `oneOf`, `anyOf`, `allOf`, `$ref`, or other advanced JSON Schema features, fall back to JSON-only mode.
- **New .swift files MUST be added via `mcp__xcode__XcodeWrite`**
- **Build after every change** — zero errors required
