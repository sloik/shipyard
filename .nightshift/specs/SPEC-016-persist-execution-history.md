---
id: SPEC-016
priority: 1
layer: 3
type: feature
status: ready
after: [SPEC-009, SPEC-015]
prior_attempts: []
created: 2026-03-27
---

# Persist Execution History Across App Restarts

## Problem

The execution queue history (`ExecutionQueueManager.history`) is in-memory only — it resets to empty on every app launch. Users who restart Shipyard lose all visibility into previous tool calls. Since the queue panel and its Retry/Fast Retry/View buttons only work on entries in `history`, users cannot review or re-run past executions after a restart.

Recent calls (per-tool, max 5) already persist via UserDefaults and survive restarts. But the full execution history (up to 20 entries with request + response + status + timing) does not.

## Requirements

- [ ] R1: On app launch, `ExecutionQueueManager` loads the last persisted execution history from UserDefaults. History entries appear in the queue panel immediately — no execution needed first.
- [ ] R2: After every execution completes (success or failure) or is cancelled, the full history array is persisted to UserDefaults.
- [ ] R3: Persisted entries include: tool name, request arguments, response JSON (if success), error string (if failure), status, startedAt, completedAt.
- [ ] R4: The persistence cap matches the existing in-memory cap: 20 entries. Oldest entries are evicted on overflow (same as current `moveToHistory` logic).
- [ ] R5: Active/pending/executing executions are NOT persisted — they are transient. Only completed (success/failure/cancelled) entries are stored.
- [ ] R6: Restored history entries are read-only for display — View button works (shows request + response). Retry and Fast Retry work (they create new executions from the stored request).
- [ ] R7: If persisted data is corrupt or unreadable, fail gracefully — start with empty history, log a warning. Do not crash.

## Acceptance Criteria

- [ ] AC 1: Launch app → execute a tool → quit app → relaunch → the execution appears in the queue panel history section.
- [ ] AC 2: View button on a restored execution shows the request and response in ExecutionDetailView.
- [ ] AC 3: Retry on a restored execution opens the sheet pre-filled with the original parameters (SPEC-015 behavior).
- [ ] AC 4: Fast Retry on a restored execution immediately re-executes with the original parameters.
- [ ] AC 5: History cap is enforced: if 20 entries are persisted and a new execution completes, the oldest persisted entry is evicted.
- [ ] AC 6: Corrupt or missing UserDefaults data results in empty history (no crash, warning logged).
- [ ] AC 7: Active executions do NOT appear in persisted data — only completed/failed/cancelled.
- [ ] AC 8: Build succeeds with zero errors; all existing tests pass.

## Context

**Key files (read ALL before coding):**

- `Shipyard/Models/ExecutionQueueManager.swift` — the queue manager. Has `history: [ToolExecution]` array and `moveToHistory()` method. Already uses UserDefaults for recent calls persistence (`recentCallsPrefix`). Add history persistence here.
- `Shipyard/Models/ToolExecution.swift` — `@Observable @MainActor` class with `id`, `toolName`, `request`, `status`, `startedAt`, `completedAt`, `response`, `error`. Not `Codable` — you'll need to add serialization.
- `Shipyard/Models/ToolExecutionRequest.swift` — `Codable` struct with `toolName` and `arguments: [String: Any]`. Has custom Codable (encodes arguments as Data). **Important:** SPEC-015 fixed the save/load to use JSONSerialization directly — follow the same pattern, not Codable.
- `Shipyard/Models/ToolExecutionResponse.swift` — has `responseJSON: String`. Check if it's Codable.
- `Shipyard/Views/ExecutionQueueRowView.swift` — row view with View, Retry, Fast Retry buttons.
- `Shipyard/Views/ExecutionQueuePanelView.swift` — panel showing history.
- `Shipyard/Views/ExecutionDetailView.swift` — detail view for View button.

**Serialization approach:**
Since `ToolExecution` is `@Observable @MainActor` (not Codable), the simplest approach is manual dictionary serialization in `ExecutionQueueManager`:

```
// Save: ToolExecution → [String: Any] dictionary
// Load: [String: Any] dictionary → ToolExecution

// Use JSONSerialization for arguments (same as SPEC-015 fix)
// Store as [[String: Any]] in UserDefaults key "execution.history"
```

**Data flow:**
1. `moveToHistory()` already runs after every execution — add `persistHistory()` call there
2. `init()` loads persisted history on startup
3. Restored `ToolExecution` objects need valid `status`, `startedAt`, `completedAt`, `request`, `response`/`error` — but NOT a `Task` reference (they're not running)

## Out of Scope

- Persisting active/executing executions (they're transient)
- Migration from older data formats (first implementation, no legacy data)
- Exporting history to file
- History search/filter

## Notes for the Agent

- **Read DevKB/swift.md** before writing any code
- **Do NOT use Codable on ToolExecution** — it's `@Observable @MainActor` which doesn't play well with Codable synthesis. Use manual dictionary serialization via JSONSerialization.
- **Follow the SPEC-015 pattern** for serialization — `saveRecentCall()` and `getRecentCalls()` use direct dictionary storage, not Codable. Do the same for history.
- **Arguments are `[String: Any]`** — store them as-is in the dictionary (UserDefaults handles plist-compatible types). If arguments contain non-plist types, serialize via JSONSerialization first.
- **Do NOT create new .swift files** — all changes should be in existing files
- **Build after every change** — zero errors required
- **Do NOT use Combine**
