---
id: UX-004
priority: 2
layer: 3
type: feature
status: done
after: [UX-003]
created: 2026-03-28
---

# App-Wide Clean JSON Display — Unescape Slashes + Decode Unicode

## Problem

JSON displayed in the tool execution detail view (and other places app-wide) contains:

1. **Escaped forward slashes** (`\/`) — e.g., `\/opt\/homebrew\/bin\/python3` instead of `/opt/homebrew/bin/python3`
2. **Escaped quotes** (`\"`) inside embedded JSON strings — makes MCP responses unreadable
3. **Unicode escapes** (`\u05e9`, `\u2019`, etc.) — instead of actual Hebrew, smart quote, and other Unicode characters

The root cause: `ExecutionDetailView.formatJSON()` uses `JSONSerialization.data(withJSONObject:options:)` with `[.prettyPrinted, .sortedKeys]` but **without `.withoutEscapingSlashes`**. Additionally, MCP servers often return responses where string values contain `\uXXXX` escapes that JSONSerialization preserves verbatim.

## Requirements

### R1: Add `.withoutEscapingSlashes` to all `JSONSerialization.data()` calls in formatJSON

In `ExecutionDetailView.swift`, the `formatJSON(_ data: Any)` method has two `JSONSerialization.data(withJSONObject:options:)` calls (one for dict, one for array). Both must include `.withoutEscapingSlashes` in the options array.

**Before:**
```swift
JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys])
```

**After:**
```swift
JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
```

Apply to BOTH the `dict` and `array` branches.

### R2: Create a shared `JSONFormatter` utility

Extract the JSON formatting logic from `ExecutionDetailView.formatJSON()` into a standalone utility struct in `Shipyard/Utilities/JSONFormatter.swift`. This ensures all JSON display surfaces use the same clean formatting logic.

```swift
enum JSONFormatter {
    /// Standard serialization options for all JSON display in Shipyard
    static let displayOptions: JSONSerialization.WritingOptions = [
        .prettyPrinted, .sortedKeys, .withoutEscapingSlashes
    ]

    /// Format any value as clean, human-readable JSON
    static func format(_ data: Any) -> String { ... }

    /// Format a response JSON string (unwraps {"result": ...} wrapper)
    static func formatResponse(_ responseJSON: String) -> String { ... }

    /// Decode unicode escape sequences (\uXXXX) in a string to actual characters
    static func decodeUnicodeEscapes(_ string: String) -> String { ... }
}
```

### R3: Decode unicode escape sequences

After JSONSerialization produces its output string, apply a post-processing step to decode `\uXXXX` escape sequences to actual Unicode characters. This handles cases where the MCP server's JSON encoder produced unicode escapes that JSONSerialization preserves in string values.

Implementation approach:
- Use a regex to find `\\uXXXX` patterns in the serialized output
- Convert each match to the actual Unicode scalar
- Handle surrogate pairs (`\uD800-\uDBFF` followed by `\uDC00-\uDFFF`) for characters outside the BMP (like emoji)
- Apply this AFTER serialization, on the final output string

**Important:** Only decode `\uXXXX` sequences that appear inside JSON string values (between quotes). Do NOT blindly replace across the entire string — that could corrupt non-string content. However, since JSONSerialization output puts `\uXXXX` only inside strings, a global replace is safe in practice for well-formed JSON.

### R4: Wire JSONFormatter into all JSON display surfaces

Replace direct `formatJSON` calls with `JSONFormatter`:

1. **`ExecutionDetailView.swift`**: Replace private `formatJSON()` and `formatResponseJSON()` with calls to `JSONFormatter.format()` and `JSONFormatter.formatResponse()`
2. **`ConfigEditorSheet.swift`**: Use `JSONFormatter.displayOptions` in both `loadConfig()` and `saveConfig()` instead of inline options arrays (keep the existing UX-003 logic, just reference the shared constant)

### R5: Unit tests

Create `ShipyardTests/JSONFormatterTests.swift` with tests for:

- **`testFormatSlashEscaping`**: Input dict with paths containing `/` → output has unescaped `/`
- **`testFormatUnicodeDecoding`**: Input dict with `\u05e9` (Hebrew shin) and `\u2019` (right single quote) → output has actual characters `ש` and `'`
- **`testFormatSurrogatePairs`**: Input with `\uD83D\uDE00` → output has 😀
- **`testFormatPreservesValidJSON`**: Roundtrip — format produces valid JSON that can be re-parsed
- **`testFormatStringContainingJSON`**: Input is a string containing embedded JSON → properly parsed and formatted
- **`testFormatResponseUnwrapsResult`**: Input `{"result": {...}}` → unwrapped to inner content
- **`testFormatArray`**: Array input formatted correctly
- **`testFormatFallback`**: Non-JSON input returns string representation

## Acceptance Criteria

- **AC1**: `formatJSON` output for paths no longer contains `\/` — shows `/` instead
- **AC2**: Unicode escapes like `\u05e9` are decoded to actual characters (`ש`) in displayed JSON
- **AC3**: Surrogate pairs (`\uD83D\uDE00`) are decoded to actual emoji (😀)
- **AC4**: All JSON display surfaces (ExecutionDetailView request + response, ConfigEditorSheet) use the same formatting logic
- **AC5**: Round-trip safety: `JSONFormatter.format()` output is valid, re-parseable JSON
- **AC6**: `JSONFormatter` is a standalone utility (not embedded in a View)
- **AC7**: All 8 unit tests pass
- **AC8**: Project builds with zero errors and all existing tests continue to pass

## Target Files

- `Shipyard/Utilities/JSONFormatter.swift` — **NEW** — shared formatting utility
- `Shipyard/Views/ExecutionDetailView.swift` — replace private formatJSON with JSONFormatter calls
- `Shipyard/Views/ConfigEditorSheet.swift` — use JSONFormatter.displayOptions
- `ShipyardTests/JSONFormatterTests.swift` — **NEW** — unit tests

## Notes

- `.withoutEscapingSlashes` is available since macOS 10.15 — Shipyard's deployment target is already ≥ 10.15
- JSONSerialization does NOT produce `\uXXXX` for non-ASCII by default on macOS — it writes UTF-8. But if the INPUT data already contains literal `\uXXXX` text in string values (e.g., from an MCP server that over-encodes), those are preserved. The R3 post-processing catches these.
- This does NOT expand embedded JSON strings (per user preference: "unescape top-level only"). A string value containing JSON remains a string — but its `\/` and `\uXXXX` sequences are decoded.
- New .swift files MUST be added via `mcp__xcode__XcodeWrite` — writing to disk alone won't register them in the xcodeproj.
