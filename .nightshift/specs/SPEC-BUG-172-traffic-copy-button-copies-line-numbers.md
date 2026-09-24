---
id: SPEC-BUG-172
template_version: 3
priority: 1
layer: 3
type: bugfix
status: done
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

- [x] R1: The Traffic detail copy buttons copy the pretty-printed payload
  exactly as displayed, without line numbers, with newlines preserved.
- [x] R2: The copied request/response text parses as JSON whenever the
  captured payload is JSON.
- [x] R3: Any other viewer that derives copy text from a line-numbered
  `.json-viewer` via `textContent` gets the same fix.

## Acceptance Criteria

- [x] AC1: Headless check: click the request copy button in an expanded
  traffic row; `navigator.clipboard.readText()` parses with `JSON.parse` and
  deep-equals the captured payload.
- [x] AC2: Same for the response copy button.
- [x] AC3: Copy text contains no line-number prefixes (`/^\d+\{/` does not
  match; line count equals the viewer's line count).
- [x] AC4: `go test ./...`, `go vet ./...`, `go build ./...` pass.

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

## Resolution — 2026-09-24

- New `DS.jsonViewerText(viewer)` in `ds.js` rebuilds text from each
  `.json-line .lc` joined with `\n`. `wireCopyButtons()` and the generic
  `handleCopy()` fallback both use it (R3). No other view copies from a
  line-numbered viewer's `textContent`.
- The copy covers the whole payload even while the JSON filter hides lines.
- Tests: `TestSPECBUG172_JsonViewerCopyTextSkipsLineNumbers`; the
  SPEC-BUG-142 wiring assertion now expects `DS.jsonViewerText(jv)`;
  `test/smoke/traffic_smoke.mjs` reads the clipboard for both panes, parses
  it and deep-compares it with the payload from `/api/traffic/{id}`.
- Verification: same as SPEC-BUG-171 (`go test -race`/`go vet` pass except
  `cmd/shipyard`, which needs the desktop GTK/WebKit libraries CI installs).
