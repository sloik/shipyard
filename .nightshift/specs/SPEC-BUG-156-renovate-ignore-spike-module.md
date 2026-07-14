---
id: SPEC-BUG-156
template_version: 4
priority: 4
layer: 1
type: bugfix
status: done
parent: null
after: []
nfrs: []
devkb_required: []
prior_attempts: []
attachments: []
created: 2026-07-14
---

# Renovate keeps recreating a stale Wails v2 PR from the spike module

## Problem

`spike/wails-websocket/` is a throwaway experiment with its own `go.mod` that
imports `github.com/wailsapp/wails/v2`. It is a separate Go module, so it is not
part of the app's `go build ./...` and does not affect CI. Renovate, however,
scans every `go.mod` in the repo and keeps opening (and, when closed, reopening)
a PR to bump `github.com/wailsapp/wails/v2` in that spike — noise that will never
be merged, since the desktop app migrated to Wails v3 (SPEC-018).

## Requirements

- [x] R1: Renovate no longer proposes dependency updates for files under
  `spike/`.
- [x] R2: The main module's dependency updates are unaffected.

## Acceptance Criteria

- [x] AC1: `renovate.json` includes an `ignorePaths` entry covering `spike/**`.
- [x] AC2: The config remains valid against the Renovate schema (still extends
  `config:recommended`).

## Context

Discovered while merging the open Renovate PR backlog. The recreated PR was
`sloik/shipyard#16` (previously #13), "Update module
github.com/wailsapp/wails/v2 to v2.13.0".

Target file:
- `renovate.json`

## Out of Scope

- Deleting or rewriting the `spike/` experiment.
- Any change to the main module's dependencies.

## Gap Protocol

- Research-acceptable gaps: none.
- Stop-immediately gaps: changing update behavior for the main module.
- Max research subagents before stopping: 0
