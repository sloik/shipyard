---
id: SPEC-BUG-134
template_version: 3
priority: 1
layer: 1
type: feature
status: done
after: [SPEC-018]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Runtime Performance Telemetry Baseline

## Problem

Shipyard can feel slow when loading tools and can become laggy after running for
a long time, but the app does not currently expose enough runtime telemetry to
identify whether the bottleneck is backend handler latency, child `tools/list`
RPCs, SQLite query cost, WebSocket volume, frontend render time, or process
resource growth.

Without a low-overhead telemetry baseline, performance regressions are diagnosed
from subjective UI symptoms after the fact.

## Probable Causes From Source Inspection

- `internal/web/ui/index.html` loads the Tools view by fetching gateway tools,
  `/api/servers`, one `/api/tools?server=...` call per child server, and then
  `/api/tools/conflicts`.
- `internal/web/server.go` serves `/api/tools?server=...` by making a live
  child `tools/list` RPC, while gateway catalog already uses schema snapshots.
- The schema watcher in `internal/proxy/manager.go` also polls child
  `tools/list`, so tool discovery work can overlap with user-triggered loads.
- Traffic and history endpoints query SQLite and count totals on each request,
  but there is no handler timing or database-size visibility.
- The frontend has no render-duration, row-count, request-timing, or long-session
  state snapshot that can explain lag after hours of use.

## Requirements

- [x] R1: Add low-overhead backend timing telemetry for HTTP API handlers,
  including route, method, status code, duration, and response size where
  practical.
- [x] R2: Add child RPC timing telemetry for manager-mediated requests,
  including server, JSON-RPC method, duration, result/error, and timeout/cancel
  reason.
- [x] R3: Add runtime process telemetry: uptime, goroutine count, heap allocation,
  database file size, traffic row count, schema snapshot count, and access-log
  row count.
- [x] R4: Add a read-only API endpoint for current performance telemetry that is
  safe to call from the dashboard and MCP clients.
- [x] R5: Add frontend telemetry for major UI load/render paths, at minimum:
  Tools load, Servers render, Timeline page load/render, and History/Sessions
  load/render.
- [x] R6: Telemetry must have bounded memory use and must not log secrets,
  request bodies, tool arguments, environment variables, or token values.
- [x] R7: Telemetry must be testable without relying on wall-clock sleeps longer
  than a few milliseconds.

## Acceptance Criteria

- [x] AC 1: `GET /api/performance/runtime` returns process uptime, Go memory
  stats, goroutine count, DB file size, and core table row counts.
- [x] AC 2: `GET /api/performance/http` returns recent or aggregated handler
  latency samples by route without exposing sensitive payloads.
- [x] AC 3: `GET /api/performance/rpc` returns recent or aggregated child
  JSON-RPC timings by server and method without exposing params/results.
- [x] AC 4: The dashboard can record client-side load/render durations for Tools,
  Servers, Timeline, and History/Sessions paths.
- [x] AC 5: Telemetry storage is bounded by count, duration, or both; tests prove
  old samples are evicted or compacted.
- [x] AC 6: Unit tests verify status-code capture, timing capture, redaction, and
  bounded retention.
- [x] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- User report: tool load is slow; app starts to lag after running for a long
  time.
- Backend web server: `internal/web/server.go`
- Proxy manager RPC path: `internal/proxy/manager.go`
- Capture store and DB tables: `internal/capture/store.go`,
  `internal/capture/access_log.go`
- Frontend single-file app: `internal/web/ui/index.html`
- Existing profiling view: `internal/web/server.go` profiling handlers and
  `internal/web/ui/index.html` History > Performance UI

## Out of Scope

- Optimizing the slow paths directly
- Sending telemetry outside the local app
- Recording request/response bodies, tool arguments, tokens, env values, or
  secrets
- Replacing the existing traffic capture or profiling features

## Code Pointers

- `internal/web/server.go` - handler registration and API handlers
- `internal/proxy/manager.go` - `SendRequest`, schema watcher, child RPC timing
- `internal/capture/store.go` - SQLite-backed traffic/session/schema storage
- `internal/capture/access_log.go` - access log and profiling aggregates
- `internal/web/ui/index.html` - frontend load/render paths
- `internal/web/server_test.go` - API handler tests
- `internal/proxy/manager_test.go` - manager request tests
- `internal/web/ui_layout_test.go` - source-level UI regression tests

## Gap Protocol

- Research-acceptable gaps:
  - Whether telemetry should live in memory only or also persist compacted
    aggregates in SQLite
  - Exact route names for dynamic paths
  - Exact frontend render budget thresholds after initial baseline data
- Stop-immediately gaps:
  - The proposed telemetry requires storing sensitive request bodies or secrets
  - The telemetry adds unbounded memory growth
  - The telemetry introduces race detector failures
- Max research subagents before stopping: 1
