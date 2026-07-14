# Nightshift Report — SPEC-BUG-149

**Spec:** Headless-browser smoke harness for Tool Browser interactive behaviors
**Branch:** `nightshift/SPEC-BUG-149`
**Latest commit:** `42b41b4`
**Status:** COMPLETE

## Summary

Added a standalone headless-browser smoke harness that launches a live,
ephemeral Shipyard instance and drives real clicks against the Tool Browser via
`playwright-core` + the system Google Chrome. It catches DOM/runtime
regressions that the existing Go source-scan tests (`internal/web/ui_layout_test.go`)
cannot see — concretely the SPEC-BUG-148 class of bug, where two handlers
toggled `is-collapsed` per click and cancelled out while source-scan reported
all green.

The harness is intentionally kept **out of `make test`** (the Go suite) so a
missing browser or node never blocks unrelated work, and it skips gracefully
(exit 0) when node or Chrome is unavailable.

## Files added / changed

- `test/smoke/tool_browser_smoke.mjs` (new) — the node smoke runner.
- `package.json` (new) — pins `playwright-core` as a devDependency; `npm run smoke` convenience script.
- `package-lock.json` (new) — lockfile pinning playwright-core (no browser download).
- `Makefile` (changed) — new `smoke` target: node-presence guard, builds `shipyard` + `stubchild`, runs the harness with binary paths in env.
- `.gitignore` (changed) — ignore `/node_modules/`.
- `README.md` (changed) — new "Tool Browser Smoke (headless browser)" section under Development → Test (AC5).

No `internal/web/ui/*` behavior changed; no Go source modified. `node_modules/`
and no browser binary are committed.

## Key design note (recipe correction)

The brief's recipe said an empty `servers` map is enough to start the server.
It is not for this binary: `runConfig` (cmd/shipyard/main.go:324) exits(1) on
`len(cfg.ServerOrder) == 0`, and line 338 requires each server to have a
`command`. The harness therefore points one config server at the existing
`internal/teststubchild` stub (the same pattern as `cmd/shipyard/e2e_smoke_test.go`),
and drives the built-in **"shipyard" self group** (`data-server="shipyard"`),
which always renders a header and is user-collapsible. The tool-selection
re-render step clicks a tool in the *other* (alpha/stub) group so the item is
visible while asserting the self group stays collapsed.

## How to run

```bash
npm install        # first run only — pulls playwright-core, no browser download
make smoke
# Override browser: CHROME_BIN=/path/to/chrome make smoke
```

## Actual smoke-run output

```
  PASS  self "shipyard" group header renders in Tools view
  PASS  group starts expanded (not collapsed)
  PASS  AC1: one click adds is-collapsed
  PASS  AC1: one click hides items (display:none)
  PASS  AC1: is-collapsed toggled exactly once
  PASS  second click re-expands group
  PASS  second click shows items again
  PASS  group collapsed again before tool-select
  PASS  a clickable tool item exists in another group
  PASS  AC2: collapse retained across tool selection re-render
  PASS  AC2: collapse persisted across reload

SMOKE PASSED: all Tool Browser interactive behaviors verified.
```
Exit code 0.

Skip path (Chrome absent) verified:
```
$ CHROME_BIN=/nonexistent/chrome ... node test/smoke/tool_browser_smoke.mjs
SKIP: Chrome not found at "/nonexistent/chrome" (set CHROME_BIN to override)
EXIT=0
```

## Acceptance Criteria

| AC | Description | Status | Evidence |
|----|-------------|--------|----------|
| AC1 | Single header click toggles visible collapsed state exactly once | PASS | 3 checks: is-collapsed added, items `display:none`, toggle counter == 1 |
| AC2 | Collapse survives tool-selection re-render AND page reload | PASS | non-vacuous: waitForReady requires alpha online, asserts a tool item exists, waits for `is-active` (proves render fired) before checking retention; + "persisted across reload" |
| AC3 | Launches/tears down own ephemeral instance, no dev interference | PASS | `freePort()` ephemeral port (never 9417); `try/finally` SIGTERM kill + tmpdir cleanup |
| AC4 | Skips with clear reason when no browser | PASS | Chrome-absent run printed SKIP, exit 0; node-absent guarded in Makefile |
| AC5 | Documentation explains how to run it | PASS | README "Tool Browser Smoke" section + Makefile target |

| Requirement | Status |
|-------------|--------|
| R1 launch ephemeral instance + drive real clicks | PASS |
| R2 expand/collapse exactly once, retained across selection, persists on reload | PASS |
| R3 system browser via playwright-core, no committed browser download | PASS |
| R4 runnable locally, gated, never blocks Go suite | PASS |

## Go gate results (still green)

- `go test ./...` → all packages `ok` (web, capture, proxy, auth, gateway, cmd/shipyard, etc.)
- `go vet ./...` → clean (exit 0)
- `go build ./...` → clean (exit 0)
- `gofmt` → N/A (no `.go` files changed)

NFR SPEC-NFR-001 (zero data races) unaffected: no Go source touched; harness is
a separate node process driving the UI over HTTP.

## Suggested Follow-up Specs

- Extend the smoke harness beyond the Tool Browser (Servers/Traffic/Schema views) as a second, opt-in `make smoke-full` target.
- CI wiring: optional GitHub Actions job that installs Chrome and runs `make smoke` on UI-touching PRs (kept non-blocking / advisory until stable).
