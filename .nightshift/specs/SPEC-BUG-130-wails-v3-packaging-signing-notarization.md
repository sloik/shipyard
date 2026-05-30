---
id: SPEC-BUG-130
template_version: 3
priority: 2
layer: 3
type: feature
status: in_progress
after: [SPEC-018]
nfrs: [SPEC-013, SPEC-014, SPEC-015, SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-29
---

# Wails v3 Packaging, Signing, and Notarization

## Problem

SPEC-018 migrated Shipyard to Wails v3 and verified that `wails3 task build`
produces raw macOS binaries under the size budget. That is enough for
development validation, but not enough for a distributable macOS application.

Shipyard still needs a packaging path for `.app` artifacts, developer signing,
notarization, and release documentation before Wails v3 desktop builds can be
shared with users outside the local development machine.

## Requirements

- [ ] R1: Define the Wails v3 packaging path for a distributable macOS `.app`
  artifact.
- [ ] R2: Add or document the signing flow, including required local
  environment variables or keychain identities.
- [ ] R3: Add or document the notarization flow, including required Apple
  credentials and expected commands.
- [ ] R4: Integrate packaging outputs with the existing release/build scripts
  without breaking raw development builds.
- [ ] R5: Document how unsigned local builds differ from signed/notarized
  release artifacts.
- [ ] R6: Existing CI/build/test gates must remain green.

## Acceptance Criteria

- [ ] AC 1: A maintainer can run a documented command to create a macOS `.app`
  artifact from the Wails v3 project.
- [ ] AC 2: The repo documents all signing and notarization prerequisites.
- [ ] AC 3: The release/package command fails clearly when signing credentials
  are absent, without breaking ordinary local `wails3 task build`.
- [ ] AC 4: The package artifact path is documented in README or developer
  release docs.
- [ ] AC 5: `go test ./...`, `go vet ./...`, `go build ./...`, and relevant
  Wails build commands pass.
- [ ] AC 6: The packaging path remains compatible with SPEC-014/SPEC-015
  cross-platform release expectations.

## Context

- Parent spec: `.nightshift/specs/SPEC-018-wails-v3-native-features.md`
- Parent report: `.nightshift/reports/2026-05-29-nightshift-report.md`
- Release/build NFRs:
  - `.nightshift/specs/SPEC-013-readme.md`
  - `.nightshift/specs/SPEC-014-goreleaser.md`
  - `.nightshift/specs/SPEC-015-github-actions-ci.md`
- Build files:
  - `Taskfile.yml`
  - `Makefile`
  - `.github/workflows/`

## Out of Scope

- Adding an auto-update framework
- Publishing a public release
- Windows/Linux signing beyond documenting how this macOS path fits the broader
  release matrix
- Changing runtime Wails v3 desktop behavior

## Code Pointers

- `Taskfile.yml` - current Wails v3 build tasks
- `Makefile` - developer build targets
- `.goreleaser.yml` - existing release packaging configuration, if present
- `README.md` - user-facing install/release documentation
- `.github/workflows/` - CI/release automation

## Gap Protocol

- Research-acceptable gaps:
  - Current Wails v3 packaging/signing command names
  - Whether GoReleaser should own the `.app` packaging step or call a Wails task
  - Which Apple notarization credentials are available locally or in CI
- Stop-immediately gaps:
  - Signing/notarization requires unavailable Apple developer credentials
  - Current Wails v3 alpha cannot produce a packageable `.app`
- Max research subagents before stopping: 2
