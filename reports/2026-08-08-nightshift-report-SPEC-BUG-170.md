# Nightshift Report — SPEC-BUG-170

**Outcome:** done — first CI security-gate evidence recorded

## Summary

- Published the revision containing SPEC-BUG-159 and captured metadata for CI run [31273524268](https://github.com/sloik/shipyard/actions/runs/31273524268) at SHA `4877ea5b765f555ad03ce32e32de7d7347f2b2a6`.
- The run completed with conclusion `failure` after it executed `Run reachable vulnerability and Go security analysis`; this is the first retained outcome for the hardened security gate.
- Evidence is limited to run, job, and step metadata. No scanner output, raw scanner logs, secrets, or artifacts were retained.

## Changes

- Published the previously local security-gate workflow and repaired two declared CI runtime prerequisites (`zsh` and `ripgrep`) that blocked canonical quality before the security step.
- Added this bounded, non-sensitive CI-evidence record; production scanner configuration remains unchanged.

## Validation

- `make script-check` and `make security-config-check` — pass after declaring CI prerequisites.
- GitHub Actions metadata for run `31273524268` — the canonical quality gate passed, then `Run reachable vulnerability and Go security analysis` executed and concluded `failure`.
- The job metadata identifies pinned `actions/checkout` and `actions/setup-go` SHA steps on the exact published revision; workflow default permission remains `contents: read`.

## Acceptance Criteria

- [x] AC1: Run `31273524268` identifies the exact published SHA, overall `failure` conclusion, and the executed `Run reachable vulnerability and Go security analysis` step.
- [x] AC2: Evidence is limited to non-sensitive run/job/step metadata; no scanner output, raw job logs, secrets, or uploaded artifacts were retained.
- [x] AC3: This run verifies SPEC-BUG-159's published workflow permissions and pinned actions. CI-only finding: the security gate itself failed; diagnose that failure separately without weakening the gate.

## CI-only Finding

The security gate executed and failed. This report intentionally records only that metadata; resolving the gate failure is separate from proving that the CI workflow now runs it.

## Suggested Follow-up Specs

(none)
