# Nightshift Report — SPEC-BUG-169

**Outcome:** done

## Summary

- Added a version-controlled, locked `file://` vulnerability database and a
  vendored vulnerable dependency reachable from the fixture's `main` package.
- `make security-self-test` now executes the real pinned `govulncheck` offline
  probe and requires its deterministic nonzero result to name `GO-SHIPYARD-0001`.
- Production `security-govulncheck` configuration is unchanged.

## Changes

- Added `security-govulncheck-offline-fixture`, isolated from the production
  security target.
- Added `test/security-fixtures/govulncheck-offline/`, including the vendored
  `v0.0.1` dependency, advisory database, and usage documentation.
- Extended the security self-test to reject a passing scanner or an advisory
  result that does not contain the locked advisory ID.

## Validation

- `python3 .nightshift/preflight.py --spec-id SPEC-BUG-169` — pass.
- `make security-self-test` — pass; the real offline probe rejected
  `GO-SHIPYARD-0001` as expected.
- `make coverage-check` — pass (75.3%).
- `make lint`, `make type-check`, `make format-check`, and `make quality` — pass.
- `go test -race -count=1 -timeout 5m ./...` — pass.
- `make security-config-check` — pass.

## Acceptance Criteria

- [x] AC1: The fixture's reachable vulnerable dependency causes the pinned
  `govulncheck` to exit nonzero deterministically.
- [x] AC2: The probe uses a checked-in `file://` database with `GOPROXY=off`,
  `GOSUMDB=off`, and `GOVCS=*:off`; its dependency is vendored.
- [x] AC3: `make security-self-test` documents and executes the offline probe.

## Review

All configured self-review personas found no critical issue. The detailed
verification artifact is `.nightshift/reports/SPEC-BUG-169/verification.json`.

## Metrics Fidelity

The parent kickoff agent owns the terminal lifecycle transition and its
completion metric. Worker evidence is recorded in
`.nightshift/metrics/SPEC-BUG-169.preflight.json` and the verification artifact.

## Blockers / Discoveries

None. The pinned v1.4.0 release supports a stable local `-db file://` source,
so no fallback command-path-only probe was needed.

## Suggested Follow-up Specs

(none)
