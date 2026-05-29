# Nightshift Report - 2026-05-29 - SPEC-018

## Summary Stats

- Specs run: 1
- Spec status changed by this run: no; `SPEC-018` remains `in_progress` for parent review
- Implementation result: completed with GUI-manual-test caveat
- Files changed: 12 tracked source/config files plus this report
- Required validation commands passed: 8/8
- Wails-specific build commands passed: 2/2
- Server smoke checks passed: 2/2
- macOS arm64 binary sizes:
  - `bin/shipyard`: 18,693,986 bytes
  - `bin/shipyard-server`: 18,214,610 bytes

## Per-Spec Changes

### SPEC-018 - Wails v3 Native Desktop Features

Status: implemented in branch; parent should resolve final spec status.

- Migrated Shipyard desktop integration from Wails v2 imports/config to Wails v3 `application.New`, `AssetOptions`, `WebviewWindowOptions`, window hooks, and system tray APIs.
- Preserved the existing localhost HTTP server architecture: Wails serves the bundled UI and the desktop bridge proxies `/api/*` and `/ws` to the local server.
- Added a Wails v3 system tray with a generated template icon, left-click dashboard toggle, right-click menu, `Show Dashboard`, and `Quit`.
- Changed main-window close behavior to hide the window and keep Shipyard running; quit paths save layout, cancel server/proxy context, and exit.
- Added native multi-window detach support for Timeline, Tools, History, and Servers through `/_shipyard/windows/open?panel=...`.
- Added top-tab right-click menu: `Open in New Window`.
- Added window layout persistence at `dataDir/window-layout.json`, including main bounds, detached panel state, and panel bounds.
- Added `Taskfile.yml` with `build` and `build:server`; `build:server` compiles with `-tags server`.
- Added `server` build-tag seam so `wails3 task build:server` defaults to headless mode without requiring `--headless`.
- Removed stale Wails v2 app config from `cmd/shipyard/wails.json` and updated Makefile Wails targets.
- Added regression coverage for native bridge config, panel detach endpoint validation, layout save/load, UI context menu wiring, native endpoint fetch bypass, and context menu CSS.

## Wails Research Notes

- Official migration guide checked: https://v3.wails.io/migration/v2-to-v3/
- Installed and used Wails CLI/module: `v3.0.0-alpha.96`.
- `go list -m -versions github.com/wailsapp/wails/v3` showed `v3.0.0-alpha.96` as the latest listed module version.
- `wails3 releasenotes -v v3.0.0-alpha.96 -n` completed and identified the release as pre-release alpha software.
- `wails3 doctor` is available but did not complete: it printed the Wails Doctor heading, completed "Scanning system", printed `# System`, then timed out after 20 seconds in this run. Earlier manual attempt showed the same hang pattern after the `# System` heading.

## Test Results

```text
go build ./...
PASS
note: macOS linker warnings from Wails native objects built for macOS 26.0 while linking target 11.0

go test ./...
PASS
ok   github.com/sloik/shipyard/cmd/shipyard         7.034s
ok   github.com/sloik/shipyard/cmd/shipyard-mcp     cached
ok   github.com/sloik/shipyard/internal/auth        cached
ok   github.com/sloik/shipyard/internal/capture     cached
ok   github.com/sloik/shipyard/internal/gateway     cached
ok   github.com/sloik/shipyard/internal/proxy       cached
ok   github.com/sloik/shipyard/internal/secrets     cached
ok   github.com/sloik/shipyard/internal/web         cached

go vet ./...
PASS

go build -tags server ./...
PASS
note: same macOS linker warnings from Wails native objects

wails3 task build
PASS
produced bin/shipyard, 18,693,986 bytes

wails3 task build:server
PASS
produced bin/shipyard-server, 18,214,610 bytes

./bin/shipyard-server --config /tmp/shipyard-spec018-server-config.json
PASS: started without --headless, logged dashboard URL http://localhost:19419

curl -fsS http://127.0.0.1:19419/api/servers
PASS: returned self server plus alpha test server

curl -fsSI http://127.0.0.1:19419/
PASS: returned HTTP/1.1 200 OK and text/html

go test -race -count=1 -timeout 5m ./...
PASS
ok   github.com/sloik/shipyard/cmd/shipyard         34.591s
ok   github.com/sloik/shipyard/cmd/shipyard-mcp     6.267s
ok   github.com/sloik/shipyard/internal/auth        11.434s
ok   github.com/sloik/shipyard/internal/capture     13.188s
ok   github.com/sloik/shipyard/internal/gateway     3.063s
ok   github.com/sloik/shipyard/internal/proxy       12.878s
ok   github.com/sloik/shipyard/internal/secrets     1.893s
ok   github.com/sloik/shipyard/internal/web         13.519s

python3 .nightshift/validate_specs.py .nightshift/specs/SPEC-018-wails-v3-native-features.md
PASS: [nightshift validate-specs] OK - 1 spec(s) valid
```

## Acceptance Checklist

- AC1: PASS - `go build ./...`, `go test ./...`, `go vet ./...`, and race validation passed after the v3 migration.
- AC2: IMPLEMENTED - macOS tray icon is created with Wails v3 `SystemTray.New()` and `SetTemplateIcon`; click toggles the main window. Manual visual tray inspection was not performed in this run.
- AC3: PASS BY IMPLEMENTATION - tray menu contains `Show Dashboard`, separator, and `Quit`.
- AC4: PASS BY IMPLEMENTATION - main window close hook hides the window and cancels the close; Quit sets the quitting state, saves layout, cancels context, and calls `app.Quit()`.
- AC5: PASS - top-tab context menu posts to the native bridge; backend opens detachable native panel windows for Timeline, Tools, History, and Servers. Covered by Go/UI source tests.
- AC6: PASS BY ARCHITECTURE - detached windows load the same SPA route and connect to the same existing `/ws` hub, so Timeline and History receive the same real-time event stream. Existing websocket behavior was preserved by full test/race validation.
- AC7: PASS - `wails3 task build:server` produced `bin/shipyard-server`; the binary starts without `--headless` and serves both `/` and `/api/servers`.
- AC8: PASS - layout JSON save/load is implemented and covered by tests; runtime hooks update main and panel bounds/detached state.
- AC9: PASS - both built macOS arm64 binaries are under 30 MB.

## Blockers / Discoveries

- No implementation blocker remains.
- `wails3 doctor` is not reliable in this environment. It hangs after the `# System` heading; report evidence captured `DOCTOR_TIMEOUT_AFTER_20S`.
- Wails v3 alpha.96 raises non-fatal macOS linker warnings about native objects built for macOS 26.0 while linking target 11.0. The warnings did not block build, test, server-tag build, Wails task builds, or runtime server smoke.
- Adding Wails v3 required raising `go.mod` from `go 1.22.0` to `go 1.25.0`. The local toolchain is Go 1.26.2, and Shipyard CI is already pinned to Go 1.26 per repo context.
- GUI-native AC2-AC4 were implemented against current Wails v3 APIs and compiled, but this run did not perform an interactive macOS menu-bar click/right-click inspection.

## Suggested Follow-up Specs

1. Add an automated or semi-automated macOS GUI smoke for Wails tray/menu/window detach behavior, using accessibility or a small manual-evidence checklist if menu-bar automation is brittle.
2. Add Wails v3 app packaging/signing/notarization work once the project wants distributable `.app` artifacts beyond raw task-built binaries.
