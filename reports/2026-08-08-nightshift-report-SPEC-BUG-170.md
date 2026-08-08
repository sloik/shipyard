# Nightshift Report — SPEC-BUG-170

**Outcome:** blocked — CI evidence gap

## Summary

- Dispatched CI run [31270602549](https://github.com/sloik/shipyard/actions/runs/31270602549) on remote `main` and retained only run metadata, job status, and executed step names.
- The run completed with conclusion `success`, but it executed remote SHA `0a9627dc7c7da27e98e9e3b11c02ea9c17a84a73`, which predates SPEC-BUG-159's local workflow hardening commit `05e58c59762849a78712774048781e6941859cb6`.
- Consequently, no CI run executing the SPEC-BUG-159 security gate is available yet. No raw GitHub Actions logs or scanner output were accessed, stored, or uploaded.

## Changes

- Added this bounded, non-sensitive CI-evidence report and the matching Nightshift metrics record.
- Did not modify application code, workflow configuration, or lifecycle state.

## Validation

- `python3 .nightshift/preflight.py --spec-id SPEC-BUG-170` — pass.
- `python3 .nightshift/audit_nfr.py --check-all --specs-dir .nightshift/specs` — pass.
- `make security-config-check` — pass for the local SPEC-BUG-159 workflow configuration.
- GitHub Actions metadata for run `31270602549` — completed `success`; completed steps were checkout, setup-go, Linux dependencies, `go vet`, race tests, and build. The security step was absent.

## Acceptance Criteria

- [ ] AC1: Not met. Run `31270602549` has an identified successful conclusion, but it was executed at the pre-SPEC-BUG-159 remote SHA and did not run `Run reachable vulnerability and Go security analysis`.
- [x] AC2: Met. Evidence is limited to non-sensitive run/job/step metadata; no scanner output, raw job logs, secrets, or uploaded artifacts were retained.
- [ ] AC3: Not met. SPEC-BUG-159 is linked above, and the CI-only gap is documented: local workflow configuration has not reached GitHub's `main`, so configured permissions and pinned actions cannot yet be confirmed as applied by CI.

## Blocker and Minimal Recovery

**Blocker:** `origin/main` is `0a9627d`, while SPEC-BUG-159's workflow change is local at `05e58c5`. GitHub therefore dispatched the legacy workflow, whose CI job has no default `permissions: contents: read`, pinned action SHAs, or security-gate step.

**Smallest bounded recovery:** publish the already-integrated local `main` revision containing `05e58c5` to `origin/main` (or open a PR containing that revision), then dispatch CI on that exact SHA and record only its run ID, conclusion, and completed `Run reachable vulnerability and Go security analysis` step. Do not collect scanner logs.

## Suggested Follow-up Specs

(none)
