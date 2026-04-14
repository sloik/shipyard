---
id: SPEC-BUG-043
template_version: 2
priority: 1
layer: 1
type: bugfix
status: ready
after: []
violates: [SPEC-NFR-001]
prior_attempts: []
created: 2026-04-14
---

# Data races in proxy and desktop tests detected by -race flag

## Problem

`go test -race -count=1 ./...` reports three data races across two packages.
The races are non-deterministic — they may or may not trigger on any given run —
but they cause intermittent test failures and will fire in nightly CI (SPEC-015).

## Reproduction

```bash
go test -race -count=1 -timeout 5m ./internal/proxy/...
go test -race -count=1 -timeout 5m ./cmd/shipyard/...
```

## Observed races

### Race 1 — `internal/proxy` · `TestChildInputWriter_WriteLineRetriesAfterNewlineFailure`

```
WARNING: DATA RACE
Write at proxy_more_test.go:77
  by goroutine spawned at proxy_more_test.go:163
    → proxy.(*failSecondWriteCloser).Write()
    → proxy.(*childInputWriter).writeLine()
    → TestChildInputWriter_WriteLineRetriesAfterNewlineFailure.func1()

Previous read at proxy_more_test.go:168
  by test goroutine (tRunner)
    → TestChildInputWriter_WriteLineRetriesAfterNewlineFailure()
```

### Race 2 — `cmd/shipyard` · `TestRunProxy_HeadlessTrue_DoesNotCallDesktop`

```
WARNING: DATA RACE
Write at desktop_test.go:225
  by Cleanup goroutine
    → TestRunProxy_HeadlessTrue_DoesNotCallDesktop.func1()

Previous read / concurrent write
  by database/sql background goroutine
    → sql.(*DB).ExecContext → sql.(*DB).exec → sql.(*DB).execDC
```

### Race 3 — `cmd/shipyard` · `TestRunProxy_HeadlessFalse_CallsDesktop`

```
WARNING: DATA RACE
Write at desktop_test.go:273 and desktop_test.go:274
  by Cleanup goroutine
    → TestRunProxy_HeadlessFalse_CallsDesktop.func1()

Concurrent write
  by database/sql background goroutine
    → sql.(*DB).ExecContext → sql.(*DB).exec → sql.(*DB).execDC
```

## Acceptance Criteria

- [ ] AC 1: `go test -race -count=1 -timeout 5m ./internal/proxy/...` reports zero races.
- [ ] AC 2: `go test -race -count=1 -timeout 5m ./cmd/shipyard/...` reports zero races.
- [ ] AC 3: `go test -race -count=1 -timeout 5m ./...` passes with zero races overall.
- [ ] AC 4: `go vet ./...` passes.
- [ ] AC 5: `go build ./...` passes.
- [ ] AC 6: No existing tests are removed or skipped to achieve the above.

## Context

- Race 1 source: `internal/proxy/proxy_more_test.go` lines 77, 163, 168
- Race 2–3 source: `cmd/shipyard/desktop_test.go` lines 225, 273, 274
- Production code involved: `internal/proxy/proxy.go:144` (`childInputWriter.writeLine`)
- NFR this violates: SPEC-NFR-001 (zero data races)

## Out of Scope

- Fixing races in packages other than `internal/proxy` and `cmd/shipyard`
- Changing test coverage or adding new test scenarios
- Refactoring production concurrency beyond what is required to eliminate the races
