---
id: SPEC-015
priority: 1
layer: 3
type: feature
status: done
after: [SPEC-010, SPEC-014]
prior_attempts: [SPEC-015-attempt-1-getRecentCalls-broken, SPEC-015-attempt-2-reset-clears-to-empty]
created: 2026-03-27
completed: 2026-03-28
---

# Pre-fill Execution Sheet with Last Used Parameters

## Problem

When a user repeatedly executes the same tool (e.g., testing an MCP during development), they must re-enter the same parameters every time. The execution sheet always opens with an empty `{}` payload. This is tedious — users want the sheet to remember the last parameters they used for a given tool so they can iterate quickly.

Additionally, the Retry button in the execution queue immediately re-fires the same request without giving the user a chance to review or tweak the parameters. And there's no way to quickly re-fire a tool call without going through the sheet at all.

## Requirements

- [ ] R1: When opening the execution sheet via the ▶ play button, the payload is pre-filled with the most recent execution's parameters for that specific tool. If no execution history exists, the payload is `{}` (current behavior).
- [ ] R2: The most recent execution is used regardless of success or failure.
- [ ] R3: The Retry button in the execution queue row opens the execution sheet pre-filled with that specific execution's parameters, instead of immediately re-executing.
- [ ] R4: A new Fast Retry button (⚡ or similar icon) in the execution queue row immediately re-executes the tool with the same parameters — no sheet, no confirmation.
- [ ] R5: A Reset button in the execution sheet resets the payload to schema defaults for required fields (same as R11 defaults: `string` → `""`, `number` → `0`, etc.). For tools with no required fields, reset to `{}`. This ensures the Reset state is always valid JSON that passes schema validation for required fields.
- [ ] R6: The response section of the sheet remains empty on open (no change from current behavior).
- [ ] R7: The existing recent calls dropdown must not be changed.
- [ ] R8: The existing execution queue panel logic must not be changed (beyond adding the new Fast Retry button and changing Retry behavior).
- [ ] R9: Fix `saveRecentCall()` and `getRecentCalls()` in `ExecutionQueueManager.swift` to use consistent serialization. The `arguments` field must be serialized as a dictionary via JSONSerialization (not via Codable), and deserialized the same way. This fixes the play button pre-fill which currently fails because `getRecentCalls()` receives base64-encoded arguments but tries to parse them as JSON strings.
- [ ] R10: In the Form tab (DynamicFormView), render required fields (those in the schema's `required` array) BEFORE optional fields. Required fields appear in schema order within the required group; optional fields appear in schema order within the optional group.
- [ ] R11: When the sheet opens with NO execution history, the JSON editor and Form fields pre-fill with empty typed defaults based on the schema: `string` → `""`, `number` / `integer` → `0`, `boolean` → `false`, `array` → `[]`, `object` → `{}`. If execution history exists, use the history values instead.

## Acceptance Criteria

- [ ] AC 1: Opening the sheet for a tool with previous executions shows the last-used parameters pre-filled in both JSON and Form tabs.
- [ ] AC 2: Opening the sheet for a tool with no execution history shows schema defaults for required fields (e.g., `{"text": ""}` for a tool with required string field `text`).
- [ ] AC 3: Clicking Retry on a completed/failed execution in the queue panel opens the execution sheet pre-filled with that execution's request parameters.
- [ ] AC 4: Clicking Fast Retry on a completed/failed execution immediately starts a new execution with the same parameters (no sheet, no confirmation). The new execution appears in the queue.
- [ ] AC 5: The Reset button in the sheet resets the JSON editor to schema defaults for required fields (e.g., `{"text": ""}`) and resets form fields accordingly. For tools with no required fields, resets to `{}`.
- [ ] AC 6: The Reset button is visible and accessible regardless of whether the sheet was opened via ▶, Retry, or recent calls.
- [ ] AC 7: Pre-fill works correctly when switching between JSON and Form tabs.
- [ ] AC 8: The recent calls dropdown continues to work as before — it is not modified.
- [ ] AC 9: Build succeeds with zero errors; all existing tests pass.
- [ ] AC 10: `getRecentCalls()` now correctly deserializes arguments from storage. Calling `getRecentCalls()` returns a non-empty array when execution history exists. Play button pre-fill now works correctly.
- [ ] AC 11: When opening the sheet for a tool with a required field (per schema), that field appears above optional fields in the Form tab.
- [ ] AC 12: When opening the sheet with no history, the JSON editor shows a pre-filled object with all required fields set to empty typed defaults (matching schema types). The Form tab pre-fills corresponding fields. When history exists, empty-default pre-fill is skipped and history values are used instead.

## Context

**Key files (read ALL before coding):**

- `Shipyard/Views/ToolExecutionSheet.swift` — the sheet view. Currently initializes with `payload: [:]` and `jsonText: "{}"`. The `.task` block loads recent calls but does not pre-fill from them.
- `Shipyard/Views/ExecutionQueueRowView.swift` — queue row with View and Retry buttons. Currently `retry()` calls `queueManager.retryExecution()` directly.
- `Shipyard/Views/ExecutionQueuePanelView.swift` — panel that hosts row views. Has `onViewExecution` callback.
- `Shipyard/Views/GatewayView.swift` — hosts the `.sheet(item: $sheetTool)` presentation. Has `onExecutionStarted` callback.
- `Shipyard/Models/ExecutionQueueManager.swift` — has `retryExecution()`, `getRecentCalls()`, `executeToolAsync()`.
- `Shipyard/Models/ToolExecution.swift` — execution model with `request: ToolExecutionRequest`.
- `Shipyard/Models/ToolExecutionRequest.swift` — request with `toolName` and `arguments: [String: Any]`.

**Existing data flow:**
- `GatewayView` sets `sheetTool` to open the sheet → `ToolExecutionSheet(tool:onExecutionStarted:)`
- The sheet's `.task` calls `queueManager.getRecentCalls(for:)` but doesn't auto-select the first one
- `ExecutionQueueRowView.retry()` calls `queueManager.retryExecution()` which calls `executeToolAsync()` directly

**Design reference:**
→ See: `docs/specs/009-tool-execution/` for design docs

## Out of Scope

- Changes to the recent calls dropdown
- Changes to the execution queue panel layout (beyond adding Fast Retry)
- Changes to the response/detail view
- Keyboard shortcuts for Fast Retry

## Prior Attempts

**Attempt 1: SPEC-015-attempt-1-getRecentCalls-broken**
- Implemented R1–R8 successfully. Play button (▶), Retry button, and Fast Retry button all functional with correct sheet pre-fill from execution history.
- However, discovered critical bug in `getRecentCalls()`: the method receives base64-encoded arguments (because `saveRecentCall()` uses `JSONEncoder` which encodes `Data` as base64), but tries to deserialize them as JSON strings. The cast `(dict["arguments"] as? String)?.data(using: .utf8)` succeeds (because base64 is a string), but `JSONSerialization.jsonObject` fails on base64 input. Result: `getRecentCalls()` always returns empty array; play button pre-fill never works.
- Retry button works because it passes `execution.request.arguments` directly to the sheet, bypassing `getRecentCalls()` entirely.
- Also incomplete: R10 (required fields sorting) and R11 (empty typed defaults pre-fill) were not implemented.
- **Action for next attempt:** Fix serialization in R9. Implement R10 and R11. Re-test play button pre-fill.

**Attempt 2: SPEC-015-attempt-2-reset-clears-to-empty**
- R9 fixed: `saveRecentCall`/`getRecentCalls` now use direct dictionary storage via JSONSerialization. Play button pre-fill works.
- R10 implemented: Required fields sorted to top in Form tab.
- R11 implemented: Schema defaults pre-fill when no history exists.
- However, `resetPayload()` clears to `{}` which fails schema validation for tools with required fields (e.g., `say` tool shows "Missing required field: text" after reset). R5 updated to reset to schema defaults instead.
- **Action for next attempt:** Change `resetPayload()` to call `buildDefaultPayload()` instead of clearing to empty dict.

## Notes for the Agent

- **Read DevKB/swift.md** before writing any code — especially entries #30 (batch array mutations), #33 (NSViewRepresentable), #34 (.onChange with .map())
- **New .swift files** MUST be added via `mcp__xcode__XcodeWrite` — writing to disk alone won't register in xcodeproj
- **Build after every change** — zero errors required
- **Do NOT use Combine** — use async/await and @Observable patterns
- **Do NOT guess API names** — grep existing code first
