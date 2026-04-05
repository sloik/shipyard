---
id: SPEC-009-002
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-008]
prior_attempts: []
parent: SPEC-009
nfrs: []
created: 2026-04-05
---

# Binary E2E Smoke Coverage

## Problem

Shipyard’s current tests are predominantly package-local white-box tests. They validate internals well, but they still leave a confidence gap around the real shipped shape of the program: starting the binary, supervising a child MCP server, exposing HTTP endpoints, and capturing traffic through the actual runtime path.

## Requirements

- [x] Add deterministic e2e smoke tests that launch the real Shipyard binary or `main` package process
- [x] Use a stub child process/server rather than mocking the proxy/web layers directly
- [x] Verify at least one real HTTP-level outcome from the running process
- [x] Keep the tests CI-safe and deterministic
- [x] Keep `go test ./...` green

## Acceptance Criteria

- [x] AC 1: At least one e2e smoke test launches Shipyard against a stub child process
- [x] AC 2: The e2e suite verifies at least one HTTP API path from the running process
- [x] AC 3: The e2e suite verifies that runtime traffic capture occurs through the real process path
- [x] AC 4: The e2e suite shuts down cleanly without leaked processes
- [x] AC 5: `go test ./...` passes

## Context

- Main entrypoint: `cmd/shipyard/main.go`
- Runtime paths likely involved:
  - `internal/proxy/proxy.go`
  - `internal/web/server.go`
  - `internal/capture/store.go`

## Alternatives Considered

- **Approach A: More handler-level tests with `httptest`.**
  Rejected because those already exist and are not true end-to-end coverage.

- **Approach B: Process-level smoke tests using a stub child executable.**
  Preferred because it exercises the actual binary/runtime integration path.

## Scenarios

1. Shipyard starts, serves HTTP, and exposes baseline API state
2. A stub child exchanges JSON-RPC traffic through Shipyard and that traffic becomes queryable via the API
3. The process terminates cleanly after the test completes

## Out of Scope

- Browser automation
- Full multi-server orchestration
- Performance/load testing

## Notes for the Agent

- Prefer a self-contained stub child written in Go test code or a small helper process already under test control.
- Avoid tests that depend on long sleeps or external tools being installed.
