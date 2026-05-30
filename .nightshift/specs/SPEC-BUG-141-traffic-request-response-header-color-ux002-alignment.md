---
id: SPEC-BUG-141
template_version: 3
priority: 4
layer: 3
type: bugfix
status: ready
after: [SPEC-BUG-140]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Traffic Request and Response Headers Use Generic Code Headers

## Problem

The Traffic expanded split view currently renders request and response headers
with the generic `.code-header` component. UX-002 defines distinct directional
headers: request is blue, response is green, and error/pending states preserve
that panel grammar while surfacing state.

Observed implementation drift:

- Request header is a generic code-block header with neutral text.
- Successful response header is a generic code-block header with neutral text.
- Error response header places a red badge inside the generic header instead of
  using a panel header that remains aligned with the response panel grammar.
- The implementation wraps panel content in `.code-block`, so header styling is
  inherited from the generic code component rather than the split-view design.

UX-002 reference:

- `srHeader` (`1bzgW`): fill `#58a6ff15`, label `REQUEST`, JetBrains Mono
  10px/700, label color `#58a6ff`, padding `[6,10]`,
  `justifyContent: space_between`
- `resHeader` (`vdw4y`): fill `#3fb95015`, label `RESPONSE`, JetBrains Mono
  10px/700, label color `#3fb950`, padding `[6,10]`,
  `justifyContent: space_between`
- Error state reference: `State - Error Row Expanded`, `error-detail`,
  `eReq`, `eRes`

## Requirements

- [ ] R1: Request panel headers must use a request-specific blue-tinted header
  strip and blue uppercase `REQUEST` label.
- [ ] R2: Response panel headers must use a response-specific green-tinted
  header strip and green uppercase `RESPONSE` label for normal responses.
- [ ] R3: Error responses must preserve the response panel structure while
  making error status visible; they must not fall back to a generic neutral
  code header.
- [ ] R4: Pending responses must preserve the response header strip and show
  pending/awaiting state in the response body.
- [ ] R5: Tests must assert that traffic request/response panel headers do not
  use the generic `.code-header` class.

## Acceptance Criteria

- [ ] AC 1: Request panel header has a request-specific class and blue
  request-tinted background.
- [ ] AC 2: Response panel header has a response-specific class and green
  response-tinted background for successful responses.
- [ ] AC 3: Error response detail shows error state without replacing the
  response panel header with a generic `.code-header`.
- [ ] AC 4: Pending response detail shows the response header even when there is
  no matched response payload yet.
- [ ] AC 5: Source tests fail if `renderDetailPanel` emits `.code-header` for
  Traffic request/response panel headers.
- [ ] AC 6: `go test ./internal/web -run UI -count=1`, `go test ./...`,
  `go vet ./...`, and `go build ./...` pass.

## Context

- Design source: `.nightshift/specs/UX-002-dashboard-design.pen`
- Design nodes: `srHeader` (`1bzgW`), `resHeader` (`vdw4y`),
  `State - Pending Row Expanded`, `State - Error Row Expanded`
- Current implementation:
  - `internal/web/ui/index.html` - request/response header HTML in
    `renderDetailPanel`
  - `internal/web/ui/ds.css` - `.code-block .code-header`
- Related done specs: `SPEC-BUG-004`, `SPEC-006`

## Out of Scope

- Changing table row status badge labels.
- Changing HTTP/API status derivation.
- Changing Tool Browser response header styling.

## Code Pointers

- `internal/web/ui/index.html` - `renderDetailPanel(entry, matched)`
- `internal/web/ui/ds.css` - Code and Panels sections
- `internal/web/ui_layout_test.go` - tests that can pin emitted header classes

## Gap Protocol

- Research-acceptable gaps:
  - Exact class naming for request/response/error/pending header variants.
  - Whether the error label is appended to `RESPONSE` or represented as a
    status badge inside the response-specific header.
- Stop-immediately gaps:
  - Error state loses clear visual differentiation.
  - Pending response no longer tells the user a response is awaited.
- Max research subagents before stopping: 1
