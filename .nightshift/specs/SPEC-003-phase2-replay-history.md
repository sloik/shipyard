---
id: SPEC-003
priority: 3
type: main
status: draft
after: [SPEC-002]
created: 2026-04-04
---

# Phase 2: Replay + Persistent History

## Problem

When a tool call fails during an AI conversation, the exact request is gone — the AI has moved on. Developers need to capture failing requests and replay them while iterating on their server code.

## Goal

Add one-click replay of any captured request and a searchable, persistent execution history.

## Key Features

1. **One-click replay** — any traffic entry (passive or UI-initiated) can be replayed against the server
2. **Edit-and-replay** — modify arguments before resending
3. **Persistent history** — SQLite-backed, survives restarts, searchable
4. **Search and filter** — by server, tool, status, time range, free text in payload

## Acceptance Criteria

- [ ] AC-1: "Replay" button on any traffic entry re-sends the original request to the same server
- [ ] AC-2: "Edit & Replay" opens the request in the form view with pre-filled arguments
- [ ] AC-3: History persists across proxy restarts (SQLite)
- [ ] AC-4: Search by method name, server name, time range, and free text in payload
- [ ] AC-5: History pagination for large datasets (100+ entries per page)
- [ ] AC-6: Response diff — compare two executions of the same tool side by side

## Out of Scope

- Session recording export (Phase 4)
- Collections / saved requests (deferred)
