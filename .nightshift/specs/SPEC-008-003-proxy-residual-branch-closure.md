---
id: SPEC-008-003
template_version: 2
priority: 1
layer: 0
type: refactor
status: done
after: [SPEC-008-002]
prior_attempts: []
parent: SPEC-008
nfrs: []
created: 2026-04-05
---

# Proxy Residual Branch Closure

## Problem

After `SPEC-007`, `internal/proxy` is strong but not complete. Remaining gaps are concentrated in residual helper/error branches such as timeout/cancel flows in manager request handling, newline-write failures, scanner error propagation, seam passthrough branches, and a few restart/backoff edge paths.

## Requirements

- [ ] Add tests for the remaining uncovered branches in `internal/proxy/manager.go`
- [ ] Add tests for the remaining uncovered branches in `internal/proxy/proxy.go`
- [ ] Close residual seam-helper branches introduced for deterministic lifecycle testing
- [ ] Keep the existing `Proxy.Run` semantics intact
- [ ] Keep `go test ./...` green

## Acceptance Criteria

- [ ] AC 1: `internal/proxy/manager.go:SendRequest` reaches `100.0%`
- [ ] AC 2: `internal/proxy/proxy.go:writeLine` reaches `100.0%`
- [ ] AC 3: `internal/proxy/proxy.go:waitForWriter` reaches `100.0%`
- [ ] AC 4: `internal/proxy/proxy.go:pipeAndTap` reaches `100.0%`
- [ ] AC 5: `internal/proxy/proxy.go:proxyClientInput` reaches `100.0%`
- [ ] AC 6: seam passthrough helpers and remaining backoff branches reach `100.0%`
- [ ] AC 7: `go test ./...` passes

## Context

- Files under test:
  - `internal/proxy/manager.go`
  - `internal/proxy/proxy.go`
- Existing tests:
  - `internal/proxy/manager_test.go`
  - `internal/proxy/proxy_test.go`
  - `internal/proxy/proxy_additional_test.go`
  - `internal/proxy/proxy_more_test.go`
  - `internal/proxy/proxy_run_test.go`

## Alternatives Considered

- **Approach A: Small test doubles for writer and timeout behavior.**
  Preferred for deterministic edge coverage.

- **Approach B: Broader refactor of proxy/runtime helpers.**
  Rejected unless a tiny seam is truly insufficient.

## Scenarios

1. Manager request waits time out or are canceled deterministically
2. Proxy writer fails on line body or newline and retries or returns correctly
3. Pipe forwarding hits write/scanner failures and exits predictably
4. Seam helper defaults are exercised without changing runtime semantics

## Out of Scope

- New proxy features
- Restart-policy redesign
- UI or storage changes

## Research Hints

- Start from the exact uncovered function list from `go tool cover -func`
- Use deterministic fake writers/readers before introducing new seams

## Gap Protocol

- Research-acceptable gaps:
  - deterministic timeout strategy for `SendRequest`
  - clean reproduction of newline write failure
- Stop-immediately gaps:
  - remaining uncovered branches are compiler/generated artifacts rather than real code paths
- Max research subagents before stopping: 2

## Notes for the Agent

- This spec is about finishing the proxy package cleanly, not reopening `SPEC-007`.
