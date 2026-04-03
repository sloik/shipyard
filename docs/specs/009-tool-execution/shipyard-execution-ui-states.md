# Shipyard Execution Queue — UI States & Visual Reference

## State 1: Idle (Queue Empty, Panel Collapsed)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL                                     │
│                        │ (Tool list)                                │
│ ▼ Gateway              │                                            │
│   ├─ Shipyard (6)  [✓]│ Shipyard Tools                             │
│   ├─ mac-runner (3)[✓]│ ────────────────────────────────────────   │
│   ├─ lmstudio (5)  [✗]│ shipyard__gateway_call                     │
│   └─ hear-me-say (2)  │ Call a tool from a managed MCP             │
│                        │ [Toggle] [▶ Execute]                      │
│ ▼ Servers              │                                            │
│   ├─ lmac-run (4)  [✓]│ ...more tools                              │
│   └─ ...               │                                            │
├────────────────────────┴────────────────────────────────────────────┤
│ ▶ Execution Queue (0 active)                         [Discover ↻]   │
└────────────────────────────────────────────────────────────────────┘
```

**Panel collapsed:** Showing only title + divider. User sees queue exists but no entries.

---

## State 2: Tool Execution Form (Sheet Open)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Execute shipyard__gateway_call                    [Close] [Execute] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│ Call a tool from a managed MCP                                      │
│                                                                      │
│ Parameters (JSON)                                                   │
│ ────────────────────────────────────────────────────────────────── │
│ {                                                                    │
│   "tool": "mac-runner__run_command",                                │
│   "arguments": {                                                     │
│     "command": "echo hello"                                          │
│   }                                                                  │
│ }                                                                    │
│                                                                      │
│                                                                      │
│ [Syntax highlighting, JSON validation in real-time]                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

[Behind sheet: GatewayView still visible but dimmed]
```

**Sheet modal:** User fills JSON parameters, clicks Execute.

---

## State 3: Execution Starting (Panel Auto-Expanded)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL                                     │
│ (tool list)            │ (tool list unchanged)                      │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (1 active, 0 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [0.2s] 14:35:42                   │
│                                                                      │
│  (no action buttons while executing)                                │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Panel auto-expands:** Sheet closed, new queue entry visible with ⏳ spinner icon.

---

## State 4: Multiple Executions (Mixed States)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (still showing tool list)           │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (2 active, 3 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [2.4s] 14:35:42                   │
│  ⏳ logs                           [1.8s] 14:34:50                   │
│  ─────────────────────────────────────────────────────────────────  │
│  ✓ status                         [0.5s] 14:32:15  [View]           │
│  ✓ health                         [1.2s] 14:30:44  [View]           │
│  ✗ run_command                    [3.7s] 14:28:22  [View] [Retry]  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Mixed status:**
- ⏳ items are active (running now)
- ✓ items succeeded (can view response)
- ✗ items failed (can view error, retry)
- History separated by divider

---

## State 5: Execution Complete, Details Shown

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (now showing execution)             │
│ (tool list)            │                                            │
│                        │ shipyard__logs                             │
│                        │ shipyard__logs (prefixed)                  │
│                        │                                            │
│                        │ [Request] [Response] [Retry]               │
│                        │                                            │
│                        │ Response (raw JSON):                       │
│                        │ {                                          │
│                        │   "content": "INFO: Server healthy\n...",  │
│                        │   "contentLength": 1248                    │
│                        │ }                                          │
│                        │                                            │
│                        │ [Copy response] [Close]                    │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (2 active, 3 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [3.1s] 14:35:42                   │
│  ⏳ health                         [2.6s] 14:34:50                   │
│  ─────────────────────────────────────────────────────────────────  │
│  ✓ logs         ◀── SELECTED              [0.5s] 14:32:15  [View]  │
│  ✓ status                         [1.2s] 14:30:44  [View]           │
│  ✗ run_command                    [3.7s] 14:28:22  [View] [Retry]  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Detail pane switched:** User clicked "View" on a completed execution; detail now shows request/response tabs.

---

## State 6: Retry in Progress

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (showing execution detail)          │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (3 active, 4 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [4.2s] 14:35:42                   │
│  ⏳ health                         [3.7s] 14:34:50                   │
│  ⏳ run_command (RETRY)            [0.1s] 14:36:18  ← NEW ENTRY    │
│  ─────────────────────────────────────────────────────────────────  │
│  ✓ logs                           [0.5s] 14:32:15  [View]           │
│  ✓ status                         [1.2s] 14:30:44  [View]           │
│  ✗ run_command                    [3.7s] 14:28:22  [View] [Retry]  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Retry queued:** User clicked [Retry] on failed execution; new entry created, old failure stays in history.

---

## State 7: Error Handling (Socket Call Failed)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (showing error details)             │
│                        │                                            │
│                        │ shipyard__health (failed)                  │
│                        │ shipyard__health                           │
│                        │                                            │
│                        │ [Request] [Error] [Retry]                  │
│                        │                                            │
│                        │ Error:                                     │
│                        │ Bridge socket call timed out after 5s      │
│                        │                                            │
│                        │ [Copy error] [Retry] [Close]               │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (1 active, 4 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [5.3s] 14:35:42                   │
│  ─────────────────────────────────────────────────────────────────  │
│  ✗ health                         [5.0s] 14:36:25  [View] [Retry]  │
│  ✓ logs                           [0.5s] 14:32:15  [View]           │
│  ✓ status                         [1.2s] 14:30:44  [View]           │
│  ✗ run_command                    [3.7s] 14:28:22  [View] [Retry]  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Error display:** Failed execution shows error tab with message, user can retry.

---

## State 8: Queue Panel Resized (Dragging Divider)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (tool list)                         │
│                        │                                            │
│                        │ ...                                        │
│                        │ ...                                        │
├────────────────────────┴────────────────────────────────────────────┤
│ ◀━━ ▤▤ (draggable divider, 12pt tall) ━━▶                         │
├────────────────────────────────────────────────────────────────────┤
│ ▼ Execution Queue (2 active, 5 done)               [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ⏳ gateway_call                   [6.2s] 14:35:42                   │
│  ⏳ logs                           [5.0s] 14:34:50                   │
│  ─────────────────────────────────────────────────────────────────  │
│  ✓ status                         [0.5s] 14:32:15  [View]           │
│  ✓ health                         [1.2s] 14:30:44  [View]           │
│  ✗ run_command                    [3.7s] 14:28:22  [View] [Retry]  │
│  ✓ discover_tools                 [2.1s] 14:25:33  [View]           │
│  ✗ sync                           [4.5s] 14:20:08  [View] [Retry]  │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘

[Panel now taller — shows more history entries]
```

**Resize:** User dragged divider up; panel grew to show more history.

---

## State 9: Large History (Scrollable)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL                                     │
├────────────────────────┴────────────────────────────────────────────┤
│ ▼ Execution Queue (0 active, 20 done)              [Clear history]  │
├────────────────────────────────────────────────────────────────────┤
│  ✓ gateway_call                   [0.2s] 14:50:12  [View]  ▲        │
│  ✓ logs                           [0.5s] 14:49:30  [View]  │        │
│  ✓ status                         [0.3s] 14:48:55  [View]  │        │
│  ✓ health                         [1.2s] 14:47:20  [View]  │        │
│  ✓ run_command                    [2.1s] 14:46:08  [View]  │        │
│  ✓ discover_tools                 [0.8s] 14:45:33  [View]  │        │
│  ✓ sync                           [1.5s] 14:44:00  [View]  │        │
│  ✓ check_health                   [0.4s] 14:42:45  [View]  │        │
│  ✓ restart_server                 [3.2s] 14:41:15  [View]  │        │
│  ✓ get_logs                       [0.9s] 14:39:22  [View]  │        │
│  ✓ ...                            [X.Xs] HH:MM:SS  [View]  │ SCROLL │
│  ✓ ...                            [X.Xs] HH:MM:SS  [View]  │        │
│  ✓ ...                            [X.Xs] HH:MM:SS  [View]  │        │
│  ✓ oldest_entry                   [0.6s] 14:00:01  [View]  ▼        │
│                                                                      │
│  [Only last 20 kept in history]                                     │
│                                                                      │
└────────────────────────────────────────────────────────────────────┘
```

**Scrollable history:** Panel scrolls when history exceeds visible height. Only last 20 kept to avoid memory issues.

---

## State 10: Panel Collapsed (Minimized)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Shipyard Gateway Tab                                                │
├────────────────────────┬────────────────────────────────────────────┤
│ SIDEBAR                │ DETAIL (full height again)                 │
│                        │ (more visible)                             │
│                        │                                            │
│                        │                                            │
│                        │                                            │
│                        │                                            │
│                        │                                            │
│                        │                                            │
│                        │                                            │
│                        │                                            │
├────────────────────────┴────────────────────────────────────────────┤
│ ▶ Execution Queue (2 active, 8 done)               [Clear history]  │
└────────────────────────────────────────────────────────────────────┘

[Only title bar visible; click ▶ to expand]
```

**Collapsed:** Panel minimized to title bar. User can click ▶ to expand, or click [Clear history] without expanding.

---

## Responsive Behavior: Narrow Window

```
┌────────────────────────────────────────────┐
│ Shipyard Gateway                           │
├─────────────┬──────────────────────────────┤
│ SIDEBAR     │ DETAIL                       │
│ (narrow)    │ (narrow too, but readable)  │
├─────────────┴──────────────────────────────┤
│ ▼ Queue (2 active, 3 done) [Clear]        │
├────────────────────────────────────────────┤
│  ⏳ gateway_call [2.4s] 14:35 [View]      │
│  ⏳ logs         [1.8s] 14:34 [View]      │
│  ─────────────────────────────────────    │
│  ✓ status       [0.5s] 14:32 [View]      │
│  ✓ health       [1.2s] 14:30 [View]      │
│  ✗ run_cmd      [3.7s] 14:28 [Retry]    │
│                                            │
└────────────────────────────────────────────┘

[Timestamps wrapped, action buttons on next line if needed]
```

**Narrow window:** Queue entries adapt to narrow widths; timestamps truncated, buttons on next line.

---

## Touch/Trackpad Gesture: Pan to Resize

```
User drags up from divider:
         User touches divider
              │
              ▼
         Cursor changes to ⇅ (resize)
              │
              ▼
         User drags upward (toward top)
              │
              ▼
         Panel grows (takes up more space)
              │
              ▼
         Release touch
              │
              ▼
         Panel height persists (UserDefaults)
              │
              ▼
         Next session opens at same height
```

**Draggable:** Divider has 12pt drag target; visual feedback shows resize cursor.

---

## Keyboard Shortcuts (Future Enhancement)

```
⌘E      - Open execution sheet for currently selected tool
⌘W      - Close execution detail (return to tool list)
⌘K      - Focus queue search (filter by tool name)
↑↓      - Navigate queue entries
Enter   - Select entry / open detail view
Delete  - Remove entry from queue (if not executing)
```

---

## Accessibility: VoiceOver Labels

### ExecutionQueueRowView

```
For a running entry:
"Shipyard gateway call tool, executing, started 2:35 PM, 2.4 seconds elapsed"

For a successful entry:
"Shipyard logs tool, completed successfully, 0.5 seconds elapsed, 2:32 PM"

For a failed entry:
"Mac runner run command tool, failed, 3.7 seconds elapsed, 2:28 PM. Retry button available."
```

### Buttons

```
[View] button: "Show request and response details for this execution"
[Retry] button: "Run this tool again with the same parameters"
[Clear history] button: "Remove all completed executions from the queue"
```

### Panel Header

```
"Execution Queue, 2 active executions, 8 completed. Expand button to show entries."
```

---

## Summary: UI State Transitions

```
IDLE
  ↓
user clicks ▶ Execute (on tool row)
  ↓
FORM OPEN (sheet modal)
  ↓
user fills parameters, clicks Execute
  ↓
sheet dismisses, execution starts
  ↓
EXECUTING (queue entry visible with ⏳)
  ↓ [if user clicks View immediately]
DETAIL VIEW (shows "still running..." message)
  ↓ [when execution completes]
COMPLETED (entry shows ✓ or ✗, moves to history)
  ↓
[user clicks View / Retry / Clear]
  ↓
DETAIL VIEW (shows request/response) OR back to IDLE
```

Each state is independent; users can:
- Start multiple executions concurrently
- View any completed execution while others are running
- Resize panel independently of viewing details
- Collapse/expand panel to focus on tool list or queue
