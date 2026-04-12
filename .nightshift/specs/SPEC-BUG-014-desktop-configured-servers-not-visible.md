---
id: SPEC-BUG-014
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-004, SPEC-017, SPEC-BUG-011, SPEC-BUG-012, SPEC-BUG-013]
prior_attempts: []
violates: [SPEC-004, SPEC-017, UX-002]
created: 2026-04-11
---

# Desktop app launched with `--config ~/servers.json` still shows Servers empty state

## Problem

When Shipyard is launched as the desktop app with a valid config file from the
user's home directory, the Servers tab still behaves like no servers are
configured. The UI shows the empty-state onboarding instead of the configured
server list/status view, even though `~/servers.json` contains real server
entries and the app was launched with that config path.

This breaks the core desktop workflow: a user follows the documented/configured
launch path, but the native app behaves as if no configuration was loaded.

**Violated specs:**
- `SPEC-004` — Phase 3: Multi-Server Management
- `SPEC-017` — Standalone Desktop App via Wails
- `UX-002` — Dashboard Design

**Violated criteria:**
- `SPEC-004 AC-1` — config file supports multiple server entries with command, args, env, cwd
- `SPEC-004 AC-2` — dashboard shows all servers with status indicators
- `SPEC-017 AC 1` — running `shipyard --config servers.json` opens a native window with the dashboard loaded
- `SPEC-017 R3` — existing functionality works identically in the native window, including the Servers view
- `UX-002` server-management contract — configured servers appear as server status cards/list, not the first-run empty state

## Reproduction

1. Create a valid config at `~/servers.json` with one or more server entries.
2. Launch the macOS desktop app with `--config ~/servers.json` (for example via the local helper script that passes that path to the app binary).
3. Open the `Servers` tab.
4. **Actual:** the Servers view shows the empty-state onboarding (`No servers configured`, `Auto-Import`, `Add Server`) or the header/server count behaves as if zero servers are configured.
5. **Expected:** the Servers view shows the configured servers from `~/servers.json` with their status indicators, and the empty state is not shown.

## Root Cause

Unknown. The failure could be in one of three places:

- desktop launch path not passing the config path through correctly
- config file loading succeeding for the process but not reaching the web/API layer used by the desktop UI
- Servers view rendering logic incorrectly falling back to the empty state despite `/api/servers` having configured servers

Do not assume the cause until the desktop launch path and `/api/servers` response are verified together.

## Requirements

- [ ] R1: Desktop launch with `--config <absolute-path>` must use that config file as the source of truth for managed servers.
- [ ] R2: If the config defines one or more servers, the desktop UI must render the configured-server view, not the empty state.
- [ ] R3: The Servers tab and header server-count badge must reflect the actual configured server set from the loaded config.
- [ ] R4: The behavior must work for an absolute config path in the user's home directory, not only for project-local `servers.json`.

## Acceptance Criteria

- [ ] AC 1: Launching Shipyard desktop mode with `--config <absolute-path>` where the config contains at least one valid server results in a non-empty `GET /api/servers` response.
- [ ] AC 2: In that launch mode, the Servers tab renders configured servers/status cards and does not render the first-run empty state.
- [ ] AC 3: The header server-count badge reflects the number of configured servers from the loaded config and is not stuck at `0 servers`.
- [ ] AC 4: The behavior is verified specifically for a config file located under the user's home directory (for example `~/servers.json`, expanded to an absolute path before launch).
- [ ] AC 5: Desktop startup still fails clearly for a missing/invalid config file instead of silently falling back to an empty-state app.
- [ ] AC 6: Regression tests cover desktop config-mode startup plus the Servers-view empty-vs-configured rendering contract so this cannot regress silently again.
- [ ] AC 7: All existing tests pass.

## Context

- Desktop entry path:
  - `cmd/shipyard/main.go` parses `--config` and routes to `runConfig(...)`
  - `cmd/shipyard/main.go` `runConfig(...)` loads config and calls `runMultiServerFn(...)`
  - `cmd/shipyard/desktop.go` opens the Wails window against `http://localhost:<port>`
- Servers API/view path:
  - `internal/web/server.go` exposes `GET /api/servers`
  - `internal/web/ui/index.html` contains the Servers empty state and configured-server rendering logic
- Contract sources:
  - `.nightshift/specs/SPEC-004-phase3-multi-server.md`
  - `.nightshift/specs/SPEC-017-wails-desktop-app.md`
  - `.nightshift/specs/UX-002-dashboard-design.md`
- Related bugfixes:
  - `SPEC-BUG-011` first-run routing to Servers
  - `SPEC-BUG-012` tab/view routing isolation
  - `SPEC-BUG-013` Add Server CTA actionability

## Out of Scope

- Redesigning the Servers screen
- Changing auto-import behavior
- Editing the schema/tool/history views
- Introducing server persistence beyond the existing config-file model

## Research Hints

- Verify whether the desktop process launched with `--config` actually reaches `runConfig(...)` and `runMultiServer(...)` rather than `runNoServers(...)`.
- Compare `GET /api/servers` in desktop mode vs headless mode using the same config file.
- Check whether the frontend is incorrectly deciding to show `servers-empty` based on stale/default state before the API response lands.
- Test an absolute path under `$HOME` directly; do not rely only on relative `servers.json` scenarios already covered by existing tests.
- Relevant files:
  - `cmd/shipyard/main.go`
  - `cmd/shipyard/desktop.go`
  - `cmd/shipyard/desktop_test.go`
  - `internal/web/server_test.go`
  - `internal/web/ui/index.html`
  - `internal/web/ui_layout_test.go`

## Gap Protocol

- Research-acceptable gaps: whether the regression is in launch wiring, API population, or frontend state/rendering
- Stop-immediately gaps: fix requires changing the config-file architecture or contradicting `SPEC-004` multi-server behavior
- Max research subagents before stopping: 0
