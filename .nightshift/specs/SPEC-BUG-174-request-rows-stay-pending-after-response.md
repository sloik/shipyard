---
id: SPEC-BUG-174
template_version: 3
priority: 2
layer: 3
type: bugfix
status: ready
after: [SPEC-BUG-173]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
parent: UX-002
created: 2026-09-24
---

# Request rows stay "pending" forever after their response arrives

## Problem

Found during the UX-002 acceptance-criteria audit (AC-2, Phase 0 timeline
matches the design).

The UX-002 design (`Phase 0 — Traffic Timeline`, rows `row-1` … `row-6`)
shows a request row as **Pending** only while it is unanswered (`row-1`,
latency `—`). Once answered, the request shows its outcome (`row-3`, `row-5`:
REQ with status `200 OK`).

In the implementation every request row shows `pending` permanently, even
when its matched response is present and the row already shows a latency
(e.g. REQ `tools/call` · `pending` · `0ms`). This is misleading: users cannot
tell answered requests from hung ones, which is the point of the status
column. `GET /api/traffic` confirms the stored request row keeps
`status: "pending"` after correlation.

## Requirements

- [ ] R1: When a response is correlated to a request, the request's stored
  status becomes the response outcome (`ok` / `error`).
- [ ] R2: Requests that are never answered stay `pending`; notifications
  (no `id`) show no pending status (they expect no response).
- [ ] R3: The Traffic view reflects R1 both on reload and live (building on
  SPEC-BUG-173's live row update).
- [ ] R4: The status badge label for a successful response matches the
  design wording, or the design is updated to the implementation's wording —
  record the decision in this spec's run report.

## Acceptance Criteria

- [ ] AC1: Go store test: insert request, insert matching response ⇒ request
  row status equals response status; unmatched request stays `pending`.
- [ ] AC2: Headless check: after a tool call, the REQ row shows the success
  badge, not `pending`.
- [ ] AC3: A `notifications/initialized` row does not show `pending`.
- [ ] AC4: `go test -race ./...`, `go vet ./...`, `go build ./...` pass.

## Out of Scope

- Timeouts / marking stale requests as failed.

## Code Pointers

- `internal/capture/store.go` — `Insert()` correlation and request-row update
  (~455–510)
- `internal/proxy/proxy.go` — status derivation (~535–541)
- `internal/web/ui/index.html` — `statusBadge()`, `renderRow()` (~1350)
- `.nightshift/specs/UX-002-dashboard-design.pen` — frame `rRx2E`, rows
  `row-1` … `row-6`
