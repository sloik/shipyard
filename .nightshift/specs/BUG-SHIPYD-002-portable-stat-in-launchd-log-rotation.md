---
id: BUG-SHIPYD-002
template_version: 3
priority: 1
layer: 2
type: bugfix
status: in_progress
after:
- SPEC-SHIPYD-001
violates:
- SPEC-SHIPYD-001
nfrs: []
nfr_waivers:
- id: SPEC-NFR-001
  reason: Shell-only change to a log rotation script and its test; no Go code and no goroutines are touched
prior_attempts: []
attachments: []
created: 2026-11-13
stack: shell
devkb_required:
- shell.md
scope:
  write:
  - scripts/rotate-launchd-logs.sh
  - scripts/rotate-launchd-logs.test
---

# CI red on main: launchd log rotation script and its test depend on BSD-only `stat -f`

## Problem

Since SPEC-SHIPYD-001 landed on `main` (2026-11-13, run 43407198224), the CI job `test` fails in
the step "Run canonical quality gate". `make quality` reaches `make script-check`, which runs
`sh scripts/rotate-launchd-logs.test` on `ubuntu-latest`:

```
sh scripts/rotate-launchd-logs.test
stat: cannot read file system information for '%i': No such file or directory
make: *** [Makefile:127: script-check] Error 1
```

`stat -f %z` and `stat -f %i` are the BSD form. On GNU coreutils `-f` means "file system status",
so the call fails. `main` is red, and every open dependency pull request inherits the same failing
check, so none of them can be judged on its own merits.

**Violated spec:** SPEC-SHIPYD-001 (Capture and log retention policy)
**Violated criteria:** AC5 (log rotation script with a passing test) together with the repository
rule that `make quality` passes on `main` in CI.

## Reproduction

1. On any Linux host with GNU coreutils (the `ubuntu-latest` runner), check out `main` at 0ae09d9.
2. Run `sh scripts/rotate-launchd-logs.test`.
3. **Actual:** exits non-zero with the `stat` error above.
4. **Expected:** prints `PASS: rotate-launchd-logs` and exits 0, as it does on macOS.

## Root Cause

`scripts/rotate-launchd-logs.sh:43` and `scripts/rotate-launchd-logs.test:9-10` call `stat` with
BSD-only flags. The script and its test were written and run only on macOS; the Linux runner was
the first GNU environment to execute them.

## Requirements

- [ ] R1: `scripts/rotate-launchd-logs.sh` reads a file's size without any `stat` call, using only
      POSIX utilities, and keeps its current behaviour (copy-truncate in place, same inode,
      `SHIPYARD_LOG_MAX_BYTES` and `SHIPYARD_LOG_KEEP` semantics).
- [ ] R2: `scripts/rotate-launchd-logs.test` reads size and inode without any `stat` call, using
      only POSIX utilities, and keeps every existing assertion.
- [ ] R3: The test fails if either file starts depending on `stat` again, on macOS as well as on
      Linux, so the regression is caught before it reaches CI.

## Acceptance Criteria

- [ ] AC1: `sh scripts/rotate-launchd-logs.test` prints `PASS: rotate-launchd-logs` and exits 0 on
      macOS (BSD userland).
- [ ] AC2: The CI job `test` passes the step "Run canonical quality gate" on `ubuntu-latest` for
      the commit that carries this fix.
- [ ] AC3: The test runs the script with a `stat` shim first on `PATH` that always fails, and still
      passes. Non-vacuity: with the fix reverted in either file, the same test fails on macOS.
- [ ] AC4: No assertion in `scripts/rotate-launchd-logs.test` is removed or loosened; the diff to
      the test only replaces the two helpers and adds the shim.
- [ ] AC5: `make script-check` passes locally. SPEC-SHIPYD-001 AC5 holds again in CI.

## Context

- Violated spec: `.nightshift/specs/SPEC-SHIPYD-001-capture-and-log-retention.md`
- Introduced by commit aaaf9fb.
- `Makefile:127` runs the test with `sh`; on Ubuntu `sh` is `dash`, so the fix must be POSIX `sh`.
- DevKB `shell.md`: "CI shell prerequisites must match Makefile shell requirements" (SPEC-BUG-170).

## Out of Scope

- Any change to rotation behaviour, thresholds or the launchd plist.
- `zsh scripts/deploy-canonical-runtime.test`, which already passes on the runner.
- Adding a macOS runner to CI.

## Code Pointers

- Bug area: `scripts/rotate-launchd-logs.sh` (line 43)
- Bug area: `scripts/rotate-launchd-logs.test` (lines 9-10)
- Gate: `Makefile` target `script-check`

## State rationale

```yaml
schema_version: 1
status: in_progress
reason: mechanical transition to 'in_progress' via run run-20261113-shipyd002
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261113T174737Z-status-transition-ready-in-progress-mechanical-transition-.json
```
