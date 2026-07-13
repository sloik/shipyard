---
id: SPEC-BUG-155
template_version: 4
priority: 2
layer: 1
type: bugfix
status: done
parent: null
after: []
nfrs: []
devkb_required: [shell.md, git.md]
prior_attempts: []
attachments: []
created: 2026-07-13
---

# Desktop Build workflow calls a non-existent `package` task

## Problem

The `Desktop Build` GitHub Actions workflow (`.github/workflows/desktop.yml`)
fails on every push to `main`. The "Package unsigned macOS app" step runs
`wails3 package GOOS=darwin`, which resolves to a Taskfile task literally named
`package`. That task does not exist — CI fails with:

```
Wails v3.0.0-alpha2.117 › Package
ERROR  task: Task "package" does not exist
```

The Taskfile (`Taskfile.yml`) defines the macOS packaging task as
`darwin:package`. The workflow and the task were introduced in the same commit
(`d6c1094 feat: add Wails v3 macOS packaging flow`) with the mismatched name, so
the Desktop Build has never succeeded.

## Requirements

- [x] R1: The "Package unsigned macOS app" step invokes the packaging task that
  actually exists in `Taskfile.yml`.
- [x] R2: The packaging step still produces `bin/Shipyard.app` so the downstream
  size/zip/upload steps continue to work unchanged.
- [x] R3: `SHIPYARD_VERSION` / `SHIPYARD_BUILD` env vars are still passed through
  to the packaging script.

## Acceptance Criteria

- [x] AC1: Running `SHIPYARD_VERSION=main SHIPYARD_BUILD=51 wails3 task
  darwin:package` locally exits 0 and produces
  `bin/Shipyard.app/Contents/MacOS/shipyard`.
- [x] AC2: The Desktop Build workflow run on `main` succeeds after the change.

## Context

Discovered while auditing failing CI across `sloik/*` repositories. This was the
only current failure on a default branch — the May nightly failures had already
self-recovered (subsequent nightly runs green), and remaining failures are on
Renovate dependency-update PR branches.

Target file:
- `.github/workflows/desktop.yml`

Verified locally with the installed `wails3` (v3.0.0-alpha2.117): the corrected
invocation builds and packages the app (exit 0, 18M `Shipyard.app`).

## Out of Scope

- Renovate PR-branch CI failures (dependency bumps).
- The `ld: warning ... built for newer 'macOS' version` linker warnings (benign).
- Code signing / notarization (`darwin:sign*` tasks).

## Gap Protocol

- Research-acceptable gaps: none.
- Stop-immediately gaps: changing the packaging script behavior or downstream
  workflow steps.
- Max research subagents before stopping: 0
