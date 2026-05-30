---
id: SPEC-BUG-129
template_version: 3
priority: 1
layer: 3
type: bugfix
status: in_progress
after: [SPEC-018]
violates: [SPEC-018]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-29
---

# Add Wails v3 GUI Smoke Coverage

## Problem

SPEC-018 migrated Shipyard to Wails v3 and implemented the native tray,
tray-menu, close-to-tray, and detachable-window paths. The kickoff run validated
the code, server mode, Wails builds, binary size, and source-level UI wiring, but
the run report noted that macOS tray click/right-click behavior was not manually
or automatically inspected in the native GUI.

This leaves SPEC-018's GUI-native acceptance criteria covered by implementation
and build evidence, but without a repeatable native GUI smoke procedure.

**Violated spec:** SPEC-018 (Wails v3 Native Desktop Features)

**Violated criteria:** AC2, AC3, AC4, and AC5 depend on native GUI behavior that
should have repeatable smoke evidence after the Wails v3 migration.

## Reproduction

1. Read `.nightshift/reports/2026-05-29-nightshift-report.md`.
2. Check the SPEC-018 acceptance checklist.
3. **Actual:** tray/menu/window-detach criteria are implemented and compiled, but
   the report records that interactive macOS menu-bar inspection was not
   performed.
4. **Expected:** Shipyard has an automated or semi-automated GUI smoke path that
   produces evidence for tray toggle, tray menu, close-to-tray, and panel detach.

## Root Cause

Leave blank for the implementation pass.

## Requirements

- [ ] R1: Add a repeatable smoke procedure for macOS Wails v3 tray and
  multi-window behavior.
- [ ] R2: The smoke procedure must cover tray icon visibility or accessibility,
  click-to-show/toggle behavior, right-click menu contents, close-to-tray, and
  panel detach.
- [ ] R3: If full automation is brittle for menu-bar UI, provide a
  semi-automated script plus a structured manual evidence checklist.
- [ ] R4: The smoke procedure must write or reference evidence artifacts under
  `.nightshift/reports/` or another repo-documented evidence path.
- [ ] R5: Existing Go, Wails build, and server-mode validation must remain green.

## Acceptance Criteria

- [ ] AC 1: A documented command or checklist exists for Wails v3 macOS GUI smoke
  coverage.
- [ ] AC 2: The smoke path verifies tray show/toggle behavior.
- [ ] AC 3: The smoke path verifies tray menu items: `Show Dashboard` and `Quit`.
- [ ] AC 4: The smoke path verifies closing the main window hides to tray rather
  than exiting.
- [ ] AC 5: The smoke path verifies panel detach opens a separate native window.
- [ ] AC 6: Evidence from a successful smoke run is recorded in the Nightshift
  report or linked artifact.
- [ ] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and relevant Wails
  build commands pass.

## Context

- Parent run report: `.nightshift/reports/2026-05-29-nightshift-report.md`
- Parent spec: `.nightshift/specs/SPEC-018-wails-v3-native-features.md`
- Desktop integration: `cmd/shipyard/desktop.go`
- UI detach wiring: `internal/web/ui/index.html`
- Existing desktop tests: `cmd/shipyard/desktop_test.go`

## Out of Scope

- Shipping signed/notarized application artifacts
- Reworking the Wails v3 migration
- Adding new native desktop features beyond smoke evidence for SPEC-018 paths

## Code Pointers

- `cmd/shipyard/desktop.go` - tray, close, detach, layout persistence behavior
- `cmd/shipyard/desktop_test.go` - desktop regression tests
- `internal/web/ui/index.html` - panel-tab context menu and detach bridge calls
- `.nightshift/reports/2026-05-29-nightshift-report.md` - source of follow-up

## Gap Protocol

- Research-acceptable gaps:
  - Whether macOS accessibility tooling can observe menu-bar tray items reliably
  - Whether Wails v3 exposes enough hooks for a non-interactive GUI smoke
- Stop-immediately gaps:
  - The only possible evidence requires destructive system settings changes
  - The GUI cannot launch in the available environment
- Max research subagents before stopping: 1
