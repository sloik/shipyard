---
id: SPEC-BUG-173
template_version: 3
priority: 2
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

# Live traffic rows miss correlated method and latency until page reload

## Problem

Found during the UX-002 acceptance-criteria audit (AC-2, Phase 0 timeline
matches the design). In the design every RES row shows its method
(`tools/list`, `initialize`, …).

Rows that arrive over the WebSocket while the Traffic view is open render
incompletely:

- A **response** row shows method `—` instead of the method of its matched
  request.
- The matched **request** row keeps latency `–`; it is never updated when the
  response arrives.

After a page reload both rows are correct, because `GET /api/traffic` reads
the correlated values from the store. Runtime-confirmed with the smoke
harness: the dashboard's own `tools/list` refresh after page load produced a
live `RES alpha —` row whose API record has `method: "tools/list"`,
`latency_ms: 0`.

### Root cause

`internal/proxy/proxy.go` (capture path, ~line 540–580) builds the broadcast
`capture.TrafficEvent` from the local `method` variable, which is empty for
responses. `store.Insert()` (`internal/capture/store.go` ~462–475) correlates
the response and fills `entry.Method` from the matched request, but the
event uses `method`, not `entry.Method`. The store also updates the request
row's latency, but no event tells the UI to update the already-rendered
request row.

`internal/proxy/manager.go` (~735–750) has a second broadcast path that
should be checked for the same issue.

## Requirements

- [ ] R1: Live response events carry the correlated method (as stored).
- [ ] R2: When a response is correlated, the already-rendered request row in
  the Traffic view updates its latency (and status per SPEC-BUG-174 if that
  lands first) without a reload.
- [ ] R3: Live and reloaded renderings of the same traffic are identical for
  the method, latency and status columns.

## Acceptance Criteria

- [ ] AC1: Go test: capturing a request then its response broadcasts a
  response event whose `method` equals the request's method.
- [ ] AC2: Headless check: with the Traffic view open, invoke a tool; the
  new RES row shows `tools/call` and the REQ row shows a latency value — and
  the rendered cells equal those after `page.reload()`.
- [ ] AC3: `go test -race ./...`, `go vet ./...`, `go build ./...` pass.

## Out of Scope

- Changing status wording (`ok` vs `200 OK`) — see SPEC-BUG-174.

## Code Pointers

- `internal/proxy/proxy.go` — `TrafficEvent` construction (~573)
- `internal/proxy/manager.go` — WS broadcast (~735–750)
- `internal/capture/store.go` — `Insert()` correlation (~455–510)
- `internal/web/ui/index.html` — `ws.onmessage` live insert (~2118–2135),
  `renderRow()` (~1350)
