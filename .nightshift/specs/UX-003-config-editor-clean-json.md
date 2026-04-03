---
id: UX-003
priority: 2
layer: 3
type: feature
status: done
after: [UX-002]
created: 2026-03-28
---

# Config Editor — Clean JSON Display (Unescape on Load, Re-serialize on Save)

## Problem

When editing `mcps.json` in the ConfigEditorSheet (UX-002), paths and strings appear with escaped forward slashes (`\/`) because the file was written by a JSON encoder that escapes `/`. For example:

```json
"command": "\/opt\/homebrew\/bin\/python3"
```

This is valid JSON (RFC 8259 allows `\/`), but it's hard to read and edit. Users expect to see normal paths like `/opt/homebrew/bin/python3` and shouldn't need to manually escape or unescape anything.

## Requirements

### R1: Unescape on load

When `ConfigEditorSheet.loadConfig()` reads `mcps.json`, it must:

1. Parse the raw file content as JSON via `JSONSerialization.jsonObject(with:)`
2. Re-serialize it with `JSONSerialization.data(withJSONObject:options:)` using **`.prettyPrinted`** and **`.withoutEscapingSlashes`** (available since macOS 10.15)
3. Convert the resulting `Data` back to `String` and display in the editor

This ensures the user always sees clean, human-readable JSON regardless of how the file was originally written.

If parsing fails (malformed JSON), fall back to displaying the raw file content as-is (current behavior) so the user can manually fix syntax errors.

### R2: Re-serialize on save

When `ConfigEditorSheet.saveConfig()` writes back to disk, it must:

1. Parse the editor text as JSON via `JSONSerialization.jsonObject(with:)`
2. Re-serialize with **`.prettyPrinted`** and **`.withoutEscapingSlashes`** and **`.sortedKeys`**
3. Append a trailing newline (`\n`) for POSIX compliance
4. Write the resulting string to disk

This normalizes the output — consistent indentation, no unnecessary escaping, sorted keys for stable diffs.

### R3: Validation unchanged

The existing `validateJSON()` method does not need changes — it already uses `JSONSerialization.jsonObject(with:)` which accepts both escaped and unescaped forms.

## Acceptance Criteria

- **AC1**: Opening ConfigEditorSheet for an MCP whose config contains `\/` shows unescaped paths (e.g., `/opt/homebrew/bin/python3`)
- **AC2**: Saving the config writes clean JSON without `\/` escaping
- **AC3**: If the raw file contains malformed JSON, the editor shows the raw content (not a blank editor or crash)
- **AC4**: Round-trip: load → save without edits produces identical output (idempotent re-serialization)
- **AC5**: Trailing newline present in saved file

## Target Files

- `Shipyard/Views/ConfigEditorSheet.swift` — `loadConfig()` and `saveConfig()` methods

## Notes

- `.withoutEscapingSlashes` is available on macOS 10.15+ (`JSONSerialization.WritingOptions`)
- `.sortedKeys` ensures deterministic output order for cleaner git diffs
- This does NOT affect `JSONEditorView` (the schema-validated editor for tool arguments) — only `ConfigEditorSheet`
