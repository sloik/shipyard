---
id: SPEC-BUG-147
template_version: 3
priority: 3
layer: 3
type: feature
status: in_progress
after: [SPEC-BUG-145]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Persist Tool Browser group collapse state across Tools reload / app restart

## Problem

SPEC-BUG-145 retains each server group's user-set collapse state across tool
selection changes within a live Tools session, but deliberately scoped out
persistence across a full Tools reload, page reload, or app restart (the
`userCollapsedGroups` store is in-memory only). If a user folds groups and then
reloads or restarts, the folds are lost. Some users may want their folds to
survive reloads.

This spec is the deferred enhancement explicitly listed as out of scope in
SPEC-BUG-145.

## Requirements

- [ ] R1: A server group's collapse state set by the user persists across a
  Tools reload / page reload.
- [ ] R2: Collapse state persists across an app restart.
- [ ] R3: Persisted state is keyed per server and does not leak between servers.
- [ ] R4: In-session retention across tool selection changes (SPEC-BUG-145)
  continues to work and is not regressed.

## Acceptance Criteria

- [ ] AC1: After folding a group and reloading the page, the group is still
  folded.
- [ ] AC2: After folding a group and restarting the app, the group is still
  folded.
- [ ] AC3: Persisted collapse state is per-server (folding server A does not
  fold server B after reload).
- [ ] AC4: Switching the selected tool still retains folds (SPEC-BUG-145
  behavior intact).
- [ ] AC5: A regression test covers persistence of collapse state across a
  simulated reload.
- [ ] AC6: `go test ./...` passes.
- [ ] AC7: `go vet ./...` passes.
- [ ] AC8: `go build ./...` passes.

## Context

Builds directly on SPEC-BUG-145's `userCollapsedGroups` store in
`internal/web/ui/index.html`. A storage mechanism (e.g. `localStorage`) would
back the in-memory store so it survives reloads.

## Out of Scope

- Persisting any Tool Browser state other than per-server group collapse.
- Syncing collapse state across browsers / machines / server-side storage.

## Code Pointers

- `internal/web/ui/index.html` — `userCollapsedGroups` store and Tool Browser
  sidebar render/handler
- `internal/web/ui_layout_test.go` — Tool Browser tests

## Gap Protocol

- Research-acceptable gaps:
  - Choice of storage key namespace/versioning.
- Stop-immediately gaps:
  - Any change that regresses SPEC-BUG-145 in-session retention.
- Max research subagents before stopping: 0
