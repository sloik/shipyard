# Nightshift Report — SPEC-BUG-150 (inline, parent-completed)

**Date:** 2026-06-04
**Spec:** SPEC-BUG-150 — Extend the headless smoke harness to other views (opt-in `make smoke-full`)
**Outcome:** DONE (hermetic harness; verified)
**Mode:** Completed inline by the parent. The original kickoff run timed out (API stream idle) after writing an unvalidated, non-hermetic first cut; that cut was reverted off main, and this redo applied the three isolation fixes.

## What landed

- `test/smoke/lib/harness.mjs` — shared launch/teardown/skip scaffolding (ephemeral port, system Chrome via playwright-core, graceful SKIP when absent).
- `test/smoke/servers_smoke.mjs` — Servers view: server enable/disable toggle round-trip (switch-on → disabled card + "Blocked by gateway policy" banner → back to switch-on).
- `test/smoke/tool_browser_smoke.mjs` — refactored onto the shared lib.
- `Makefile` — `make smoke` (fast, Tool Browser only) and `make smoke-full` (Tool Browser + Servers).

No `internal/web/ui/*` behavior changes. No Go changes.

## The three fixes that made it hermetic

The first cut polluted global state and broke the Go e2e suite. This redo:

1. **Global-state isolation.** The spawned shipyard writes gateway policy/DB to the GLOBAL `~/Library/Application Support/shipyard/`. The harness now spawns it with `env.HOME` / `XDG_*` pointed at the per-run tmpdir, so toggling the test server "alpha" no longer leaks into the user's real policy or collides with the Go e2e test `TestShipyardE2E_ConfigMode_RealProcessFlow` (which also uses "alpha").
2. **Cold-cache tool warm.** With an isolated HOME there is no cached tool snapshot, so the stub group would render "snapshot not available" (no clickable tools). The harness now force-fetches the stub's tools (`/api/tools?server=alpha&force_refresh=1`) until they load, before handing back the page.
3. **Robust banner waits.** `servers_smoke` waits for the "Blocked by gateway policy" banner to appear/disappear (via `waitForFunction`) instead of reading `textContent` the instant the switch class flips.

## Verification

- `make smoke-full` → **PASS twice** (no flapping): Tool Browser (11 checks) + Servers view (toggle off → switch-off + banner; toggle on → switch-on, banner gone).
- Global `~/Library/Application Support/shipyard/gateway-policy.json` → **unchanged** after the runs (`servers: ['lmstudio']`, no `alpha` leak) — confirms hermetic isolation.
- `go test ./...` → **GREEN** after the smoke runs (e2e no longer broken by leaked policy).
- `make smoke` (fast path) → still PASS.

## Acceptance criteria

- AC1 (`make smoke-full` runs Tool Browser + ≥1 more view): PASS (Servers).
- AC2 (`make smoke` stays the fast Tool-Browser-only path): PASS.
- AC3 (new checks skip gracefully when no browser/node): PASS (shared SKIP path).
- AC4 (README/Makefile documents `make smoke-full`): PASS (README section + Makefile target).
- R1–R4: PASS.

## Notes / lessons

- A smoke/e2e harness that spawns the real binary MUST isolate global state (HOME/XDG → tmpdir); otherwise it pollutes the developer's environment and collides with other tests sharing a server name. (Cortex #53.)
- The Servers smoke caught SPEC-BUG-152 (dead toggle) on its first run — now fixed; this harness is its behavioral regression guard.

## Suggested Follow-up Specs

- SPEC-BUG-151 (already filed, `planning`): non-blocking CI job running `make smoke` on UI-touching PRs.
