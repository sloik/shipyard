---
id: SPEC-BUG-158
template_version: 7
priority: 2
layer: 0
type: refactor
status: in_progress
after: [SPEC-BUG-157, SPEC-015]
provides: [canonical-quality-command, blocking-static-analysis]
requires: [nightshift-valid-control-plane]
touches: [Makefile, .github/workflows/ci.yml, .nightshift/config.yaml]
prior_attempts: []
nfrs: [SPEC-NFR-001]
created: 2026-07-18
stack: go
domain: code
output_type: config
devkb_required: [go.md, testing.md, shell.md, git.md]
cortex_cites: []
karpathy_checklist: [simple, surgical, goal]
---

# Enforce Formatting and Comprehensive Static Analysis

## Problem

Shipyard's blocking quality gate is only `go vet`, race tests, and build. Seven
tracked Go files currently fail `gofmt -l`, and CI still passes because formatting
is never checked. There is no repository-owned Staticcheck/golangci-lint or workflow
syntax gate, while Nightshift duplicates `go test` as `type_check` and leaves
`format` empty. Local, Nightshift, and CI definitions can disagree about "green."

## Requirements

- [ ] R1: Define one repository-owned `make quality` command used locally, by Nightshift, and by CI.
- [ ] R2: Make canonical Go formatting a blocking check and fix the existing seven-file drift without behavior changes.
- [ ] R3: Add a pinned, reviewed Go analyzer configuration that includes Staticcheck-class bug, correctness, inefficiency, and vet checks.
- [ ] R4: Add blocking syntax/static checks for GitHub workflows, plain JavaScript (including the embedded inline script), and zsh parseability.
- [ ] R5: Make the active race NFR part of the canonical test contract rather than a CI-only special case.
- [ ] R6: Document every analyzer exclusion narrowly with rule, exact location, rationale, and review condition.

## Acceptance Criteria

- [ ] AC1 (R1): `make quality` runs formatting, analyzers, workflow/script syntax, build, ordinary tests, and `go test -race -count=1 -timeout 5m ./...`.
- [ ] AC2 (R2): `test -z "$(gofmt -l $(git ls-files '*.go'))"` passes.
- [ ] AC3 (R3): The pinned Go analyzer exits 0 with no unreviewed findings on `./...`; a controlled bad fixture/probe proves the command exits nonzero.
- [ ] AC4 (R4): `actionlint`, JavaScript syntax checks, and `zsh -n scripts/*.sh` are blocking parts of `make quality`; each has a negative self-test or fixture.
- [ ] AC5 (R1, R5): `.nightshift/config.yaml` maps `lint`, `type_check`, `format`, and `test` to distinct meaningful gates and includes the race/count/timeout contract.
- [ ] AC6 (R1): `.github/workflows/ci.yml` invokes the same repository command rather than reimplementing a divergent list.
- [ ] AC7 (R6): No blanket analyzer disable or whole-directory exclusion is added to make the first run green.
- [ ] AC8: `go mod tidy -diff`, `go mod verify`, `go test -count=1 ./...`, and the full race suite remain clean.

## Context

- Current CI gate: `.github/workflows/ci.yml:28-30`.
- Current local test target: `Makefile:53-54`.
- Current Nightshift commands: `.nightshift/config.yaml:13-20`.
- Confirmed formatting drift on 2026-07-18: `internal/proxy/proxy.go`, `internal/proxy/proxy_more_test.go`, `internal/auth/middleware.go`, `internal/auth/ratelimit.go`, `internal/auth/store.go`, `internal/auth/scope_test.go`, and `internal/secrets/ref_test.go`.
- ShellCheck does not support the repository's zsh scripts; use `zsh -n` or a reviewed zsh-capable analyzer instead of treating SC1071 as a code defect.
- Tool versions must be pinned in repository/CI configuration, not installed with unbounded `@latest` during a run.

## Scenarios

1. A developer commits non-gofmt Go -> local/CI `make quality` fails with the file list.
2. A change introduces a Staticcheck-class bug -> the pinned analyzer fails identically locally and in CI.
3. A workflow or embedded UI script has invalid syntax -> the static gate fails even if browser smoke is skipped.

## Out of Scope

- Style-only rewrites beyond `gofmt`.
- Browser behavior assertions; keep those in smoke tests.
- Vulnerability database and supply-chain scanning (SPEC-BUG-159).
- Raising coverage thresholds (SPEC-BUG-160).
- Installing editor-only tooling globally.

## Documentation Impact

- `README.md` or `CONTRIBUTING.md` — document `make quality`, pinned tool bootstrap, and narrow suppression policy.
- `.nightshift/config.yaml` — align autonomous validation with the canonical command.

## Research Hints

- Read `Argo Home/DevKB/go.md`, `testing.md`, `shell.md`, and `git.md`.
- Prefer one reviewed analyzer configuration over overlapping ad hoc commands.
- Staticcheck's official baseline is `staticcheck ./...`; if golangci-lint is chosen, pin its major/version and enable a small explicit analyzer set first.
- Extract the inline script from `internal/web/ui/index.html` deterministically before `node --check`.

## Validation Commands

```bash
make quality
test -z "$(gofmt -l $(git ls-files '*.go'))"
go vet ./...
go test -count=1 ./...
go test -race -count=1 -timeout 5m ./...
go mod tidy -diff
go mod verify
```
