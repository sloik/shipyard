---
id: SPEC-BUG-137
template_version: 3
priority: 3
layer: 2
type: feature
status: ready
after: [SPEC-BUG-134]
nfrs: [SPEC-NFR-001]
prior_attempts: []
attachments: []
created: 2026-05-30
---

# Performance History and Debug Bundle

## Problem

Even after runtime telemetry exists, Shipyard needs a way to track performance
over time and produce a compact debugging artifact when the app feels slow after
hours of use. The existing History > Performance view focuses on tool-call
latency from access logs, not app health, handler latency, frontend render cost,
database growth, or child RPC fan-out.

Without historical baselines and an exportable debug bundle, long-session lag is
hard to compare across builds.

## Requirements

- [ ] R1: Persist compact performance rollups over time, using bounded storage.
- [ ] R2: Track at minimum API handler latency, child RPC latency, frontend
  render/load duration, active DOM row counts, process memory/goroutine count,
  DB file size, traffic row count, and schema snapshot count.
- [ ] R3: Add a dashboard surface that shows recent performance trend lines or
  tables for app health, not only tool-call latency.
- [ ] R4: Add a one-click or one-command debug bundle export that includes
  performance rollups, current runtime telemetry, app version/build info, config
  shape without secrets, and table counts.
- [ ] R5: The debug bundle must redact secrets, token plaintext/hashes, request
  bodies, tool arguments, environment variables, and large payloads.
- [ ] R6: The history format must survive app restarts and support comparing
  before/after a performance fix.
- [ ] R7: Retention limits must prevent the telemetry history from becoming a
  new source of long-session lag.

## Acceptance Criteria

- [ ] AC 1: Performance rollups persist across restart and can be queried by
  recent time window.
- [ ] AC 2: Retention or compaction tests prove telemetry history remains
  bounded.
- [ ] AC 3: A dashboard view shows app health metrics separately from existing
  tool-call profiling.
- [ ] AC 4: A debug bundle endpoint or command exports redacted JSON suitable for
  attaching to a Nightshift report.
- [ ] AC 5: Redaction tests prove secrets, tokens, env values, tool arguments,
  request payloads, and large response payloads are absent from the bundle.
- [ ] AC 6: The bundle includes enough build/runtime metadata to detect stale
  binary problems, including git revision, modified flag if available, binary
  path, uptime, and config path.
- [ ] AC 7: `go test ./...`, `go vet ./...`, `go build ./...`, and
  `go test -race -count=1 -timeout 5m ./...` pass.

## Context

- User request: add telemetry specs so performance can be tracked over time and
  help with debugging later.
- Runtime telemetry foundation: `SPEC-BUG-134`
- Existing History > Performance view: `internal/web/ui/index.html`
- Existing profiling handlers: `internal/web/server.go`
- Capture/access-log storage: `internal/capture/store.go`,
  `internal/capture/access_log.go`
- Build metadata is visible in Wails startup logs but not exposed as a
  structured local diagnostic artifact.

## Out of Scope

- Uploading telemetry or bundles to an external service
- Full distributed tracing
- Retaining raw request/response payloads in performance history
- Replacing existing access-log profiling

## Code Pointers

- `internal/web/server.go` - new debug/performance endpoints
- `internal/capture/store.go` - persistent rollup storage and retention
- `internal/capture/access_log.go` - existing profiling aggregates
- `internal/web/ui/index.html` - dashboard performance surface and export action
- `cmd/shipyard/main.go` - config path/build metadata plumbing if needed
- `cmd/shipyard/desktop.go` - Wails desktop runtime metadata if needed
- `internal/web/server_test.go` - endpoint and redaction tests
- `internal/web/ui_layout_test.go` - UI source-level tests

## Gap Protocol

- Research-acceptable gaps:
  - Exact rollup interval and retention window
  - Whether bundle export belongs under `/api/performance/debug-bundle` or an
    existing Shipyard self-tool
  - Whether build metadata should come from `debug.ReadBuildInfo` or explicit
    ldflags
- Stop-immediately gaps:
  - The bundle can expose secrets, tokens, env values, request payloads, or tool
    arguments
  - Persistent telemetry grows without retention
  - The history collection causes measurable UI or API slowdown
- Max research subagents before stopping: 1
