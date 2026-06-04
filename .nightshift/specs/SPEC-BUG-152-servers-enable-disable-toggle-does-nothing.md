---
id: SPEC-BUG-152
template_version: 3
priority: 1
layer: 3
type: bugfix
status: done
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Servers view: clicking a server's enable/disable toggle does nothing

## Problem

In the Servers view, each server card has an enable/disable toggle switch.
Clicking it has **no effect**: the server's enabled state does not change, the
card does not move to its disabled appearance, and no disable/enable actually
takes place. The switch is visually present but non-functional.

Observed behavior (runtime-confirmed in headless Chrome against a current build):

- The server's `enabled` state via `GET /api/servers` is `true` before the
  click and still `true` after — the toggle never reaches the backend.
- The browser console logs an uncaught error on click:
  `toggleServer is not defined`.
- The card shows no disabled-state indicator after the click.

This was discovered by the Servers-view headless smoke test added under
SPEC-BUG-150 (`test/smoke/servers_smoke.mjs`), which fails because disabling a
server does not take effect.

## Reproduction

1. Run a Shipyard instance with at least one child server (e.g. via
   `--config`), open the dashboard, go to the **Servers** view.
2. On an enabled server's card, click the enable/disable toggle switch.
3. **Actual:** nothing happens — the server stays enabled; the browser console
   shows `Uncaught ReferenceError: toggleServer is not defined`.
4. **Expected:** the toggle disables (or re-enables) the server — the backend
   enabled state changes and the card reflects the new state.

## Requirements

- [ ] R1: Clicking a server card's enable/disable toggle changes that server's
  enabled state (the backend `enabled` flag flips) and the card reflects it.
- [ ] R2: Clicking it again restores the previous state.
- [ ] R3: No uncaught console error occurs on the click.

## Acceptance Criteria

- [ ] AC1: Clicking the toggle on an enabled server disables it — `GET
  /api/servers` shows that server's `enabled` is now `false` and the card shows
  its disabled state.
- [ ] AC2: Clicking the toggle on a disabled server re-enables it (`enabled`
  back to `true`, card returns to enabled state).
- [ ] AC3: No uncaught JavaScript error (e.g. `toggleServer is not defined`)
  occurs when the toggle is clicked.
- [ ] AC4: The SPEC-BUG-150 Servers smoke test (`test/smoke/servers_smoke.mjs`,
  via `make smoke-full`) passes against the fix.
- [ ] AC5: `go test ./...` passes.
- [ ] AC6: `go vet ./...` passes.
- [ ] AC7: `go build ./...` passes.

## Context

The toggle is rendered in the Servers view in `internal/web/ui/index.html`
(server card markup with the enable/disable switch). The smoke test added under
SPEC-BUG-150 exercises this behavior and is currently red because of this bug;
fixing this bug should turn `make smoke-full` green and unblock SPEC-BUG-150.

## Out of Scope

- Changing server card visual styling beyond making the toggle functional.
- Changing the backend enable/disable API.

## Code Pointers

- `internal/web/ui/index.html` — Servers view card rendering + the toggle's
  click wiring
- `test/smoke/servers_smoke.mjs` — the smoke test that caught this (SPEC-BUG-150)

## Gap Protocol

- Research-acceptable gaps:
  - Whether other inline click handlers in the same view share the same
    non-functional symptom (audit the Servers view's interactive controls).
- Stop-immediately gaps:
  - Any change that weakens or skips the SPEC-BUG-150 Servers smoke test instead
    of making the toggle work.
- Max research subagents before stopping: 0
