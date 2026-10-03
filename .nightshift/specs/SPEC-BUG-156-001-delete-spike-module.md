---
id: SPEC-BUG-156-001
template_version: 12
priority: 2
layer: 1
type: bugfix
status: in_progress
parent: SPEC-BUG-156
after:
- SPEC-BUG-156
violates:
- SPEC-BUG-156
nfrs: []
nfr_waivers:
- id: SPEC-NFR-001
  reason: Deletes a separate, unbuilt Go module and two config references; no code in the main module changes.
prior_attempts: []
attachments: []
created: 2026-10-03
scope:
  write:
  - spike/**
  - Makefile
  - renovate.json
---

# Delete the stale spike module so Dependabot stops flagging its vulnerable dependencies

## Problem

`spike/wails-websocket/` is a throwaway SPEC-017 experiment with its own
`go.mod`. SPEC-BUG-156 made Renovate ignore it and explicitly left deleting it
out of scope. GitHub Dependabot security updates do not read `renovate.json`,
so they still open PRs against it: #39 (`golang.org/x/crypto` 0.50.0 → 0.52.0)
and #40 (`github.com/labstack/echo/v4` 4.13.3 → 4.15.3), both opened
2026-10-03.

Neither PR can pass CI's `dependency-review` check (`fail-on-severity:
moderate`, `.github/workflows/ci.yml:74`):

- #39 fixes two critical x/crypto advisories (GHSA-rm3j-f69w-wqmq,
  GHSA-5cgq-3rg8-m6cv), but pulls in `golang.org/x/net` 0.54.0, which has a
  moderate advisory (GHSA-5cv4-jp36-h3mw, fixed in 0.55.0).
- #40 still uses the vulnerable x/crypto 0.50.0.

The spike is not part of the shipped binary, is excluded from gosec
(`Makefile:145`), and has not changed since SPEC-017. Keeping it brings only
vulnerability noise and PRs that will never be merged.

**Violated spec:** SPEC-BUG-156 (R1 intent: dependency bots should not keep
proposing updates for the spike).

## Root Cause

(Filled in at resolution.)

## Requirements

- [ ] R1: Delete the `spike/wails-websocket/` directory and its `go.mod`/`go.sum`.
- [ ] R2: Remove the now-dead spike references: the `-exclude-dir=spike/wails-websocket`
  gosec flag in `Makefile` and the `spike/**` entry in `renovate.json`'s
  `ignorePaths`.
- [ ] R3: Leave SPEC-017 and SPEC-BUG-156 (both done) unchanged. Their findings
  remain readable in git history at the deletion commit's parent.
- [ ] R4: Close Dependabot PRs #39 and #40 as obsolete once the deletion merges.

## Acceptance Criteria

- [ ] AC1 (R1): `git ls-files spike` is empty and no `go.mod` remains under `spike/`.
- [ ] AC2 (R2): `git grep -n 'spike/'` finds matches only in `.nightshift/specs/`.
- [ ] AC3: `go build ./...`, `go vet ./...` and `go test -race -count=1 ./...`
  pass, and `renovate.json` is valid JSON.
- [ ] AC4: The PR's `dependency-review` check passes.
- [ ] AC5 (R4): #39 and #40 are closed with a comment that links the deletion PR.

## Context

- Spike: `spike/wails-websocket/` (go.mod, go.sum, main.go, frontend).
- References: `Makefile:145` (gosec exclude), `renovate.json:8` (`ignorePaths`).
- CI: `.github/workflows/ci.yml` dependency-review job.
- Parent: `.nightshift/specs/SPEC-BUG-156-renovate-ignore-spike-module.md`.

## Out of Scope

- Changes to the main module's dependencies.
- Configuring Dependabot (`.github/dependabot.yml`); once the spike is gone
  there is nothing left for it to target.

## State rationale

```yaml
schema_version: 1
status: in_progress
reason: mechanical transition to 'in_progress' via run coord-20261003-bug156-001
reconsider_when: null
evidence: []
provenance: authored
record: artifacts/20261003T155601Z-status-transition-ready-in-progress-mechanical-transition-.json
```
