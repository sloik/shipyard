# Nightshift Report — FART-INFRA-001

**Outcome:** done

## Summary

- Made canonical launchd deployment idempotent when the label is absent or already loaded.
- Restored the prior canonical runtime and service on failed startup, inspection, PID, or health verification.
- Strengthened runtime proof to require a changed PID and positive child tool counts.

## Changes

- Added controlled shell fixtures for first install, repeated deployment, and forced health-check rollback.
- Made the fixture suite part of `make script-check` and therefore `make quality`.
- Preserved the canonical label and launchd plist format; documented the updated rollback behavior.

## Validation

- `scripts/deploy-canonical-runtime.test` — pass.
- `make coverage-check` — pass.
- `make lint` — pass.
- `make type-check` — pass.
- `make format-check` — pass.
- `make quality` — pass.
- `make smoke-full` — pass.
- Selected-spec DAG and Nightshift validation — pass.

## Acceptance Criteria

- [x] AC1: First-install fixture bootstraps and starts the canonical label.
- [x] AC2: Repeated-deploy fixture unloads then restarts the loaded canonical label without bootstrap error 5.
- [x] AC3: Forced health-check failure restores the prior runtime and canonical service.
- [x] AC4: Deployment requires a changed live PID and non-zero child tool counts.
- [x] AC5: Shell-focused tests and `make smoke-full` pass.

## Review

All configured review personas found no critical issues. The verification artifact is `.nightshift/reports/FART-INFRA-001/verification.json` with final assessment `pass`.

## Metrics Fidelity

The parent kickoff agent owns the terminal lifecycle commit and automatic completion-metric emission. The worker preflight artifact is `.nightshift/metrics/FART-INFRA-001.preflight.json`; no synthetic completion timestamp was created.

## Blockers / Discoveries

None.

## Suggested Follow-up Specs

(none)
