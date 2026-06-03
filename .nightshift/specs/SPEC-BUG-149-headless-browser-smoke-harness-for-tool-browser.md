---
id: SPEC-BUG-149
template_version: 3
priority: 2
layer: 1
type: feature
status: in_progress
after: [SPEC-BUG-148]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Headless-browser smoke harness for Tool Browser interactive behaviors

## Problem

Shipyard's UI tests (`internal/web/ui_layout_test.go`) are Go **source-scan**
assertions over the embedded `index.html`/`ds.js` — they check that strings
exist, not that the UI behaves. This class of test cannot see runtime/DOM bugs.

SPEC-BUG-148 demonstrated the gap concretely: two handlers (`ds.js` +
`index.html`) both toggled `is-collapsed` per click and cancelled out. The
SPEC-BUG-145/147 source-scan tests reported 8/8 ACs passing while the feature
was actually broken on click. The bug was only found (and the fix only proven)
with an ad-hoc headless-Chrome reproduction.

A lightweight, repeatable headless-browser smoke test for the Tool Browser's
interactive behaviors would catch this class of regression at merge time.

## Requirements

- [ ] R1: A headless-browser smoke test can launch a Shipyard instance (e.g. a
  `--headless` server on an ephemeral port with a minimal/throwaway config) and
  drive real clicks against the Tool Browser.
- [ ] R2: It covers the core interactive behaviors: group expand/collapse toggles
  on header click (exactly one visible state change per click), collapse state
  retained across tool selection, and persistence across reload.
- [ ] R3: It uses the system browser (e.g. Playwright/puppeteer-core against
  installed Chrome) without committing a large browser download to the repo.
- [ ] R4: It is runnable locally and gated appropriately (it need not block the
  Go unit suite if a browser is unavailable — skip with a clear message).

## Acceptance Criteria

- [ ] AC1: A smoke test exists that opens the Tool Browser headlessly and asserts
  a single header click toggles the group's visible collapsed state exactly once.
- [ ] AC2: The smoke test asserts collapse state survives a tool-selection
  re-render and a page reload.
- [ ] AC3: The harness launches and tears down its own Shipyard instance on an
  ephemeral port and does not interfere with a developer's running instance.
- [ ] AC4: When no browser is available, the test skips with a clear reason
  rather than failing.
- [ ] AC5: Documentation (README or Makefile target) explains how to run it.

## Context

Reference implementation already proven during SPEC-BUG-148: `playwright-core`
driving the installed Google Chrome against a `--headless` `bin/shipyard` on an
ephemeral port; the self "shipyard" group renders even with no child servers, so
a minimal config suffices.

## Out of Scope

- Full end-to-end coverage of every view; this is a focused Tool Browser smoke
  test, expandable later.
- Bundling a browser binary into the repo.
- Replacing the existing Go source-scan tests (they stay as cheap guards).

## Code Pointers

- `internal/web/ui/index.html`, `internal/web/ui/ds.js` — Tool Browser UI
- `cmd/shipyard` — `--headless` server mode, `web.port` config
- `internal/web/ui_layout_test.go` — existing source-scan tests

## Gap Protocol

- Research-acceptable gaps:
  - Test runner placement (Go-invoked vs a separate `npm`/script target) and how
    it is wired into CI.
- Stop-immediately gaps:
  - Committing a multi-hundred-MB browser download into the repo.
- Max research subagents before stopping: 0
