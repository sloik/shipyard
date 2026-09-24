---
id: SPEC-BUG-172
template_version: 3
priority: 1
layer: 3
type: bugfix
status: ready
after: []
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
parent: UX-002
created: 2026-09-24
---

# Traffic detail copy button copies line numbers and drops newlines

## Problem

Found during the UX-002 acceptance-criteria audit (AC-6, "Copy-to-clipboard
button on JSON payloads").

The copy buttons on the Traffic detail panel's REQUEST / RESPONSE panes are
present, but the text they put on the clipboard is not the payload. Runtime-
confirmed in headless Chromium (clipboard read after clicking the request
copy button):

```
1{2  "id": "shipyard-3",3  "jsonrpc": "2.0",4  "method": "tools/call",5  "params": {6 ...
```

Every line number is glued to its line and all newlines are lost, so the
result is not valid JSON (`JSON.parse` fails). Pasting it anywhere is useless.

### Root cause

`wireCopyButtons()` in `internal/web/ui/index.html` sets

```js
btn.setAttribute('data-copy', jv.textContent);
```

where `jv` is the `.json-viewer` rendered by `highlightJSON()` as one
`<div class="json-line">` per line containing `<span class="ln">N</span>` and
`<span class="lc">…</span>`. `textContent` concatenates the line-number spans
and has no newline between the `div`s.

## Requirements

- [ ] R1: The Traffic detail copy buttons copy the pretty-printed payload
  exactly as displayed, without line numbers, with newlines preserved.
- [ ] R2: The copied request/response text parses as JSON whenever the
  captured payload is JSON.
- [ ] R3: Any other viewer that derives copy text from a line-numbered
  `.json-viewer` via `textContent` gets the same fix.

## Acceptance Criteria

- [ ] AC1: Headless check: click the request copy button in an expanded
  traffic row; `navigator.clipboard.readText()` parses with `JSON.parse` and
  deep-equals the captured payload.
- [ ] AC2: Same for the response copy button.
- [ ] AC3: Copy text contains no line-number prefixes (`/^\d+\{/` does not
  match; line count equals the viewer's line count).
- [ ] AC4: `go test ./...`, `go vet ./...`, `go build ./...` pass.

## Out of Scope

- Changing copy-button visuals or feedback animation.
- The Tool Browser response copy (`toolResponseCopy`), which already sets a
  raw string.

## Code Pointers

- `internal/web/ui/index.html` — `wireCopyButtons()` (~line 1465),
  `highlightJSON()` (~1309), detail panel copy buttons (~1417–1448)

## Gap Protocol

- Research-acceptable gaps:
  - Audit History, Sessions and Schema views for the same
    `textContent`-of-line-numbered-viewer pattern (R3).
