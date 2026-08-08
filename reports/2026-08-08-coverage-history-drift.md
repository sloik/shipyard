# Coverage history drift record

On 2026-08-08, a clean `go test -count=1 -coverprofile=... ./...` measurement
reported **74.8%** repository statement coverage. This replaces neither the
historical evidence nor the `done` status of SPEC-008/SPEC-009: those records
describe the intended 100% closure and threshold work at that time, not a
permanent proof that every later repository state remains at 100%.

SPEC-BUG-160 establishes the truthful current baseline and blocking ratchet.
The historical all-package measurement was 74.8%; the reviewed 75.1% policy
baseline excludes only the explicit test-stub package. Each included package is recorded in
`.nightshift/coverage-baseline.json`; it is a floor that future changes may
improve but may not regress without an explicit reviewed change.
