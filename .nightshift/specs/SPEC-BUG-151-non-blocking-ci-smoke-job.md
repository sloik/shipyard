---
id: SPEC-BUG-151
template_version: 3
priority: 3
layer: 1
type: feature
status: draft
after: [SPEC-BUG-149]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Non-blocking CI job running `make smoke` on UI-touching PRs

## Problem

SPEC-BUG-149's headless smoke harness only runs when a developer invokes
`make smoke` locally. The regression it guards against (SPEC-BUG-148's
double-toggle) reached `main` precisely because the Go source-scan tests passed
while the behavior was broken. A CI job that runs the smoke harness on PRs that
touch the UI would catch this class at review time — but it must not become a
flaky gate that blocks unrelated merges.

## Requirements

- [ ] R1: A CI job runs `make smoke` (system Chrome, headless) on PRs that
  change UI assets (`internal/web/ui/**`) or the smoke harness.
- [ ] R2: The job is **non-blocking** (informational / does not gate merge) at
  least initially, to avoid a flaky browser job blocking unrelated work.
- [ ] R3: The job skips gracefully (and reports skip) when a browser cannot be
  provisioned in CI, rather than failing red.
- [ ] R4: The existing blocking Go CI (`go test -race`, vet, build) is unchanged.

## Acceptance Criteria

- [ ] AC1: A CI workflow/job runs `make smoke` triggered on UI-touching PRs.
- [ ] AC2: The job is configured non-blocking (e.g. `continue-on-error` or a
  separate informational check) and documented as such.
- [ ] AC3: Browser provisioning failure produces a SKIP/neutral result, not a
  hard failure.
- [ ] AC4: The existing CI test/vet/build jobs are untouched.

## Context

Builds on SPEC-BUG-149 (`make smoke`, `test/smoke/`). Existing CI lives in
`.github/workflows/ci.yml` (SPEC-015). CI runs on Linux runners — provisioning
Chrome there (vs the local macOS system Chrome) is the main design question.

## Out of Scope

- Making the smoke job a blocking merge gate (revisit after it proves stable).
- Cross-browser matrices.

## Gap Protocol

- Research-acceptable gaps:
  - How to provision Chrome on the CI runner (e.g. setup-chrome action) vs
    skipping when absent.
- Stop-immediately gaps:
  - Turning the smoke job into a blocking gate in this spec.
  - Changing the existing Go CI jobs.
- Max research subagents before stopping: 0
