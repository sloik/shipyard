---
id: SPEC-NFR-001
priority: 1
layer: 0
type: nfr
status: ongoing
after: [SPEC-BUG-043]
created: 2026-04-14
---

# NFR: Zero data races — go test -race must pass clean

## Policy

`go test -race -count=1 ./...` must pass with **zero** race detector warnings
on every commit to `main`. This is an ongoing quality constraint with no final
"done" state — it is monitored permanently.

Any new race detected by the race detector is a blocking defect. File a
`SPEC-BUG-*` spec, set `violates: [SPEC-NFR-001]`, and promote to `ready`
before merging the offending code.

## Rationale

Go's race detector (`-race`) catches concurrent memory accesses that are
correct today but non-deterministically corrupt state or crash under load.
Races in test helpers mask real bugs in production code. Shipyard is a
long-running proxy process with goroutines per connected client — race
conditions surface in production before they surface in tests.

## Verification

The nightly CI job (SPEC-015 / `.github/workflows/ci.yml`) runs
`go test -race -count=1 -timeout 5m ./...`. A red nightly build is the
primary signal that this NFR is violated.

Manual check:
```bash
go test -race -count=1 -timeout 5m ./...
# Expected: exit 0, zero "WARNING: DATA RACE" lines
```

## Current status

SPEC-BUG-043 tracks three known races introduced before this NFR was
established. Once SPEC-BUG-043 is `done`, the baseline is clean and this
policy applies prospectively.

## Scope

- All packages under `./...` (the full module)
- Both unit tests and integration tests
- Does NOT apply to generated code outside the module (vendor/, third-party)

## Exemptions

None. If a test genuinely cannot avoid a race (e.g. intentional concurrent
stress test), use `//go:build !race` build tag with a comment explaining why,
and get explicit approval before merging.
