---
id: SPEC-026-003
priority: 2
layer: 3
type: feature
status: done
after: [SPEC-026-001]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# Centralized Paths and Binary Setup

## Problem

Shipyard currently has paths scattered across multiple files: socket path in SocketServer, log path in LogFileWriter, config path in MCPConfig, bridge binary path in various places. For public release, all user-facing paths must be centralized in a single PathManager so they can be configured for different install methods (manual, Homebrew, development). Additionally, ShipyardBridge needs a first-run setup that copies the binary to a known location.

## Requirements

- [ ] Create `PathManager` (or `ShipyardPaths`) as a single source of truth for all user-facing paths
- [ ] Centralize: socket path, log directory, config directory (mcps.json location), bridge binary path, data directory
- [ ] PathManager must support multiple profiles: development (in-tree), installed (~/. shipyard/), Homebrew (/opt/homebrew/...)
- [ ] Active profile determined by environment variable or compile-time flag
- [ ] First-run binary setup: detect if ShipyardBridge is at the expected installed path; if not, copy it there
- [ ] Binary setup creates directory structure if needed (~/.shipyard/bin/, ~/.shipyard/config/, ~/.shipyard/logs/)
- [ ] All existing path references across the codebase updated to use PathManager
- [ ] PathManager is testable: paths can be overridden in tests without touching the filesystem

## Acceptance Criteria

- [ ] AC 1: `PathManager.shared.socketPath` returns the correct path for the active profile
- [ ] AC 2: `PathManager.shared.configDirectory` returns the directory containing mcps.json
- [ ] AC 3: Changing the profile (via env var) changes all returned paths consistently
- [ ] AC 4: No hardcoded path strings remain outside PathManager (grep verification)
- [ ] AC 5: First launch with no ~/.shipyard/ directory creates the full directory tree
- [ ] AC 6: ShipyardBridge binary is copied to ~/.shipyard/bin/ShipyardBridge and is executable
- [ ] AC 7: If binary already exists at target and is same version, skip copy (no unnecessary writes)
- [ ] AC 8: PathManager can be initialized with custom paths for testing (no singleton dependency in tests)

## Context

- Current path locations:
  - Socket: `SocketServer.swift` (likely `/tmp/` or similar)
  - Logs: `LogFileWriter.swift`
  - Config: `MCPConfig.swift` (for mcps.json)
  - Bridge: referenced in config generation and documentation
- The standard macOS convention is `~/Library/Application Support/Shipyard/` but `~/.shipyard/` is more developer-friendly and visible
- PathManager should be `@MainActor` to match the rest of the service layer, or `nonisolated` if paths are needed from any context
- SPEC-026-002 (importer) depends on PathManager to know where mcps.json lives

## Scenarios

1. Developer clones repo → builds and runs → PathManager detects development profile → uses in-tree paths → everything works without setup
2. User installs Shipyard.app → first launch → PathManager detects installed profile → creates ~/.shipyard/ tree → copies bridge binary → mcps.json created at ~/.shipyard/config/mcps.json → app launches normally
3. User has existing ~/.shipyard/ from previous install → PathManager detects existing paths → skips directory creation → checks bridge binary version → updates if newer → preserves existing mcps.json

## Alternatives Considered

- **~/Library/Application Support/Shipyard/** — standard macOS convention but hidden from terminal users. Rejected because Shipyard's audience is developers who want visible config files.
- **XDG-style paths** — cross-platform but unfamiliar on macOS. Rejected for now; could add as a profile later.

## Out of Scope

- Auto-update mechanism for the bridge binary (future)
- Path migration from old locations to new (if paths change in the future)
- Homebrew formula creation (SPEC-026-005 covers documentation, actual formula is separate)

## Notes for the Agent

- Grep for hardcoded paths across the entire project: `/tmp/`, `socketPath`, `logPath`, `configPath`, file URLs with absolute paths
- PathManager should be a lightweight struct or class, not a heavy service — it just computes and returns paths
- Consider making it `nonisolated` with `static` computed properties so it's usable from any isolation context
- Test by overriding paths, not by creating real directories
