---
id: UX-006
priority: 2
layer: 3
type: refactor
status: done
after: [SPEC-019]
prior_attempts: []
created: 2026-03-31
---

# Remove Redundant "Configured via mcps.json" Description Text

## Problem

Config-sourced MCPs display "Configured via mcps.json" as their description in the server row. This text is redundant — the "JSON" pill badge already communicates that the server originates from `mcps.json`. Showing both creates visual noise.

**Source:** `MCPRegistry.swift` line ~493, inside `makeManifest(name:entry:)`:

```swift
description: entry.cwd.map { "Configured via mcps.json (cwd: \($0))" } ?? "Configured via mcps.json",
```

## Fix

Strip the "Configured via mcps.json" prefix. If a `cwd` is set, preserve only the cwd value (it's genuinely useful context). If no `cwd`, use an empty description.

```swift
// Before
description: entry.cwd.map { "Configured via mcps.json (cwd: \($0))" } ?? "Configured via mcps.json",

// After
description: entry.cwd.map { "cwd: \($0)" } ?? "",
```

## Acceptance Criteria

- [x] AC 1: Config MCPs with no `cwd` show an empty description (no text below the name in the row, just the JSON pill)
- [x] AC 2: Config MCPs with `cwd` set show `"cwd: /path/to/dir"` as the description
- [x] AC 3: The "JSON" pill badge remains visible and unaffected
- [x] AC 4: Manifest-sourced MCPs are unaffected
- [x] AC 5: Build succeeds with zero errors; existing tests pass

## Files

- `Shipyard/Services/MCPRegistry.swift` — one-line change in `makeManifest(name:entry:)`
