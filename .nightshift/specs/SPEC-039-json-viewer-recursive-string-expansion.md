---
id: SPEC-039
template_version: 2
priority: 1
layer: 2
type: feature
status: ready
after: [SPEC-BUG-001, SPEC-036]
prior_attempts: []
created: 2026-04-13
---

# JSON Viewer — Recursive JSON String Expansion

## Problem

MCP tool responses frequently embed JSON inside string fields — for example,
a `tools/call` result where `content[0].text` contains a serialised JSON
blob. The current viewer renders these as escaped string literals
(`"{\"key\":\"value\"}"`) because it does one level of `JSON.parse` and then
re-serialises. Users must manually decode the escaping to understand the
nested structure.

The macOS SwiftUI predecessor (`swiftui/v0` branch, `Utilities/JSONFormatter.swift`)
solved this with a recursive expander: after parsing the outer JSON, every
string value is tested for JSON validity and, if valid, replaced with the
parsed object before pretty-printing. This makes nested responses immediately
readable without extra steps.

The same limitation affects both the tool browser response panel and the
traffic detail panels.

## Requirements

- [ ] R1: After `JSON.parse`, walk the parsed object recursively; if any
  string value is itself valid JSON (parses to an object or array),
  replace it with the parsed value before `JSON.stringify`.
- [ ] R2: Recursion applies to object values, array elements, and nested
  structures at any depth.
- [ ] R3: A depth limit of 5 prevents infinite expansion on pathological
  inputs.
- [ ] R4: String values that are not valid JSON, or that parse to a primitive
  (number, boolean, null, bare string), are displayed as-is — no false
  positives.
- [ ] R5: The enhancement is contained inside `highlightJSON()`. Its
  signature and call sites are unchanged.
- [ ] R6: The feature applies to both the tool browser response panel
  (`#tool-response-json`) and the traffic detail panels
  (`renderDetailPanel` — request and response sides).

## Acceptance Criteria

- [ ] AC 1: A tool response containing
  `{"content":[{"type":"text","text":"{\"key\":\"value\"}"}]}`
  renders the `text` field as an expanded nested JSON block — not as the
  escaped string `"{\"key\":\"value\"}"`.
- [ ] AC 2: A response with `{"name":"Alice"}` (no nested JSON strings)
  renders identically to the current implementation.
- [ ] AC 3: `{"val":"hello world"}` — plain string value, not expanded.
- [ ] AC 4: A response with 3+ levels of nested JSON strings is fully
  expanded at all levels (recursive).
- [ ] AC 5: A string that parses as a JSON number, boolean, or null is
  treated as a plain string — not expanded.
- [ ] AC 6: `ui_layout_test.go` contains tests covering:
  - String value containing a JSON object → expanded
  - String value containing a JSON array → expanded
  - Plain string value → unchanged
  - 2-level nested expansion (recursive)
  - Non-JSON parseable string (number as string) → unchanged
- [ ] AC 7: `go test ./...` passes.
- [ ] AC 8: `go vet ./...` passes.
- [ ] AC 9: `go build ./...` passes.

## Context

- Reference implementation: `swiftui/v0` branch →
  `Utilities/JSONFormatter.swift` — `format(_:)` method (recursive string
  detection) and `formatResponse(_:)` (result unwrapping).
- JSON renderer: `internal/web/ui/index.html`
  - `highlightJSON(str)` — lines 954–988. Currently:
    `JSON.parse → JSON.stringify → line-by-line coloring`.
    Enhancement: add `expandJSONStrings(obj, 0)` call between parse and
    stringify.
  - Add `expandJSONStrings(obj, depth)` helper adjacent to `highlightJSON`.
- Call sites (unchanged): `toolResponseBody()` (~line 2125),
  `renderDetailPanel()` (lines 1056, 1073, 1079).
- Test file: `internal/web/ui_layout_test.go`
- JS conventions: `var`, `.then()`, no `async/await`, no `let`/`const`.
- Note: JS `JSON.parse`/`JSON.stringify` already handle `\uXXXX` unicode
  escapes and forward-slash escaping natively — no extra porting needed.

## Out of Scope

- Click-to-collapse/expand sections
- `{"result":…}` wrapper stripping (separate spec if needed)
- Changes to the JQ filter or Copy button behaviour
- Modifying the traffic capture backend
- Horizontal scroll or word-wrap changes
