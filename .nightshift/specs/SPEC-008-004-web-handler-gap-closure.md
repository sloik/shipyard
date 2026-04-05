---
id: SPEC-008-004
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-008-003]
prior_attempts: []
parent: SPEC-008
nfrs: []
created: 2026-04-05
---

# Web Handler Coverage Gap Closure

## Problem

`internal/web/server.go` still has residual uncovered branches in traffic listing, tool-call error handling, startup/shutdown, and websocket edge behavior. These paths are externally visible API/runtime behavior and should be fully pinned down if the project is pursuing complete statement coverage.

## Requirements

- [x] Add tests for the remaining uncovered branches in `handleTraffic`
- [x] Add tests for the remaining uncovered branches in `handleToolCall`
- [x] Add tests for the remaining uncovered branches in `Start`
- [x] Add tests for the remaining uncovered branches in `handleWebSocket`
- [x] Keep `go test ./...` green

## Acceptance Criteria

- [x] AC 1: `internal/web/server.go:handleTraffic` reaches `100.0%`
- [x] AC 2: `internal/web/server.go:handleToolCall` reaches `100.0%`
- [x] AC 3: `internal/web/server.go:Start` reaches `100.0%`
- [x] AC 4: `internal/web/server.go:handleWebSocket` reaches `100.0%`
- [x] AC 5: Tests cover handler error/default branches, not just happy paths
- [x] AC 6: `go test ./...` passes

## Context

- File under test: `internal/web/server.go`
- Existing tests:
  - `internal/web/server_test.go`
  - `internal/web/web_extra_test.go`

## Alternatives Considered

- **Approach A: Continue using real HTTP/WebSocket test servers where practical.**
  Preferred because it exercises actual handler behavior.

- **Approach B: Shallow unit tests with mocked transport only.**
  Rejected when they stop reflecting real handler behavior.

## Scenarios

1. Traffic listing applies defaults and handles store failure paths
2. Tool-call API returns structured errors for remaining invalid RPC/body cases
3. Server startup/shutdown covers the remaining control-flow branches
4. Websocket handling covers the remaining read/write edge cases without flakiness

## Out of Scope

- UI redesign
- New API endpoints
- Websocket protocol changes

## Research Hints

- Reuse the existing real-handshake websocket tests
- Favor `httptest` and real handler execution over mocked internals

## Gap Protocol

- Research-acceptable gaps:
  - forcing remaining websocket write/read failure branches deterministically
  - store/query failure injection from the handler layer
- Stop-immediately gaps:
  - remaining uncovered web branches require invasive runtime redesign
- Max research subagents before stopping: 2

## Notes for the Agent

- Keep assertions focused on user-visible HTTP/WebSocket behavior, status codes, and payloads.
