---
id: SPEC-008
priority: 8
type: feature
status: draft
after: [SPEC-004]
created: 2026-04-06
---

# Latency Profiling

## Problem

Developers running multiple MCP servers have no aggregate view of tool performance. They can see individual request latencies in the traffic timeline, but can't answer "which tool is slowest?" or "what's my P95 across all tools?" without manually scanning rows.

## Goal

Add latency profiling: aggregate stats from existing traffic data, per-tool/server breakdown with percentiles, time-range filtering, and color-coded performance indicators.

## Architecture

```
GET /api/profiling/summary?range=24h&server=
  → SQL aggregation over traffic table
  → Returns: total_calls, avg_latency, p95_latency, error_rate + deltas

GET /api/profiling/tools?range=24h&server=&sort=p95&order=desc
  → SQL GROUP BY method, server_name
  → Returns: per-tool stats with min/avg/p50/p95/max/error_rate
```

No new tables needed — all data comes from the existing `traffic` table using SQL aggregation.

## Key Changes

### 1. Store Methods (internal/capture/store.go)

```go
type ProfilingSummary struct {
  TotalCalls    int     `json:"total_calls"`
  AvgLatencyMs  float64 `json:"avg_latency_ms"`
  P95LatencyMs  float64 `json:"p95_latency_ms"`
  ErrorRate     float64 `json:"error_rate"`
  PrevTotalCalls   int     `json:"prev_total_calls"`
  PrevAvgLatencyMs float64 `json:"prev_avg_latency_ms"`
  PrevErrorRate    float64 `json:"prev_error_rate"`
}

type ToolProfile struct {
  Tool       string  `json:"tool"`
  Server     string  `json:"server"`
  Calls      int     `json:"calls"`
  MinMs      float64 `json:"min_ms"`
  AvgMs      float64 `json:"avg_ms"`
  P50Ms      float64 `json:"p50_ms"`
  P95Ms      float64 `json:"p95_ms"`
  MaxMs      float64 `json:"max_ms"`
  ErrorRate  float64 `json:"error_rate"`
}

func (s *Store) ProfilingSummary(rangeStr, server string) (*ProfilingSummary, error)
func (s *Store) ProfilingByTool(rangeStr, server, sortBy, order string) ([]ToolProfile, error)
```

**Time ranges:** Parse `range` parameter into SQL time filter:
- `1h` → `ts > datetime('now', '-1 hour')`
- `24h` → `ts > datetime('now', '-1 day')`
- `7d` → `ts > datetime('now', '-7 days')`
- `30d` → `ts > datetime('now', '-30 days')`

**Percentile calculation:** SQLite doesn't have native percentile functions. Use `ORDER BY latency_ms` with `LIMIT 1 OFFSET (count * 0.5)` for P50 and `OFFSET (count * 0.95)` for P95. Alternatively, fetch all latency values for a tool and compute in Go.

**Delta calculation:** Run the same query for the previous period (e.g., if range is 24h, also query 48h-24h ago) to compute deltas.

**Error rate:** `COUNT(CASE WHEN status = 'error' THEN 1 END) / COUNT(*)` — uses the existing `status` column.

### 2. HTTP Endpoints (internal/web/server.go)

```
GET /api/profiling/summary  → handleProfilingSummary
GET /api/profiling/tools    → handleProfilingTools
```

Query params: `range` (default: `24h`), `server` (default: all), `sort` (default: `p95`), `order` (default: `desc`).

### 3. UI (internal/web/ui/index.html)

Add Performance sub-view under History tab (hash route: `#/history/performance`):
- Sub-nav: `Requests | Sessions | Performance` (Performance active)
- Action bar: Time Range dropdown (1h, 24h, 7d, 30d), Server filter dropdown
- Stats cards row: Total Calls, Avg Latency, P95 Latency, Error Rate — each with delta and trend arrow
- Color legend: green dot "< 100ms", yellow dot "100–500ms", red dot "> 500ms"
- Latency table: Tool, Server, Calls, Min, Avg, P50, P95, Max, Err% — sortable by clicking column headers
- P95 column highlighted as active sort with arrow-down icon
- Empty state: bar-chart icon + "No traffic data yet"

**Color coding function:**
```javascript
function latencyColor(ms) {
  if (ms < 100) return 'var(--success-fg)';
  if (ms < 500) return 'var(--warning-fg)';
  return 'var(--danger-fg)';
}
```

## Acceptance Criteria

- [ ] AC-1: `GET /api/profiling/summary` returns aggregate stats for the specified time range
- [ ] AC-2: Summary includes deltas from the previous equivalent period
- [ ] AC-3: `GET /api/profiling/tools` returns per-tool stats with min/avg/P50/P95/max
- [ ] AC-4: Tool stats are sortable by any numeric column
- [ ] AC-5: Server filter limits stats to traffic from a specific server
- [ ] AC-6: Latency values in the UI use semantic colors (green/yellow/red)
- [ ] AC-7: Stats cards show trend arrows (up/down) alongside deltas
- [ ] AC-8: Color legend is visible below stats cards
- [ ] AC-9: Empty state shown when no traffic exists in the selected range
- [ ] AC-10: All tests pass (`go test ./...`)

## Out of Scope

- Sparklines or time-series charts (numbers-only for v1)
- Custom latency threshold configuration (hardcoded 100ms/500ms)
- Per-request latency breakdown within a tool call
- Exporting profiling data

## Notes for Implementation

- All data comes from the existing `traffic` table — no schema changes needed.
- Filter only `direction = 'response'` rows for latency aggregation (requests don't have latency).
- The `latency_ms` column is already populated by `InsertTraffic` in store.go.
- For P50/P95 with few data points, handle edge cases (0 rows → null, 1 row → that value).
- The delta calculation queries the previous period; if no previous data exists, return null deltas.
- Use `DS.toast()` for error feedback if API calls fail.
- Sort arrows: only the active sort column gets `accent-fg` color + arrow icon; others stay `text-muted`.

## Target Files

- `internal/capture/store.go` — ProfilingSummary, ProfilingByTool methods
- `internal/capture/store_test.go` — profiling query tests (seed traffic data, verify aggregates)
- `internal/web/server.go` — 2 new handlers
- `internal/web/server_test.go` — handler tests
- `internal/web/ui/index.html` — Performance sub-view UI
