---
id: BUG-SHIPYD-003
template_version: 3
priority: 1
layer: 0
type: bugfix
status: done
after:
- SPEC-BUG-159
violates:
- SPEC-BUG-159
nfrs: []
nfr_waivers:
- id: SPEC-NFR-001
  reason: Workflow-only change to how CI installs Go; no Go source and no goroutines are touched
prior_attempts: []
attachments: []
created: 2026-11-13
stack: github-actions
devkb_required:
- github.md
- go.md
scope:
  write:
  - .github/workflows/*.yml
---

# CI security gate red: workflows build with Go 1.26.10, which carries GO-2026-6859

## Problem

With the quality gate fixed (BUG-SHIPYD-002), the CI job `test` reaches the step "Run reachable
vulnerability and Go security analysis" and fails there (run 43416709784):

```
Vulnerability #1: GO-2026-6859
  Standard library
    Found in: net/http@go1.26.10
    Fixed in: net/http@go1.26.11
Your code is affected by 1 vulnerability from the Go standard library.
make: *** [Makefile:143: security-govulncheck] Error 3
```

Go 1.26.11 is released and fixes it. Every workflow asks `actions/setup-go` for `go-version: "1.26"`
without `check-latest`, so the action is satisfied by whichever 1.26.x the runner image has cached
(1.26.10 today). `main` therefore stays red until the image catches up, and `release.yml` would
publish binaries built with the vulnerable standard library in the meantime.

**Violated spec:** SPEC-BUG-159 (vulnerability and supply-chain gates)
**Violated criteria:** the reachable-vulnerability gate (`make security`) passes on `main` in CI.

## Reproduction

1. Open GitHub Actions run 43416709784, job `test`.
2. **Actual:** `make security` exits non-zero on GO-2026-6859 with `net/http@go1.26.10`.
3. **Expected:** the job uses the newest released Go 1.26 patch and `govulncheck` reports no
   reachable standard-library vulnerability that a released patch already fixes.

## Root Cause

`actions/setup-go` resolves a partial version such as `"1.26"` against the runner tool cache first
and only downloads when nothing cached satisfies it. Without `check-latest: true` the cached
1.26.10 wins over the released 1.26.11.

## Requirements

- [x] R1: Every `actions/setup-go` step in `.github/workflows/` resolves the newest released patch
      of the requested Go minor, not the runner's cached one.
- [x] R2: The Go minor line (1.26) and the pinned action SHA are unchanged.
- [x] R3: The CI job `test` passes `make security` on `ubuntu-latest`.

## Acceptance Criteria

- [x] AC1: Each of the five `actions/setup-go` steps (`ci.yml` x2, `release.yml`, `desktop.yml`,
      `smoke.yml`) sets `check-latest: true`; a count of `setup-go` uses equals a count of
      `check-latest: true` lines.
- [x] AC2: `actionlint` passes on all workflows (`make script-check`).
- [x] AC3: On the PR that carries this change, job `test` passes, including the step "Run reachable
      vulnerability and Go security analysis", and the job log shows Go 1.26.11 or newer.
- [x] AC4: `go-version` values and action SHAs in the diff are unchanged. The SPEC-BUG-159
      reachable-vulnerability gate passes again on `main` after merge.

## Scope Amendments

| Date | Path or glob | Change (old → new) | Reason | Approved by |
| --- | --- | --- | --- | --- |
| 2026-11-13 | .nightshift/specs/BUG-SHIPYD-003-ci-go-patch-release-for-govulncheck.md | not in scope → this spec's own file may be created by the delivering commit | The spec file was first committed together with the fix (PR #53), not on `main` beforehand, so the scope gate reads the new file as a `scope_self_edit`. The declared `scope.write` list itself was never widened. | human |

## Context

- Violated spec: `.nightshift/specs/SPEC-BUG-159-vulnerability-supply-chain-gates.md`
- Gate: `Makefile` target `security-govulncheck`.
- Go releases: 1.26.11 is listed at https://go.dev/dl/.
- Uncovered by: BUG-SHIPYD-002, whose earlier failure in the same job hid this one.

## Out of Scope

- Moving to Go 1.27 or changing `go.mod`.
- Suppressing or allow-listing the advisory.
- Third-party module vulnerabilities reported by Dependabot (SPEC-BUG-186).

## Code Pointers

- `.github/workflows/ci.yml` (lines 20-22, 58-60)
- `.github/workflows/release.yml` (lines 19-21)
- `.github/workflows/desktop.yml` (lines 17-19)
- `.github/workflows/smoke.yml` (lines 27-29)

## State rationale

```yaml
schema_version: 1
status: done
reason: mechanical transition to 'done' via run run-20261113-shipyd003
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261113T180143Z-status-transition-in-progress-done-mechanical-transition-t.json
```
