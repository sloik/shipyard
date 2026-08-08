---
id: SPEC-BUG-161
template_version: 7
priority: 1
layer: 1
type: refactor
status: in_progress
after: [SPEC-BUG-157, SPEC-BUG-158, SPEC-012]
provides: [tested-access-log-contract, drainable-audit-writes]
requires: [nightshift-valid-control-plane, canonical-quality-command]
touches: [internal/auth, internal/capture/access_log.go, internal/web/server.go]
prior_attempts: [SPEC-012]
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: go
domain: code
output_type: code
devkb_required: [go.md, testing.md, architecture.md]
cortex_cites: []
karpathy_checklist: [think, simple, surgical, goal]
---

# Test and Harden Access-Log Production-Path Durability

## Problem

SPEC-012 marks the access log complete, but both access-log HTTP handlers currently
measure 0% statement coverage. Tests exercise store pieces without proving the real
authenticated `tools/call` path persists allowed/denied calls and exposes them through
filter, pagination, and statistics endpoints. Audit writes are asynchronous and database
insert errors are discarded, with no deterministic shutdown-drain contract. No data loss
was reproduced during this review; this spec closes a high-impact correctness blind spot.

## Requirements

- [ ] R1: Add production-entry integration tests that invoke authenticated `tools/call` and verify persisted access-log records.
- [ ] R2: Cover allowed, denied, log-level, server/tool, time-range, pagination, invalid-parameter, and statistics behavior through HTTP handlers.
- [ ] R3: Give accepted asynchronous audit writes a deterministic drain/close contract used during shutdown and in tests.
- [ ] R4: Make persistence failures observable without changing the original MCP call result or leaking secrets.
- [ ] R5: Remove sleep-based primary oracles from the new tests and prove lifecycle cleanup under repetition/race detection.

## Acceptance Criteria

- [x] AC1 (R1): Tests enter through the authenticated JSON-RPC handler and assert persisted rows for successful, denied, failed, and configured log-level calls.
- [x] AC2 (R2): `handleAccessLog` tests cover server/tool/status/time filters, stable pagination, empty results, malformed dates, and invalid page sizes.
- [x] AC3 (R2): `handleAccessLogStats` tests assert totals and groupings from the same production-path fixture data; both handlers show non-zero coverage.
- [x] AC4 (R3): After N accepted audit writes, drain/close returns only after all N are persisted or returns an explicit error; a deterministic repeated test observes zero silent loss.
- [x] AC5 (R4): An injected database failure increments/logs a bounded observable error signal while the original JSON-RPC response preserves its defined success/error shape.
- [x] AC6 (R4): No token plaintext, secret reference value, or full sensitive params are emitted by the new error signal.
- [x] AC7 (R5): New tests use channels, wait groups, conditions, or explicit callbacks; no bare `time.Sleep` is their pass/fail oracle.
- [x] AC8: `go test -race -shuffle=on -count=20 -timeout 10m ./internal/auth ./internal/capture ./internal/web` passes with no goroutine leak or race warning.

## Live Execution Checklist

- [ ] LE1: Start Shipyard with auth and an ephemeral database, then execute one allowed and one denied tool call through the real endpoint.
- [ ] LE2: Query access-log and statistics HTTP endpoints and verify response shape, filters, and counts.
- [ ] LE3: Trigger graceful shutdown immediately after a bounded burst and verify the accepted records are durable after restart/readback.
- [ ] LE4: Force one persistence failure and verify the operator-visible signal without changing the caller's RPC contract.
- [ ] LE5: Record endpoint requests, counts, shutdown result, and redacted evidence in the run report.

## Context

- Authenticated production path: `internal/auth/middleware.go`.
- Access-log persistence: `internal/capture/access_log.go`.
- HTTP handlers: `internal/web/server.go:2587` and `internal/web/server.go:2634` (0% on 2026-07-18).
- Source spec: `.nightshift/specs/SPEC-012-tool-filtering-access-log.md`.
- Preserve the stdlib-first/real lightweight dependency test style in `Argo Home/DevKB/go.md`.

## Scenarios

1. Scoped token calls an allowed tool -> caller receives tool result -> access log shows one redacted allowed record -> stats include it.
2. Token calls a disallowed tool -> caller receives the defined denial -> access log records the denial without secret material.
3. Process receives shutdown after a burst -> drain completes -> all accepted audit events remain queryable.
4. Database rejects an insert -> RPC result remains correct -> bounded observable error evidence is emitted.

## Out of Scope

- Changing token scope semantics.
- Adding a new external queue/broker.
- Logging full tool arguments or secret values.
- General redesign of the capture store.

## Documentation Impact

- Access-log/operator documentation — persistence, shutdown, and error-observability contract.

## Research Hints

- Read `Argo Home/DevKB/go.md`, `testing.md`, and `architecture.md`.
- Prefer a small owned worker lifecycle with explicit drain/close over sleeps or unbounded goroutines.
- Use real ephemeral stores and HTTP/JSON-RPC handlers; direct store tests alone do not satisfy production-entry ACs.
- Add positive and negative authorization assertions in the same scenario family.

## Validation Commands

```bash
go test -race -shuffle=on -count=20 -timeout 10m ./internal/auth ./internal/capture ./internal/web
go test -count=1 -coverprofile=/tmp/access-log.cover ./internal/auth ./internal/capture ./internal/web
go tool cover -func=/tmp/access-log.cover
go test -race -count=1 -timeout 5m ./...
make quality
```
