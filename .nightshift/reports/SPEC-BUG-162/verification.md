# Verification — SPEC-BUG-162

## CRITICAL

None.

## WARNING

The macOS linker prints deployment-target warnings for `cmd/shipyard` test
objects. Every command exited successfully; this is unrelated to the test
synchronization changes.

## SUGGESTION

None.

## Acceptance Criteria

- AC1: Pass — `docs/testing-async-sleep-inventory.md` records all 24 original
  sites, package owner, classification, and bound.
- AC2: Pass — `rg -n 'time\.Sleep' --glob '*_test.go'` returns no hits.
- AC3: Pass — retained bounded loops name their target state and deadline
  failure; the policy documents the requirement.
- AC4: Pass — hub cancellation, proxy child cancellation, and access-log drain
  coverage prove component-owned lifecycle completion without global counts.
- AC5: Pass — the policy limits polling exceptions to `waitForFile` and
  `waitForHTTP`, both with deadline, interval, and diagnostics.
- AC6: Pass — three consecutive
  `go test -race -shuffle=on -count=50 -timeout 10m ./internal/auth ./internal/proxy ./internal/web`
  executions completed successfully.
- AC7: Pass — ordinary and race suites plus `make quality` completed
  successfully.

## Evidence

- `.nightshift/reports/_wip/SPEC-BUG-162-sleeps-before.txt`
- `rg -n 'time\.Sleep' --glob '*_test.go'` (empty)
- `go test -race -shuffle=on -count=50 -timeout 10m ./internal/auth ./internal/proxy ./internal/web` (three runs)
- `go test -count=1 ./...`
- `go test -race -count=1 -timeout 5m ./...`
- `make quality`

## Suggested Follow-up Specs

None. The remaining bounded polling is restricted to process boundaries and
documented as the deliberate exception.
