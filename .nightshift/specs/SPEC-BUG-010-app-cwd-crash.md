---
id: SPEC-BUG-010
template_version: 2
priority: 1
layer: 2
type: bugfix
status: done
after: [SPEC-017]
prior_attempts: []
violates: "SPEC-017 R1 — Shipyard launches as a native desktop app (double-click .app on macOS)"
created: 2026-04-06
---

# App crashes on macOS double-click — SQLite cannot write to root filesystem

## Problem

When Shipyard.app is launched by double-clicking on macOS, macOS LaunchServices
sets the working directory to `/` (root filesystem). The app calls
`captureNewStore("shipyard.db", "shipyard.jsonl")` with relative paths,
which resolves to `/shipyard.db`. The root filesystem is read-only (SIP),
so SQLite fails to create the database, the store init errors, and the app
exits immediately. The user sees the Dock icon appear then vanish.

**Reproduction:**
1. Download shipyard-macos.zip from GitHub release
2. Unzip, clear quarantine (`xattr -d com.apple.quarantine`)
3. Double-click Shipyard.app
4. Dock icon appears briefly, then app closes

**Error (visible only from terminal):**
```
failed to initialize capture store  error="migrate: read user_version: sqlite3: unable to open database file"
```

Running from terminal works because cwd is writable.

## Root Cause

Relative file paths (`"shipyard.db"`) resolve against cwd. macOS .app bundles
launch with cwd=`/`. All three startup paths (`runProxy`, `runMultiServer`,
`runNoServers`) had this bug.

## Fix

Use a platform-appropriate data directory:
- macOS: `~/Library/Application Support/Shipyard/`
- Windows: `%APPDATA%/Shipyard/`
- Linux: `~/.shipyard/`
- Fallback: cwd (for backward compat when running from terminal)

`dataDir()` function creates the directory and returns the absolute path.
All `captureNewStore` calls use `filepath.Join(dir, "shipyard.db")`.

## Acceptance Criteria

- [x] AC 1: Double-clicking Shipyard.app on macOS opens the dashboard (not crash)
- [x] AC 2: Database created at `~/Library/Application Support/Shipyard/shipyard.db`
- [x] AC 3: Running from terminal still works (dataDir returns platform path)
- [x] AC 4: All existing tests pass
