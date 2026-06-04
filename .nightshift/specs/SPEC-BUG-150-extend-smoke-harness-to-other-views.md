---
id: SPEC-BUG-150
template_version: 3
priority: 3
layer: 1
type: feature
status: blocked
after: [SPEC-BUG-149]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-06-03
---

# Extend the headless smoke harness to other views (opt-in `make smoke-full`)

## Block Reason

The Servers smoke extension did its job — it CAUGHT a real bug (SPEC-BUG-152, the
non-functional server enable/disable toggle), which is now FIXED on main. But the
orchestrator's harness (branch nightshift/SPEC-BUG-150, 7505b62) was never
validated (the run timed out) and is **non-hermetic**, so it was reverted off main
(revert daa6c19) to keep `make smoke`/`go test` green. It needs the following
before it can merge:

1. **Isolate global state.** The spawned shipyard writes gateway policy to the
   GLOBAL `~/Library/Application Support/shipyard/gateway-policy.json`. `servers_smoke`
   toggling "alpha" pollutes it and (a) flaps across runs (a run can leave alpha
   disabled → the next run's "starts enabled" check fails) and (b) breaks the Go
   e2e test `TestShipyardE2E_ConfigMode_RealProcessFlow`, which also uses a server
   named "alpha". Fix: spawn with `env.HOME` (and XDG_*) pointed at the per-run
   tmpdir so global state is isolated.
2. **Wait for the stub's tools under a cold cache.** With an isolated/fresh HOME
   there is no cached tool snapshot, so the Tool Browser's "a clickable tool item
   exists in another group" check fails. Fix: `waitForReady` must wait until the
   "alpha" stub's tools are actually loaded (e.g. poll `/api/servers` until
   alpha.tool_count >= 1, or force a tools fetch) before handing back the page.
3. **Robust banner waits** in `servers_smoke` (wait for the "Blocked by gateway
   policy" banner to appear/disappear rather than reading textContent the instant
   the switch class flips).

The Tool Browser smoke (SPEC-BUG-149) remains on main and green. Redo the Servers
extension with the three fixes above (do NOT weaken any assertion), verify
`make smoke-full` is green AND `go test ./...` stays green after it runs, then
merge.


## Problem

SPEC-BUG-149 added a headless-browser smoke harness covering the Tool Browser's
interactive collapse behaviors. The same harness pattern (playwright-core +
system Chrome against a `--headless` instance) could catch interactive
regressions in other views (Traffic timeline expand/detail, History
select/replay, Servers cards, Tokens UI) that the Go source-scan tests cannot
see. Today only the Tool Browser is covered.

## Requirements

- [ ] R1: Additional smoke checks cover the key interactive behaviors of at
  least one more view (e.g. Traffic expand/collapse of a row detail).
- [ ] R2: The broader coverage is opt-in via a separate target (e.g.
  `make smoke-full`) so the fast `make smoke` stays quick for the common case.
- [ ] R3: Reuses the SPEC-BUG-149 harness scaffolding (server launch on
  ephemeral port, system Chrome, graceful skip when no browser).
- [ ] R4: Does not make the Go unit suite fail when a browser is unavailable.

## Acceptance Criteria

- [ ] AC1: `make smoke-full` runs the Tool Browser checks plus at least one
  additional view's interactive checks.
- [ ] AC2: `make smoke` remains the fast Tool-Browser-only path.
- [ ] AC3: New checks skip gracefully when no browser/node is present.
- [ ] AC4: README/Makefile documents `make smoke-full`.

## Context

Builds on `test/smoke/tool_browser_smoke.mjs`, the `make smoke` target, and the
ephemeral-port/teststubchild launch pattern from SPEC-BUG-149.

## Out of Scope

- Exhaustive coverage of every view; this is incremental expansion.
- Committing browser binaries.

## Gap Protocol

- Research-acceptable gaps:
  - Which view to cover first (pick the highest-interaction one).
- Stop-immediately gaps:
  - Making `go test ./...` depend on a browser.
- Max research subagents before stopping: 0
