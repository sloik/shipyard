---
id: SPEC-BUG-013
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-BUG-011, SPEC-BUG-012]
prior_attempts: []
violates: [SPEC-BUG-011, SPEC-017, UX-002]
created: 2026-04-11
---

# Servers empty-state "Add Server" button does nothing in desktop app

## Problem

In the Servers empty state, the primary `Add Server` button is visible but not
actionable in the desktop app. Users click it and get no practical result for
adding a server, which blocks first-run setup when auto-import is unavailable or
not desired.

This leaves the app in a dead-end onboarding state: navigation works, the user
reaches Servers, but the primary CTA is ineffective.

**Violated specs:**
- `SPEC-BUG-011` — First-run UX: navigate to Servers view when 0 servers configured
- `SPEC-017` — Standalone Desktop App via Wails
- `UX-002` — Dashboard Design

**Violated criteria:**
- `SPEC-BUG-011` Problem statement intent: first-run must provide actionable setup from Servers empty state
- `SPEC-017 R1/R2`: desktop app should be usable as a standalone setup flow
- `UX-002` first-run screen contract: visible CTA buttons must be meaningful actions, not dead controls

## Reproduction

1. Launch Shipyard desktop app with zero configured servers.
2. Open Servers empty state (directly or via `0 servers` badge).
3. Click primary `Add Server` button.
4. **Actual:** no actionable add-server workflow is available to the user.
5. **Expected:** clicking `Add Server` opens a clear, usable add-server flow (modal/panel/dialog) with concrete next steps.

## Root Cause

The empty-state primary CTA was still wired as a brittle inline `alert(...)`
instead of a shared desktop-safe modal flow. In the Wails runtime that left the
button without a durable add-server path, so the user clicked a primary control
and got no actionable setup workflow.

## Requirements

- [x] R1: `Add Server` button in Servers empty state must trigger a visible, actionable flow in desktop app.
- [x] R2: The flow must not rely on fragile inline browser-only behavior; it must work reliably in Wails desktop runtime.
- [x] R3: The flow must provide concrete add-server guidance (minimum: config file path/format + runnable command).
- [x] R4: Users must be able to dismiss/close the flow and return to Servers screen without app restart.

## Acceptance Criteria

- [x] AC 1: Clicking `servers-empty-add-btn` always opens an add-server UI flow in desktop app.
- [x] AC 2: The opened flow includes a concrete command and config guidance sufficient to add a server from scratch.
- [x] AC 3: The flow is keyboard/escape dismissible and close button works.
- [x] AC 4: After closing the flow, Servers view remains interactive (tabs and buttons still work).
- [x] AC 5: The empty-state primary CTA is no longer a no-op in Wails runtime.
- [x] AC 6: Regression tests cover the add-button action wiring in `internal/web/ui/index.html` and fail if the CTA becomes non-actionable again.
- [x] AC 7: All existing tests pass.

## Context

- Current button is rendered in `internal/web/ui/index.html`:
  - `id="servers-empty-add-btn"` with inline `onclick="alert(...)"`.
- Empty-state and routing were recently stabilized under `SPEC-BUG-012`, but this CTA remains unreliable/non-actionable in desktop behavior.
- Related files:
  - `internal/web/ui/index.html` — Servers empty-state markup and handlers
  - `internal/web/ui/ds.css` — modal/empty-state styles
  - `internal/web/ui_layout_test.go` — structural UI regression tests
  - `.nightshift/specs/SPEC-BUG-011-first-run-ux.md` — first-run onboarding intent

## Out of Scope

- Full CRUD server editor with schema validation
- Editing/deleting existing server configs
- Auto-import algorithm changes
- New backend API for server persistence

## Research Hints

- Confirm whether inline `onclick` or desktop webview event handling is dropping the action.
- Prefer explicit DOM event wiring over inline handlers for desktop reliability.
- Reuse existing modal patterns in `index.html` (auto-import modal) instead of introducing a new ad-hoc UI system.
- Relevant tags: `shipyard`, `wails`, `servers`, `onboarding`, `ui`
- DevKB: `DevKB/architecture.md`, `DevKB/git.md`

## Gap Protocol

- Research-acceptable gaps: exact interaction detail of add-server UI (modal copy/layout), existing reusable modal patterns
- Stop-immediately gaps: fix requires backend persistence redesign or conflicts with first-run UX contract
- Max research subagents before stopping: 0
