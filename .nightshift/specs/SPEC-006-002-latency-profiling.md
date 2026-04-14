---
id: SPEC-006-002
template_version: 2
priority: 2
layer: 2
type: feature
status: done
parent: SPEC-006
after: [SPEC-004]
nfrs: [SPEC-NFR-001]
prior_attempts: []
created: 2026-04-14
---

# Latency Profiling

## Problem

Developers using Shipyard to debug MCP servers have no visibility into performance
patterns. Individual request latencies are visible in the traffic timeline, but there
is no aggregate view showing which tools are slow, what the P95 latency is, or how
performance trends over time. Without this, performance regressions go unnoticed until
they cause user-visible problems.

## Requirements

- [ ] R1: Summary stats cards showing total calls, average latency, P95 latency, and
  error rate for the selected time range, with delta from the prior equivalent period.
- [ ] R2: Per-tool latency table showing tool name, server, call count, min, avg, P50,
  P95, max latency, and error rate.
- [ ] R3: Latency values color-coded: green (<100ms), yellow (100-500ms), red (>500ms).
- [ ] R4: Time range filter with presets: last hour, 24h, 7d, 30d, and custom range.
- [ ] R5: Server filter: all servers or a specific server.
- [ ] R6: All stats computed from existing SQLite traffic history — no new data collection
  required.

## Acceptance Criteria

- [ ] AC 1: Summary cards display total calls, avg latency, P95 latency, and error rate
  for the selected time range.
- [ ] AC 2: Summary cards show delta values (e.g., "+12%", "-5ms") comparing current
  period to the prior equivalent period.
- [ ] AC 3: Per-tool table shows all tools with columns: tool, server, calls, min, avg,
  P50, P95, max, error rate — sorted by P95 descending by default.
- [ ] AC 4: Table sort is configurable by clicking column headers.
- [ ] AC 5: Latency cells use semantic colors: green for <100ms, yellow for 100-500ms,
  red for >500ms.
- [ ] AC 6: Selecting a time range (last hour / 24h / 7d / 30d / custom) updates all
  stats and the table.
- [ ] AC 7: Selecting a server filter narrows all data to that server's traffic.
- [ ] AC 8: `GET /api/profiling/summary?range=24h` returns aggregate stats computed from
  existing capture store data.
- [ ] AC 9: `GET /api/profiling/tools?range=24h&sort=p95&order=desc` returns per-tool
  breakdown.
- [ ] AC 10: `go test -race -count=1 -timeout 5m ./...` passes with zero race warnings.
- [ ] AC 11: `go vet ./...` passes clean.
- [ ] AC 12: `go build ./...` compiles without errors.

## API Endpoints

- `GET /api/profiling/summary` — aggregate stats (query: `?range=24h&server=`)
- `GET /api/profiling/tools` — per-tool latency breakdown (query: `?range=&server=&sort=p95&order=desc`)

## Context

### Target files

- `internal/profiling/stats.go` — new: query functions against capture store SQLite,
  percentile calculations (P50, P95), delta computation
- `internal/profiling/handler.go` — new: HTTP handlers for profiling API endpoints
- `internal/web/ui/index.html` — add Profiling tab with summary cards and latency table
- `internal/web/routes.go` — register profiling API routes

### Test files

- `internal/profiling/stats_test.go` — percentile calculation tests, time range filtering,
  delta computation
- `internal/profiling/handler_test.go` — HTTP handler tests with seeded traffic data
- `internal/web/ui_layout_test.go` — UI tab presence and structure

### Design reference

`UX-002-dashboard-design.pen` → "Phase 4 — Profiling" screen:
- Header with nav tabs (Profiling is a new tab)
- ProfilingActionBar: time range filter (dropdown), server filter (dropdown)
- ProfilingContent: row of summary stat cards + per-tool latency table with
  color-coded latency values

### Data source

All profiling data is computed from the existing `internal/capture/store.go` SQLite
database. The capture store already records request timestamps and latency for every
proxied call. Profiling queries aggregate this data — no new data collection is needed.

## Scenarios

1. Developer opens Profiling tab → sees summary cards for last 24h showing 142 total
   calls, 85ms avg latency, 320ms P95, 2.1% error rate → scrolls down to per-tool
   table sorted by P95 → spots "generate_code" tool at 1200ms P95 (red) while most
   tools are green.
2. Developer selects "Last Hour" time range → all cards and table update → sees only
   recent data → compares deltas to previous hour.
3. Developer filters by server "my-llm-server" → summary cards show only that server's
   stats → table shows only tools from that server.
4. Developer clicks the "Avg" column header → table re-sorts by average latency → clicks
   again → sorts ascending.
5. Developer selects "7d" range on a fresh install with no traffic → sees "No data" state
   with zero values in summary cards and empty table.

## Out of Scope

- Custom latency threshold configuration (hardcoded green/yellow/red bands)
- Latency export or sharing
- Historical trend charts (line graphs over time)
- Alerting on latency thresholds
- Per-request drill-down from the profiling table (use Traffic tab for that)

## Research Hints

- Files to study: `internal/capture/store.go` (SQLite schema and query patterns for
  traffic data), `internal/web/ui/index.html` (tab structure, summary card patterns
  if any exist)
- Patterns to look for: how existing queries compute aggregates from the captures table,
  column naming conventions, DS class names for cards and tables
- DevKB: DevKB/go.md, DevKB/javascript.md

## Gap Protocol

- Research-acceptable gaps: exact column names in capture store SQLite schema, existing
  DS card component patterns
- Stop-immediately gaps: capture store does not record latency (would invalidate R6),
  unclear percentile calculation requirements
- Max research subagents before stopping: 2

---

## Notes for the Agent

- **Vanilla JS only**: use `var` declarations, `.then()` callbacks — no `async/await`,
  no `let/const`. This matches the project convention in all existing UI code.
- **Reuse existing capture store queries**: the capture store already has traffic data
  with timestamps and latency. Write SQL queries against the existing schema rather than
  adding new tables.
- **New navigation tab**: Profiling is tab 6 in the main nav. Follow the existing tab
  pattern in `index.html`.
- **Percentile calculation**: P50 and P95 can be computed in Go from sorted slices or
  via SQL `NTILE` / ordered queries. Keep it simple — Go-side computation from a slice
  of latency values is fine for the expected data volumes.
- **Color coding**: apply DS classes to latency cells based on value thresholds. Use
  inline style or data attributes only if no DS class exists for semantic coloring.
- **Delta computation**: "prior equivalent period" means if range=24h, compare current
  24h to the previous 24h. If range=7d, compare current 7d to previous 7d.
- **Summary cards**: use the DS card component pattern. Each card shows a metric value,
  label, and delta indicator (up/down arrow with percentage or absolute change).
