# Nightshift Report — SPEC-BUG-161

**Outcome:** done

## Summary

Access-log writes from the authenticated JSON-RPC `tools/call` production path
now enter an owned asynchronous lifecycle. Every accepted write is included in
`DrainAccessLog` and `Store.Close`; failures create a bounded redacted signal
without changing the caller's JSON-RPC result.

## Changes

- Replaced fire-and-forget access-log goroutines with `RecordAccessAsync`.
- Added deterministic drain/close behavior and an operator-visible failure count.
- Replaced sleep-based auth test synchronization with the drain contract.
- Added production-path allowed, denied, upstream-error, configured-log-level,
  injected-persistence-failure, HTTP filter/pagination/stats, and repeated-drain tests.

## Acceptance Criteria

- [x] AC1 — authenticated JSON-RPC calls cover successful, denied, failed, and configured log-level records.
- [x] AC2 — HTTP access-log filters, stable pagination, empty/default behavior, malformed dates, and invalid page size handling are covered.
- [x] AC3 — access-log statistics totals and groupings are asserted from fixture data; handler coverage is non-zero.
- [x] AC4 — accepted asynchronous writes drain deterministically; 64 accepted writes persist with no silent loss.
- [x] AC5 — injected database-table failure increments the bounded signal while the JSON-RPC success result remains unchanged.
- [x] AC6 — persistence error signal is a fixed redacted message and tests assert no injected secret is included.
- [x] AC7 — new asynchronous tests use `DrainAccessLog`; no bare sleep is an oracle.
- [x] AC8 — repeated focused race/shuffle validation completed without race or leak diagnostics.

## Validation Evidence

- `go test -race -shuffle=on -count=20 -timeout 10m ./internal/auth ./internal/capture ./internal/web` — pass
- `go test -race -count=1 -timeout 5m ./...` — pass
- `make quality` — pass
- `go test -count=1 -coverprofile=/tmp/access-log.cover ./internal/auth ./internal/capture ./internal/web` — pass; total statements: 75.8%
- `git diff --check` — pass

## Live Execution Checklist

The production path is exercised with real ephemeral SQLite stores and HTTP/JSON-RPC handlers. No external Shipyard process was started: the runtime behavior is covered deterministically by the in-process production entrypoint, including immediate drain/close behavior and injected database failure.

## Blockers

None.

## Suggested Follow-up Specs

(none)
