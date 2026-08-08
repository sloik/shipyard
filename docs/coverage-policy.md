# Coverage policy

`make coverage` executes a clean (`-count=1`) coverage run for every reviewed
production package and writes the machine-readable current result to
`build/coverage/current.json`. `make coverage-check` runs that collection and
blocks when either the repository total or a checked-in package floor falls
below `.nightshift/coverage-baseline.json`.

The baseline is a reviewed floor, not a command that rewrites itself. Raising a
floor requires updating the baseline in the same review as the coverage gain.
Lowering a floor requires an explicit policy review and must explain the
regression. CI publishes the generated total and per-package summary.

## Diff policy

Changed non-generated Go packages must be present in the baseline. A new
package therefore cannot silently lower total coverage: add its measured floor
to the reviewed baseline (or add a narrowly justified exclusion) before the
ratchet can pass. Existing package floors are checked on every run.

## Exclusions

`.nightshift/coverage-exclusions.json` is the only exclusion list. It currently
contains only `internal/teststubchild`, a test-only helper executable. No
production package is blanket-excluded. Generated, third-party, or test-stub
code may be excluded only by adding its exact package and rationale there.

## Validation probe

`make coverage-check-probe` feeds a controlled lower-total/lower-package fixture
to the same checker and passes only if the ratchet rejects it.
