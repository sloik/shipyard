package capture

import (
	"database/sql"
	"fmt"
	"strings"
	"time"
)

// AccessLogEntry records a single tool call attempt.
type AccessLogEntry struct {
	Timestamp  time.Time
	TokenName  string
	ServerName string
	ToolName   string
	Status     string // "ok" | "error" | "denied" | "timeout" | "rate_limited"
	LatencyMs  *int64
	ErrorMsg   string
	ArgsJSON   string
	LogLevel   string // "full" | "args_only" | "status_only" | "none"
}

// AccessLogFilter holds query parameters for GetAccessLog.
type AccessLogFilter struct {
	TokenName  string
	ServerName string
	ToolName   string
	Status     string
	From       time.Time // zero = no lower bound
	To         time.Time // zero = no upper bound
	Offset     int
	Limit      int // default 100 when 0
}

// AccessLogPage is the paginated response.
type AccessLogPage struct {
	Items      []AccessLogRow `json:"items"`
	TotalCount int64          `json:"total_count"`
}

// AccessLogRow is the DB-row shape returned to the API.
type AccessLogRow struct {
	ID         int64  `json:"id"`
	Timestamp  int64  `json:"timestamp"` // unix ms
	TokenName  string `json:"token_name"`
	ServerName string `json:"server_name"`
	ToolName   string `json:"tool_name"`
	Status     string `json:"status"`
	LatencyMs  *int64 `json:"latency_ms"`
	ErrorMsg   string `json:"error_msg,omitempty"`
	ArgsJSON   string `json:"args_json,omitempty"`
	LogLevel   string `json:"log_level"`
}

// AccessLogStats is the response for the stats endpoint.
type AccessLogStats struct {
	TotalCalls int64            `json:"total_calls"`
	ErrorRate  float64          `json:"error_rate"`
	TopTools   []ToolCallCount  `json:"top_tools"`
	PerToken   []TokenCallCount `json:"per_token"`
}

// ToolCallCount holds aggregated call counts per tool.
type ToolCallCount struct {
	ServerName string `json:"server_name"`
	ToolName   string `json:"tool_name"`
	Count      int64  `json:"count"`
}

// TokenCallCount holds aggregated call counts per token.
type TokenCallCount struct {
	TokenName  string  `json:"token_name"`
	Count      int64   `json:"count"`
	DeniedRate float64 `json:"denied_rate"`
}

// RecordAccess writes an access log entry synchronously.
// Callers that want non-blocking behaviour should call this in a goroutine.
func (s *Store) RecordAccess(entry AccessLogEntry) {
	logLevel := entry.LogLevel
	if logLevel == "" {
		logLevel = "full"
	}

	// "none" skips insert unless it's a security event
	if logLevel == "none" {
		if entry.Status != "denied" && entry.Status != "rate_limited" {
			return
		}
		// Security events are always logged even at log_level none
	}

	ts := entry.Timestamp
	if ts.IsZero() {
		ts = time.Now().UTC()
	}
	tsStr := ts.UTC().Format(time.RFC3339Nano)

	var argsJSON *string
	var errorMsg *string

	switch logLevel {
	case "full":
		if entry.ArgsJSON != "" {
			argsJSON = &entry.ArgsJSON
		}
		if entry.ErrorMsg != "" {
			errorMsg = &entry.ErrorMsg
		}
	case "args_only":
		if entry.ArgsJSON != "" {
			argsJSON = &entry.ArgsJSON
		}
		// no error_msg
	case "status_only":
		// no args, no error_msg
	case "none":
		// security event path: log full info for denied/rate_limited
		if entry.ArgsJSON != "" {
			argsJSON = &entry.ArgsJSON
		}
		if entry.ErrorMsg != "" {
			errorMsg = &entry.ErrorMsg
		}
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	_, err := s.db.Exec(
		`INSERT INTO access_log (ts, token_name, server_name, tool_name, status, latency_ms, error_msg, args_json, log_level)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		tsStr,
		entry.TokenName,
		entry.ServerName,
		entry.ToolName,
		entry.Status,
		entry.LatencyMs,
		errorMsg,
		argsJSON,
		logLevel,
	)
	if err != nil {
		// Non-fatal: log but don't crash
		_ = err
	}
}

// GetAccessLog returns a paginated list of access log entries matching the filter.
func (s *Store) GetAccessLog(filter AccessLogFilter) (*AccessLogPage, error) {
	limit := filter.Limit
	if limit == 0 {
		limit = 100
	}

	var conditions []string
	var args []interface{}

	if filter.TokenName != "" {
		conditions = append(conditions, "token_name = ?")
		args = append(args, filter.TokenName)
	}
	if filter.ServerName != "" {
		conditions = append(conditions, "server_name = ?")
		args = append(args, filter.ServerName)
	}
	if filter.ToolName != "" {
		conditions = append(conditions, "tool_name = ?")
		args = append(args, filter.ToolName)
	}
	if filter.Status != "" {
		conditions = append(conditions, "status = ?")
		args = append(args, filter.Status)
	}
	if !filter.From.IsZero() {
		conditions = append(conditions, "ts >= ?")
		args = append(args, filter.From.UTC().Format(time.RFC3339Nano))
	}
	if !filter.To.IsZero() {
		conditions = append(conditions, "ts <= ?")
		args = append(args, filter.To.UTC().Format(time.RFC3339Nano))
	}

	whereClause := ""
	if len(conditions) > 0 {
		whereClause = "WHERE " + strings.Join(conditions, " AND ")
	}

	// Count total
	var totalCount int64
	countQuery := fmt.Sprintf("SELECT COUNT(*) FROM access_log %s", whereClause)
	if err := s.db.QueryRow(countQuery, args...).Scan(&totalCount); err != nil {
		return nil, fmt.Errorf("count access_log: %w", err)
	}

	// Fetch rows
	rowsQuery := fmt.Sprintf(
		"SELECT id, ts, token_name, server_name, tool_name, status, latency_ms, error_msg, args_json, log_level FROM access_log %s ORDER BY id DESC LIMIT ? OFFSET ?",
		whereClause,
	)
	rowArgs := append(args, limit, filter.Offset)
	rows, err := s.db.Query(rowsQuery, rowArgs...)
	if err != nil {
		return nil, fmt.Errorf("query access_log: %w", err)
	}
	defer rows.Close()

	items := []AccessLogRow{}
	for rows.Next() {
		var row AccessLogRow
		var tsStr string
		var latencyMs sql.NullInt64
		var errorMsg sql.NullString
		var argsJSON sql.NullString

		if err := rows.Scan(
			&row.ID,
			&tsStr,
			&row.TokenName,
			&row.ServerName,
			&row.ToolName,
			&row.Status,
			&latencyMs,
			&errorMsg,
			&argsJSON,
			&row.LogLevel,
		); err != nil {
			return nil, fmt.Errorf("scan access_log row: %w", err)
		}

		// Parse timestamp to unix ms
		if t, err := time.Parse(time.RFC3339Nano, tsStr); err == nil {
			row.Timestamp = t.UnixMilli()
		}

		if latencyMs.Valid {
			v := latencyMs.Int64
			row.LatencyMs = &v
		}
		if errorMsg.Valid {
			row.ErrorMsg = errorMsg.String
		}
		if argsJSON.Valid {
			row.ArgsJSON = argsJSON.String
		}

		items = append(items, row)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate access_log rows: %w", err)
	}

	return &AccessLogPage{
		Items:      items,
		TotalCount: totalCount,
	}, nil
}

// GetAccessLogStats returns aggregate statistics for the access log.
func (s *Store) GetAccessLogStats() (*AccessLogStats, error) {
	stats := &AccessLogStats{
		TopTools: []ToolCallCount{},
		PerToken: []TokenCallCount{},
	}

	// Total calls
	if err := s.db.QueryRow("SELECT COUNT(*) FROM access_log").Scan(&stats.TotalCalls); err != nil {
		return nil, fmt.Errorf("count total calls: %w", err)
	}

	// Error rate
	if stats.TotalCalls > 0 {
		var badCount int64
		if err := s.db.QueryRow(
			"SELECT COUNT(*) FROM access_log WHERE status IN ('error','denied','rate_limited')",
		).Scan(&badCount); err != nil {
			return nil, fmt.Errorf("count bad calls: %w", err)
		}
		stats.ErrorRate = float64(badCount) / float64(stats.TotalCalls)
	}

	// Top tools
	toolRows, err := s.db.Query(
		`SELECT server_name, tool_name, COUNT(*) as cnt
		 FROM access_log
		 GROUP BY server_name, tool_name
		 ORDER BY cnt DESC
		 LIMIT 10`,
	)
	if err != nil {
		return nil, fmt.Errorf("query top tools: %w", err)
	}
	defer toolRows.Close()

	for toolRows.Next() {
		var tc ToolCallCount
		if err := toolRows.Scan(&tc.ServerName, &tc.ToolName, &tc.Count); err != nil {
			return nil, fmt.Errorf("scan top tools row: %w", err)
		}
		stats.TopTools = append(stats.TopTools, tc)
	}
	if err := toolRows.Err(); err != nil {
		return nil, fmt.Errorf("iterate top tools: %w", err)
	}

	// Per token
	tokenRows, err := s.db.Query(
		`SELECT token_name, COUNT(*) as cnt,
		        SUM(CASE WHEN status IN ('denied','rate_limited','error') THEN 1 ELSE 0 END) as bad
		 FROM access_log
		 GROUP BY token_name`,
	)
	if err != nil {
		return nil, fmt.Errorf("query per token: %w", err)
	}
	defer tokenRows.Close()

	for tokenRows.Next() {
		var tc TokenCallCount
		var bad int64
		if err := tokenRows.Scan(&tc.TokenName, &tc.Count, &bad); err != nil {
			return nil, fmt.Errorf("scan per token row: %w", err)
		}
		if tc.Count > 0 {
			tc.DeniedRate = float64(bad) / float64(tc.Count)
		}
		stats.PerToken = append(stats.PerToken, tc)
	}
	if err := tokenRows.Err(); err != nil {
		return nil, fmt.Errorf("iterate per token rows: %w", err)
	}

	return stats, nil
}
