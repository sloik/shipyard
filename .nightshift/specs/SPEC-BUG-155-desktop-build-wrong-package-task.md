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
`wails3 package GOOS=darwin`, and CI fails with:

```
Wails v3.0.0-alpha2.117 › Package
ERROR  task: Task "package" does not exist
```

This is a Wails v3 alpha dependency drift. CI installs `wails3` via `@latest`.
At SPEC-BUG-130 implementation time (2026-05-30) the `wails3 package GOOS=darwin`
wrapper resolved to the Taskfile task `darwin:package` (the report records the
pre-fix error `Task "darwin:package" does not exist`, fixed by adding that task),
and Desktop Build was green through 2026-06-05. A later alpha (`alpha2.117`)
changed the wrapper so `wails3 package` now looks for a task literally named
`package` — which this project's flat `Taskfile.yml` never defines (it uses the
`darwin:`-prefixed `darwin:package`). Desktop Build first went red on 2026-07-13.

Fix: call the task directly with `wails3 task darwin:package`, which is robust to
`wails3 package` wrapper behavior changes and matches the codebase's existing
convention (`notarize-macos` already uses `wails3 task darwin:sign:notarize`).
The same broken wrapper invocation is mirrored in the `package-macos` Makefile
target, the README packaging note, and the `SPEC-BUG-130` packaging tests, all
of which are updated to the working invocation.

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
