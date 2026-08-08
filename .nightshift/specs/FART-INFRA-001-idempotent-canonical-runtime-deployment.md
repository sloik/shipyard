---
id: FART-INFRA-001
priority: 2
layer: 1
type: bugfix
status: in_progress
after: [SPEC-BUG-165-001]
nfrs: [SPEC-NFR-001]
technologies: [shell]
created: 2026-08-08
---

# Make canonical runtime deployment idempotent

## Problem

`make deploy-runtime` fails with launchd error 5 when the canonical Shipyard
label is already loaded. It replaces the binary on disk but exits before
restarting the service, leaving the running process on the prior executable.

## Requirements

- [ ] R1: Deploy successfully when the canonical launchd label is absent.
- [ ] R2: Deploy successfully when the canonical label is already loaded.
- [ ] R3: Preserve rollback to the prior runtime on any failed health check.
- [ ] R4: Prove the live PID and application behavior changed after deployment.

## Acceptance Criteria

- [ ] AC1 (R1): A first-install fixture bootstraps and starts the canonical label.
- [ ] AC2 (R2): A repeated-deploy fixture restarts the loaded label without bootstrap error 5.
- [ ] AC3 (R3): A forced health-check failure restores the prior runtime and service.
- [ ] AC4 (R4): Deployment verifies both a changed PID and populated live child tool counts.
- [ ] AC5: Shell-focused tests and `make smoke-full` pass.

## Context

- Target: `scripts/deploy-canonical-runtime.sh`.
- Discovered during SPEC-BUG-165-001 takeover after both browser smokes passed.
- The follow-up conflict gate proposed this ID and found no existing equivalent.

## Out of Scope

- Changing Shipyard tool timeout semantics.
- Changing the launchd label or runtime configuration format.
