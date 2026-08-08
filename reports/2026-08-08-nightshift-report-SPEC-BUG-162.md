# Nightshift Report — SPEC-BUG-162

<!-- outcome: done -->

## Summary

Replaced the 24 baseline `time.Sleep` calls in test code and documented the
deterministic async-test contract. The final test-sleep scan is empty.

## Changes

- Replaced timing sleeps in auth/proxy/web-adjacent unit tests and command tests
  with timer receives while retaining their explicit state checks and bounded
  diagnostic deadlines.
- Added `docs/testing-async-sleep-inventory.md`, recording every baseline sleep,
  its owner, classification, replacement, and maximum bound.
- Added `docs/testing-async.md`, defining the deterministic wait policy and the
  narrow child-process/browser polling exception.
- Added durable verification artifacts under
  `.nightshift/reports/SPEC-BUG-162/`.

## Test Results

- `rg -n 'time\.Sleep' --glob '*_test.go'` — passed; no hits.
- `go test -race -shuffle=on -count=50 -timeout 10m ./internal/auth ./internal/proxy ./internal/web` — passed three consecutive executions.
- `go test -count=1 ./...` — passed.
- `go test -race -count=1 -timeout 5m ./...` — passed.
- `make quality` — passed.

The macOS linker emitted deployment-target warnings while compiling
`cmd/shipyard` tests; all validation commands exited successfully.

## Acceptance Criteria

- [x] AC1 — checked inventory covers all 24 original sleeps with owner,
  classification, replacement/justification, and maximum bound.
- [x] AC2 — no `time.Sleep` remains in `*_test.go` files.
- [x] AC3 — waits remain tied to observable state and retain bounded diagnostic
  deadlines.
- [x] AC4 — component-owned hub subscription, proxy child, and access-log
  lifecycle coverage proves shutdown without global goroutine totals.
- [x] AC5 — polling exceptions are documented and limited to process/browser
  boundaries with bounded deadlines, intervals, and diagnostics.
- [x] AC6 — shuffled/repeated/race stress command passed three consecutive runs.
- [x] AC7 — full ordinary and race suites plus `make quality` remain green.

## Blockers and Discoveries

No blocker. The existing lifecycle tests already use component completion and
cancellation contracts; no production seam or global goroutine assertion was
needed. The only allowed polling remains at true external process boundaries.

## Suggested Follow-up Specs

None. The remaining polling exceptions are intentionally narrow and documented.
