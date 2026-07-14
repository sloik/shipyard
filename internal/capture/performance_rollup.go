package capture

import (
	"database/sql"
	"fmt"
	"time"
)

const (
	PerformanceRollupBucket       = time.Minute
	PerformanceRollupRetentionMax = 2016
)

type PerformanceRollupSample struct {
	Timestamp          time.Time
	HTTPDurationMs     int64
	RPCDurationMs      int64
	FrontendDurationMs int64
	ActiveDOMRows      int64
	Goroutines         int64
	HeapAllocBytes     int64
	DBFileSizeBytes    int64
	TrafficRows        int64
	SchemaSnapshotRows int64
	AccessLogRows      int64
}

type PerformanceRollup struct {
	BucketStart        time.Time `json:"bucket_start"`
	BucketSeconds      int64     `json:"bucket_seconds"`
	HTTPCount          int64     `json:"http_count"`
	HTTPAvgMs          float64   `json:"http_avg_ms"`
	HTTPMaxMs          int64     `json:"http_max_ms"`
	RPCCount           int64     `json:"rpc_count"`
	RPCAvgMs           float64   `json:"rpc_avg_ms"`
	RPCMaxMs           int64     `json:"rpc_max_ms"`
	FrontendCount      int64     `json:"frontend_count"`
	FrontendAvgMs      float64   `json:"frontend_avg_ms"`
	FrontendMaxMs      int64     `json:"frontend_max_ms"`
	ActiveDOMRows      int64     `json:"active_dom_rows"`
	Goroutines         int64     `json:"goroutines"`
	HeapAllocBytes     int64     `json:"heap_alloc_bytes"`
	DBFileSizeBytes    int64     `json:"db_file_size_bytes"`
	TrafficRows        int64     `json:"traffic_rows"`
	SchemaSnapshotRows int64     `json:"schema_snapshot_rows"`
	AccessLogRows      int64     `json:"access_log_rows"`
	UpdatedAt          time.Time `json:"updated_at"`
}

func (s *Store) UpsertPerformanceRollup(sample PerformanceRollupSample) error {
	if sample.Timestamp.IsZero() {
		sample.Timestamp = time.Now().UTC()
	}
	bucket := sample.Timestamp.UTC().Truncate(PerformanceRollupBucket)
	bucketStr := bucket.Format(time.RFC3339Nano)
	updatedAt := time.Now().UTC().Format(time.RFC3339Nano)

	httpCount, httpTotal, httpMax := metricParts(sample.HTTPDurationMs)
	rpcCount, rpcTotal, rpcMax := metricParts(sample.RPCDurationMs)
	frontendCount, frontendTotal, frontendMax := metricParts(sample.FrontendDurationMs)

	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(`
		INSERT INTO performance_rollups (
			bucket_start, bucket_seconds,
			http_count, http_total_ms, http_max_ms,
			rpc_count, rpc_total_ms, rpc_max_ms,
			frontend_count, frontend_total_ms, frontend_max_ms,
			active_dom_rows, goroutines, heap_alloc_bytes,
			db_file_size_bytes, traffic_rows, schema_snapshot_rows, access_log_rows,
			updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(bucket_start) DO UPDATE SET
			http_count = http_count + excluded.http_count,
			http_total_ms = http_total_ms + excluded.http_total_ms,
			http_max_ms = max(http_max_ms, excluded.http_max_ms),
			rpc_count = rpc_count + excluded.rpc_count,
			rpc_total_ms = rpc_total_ms + excluded.rpc_total_ms,
			rpc_max_ms = max(rpc_max_ms, excluded.rpc_max_ms),
			frontend_count = frontend_count + excluded.frontend_count,
			frontend_total_ms = frontend_total_ms + excluded.frontend_total_ms,
			frontend_max_ms = max(frontend_max_ms, excluded.frontend_max_ms),
			active_dom_rows = max(active_dom_rows, excluded.active_dom_rows),
			goroutines = excluded.goroutines,
			heap_alloc_bytes = excluded.heap_alloc_bytes,
			db_file_size_bytes = excluded.db_file_size_bytes,
			traffic_rows = excluded.traffic_rows,
			schema_snapshot_rows = excluded.schema_snapshot_rows,
			access_log_rows = excluded.access_log_rows,
			updated_at = excluded.updated_at
	`, bucketStr, int64(PerformanceRollupBucket/time.Second),
		httpCount, httpTotal, httpMax,
		rpcCount, rpcTotal, rpcMax,
		frontendCount, frontendTotal, frontendMax,
		sample.ActiveDOMRows, sample.Goroutines, sample.HeapAllocBytes,
		sample.DBFileSizeBytes, sample.TrafficRows, sample.SchemaSnapshotRows, sample.AccessLogRows,
		updatedAt)
	if err != nil {
		return fmt.Errorf("upsert performance rollup: %w", err)
	}
	return s.enforcePerformanceRollupRetentionLocked(PerformanceRollupRetentionMax)
}

func metricParts(durationMs int64) (count, total, max int64) {
	if durationMs <= 0 {
		return 0, 0, 0
	}
	return 1, durationMs, durationMs
}

func (s *Store) ListPerformanceRollups(since time.Time, limit int) ([]PerformanceRollup, error) {
	if limit <= 0 || limit > PerformanceRollupRetentionMax {
		limit = PerformanceRollupRetentionMax
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	where := ""
	args := []interface{}{}
	if !since.IsZero() {
		where = "WHERE bucket_start >= ?"
		args = append(args, since.UTC().Format(time.RFC3339Nano))
	}
	args = append(args, limit)

	rows, err := s.db.Query(`
		SELECT bucket_start, bucket_seconds,
			http_count, http_total_ms, http_max_ms,
			rpc_count, rpc_total_ms, rpc_max_ms,
			frontend_count, frontend_total_ms, frontend_max_ms,
			active_dom_rows, goroutines, heap_alloc_bytes,
			db_file_size_bytes, traffic_rows, schema_snapshot_rows, access_log_rows,
			updated_at
		FROM performance_rollups `+where+`
		ORDER BY bucket_start DESC
		LIMIT ?`, args...)
	if err != nil {
		return nil, fmt.Errorf("query performance rollups: %w", err)
	}
	defer rows.Close()

	out := []PerformanceRollup{}
	for rows.Next() {
		var r PerformanceRollup
		var bucketStr, updatedStr string
		var httpTotal, rpcTotal, frontendTotal int64
		if err := rows.Scan(
			&bucketStr, &r.BucketSeconds,
			&r.HTTPCount, &httpTotal, &r.HTTPMaxMs,
			&r.RPCCount, &rpcTotal, &r.RPCMaxMs,
			&r.FrontendCount, &frontendTotal, &r.FrontendMaxMs,
			&r.ActiveDOMRows, &r.Goroutines, &r.HeapAllocBytes,
			&r.DBFileSizeBytes, &r.TrafficRows, &r.SchemaSnapshotRows, &r.AccessLogRows,
			&updatedStr,
		); err != nil {
			return nil, fmt.Errorf("scan performance rollup: %w", err)
		}
		r.BucketStart, _ = time.Parse(time.RFC3339Nano, bucketStr)
		r.UpdatedAt, _ = time.Parse(time.RFC3339Nano, updatedStr)
		r.HTTPAvgMs = avg(httpTotal, r.HTTPCount)
		r.RPCAvgMs = avg(rpcTotal, r.RPCCount)
		r.FrontendAvgMs = avg(frontendTotal, r.FrontendCount)
		out = append(out, r)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate performance rollups: %w", err)
	}

	for i, j := 0, len(out)-1; i < j; i, j = i+1, j-1 {
		out[i], out[j] = out[j], out[i]
	}
	return out, nil
}

func avg(total, count int64) float64 {
	if count == 0 {
		return 0
	}
	return float64(total) / float64(count)
}

func (s *Store) EnforcePerformanceRollupRetention(limit int) error {
	if limit <= 0 {
		limit = PerformanceRollupRetentionMax
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.enforcePerformanceRollupRetentionLocked(limit)
}

func (s *Store) enforcePerformanceRollupRetentionLocked(limit int) error {
	_, err := s.db.Exec(`
		DELETE FROM performance_rollups
		WHERE bucket_start NOT IN (
			SELECT bucket_start FROM performance_rollups
			ORDER BY bucket_start DESC
			LIMIT ?
		)`, limit)
	if err != nil {
		return fmt.Errorf("enforce performance rollup retention: %w", err)
	}
	return nil
}

func (s *Store) PerformanceRollupCount() (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var count sql.NullInt64
	if err := s.db.QueryRow("SELECT COUNT(*) FROM performance_rollups").Scan(&count); err != nil {
		return 0, fmt.Errorf("count performance_rollups: %w", err)
	}
	return count.Int64, nil
}
