---
id: SPEC-BUG-009
template_version: 2
priority: 1
layer: 2
type: bugfix
status: in_progress
after: [SPEC-017]
prior_attempts: []
violates: "SPEC-017 R1 — Shipyard launches as a native desktop app (double-click .app on macOS)"
created: 2026-04-06
---

# App exits immediately when launched without arguments

## Problem

Double-clicking `Shipyard.app` on macOS passes no CLI arguments. The current
`main()` treats no-args as an error, prints usage, and exits with code 1.
This violates SPEC-017 R1 — the app should launch as a standalone desktop app.

**Reproduction:**
1. Download `shipyard-macos.zip` from GitHub release
2. Unzip, clear quarantine
3. Double-click `Shipyard.app`
4. App exits immediately, nothing visible

**Expected:** Native window opens with an empty dashboard (no servers configured).
The user can then use Auto-Import or configure servers via the UI.

## Requirements

- [ ] R1: `shipyard` with no arguments opens the desktop window with an empty dashboard
- [ ] R2: `shipyard --headless` with no arguments still prints usage and exits (CLI mode needs explicit config)
- [ ] R3: The empty dashboard is functional — Auto-Import, server status page all work

## Acceptance Criteria

- [ ] AC 1: Running `shipyard` (no args) opens a native window with the dashboard
- [ ] AC 2: Running `shipyard --headless` (no args) prints usage and exits with code 1
- [ ] AC 3: The dashboard shows empty server list (not an error page)
- [ ] AC 4: Auto-Import button works from the empty dashboard
- [ ] AC 5: All existing tests pass

## Context

- `cmd/shipyard/main.go` line 154: `if len(args) == 0` → prints usage and exits
- Fix: when not headless and no args, start HTTP server + desktop window with no child proxies
- The HTTP server, Hub, ProxyManager all work fine with zero proxies registered
