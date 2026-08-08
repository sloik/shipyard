# Nightshift Report — SPEC-BUG-160

- Date: 2026-08-08
- Status: implementation complete; awaiting parent-owned integration and lifecycle finalization
- Branch: `nightshift/SPEC-BUG-160-20260808T110520Z`

## Acceptance criteria

- [x] AC1 — `make coverage` performs a deterministic count-one collection and records total and all included package values.
- [x] AC2 — `make coverage-check` passes at the baseline; `make coverage-check-probe` proves the same checker rejects a lower total and package value.
- [x] AC3 — changed non-generated Go packages require a reviewed baseline entry; existing package floors are always checked.
- [x] AC4 — deterministic injected output writer removes process-global stdout mutation; 100 ordinary, 20 race, and 20 coverage repetitions passed.
- [x] AC5 — CI runs `make coverage-check`, publishes its summary, and Nightshift's configured test command is the same command.
- [x] AC6 — `2026-08-08-coverage-history-drift.md` documents the 74.8% all-package observation and the reviewed 75.1% policy baseline.
- [x] AC7 — `.nightshift/coverage-exclusions.json` explicitly excludes only the test-stub executable with rationale.
- [x] AC8 — ordinary/race validation and `make quality` passed.

## Validation evidence

```text
make coverage-check
make coverage-check-probe
go test -count=100 -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -race -count=20 -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -count=20 -cover -run '^TestRunChild_SuccessCapturesOutput$' ./internal/proxy
go test -race -count=1 -timeout 5m ./...
make quality
git diff --check
```

All passed. Current policy coverage: total 75.1%; per-package figures are in
`.nightshift/coverage-baseline.json` and emitted by `make coverage`.

## Suggested Follow-up Specs

- Raise package floors through focused behavior tests; do not lower the ratchet
  or pursue the historical 100% target with weakened assertions.
