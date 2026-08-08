---
id: SPEC-BUG-165-001
priority: 1
layer: 1
type: bugfix
status: in_progress
after: [SPEC-BUG-164-001]
nfrs: [SPEC-NFR-001]
technologies: [json]
created: 2026-08-08
---

# Configure Mole cleanup's Shipyard response timeout

## Problem

`mole_clean` needs a response deadline longer than Shipyard's default, while
other lmac-run tools should keep the normal deadline.

## Requirements

- [x] R1: Configure only `servers.lmac-run.tools.mole_clean` with
  `response_timeout_seconds: 81` in `~/servers.json`.
- [x] R2: Do not alter any server-level or global timeout setting.

## Acceptance Criteria

- [x] AC-1: Shipyard starts with the updated configuration.
- [x] AC-2: A `mole_clean` dry-run can complete through Shipyard without its
  former 30-second gateway timeout.
- [x] AC-3: Another lmac-run tool retains the 30-second default.

## Context

- Depends on SPEC-BUG-164-001 providing the per-tool configuration boundary.
- The lmac-run command itself has an 81-second timeout based on five dry-run
  measurements; this spec aligns Shipyard's response wait with that limit.

## Out of Scope

- Any Mole command behavior or cleanup policy.
- Shipyard source changes.
