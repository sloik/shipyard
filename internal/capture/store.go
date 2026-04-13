package capture

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	_ "github.com/ncruces/go-sqlite3/driver"
	_ "github.com/ncruces/go-sqlite3/embed"
)

const currentSchemaVersion = 2

var openSQLiteDB = func(path string) (*sql.DB, error) {
	return sql.Open("sqlite3", path)
}

var openJSONLFile = func(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
}

var queryTrafficRows = func(db *sql.DB, query string, args ...interface{}) (*sql.Rows, error) {
	return db.Query(query, args...)
}

// columnExists checks whether a column exists on the given table using PRAGMA table_info.
func (s *Store) columnExists(table, column string) (bool, error) {
	rows, err := s.db.Query(fmt.Sprintf("PRAGMA table_info(%s)", table))
	if err != nil {
		return false, fmt.Errorf("pragma table_info(%s): %w", table, err)
	}
	defer rows.Close()

	for rows.Next() {
		var cid int
		var name, ctype string
		var notnull int
		var dfltValue sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dfltValue, &pk); err != nil {
			return false, fmt.Errorf("scan table_info: %w", err)
		}
		if name == column {
			return true, nil
		}
	}
	return false, nil
}

// migrate runs sequential schema migrations based on PRAGMA user_version.
// For fresh databases (no tables yet), migration is a no-op — CREATE TABLE
// IF NOT EXISTS in NewStore handles initial schema creation.
func (s *Store) migrate() error {
	var version int
	err := s.db.QueryRow("PRAGMA user_version").Scan(&version)
	if err != nil {
		return fmt.Errorf("read user_version: %w", err)
	}

	// On a fresh DB, traffic table won't exist yet. Skip migration —
	// the CREATE TABLE IF NOT EXISTS block in NewStore will create everything.
	trafficExists, err := s.tableExists("traffic")
	if err != nil {
		return err
	}
	if !trafficExists {
		return nil
	}

	if version < 1 {
		if err := s.migrateToV1(); err != nil {
			return fmt.Errorf("migrate to v1: %w", err)
		}
	}

	if version < 2 {
		if err := s.migrateToV2(); err != nil {
			return fmt.Errorf("migrate to v2: %w", err)
		}
	}

	_, err = s.db.Exec(fmt.Sprintf("PRAGMA user_version = %d", currentSchemaVersion))
	return err
}

// tableExists checks whether a table exists in the database.
func (s *Store) tableExists(table string) (bool, error) {
	var count int
	err := s.db.QueryRow(
		"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", table,
	).Scan(&count)
	if err != nil {
		return false, fmt.Errorf("check table %s: %w", table, err)
	}
	return count > 0, nil
}

// migrateToV1 upgrades a v0 database to v1 by adding session_id column
// and creating sessions, schema_snapshots, and schema_changes tables.
func (s *Store) migrateToV1() error {
	// Add session_id column to traffic if it doesn't exist
	exists, err := s.columnExists("traffic", "session_id")
	if err != nil {
		return fmt.Errorf("check session_id column: %w", err)
	}
	if !exists {
		_, err = s.db.Exec("ALTER TABLE traffic ADD COLUMN session_id INTEGER")
		if err != nil {
			return fmt.Errorf("add session_id column: %w", err)
		}
	}

	// Create new tables
	_, err = s.db.Exec(`
		CREATE TABLE IF NOT EXISTS sessions (
			id            INTEGER PRIMARY KEY AUTOINCREMENT,
			name          TEXT NOT NULL DEFAULT '',
			server        TEXT NOT NULL DEFAULT '',
			status        TEXT NOT NULL DEFAULT 'recording',
			started_at    TEXT NOT NULL,
			stopped_at    TEXT,
			duration_ms   INTEGER,
			request_count INTEGER NOT NULL DEFAULT 0,
			size_bytes    INTEGER NOT NULL DEFAULT 0
		);
		CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
		CREATE INDEX IF NOT EXISTS idx_sessions_server ON sessions(server);

		CREATE TABLE IF NOT EXISTS schema_snapshots (
			id          INTEGER PRIMARY KEY AUTOINCREMENT,
			server_name TEXT NOT NULL,
			snapshot    TEXT NOT NULL,
			captured_at TEXT NOT NULL,
			UNIQUE(server_name, captured_at)
		);

		CREATE TABLE IF NOT EXISTS schema_changes (
			id              INTEGER PRIMARY KEY AUTOINCREMENT,
			server_name     TEXT NOT NULL,
			detected_at     TEXT NOT NULL,
			tools_added     INTEGER NOT NULL DEFAULT 0,
			tools_removed   INTEGER NOT NULL DEFAULT 0,
			tools_modified  INTEGER NOT NULL DEFAULT 0,
			before_snapshot INTEGER REFERENCES schema_snapshots(id),
			after_snapshot  INTEGER REFERENCES schema_snapshots(id),
			acknowledged    INTEGER NOT NULL DEFAULT 0,
			diff_json       TEXT NOT NULL DEFAULT '{}'
		);
		CREATE INDEX IF NOT EXISTS idx_schema_changes_server ON schema_changes(server_name);
		CREATE INDEX IF NOT EXISTS idx_schema_changes_ack ON schema_changes(acknowledged);

		CREATE INDEX IF NOT EXISTS idx_traffic_session ON traffic(session_id);
	`)
	if err != nil {
		return fmt.Errorf("create v1 tables: %w", err)
	}

	return nil
}

// migrateToV2 adds the access_log table and its indexes.
func (s *Store) migrateToV2() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS access_log (
			id          INTEGER PRIMARY KEY AUTOINCREMENT,
			ts          TEXT NOT NULL,
			token_name  TEXT NOT NULL DEFAULT '',
			server_name TEXT NOT NULL,
			tool_name   TEXT NOT NULL,
			status      TEXT NOT NULL,
			latency_ms  INTEGER,
			error_msg   TEXT,
			args_json   TEXT,
			log_level   TEXT NOT NULL DEFAULT 'full'
		);
		CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts);
		CREATE INDEX IF NOT EXISTS idx_access_token ON access_log(token_name);
		CREATE INDEX IF NOT EXISTS idx_access_tool ON access_log(tool_name);
		CREATE INDEX IF NOT EXISTS idx_access_status ON access_log(status);
	`)
	if err != nil {
		return fmt.Errorf("create access_log table: %w", err)
	}
	return nil
}

// Direction constants
const (
	DirectionClientToServer = "client→server"
	DirectionServerToClient = "server→client"
)

// TrafficEntry represents a captured JSON-RPC message.
type TrafficEntry struct {
	Timestamp  time.Time
	Direction  string
	ServerName string
	Method     string
	MessageID  string
	Payload    string
	Status     string
	IsResponse bool
}

// TrafficEvent is the JSON shape sent to the web UI.
type TrafficEvent struct {
	ID             int64  `json:"id"`
	Timestamp      int64  `json:"timestamp"`
	Direction      string `json:"direction"`
	ServerName     string `json:"server_name"`
	Method         string `json:"method"`
	MessageID      string `json:"message_id"`
	Status         string `json:"status"`
	LatencyMs      *int64 `json:"latency_ms"`
	Payload        string `json:"payload"`
	MatchedPayload string `json:"matched_payload,omitempty"`
	MatchedID      int64  `json:"matched_id,omitempty"`
}

// TrafficPage represents a paginated result of traffic events.
type TrafficPage struct {
	Items      []TrafficEvent `json:"items"`
	TotalCount int            `json:"total_count"`
	Page       int            `json:"page"`
	PageSize   int            `json:"page_size"`
}

// Store handles traffic persistence in SQLite and JSONL.
type Store struct {
	db      *sql.DB
	jsonlF  *os.File
	mu      sync.Mutex
	pending map[string]pendingRequest // keyed by message_id
}

type pendingRequest struct {
	rowID     int64
	timestamp time.Time
	method    string
}

// NewStore creates a new capture store backed by SQLite and a JSONL file.
func NewStore(dbPath, jsonlPath string) (*Store, error) {
	db, err := openSQLiteDB(dbPath)
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}

	// Run migrations for existing databases
	// We need a temporary Store to call migrate() on
	tempStore := &Store{db: db}
	if err := tempStore.migrate(); err != nil {
		db.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}

	// Create schema (safety net for fresh databases)
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS traffic (
			id          INTEGER PRIMARY KEY AUTOINCREMENT,
			ts          TEXT NOT NULL,
			direction   TEXT NOT NULL,
			server_name TEXT NOT NULL,
			method      TEXT NOT NULL DEFAULT '',
			message_id  TEXT NOT NULL DEFAULT '',
			payload     TEXT NOT NULL,
			status      TEXT NOT NULL DEFAULT 'ok',
			latency_ms  INTEGER,
			matched_id  INTEGER,
			session_id  INTEGER REFERENCES sessions(id)
		);
		CREATE INDEX IF NOT EXISTS idx_traffic_ts ON traffic(ts);
		CREATE INDEX IF NOT EXISTS idx_traffic_method ON traffic(method);
		CREATE INDEX IF NOT EXISTS idx_traffic_server ON traffic(server_name);
		CREATE INDEX IF NOT EXISTS idx_traffic_message_id ON traffic(message_id);
		CREATE INDEX IF NOT EXISTS idx_traffic_session ON traffic(session_id);

		CREATE TABLE IF NOT EXISTS sessions (
			id            INTEGER PRIMARY KEY AUTOINCREMENT,
			name          TEXT NOT NULL DEFAULT '',
			server        TEXT NOT NULL DEFAULT '',
			status        TEXT NOT NULL DEFAULT 'recording',
			started_at    TEXT NOT NULL,
			stopped_at    TEXT,
			duration_ms   INTEGER,
			request_count INTEGER NOT NULL DEFAULT 0,
			size_bytes    INTEGER NOT NULL DEFAULT 0
		);
		CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
		CREATE INDEX IF NOT EXISTS idx_sessions_server ON sessions(server);

		CREATE TABLE IF NOT EXISTS schema_snapshots (
			id          INTEGER PRIMARY KEY AUTOINCREMENT,
			server_name TEXT NOT NULL,
			snapshot    TEXT NOT NULL,
			captured_at TEXT NOT NULL,
			UNIQUE(server_name, captured_at)
		);

		CREATE TABLE IF NOT EXISTS schema_changes (
			id              INTEGER PRIMARY KEY AUTOINCREMENT,
			server_name     TEXT NOT NULL,
			detected_at     TEXT NOT NULL,
			tools_added     INTEGER NOT NULL DEFAULT 0,
			tools_removed   INTEGER NOT NULL DEFAULT 0,
			tools_modified  INTEGER NOT NULL DEFAULT 0,
			before_snapshot INTEGER REFERENCES schema_snapshots(id),
			after_snapshot  INTEGER REFERENCES schema_snapshots(id),
			acknowledged    INTEGER NOT NULL DEFAULT 0,
			diff_json       TEXT NOT NULL DEFAULT '{}'
		);
		CREATE INDEX IF NOT EXISTS idx_schema_changes_server ON schema_changes(server_name);
		CREATE INDEX IF NOT EXISTS idx_schema_changes_ack ON schema_changes(acknowledged);

		CREATE TABLE IF NOT EXISTS access_log (
			id          INTEGER PRIMARY KEY AUTOINCREMENT,
			ts          TEXT NOT NULL,
			token_name  TEXT NOT NULL DEFAULT '',
			server_name TEXT NOT NULL,
			tool_name   TEXT NOT NULL,
			status      TEXT NOT NULL,
			latency_ms  INTEGER,
			error_msg   TEXT,
			args_json   TEXT,
			log_level   TEXT NOT NULL DEFAULT 'full'
		);
		CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts);
		CREATE INDEX IF NOT EXISTS idx_access_token ON access_log(token_name);
		CREATE INDEX IF NOT EXISTS idx_access_tool ON access_log(tool_name);
		CREATE INDEX IF NOT EXISTS idx_access_status ON access_log(status);
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("create schema: %w", err)
	}

	// Ensure user_version is set for fresh databases
	_, _ = db.Exec(fmt.Sprintf("PRAGMA user_version = %d", currentSchemaVersion))

	// Enable WAL mode for better concurrent read/write
	_, _ = db.Exec("PRAGMA journal_mode=WAL")

	jsonlF, err := openJSONLFile(jsonlPath)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("open jsonl: %w", err)
	}

	return &Store{
		db:      db,
		jsonlF:  jsonlF,
		pending: make(map[string]pendingRequest),
	}, nil
}

// Insert stores a traffic entry and returns the row ID and optional latency.
func (s *Store) Insert(entry *TrafficEntry) (int64, *int64) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var latencyMs *int64

	// If this is a response, try to correlate with a pending request
	if entry.IsResponse && entry.MessageID != "" {
		if req, ok := s.pending[entry.MessageID]; ok {
			lat := entry.Timestamp.Sub(req.timestamp).Milliseconds()
			latencyMs = &lat
			// Fill in method from the request if response doesn't have one
			if entry.Method == "" {
				entry.Method = req.method
			}
			delete(s.pending, entry.MessageID)

			// Update the original request row with latency and matched_id (will set after insert)
			defer func(reqID int64, lat int64) {
				// We'll update both rows after we get the response row ID
			}(req.rowID, lat)
		}
	}

	// Insert into SQLite
	res, err := s.db.Exec(
		`INSERT INTO traffic (ts, direction, server_name, method, message_id, payload, status, latency_ms)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		entry.Timestamp.UTC().Format(time.RFC3339Nano),
		entry.Direction,
		entry.ServerName,
		entry.Method,
		entry.MessageID,
		entry.Payload,
		entry.Status,
		latencyMs,
	)
	if err != nil {
		slog.Error("failed to insert traffic", "error", err)
		return 0, nil
	}

	rowID, _ := res.LastInsertId()

	// Cross-link request and response
	if entry.IsResponse && entry.MessageID != "" && latencyMs != nil {
		// Find the request row and update matched_id
		var reqID int64
		err := s.db.QueryRow(
			`SELECT id FROM traffic WHERE message_id = ? AND direction = ? AND id != ? ORDER BY id DESC LIMIT 1`,
			entry.MessageID, DirectionClientToServer, rowID,
		).Scan(&reqID)
		if err == nil {
			s.db.Exec(`UPDATE traffic SET matched_id = ?, latency_ms = ? WHERE id = ?`, rowID, latencyMs, reqID)
			s.db.Exec(`UPDATE traffic SET matched_id = ? WHERE id = ?`, reqID, rowID)
		}
	}

	// If this is a request, track it for correlation
	if !entry.IsResponse && entry.MessageID != "" {
		s.pending[entry.MessageID] = pendingRequest{
			rowID:     rowID,
			timestamp: entry.Timestamp,
			method:    entry.Method,
		}
	}

	// Append to JSONL
	jsonLine, _ := json.Marshal(map[string]interface{}{
		"id":          rowID,
		"ts":          entry.Timestamp.UTC().Format(time.RFC3339Nano),
		"direction":   entry.Direction,
		"server_name": entry.ServerName,
		"method":      entry.Method,
		"message_id":  entry.MessageID,
		"payload":     entry.Payload,
		"status":      entry.Status,
		"latency_ms":  latencyMs,
	})
	s.jsonlF.Write(jsonLine)
	s.jsonlF.Write([]byte("\n"))

	return rowID, latencyMs
}

// QueryFilter defines all filter options for querying traffic entries.
type QueryFilter struct {
	Page      int
	PageSize  int
	Server    string
	Method    string
	Direction string
	Search    string  // free-text search in payload (SQL LIKE)
	FromTs    *int64  // unix milliseconds, inclusive
	ToTs      *int64  // unix milliseconds, inclusive
}

// QueryFiltered retrieves paginated traffic entries with extended filters.
func (s *Store) QueryFiltered(f QueryFilter) (*TrafficPage, error) {
	where := "WHERE 1=1"
	args := []interface{}{}

	if f.Server != "" {
		where += " AND server_name = ?"
		args = append(args, f.Server)
	}
	if f.Method != "" {
		where += " AND method = ?"
		args = append(args, f.Method)
	}
	if f.Direction != "" {
		where += " AND direction = ?"
		args = append(args, f.Direction)
	}
	if f.Search != "" {
		where += " AND payload LIKE ?"
		args = append(args, "%"+f.Search+"%")
	}
	if f.FromTs != nil {
		fromTime := time.UnixMilli(*f.FromTs).UTC().Format(time.RFC3339Nano)
		where += " AND ts >= ?"
		args = append(args, fromTime)
	}
	if f.ToTs != nil {
		toTime := time.UnixMilli(*f.ToTs).UTC().Format(time.RFC3339Nano)
		where += " AND ts <= ?"
		args = append(args, toTime)
	}

	// Count total
	var total int
	countArgs := make([]interface{}, len(args))
	copy(countArgs, args)
	err := s.db.QueryRow("SELECT COUNT(*) FROM traffic "+where, countArgs...).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("count: %w", err)
	}

	// Fetch page
	page := f.Page
	pageSize := f.PageSize
	offset := (page - 1) * pageSize
	queryArgs := append(args, pageSize, offset)
	rows, err := queryTrafficRows(
		s.db,
		"SELECT id, ts, direction, server_name, method, message_id, payload, status, latency_ms, matched_id FROM traffic "+
			where+" ORDER BY id DESC LIMIT ? OFFSET ?",
		queryArgs...,
	)
	if err != nil {
		return nil, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	var items []TrafficEvent
	for rows.Next() {
		var (
			evt       TrafficEvent
			tsStr     string
			latency   sql.NullInt64
			matchedID sql.NullInt64
		)
		if err := rows.Scan(&evt.ID, &tsStr, &evt.Direction, &evt.ServerName, &evt.Method,
			&evt.MessageID, &evt.Payload, &evt.Status, &latency, &matchedID); err != nil {
			return nil, fmt.Errorf("scan: %w", err)
		}
		t, _ := time.Parse(time.RFC3339Nano, tsStr)
		evt.Timestamp = t.UnixMilli()
		if latency.Valid {
			evt.LatencyMs = &latency.Int64
		}
		if matchedID.Valid {
			evt.MatchedID = matchedID.Int64
		}
		items = append(items, evt)
	}

	return &TrafficPage{
		Items:      items,
		TotalCount: total,
		Page:       page,
		PageSize:   pageSize,
	}, nil
}

// Query retrieves paginated traffic entries, optionally filtered.
// Deprecated: Use QueryFiltered for new code.
func (s *Store) Query(page, pageSize int, serverFilter, methodFilter string) (*TrafficPage, error) {
	where := "WHERE 1=1"
	args := []interface{}{}

	if serverFilter != "" {
		where += " AND server_name = ?"
		args = append(args, serverFilter)
	}
	if methodFilter != "" {
		where += " AND method = ?"
		args = append(args, methodFilter)
	}

	// Count total
	var total int
	countArgs := make([]interface{}, len(args))
	copy(countArgs, args)
	err := s.db.QueryRow("SELECT COUNT(*) FROM traffic "+where, countArgs...).Scan(&total)
	if err != nil {
		return nil, fmt.Errorf("count: %w", err)
	}

	// Fetch page
	offset := (page - 1) * pageSize
	queryArgs := append(args, pageSize, offset)
	rows, err := queryTrafficRows(
		s.db,
		"SELECT id, ts, direction, server_name, method, message_id, payload, status, latency_ms, matched_id FROM traffic "+
			where+" ORDER BY id DESC LIMIT ? OFFSET ?",
		queryArgs...,
	)
	if err != nil {
		return nil, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	var items []TrafficEvent
	for rows.Next() {
		var (
			evt       TrafficEvent
			tsStr     string
			latency   sql.NullInt64
			matchedID sql.NullInt64
		)
		if err := rows.Scan(&evt.ID, &tsStr, &evt.Direction, &evt.ServerName, &evt.Method,
			&evt.MessageID, &evt.Payload, &evt.Status, &latency, &matchedID); err != nil {
			return nil, fmt.Errorf("scan: %w", err)
		}
		t, _ := time.Parse(time.RFC3339Nano, tsStr)
		evt.Timestamp = t.UnixMilli()
		if latency.Valid {
			evt.LatencyMs = &latency.Int64
		}
		if matchedID.Valid {
			evt.MatchedID = matchedID.Int64
		}
		items = append(items, evt)
	}

	return &TrafficPage{
		Items:      items,
		TotalCount: total,
		Page:       page,
		PageSize:   pageSize,
	}, nil
}

// GetByID retrieves a single traffic entry by ID, including its matched pair.
func (s *Store) GetByID(id int64) (*TrafficEvent, *TrafficEvent, error) {
	evt, err := s.scanOne(id)
	if err != nil {
		return nil, nil, err
	}

	var matched *TrafficEvent
	if evt.MatchedID != 0 {
		matched, _ = s.scanOne(evt.MatchedID)
	}

	return evt, matched, nil
}

func (s *Store) scanOne(id int64) (*TrafficEvent, error) {
	var (
		evt       TrafficEvent
		tsStr     string
		latency   sql.NullInt64
		matchedID sql.NullInt64
	)
	err := s.db.QueryRow(
		`SELECT id, ts, direction, server_name, method, message_id, payload, status, latency_ms, matched_id
		 FROM traffic WHERE id = ?`, id,
	).Scan(&evt.ID, &tsStr, &evt.Direction, &evt.ServerName, &evt.Method,
		&evt.MessageID, &evt.Payload, &evt.Status, &latency, &matchedID)
	if err != nil {
		return nil, err
	}
	t, _ := time.Parse(time.RFC3339Nano, tsStr)
	evt.Timestamp = t.UnixMilli()
	if latency.Valid {
		evt.LatencyMs = &latency.Int64
	}
	if matchedID.Valid {
		evt.MatchedID = matchedID.Int64
	}
	return &evt, nil
}

// --- Session Recording ---

// Session represents a recording session.
type Session struct {
	ID           int64  `json:"id"`
	Name         string `json:"name"`
	Server       string `json:"server"`
	Status       string `json:"status"`
	StartedAt    string `json:"started_at"`
	StoppedAt    string `json:"stopped_at,omitempty"`
	DurationMs   *int64 `json:"duration_ms,omitempty"`
	RequestCount int    `json:"request_count"`
	SizeBytes    int64  `json:"size_bytes"`
}

// SessionCassette is the export format for a recorded session.
type SessionCassette struct {
	Version    int              `json:"version"`
	Name       string           `json:"name"`
	Server     string           `json:"server"`
	RecordedAt string           `json:"recorded_at"`
	DurationMs *int64           `json:"duration_ms,omitempty"`
	Requests   []CassetteEntry  `json:"requests"`
}

// CassetteEntry is a single request/response pair in a cassette.
type CassetteEntry struct {
	Method    string          `json:"method"`
	Params    json.RawMessage `json:"params"`
	Response  json.RawMessage `json:"response,omitempty"`
	LatencyMs *int64          `json:"latency_ms,omitempty"`
	OffsetMs  int64           `json:"offset_ms"`
}

// StartSession creates a new recording session and returns its ID.
func (s *Store) StartSession(name, server string) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	now := time.Now().UTC().Format(time.RFC3339Nano)
	res, err := s.db.Exec(
		`INSERT INTO sessions (name, server, status, started_at) VALUES (?, ?, 'recording', ?)`,
		name, server, now,
	)
	if err != nil {
		return 0, fmt.Errorf("start session: %w", err)
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// StopSession marks a session as complete and computes duration and size.
func (s *Store) StopSession(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	var status, startedAtStr string
	err := s.db.QueryRow(`SELECT status, started_at FROM sessions WHERE id = ?`, id).Scan(&status, &startedAtStr)
	if err != nil {
		return fmt.Errorf("session not found: %w", err)
	}
	if status != "recording" {
		return fmt.Errorf("session %d is not recording (status: %s)", id, status)
	}

	now := time.Now().UTC()
	startedAt, _ := time.Parse(time.RFC3339Nano, startedAtStr)
	durationMs := now.Sub(startedAt).Milliseconds()

	// Compute request count and size
	var reqCount int
	var sizeBytes int64
	s.db.QueryRow(`SELECT COUNT(*), COALESCE(SUM(LENGTH(payload)), 0) FROM traffic WHERE session_id = ?`, id).Scan(&reqCount, &sizeBytes)

	_, err = s.db.Exec(
		`UPDATE sessions SET status = 'complete', stopped_at = ?, duration_ms = ?, request_count = ?, size_bytes = ? WHERE id = ?`,
		now.Format(time.RFC3339Nano), durationMs, reqCount, sizeBytes, id,
	)
	if err != nil {
		return fmt.Errorf("stop session: %w", err)
	}
	return nil
}

// GetSession retrieves a single session by ID.
func (s *Store) GetSession(id int64) (*Session, error) {
	var sess Session
	var stoppedAt sql.NullString
	var durationMs sql.NullInt64

	err := s.db.QueryRow(
		`SELECT id, name, server, status, started_at, stopped_at, duration_ms, request_count, size_bytes FROM sessions WHERE id = ?`, id,
	).Scan(&sess.ID, &sess.Name, &sess.Server, &sess.Status, &sess.StartedAt, &stoppedAt, &durationMs, &sess.RequestCount, &sess.SizeBytes)
	if err != nil {
		return nil, fmt.Errorf("session not found: %w", err)
	}
	if stoppedAt.Valid {
		sess.StoppedAt = stoppedAt.String
	}
	if durationMs.Valid {
		sess.DurationMs = &durationMs.Int64
	}
	return &sess, nil
}

// ListSessions returns sessions, optionally filtered by server and status.
func (s *Store) ListSessions(server, status string) ([]Session, error) {
	where := "WHERE 1=1"
	args := []interface{}{}

	if server != "" {
		where += " AND server = ?"
		args = append(args, server)
	}
	if status != "" {
		where += " AND status = ?"
		args = append(args, status)
	}

	rows, err := s.db.Query(
		"SELECT id, name, server, status, started_at, stopped_at, duration_ms, request_count, size_bytes FROM sessions "+where+" ORDER BY id DESC",
		args...,
	)
	if err != nil {
		return nil, fmt.Errorf("list sessions: %w", err)
	}
	defer rows.Close()

	var sessions []Session
	for rows.Next() {
		var sess Session
		var stoppedAt sql.NullString
		var durationMs sql.NullInt64
		if err := rows.Scan(&sess.ID, &sess.Name, &sess.Server, &sess.Status, &sess.StartedAt, &stoppedAt, &durationMs, &sess.RequestCount, &sess.SizeBytes); err != nil {
			return nil, fmt.Errorf("scan session: %w", err)
		}
		if stoppedAt.Valid {
			sess.StoppedAt = stoppedAt.String
		}
		if durationMs.Valid {
			sess.DurationMs = &durationMs.Int64
		}
		sessions = append(sessions, sess)
	}
	if sessions == nil {
		sessions = []Session{}
	}
	return sessions, nil
}

// DeleteSession removes a session and unlinks its traffic rows.
func (s *Store) DeleteSession(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Check existence
	var exists int
	err := s.db.QueryRow(`SELECT COUNT(*) FROM sessions WHERE id = ?`, id).Scan(&exists)
	if err != nil || exists == 0 {
		return fmt.Errorf("session %d not found", id)
	}

	// Unlink traffic rows
	_, _ = s.db.Exec(`UPDATE traffic SET session_id = NULL WHERE session_id = ?`, id)
	// Delete session
	_, err = s.db.Exec(`DELETE FROM sessions WHERE id = ?`, id)
	if err != nil {
		return fmt.Errorf("delete session: %w", err)
	}
	return nil
}

// ExportSession builds a self-contained JSON cassette for a session.
func (s *Store) ExportSession(id int64) (*SessionCassette, error) {
	sess, err := s.GetSession(id)
	if err != nil {
		return nil, err
	}

	rows, err := s.db.Query(
		`SELECT ts, method, payload, latency_ms, direction FROM traffic WHERE session_id = ? ORDER BY id ASC`, id,
	)
	if err != nil {
		return nil, fmt.Errorf("export session traffic: %w", err)
	}
	defer rows.Close()

	cassette := &SessionCassette{
		Version:    1,
		Name:       sess.Name,
		Server:     sess.Server,
		RecordedAt: sess.StartedAt,
		DurationMs: sess.DurationMs,
	}

	startedAt, _ := time.Parse(time.RFC3339Nano, sess.StartedAt)
	var requests []CassetteEntry

	for rows.Next() {
		var tsStr, method, payload, direction string
		var latency sql.NullInt64
		if err := rows.Scan(&tsStr, &method, &payload, &latency, &direction); err != nil {
			return nil, fmt.Errorf("scan export row: %w", err)
		}

		ts, _ := time.Parse(time.RFC3339Nano, tsStr)
		offsetMs := ts.Sub(startedAt).Milliseconds()
		if offsetMs < 0 {
			offsetMs = 0
		}

		entry := CassetteEntry{
			Method:   method,
			OffsetMs: offsetMs,
		}

		// Parse payload to extract params or response
		var parsed map[string]json.RawMessage
		if json.Unmarshal([]byte(payload), &parsed) == nil {
			if direction == DirectionClientToServer {
				if p, ok := parsed["params"]; ok {
					entry.Params = p
				} else {
					entry.Params = json.RawMessage("{}")
				}
			} else {
				if r, ok := parsed["result"]; ok {
					entry.Response = r
				} else if errField, ok := parsed["error"]; ok {
					entry.Response = errField
				}
			}
		}

		if latency.Valid {
			entry.LatencyMs = &latency.Int64
		}

		requests = append(requests, entry)
	}

	if requests == nil {
		requests = []CassetteEntry{}
	}
	cassette.Requests = requests
	return cassette, nil
}

// InsertWithSession stores a traffic entry tagged with a session ID and returns the row ID and optional latency.
func (s *Store) InsertWithSession(entry *TrafficEntry, sessionID int64) (int64, *int64) {
	s.mu.Lock()
	defer s.mu.Unlock()

	var latencyMs *int64

	// If this is a response, try to correlate with a pending request
	if entry.IsResponse && entry.MessageID != "" {
		if req, ok := s.pending[entry.MessageID]; ok {
			lat := entry.Timestamp.Sub(req.timestamp).Milliseconds()
			latencyMs = &lat
			if entry.Method == "" {
				entry.Method = req.method
			}
			delete(s.pending, entry.MessageID)

			defer func(reqID int64, lat int64) {
			}(req.rowID, lat)
		}
	}

	// Insert into SQLite with session_id
	var sessionIDVal interface{}
	if sessionID > 0 {
		sessionIDVal = sessionID
	}

	res, err := s.db.Exec(
		`INSERT INTO traffic (ts, direction, server_name, method, message_id, payload, status, latency_ms, session_id)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		entry.Timestamp.UTC().Format(time.RFC3339Nano),
		entry.Direction,
		entry.ServerName,
		entry.Method,
		entry.MessageID,
		entry.Payload,
		entry.Status,
		latencyMs,
		sessionIDVal,
	)
	if err != nil {
		slog.Error("failed to insert traffic", "error", err)
		return 0, nil
	}

	rowID, _ := res.LastInsertId()

	// Cross-link request and response
	if entry.IsResponse && entry.MessageID != "" && latencyMs != nil {
		var reqID int64
		err := s.db.QueryRow(
			`SELECT id FROM traffic WHERE message_id = ? AND direction = ? AND id != ? ORDER BY id DESC LIMIT 1`,
			entry.MessageID, DirectionClientToServer, rowID,
		).Scan(&reqID)
		if err == nil {
			s.db.Exec(`UPDATE traffic SET matched_id = ?, latency_ms = ? WHERE id = ?`, rowID, latencyMs, reqID)
			s.db.Exec(`UPDATE traffic SET matched_id = ? WHERE id = ?`, reqID, rowID)
		}
	}

	// If this is a request, track it for correlation
	if !entry.IsResponse && entry.MessageID != "" {
		s.pending[entry.MessageID] = pendingRequest{
			rowID:     rowID,
			timestamp: entry.Timestamp,
			method:    entry.Method,
		}
	}

	// Update session request_count if tagged
	if sessionID > 0 {
		s.db.Exec(`UPDATE sessions SET request_count = request_count + 1 WHERE id = ?`, sessionID)
	}

	// Append to JSONL
	jsonLine, _ := json.Marshal(map[string]interface{}{
		"id":          rowID,
		"ts":          entry.Timestamp.UTC().Format(time.RFC3339Nano),
		"direction":   entry.Direction,
		"server_name": entry.ServerName,
		"method":      entry.Method,
		"message_id":  entry.MessageID,
		"payload":     entry.Payload,
		"status":      entry.Status,
		"latency_ms":  latencyMs,
		"session_id":  sessionIDVal,
	})
	s.jsonlF.Write(jsonLine)
	s.jsonlF.Write([]byte("\n"))

	return rowID, latencyMs
}

// --- Schema Snapshots & Changes ---

// SaveSnapshot stores a schema snapshot for a server and returns the snapshot ID.
func (s *Store) SaveSnapshot(server string, tools []ToolSchema) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := json.Marshal(tools)
	if err != nil {
		return 0, fmt.Errorf("marshal snapshot: %w", err)
	}

	now := time.Now().UTC().Format(time.RFC3339Nano)
	res, err := s.db.Exec(
		`INSERT INTO schema_snapshots (server_name, snapshot, captured_at) VALUES (?, ?, ?)`,
		server, string(data), now,
	)
	if err != nil {
		return 0, fmt.Errorf("save snapshot: %w", err)
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// GetLatestSnapshot retrieves the most recent schema snapshot for a server.
// Returns the tools, snapshot ID, and any error.
// If no snapshot exists, returns nil tools and id 0 with no error.
func (s *Store) GetLatestSnapshot(server string) ([]ToolSchema, int64, error) {
	var id int64
	var snapshot string
	err := s.db.QueryRow(
		`SELECT id, snapshot FROM schema_snapshots WHERE server_name = ? ORDER BY id DESC LIMIT 1`,
		server,
	).Scan(&id, &snapshot)
	if err == sql.ErrNoRows {
		return nil, 0, nil
	}
	if err != nil {
		return nil, 0, fmt.Errorf("get latest snapshot: %w", err)
	}

	var tools []ToolSchema
	if err := json.Unmarshal([]byte(snapshot), &tools); err != nil {
		return nil, 0, fmt.Errorf("unmarshal snapshot: %w", err)
	}
	return tools, id, nil
}

// InsertSchemaChange records a detected schema change.
func (s *Store) InsertSchemaChange(server string, diff SchemaDiff, beforeID, afterID int64) (int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	diffJSON, err := json.Marshal(diff)
	if err != nil {
		return 0, fmt.Errorf("marshal diff: %w", err)
	}

	now := time.Now().UTC().Format(time.RFC3339Nano)
	res, err := s.db.Exec(
		`INSERT INTO schema_changes (server_name, detected_at, tools_added, tools_removed, tools_modified, before_snapshot, after_snapshot, diff_json)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		server, now, len(diff.Added), len(diff.Removed), len(diff.Modified), beforeID, afterID, string(diffJSON),
	)
	if err != nil {
		return 0, fmt.Errorf("insert schema change: %w", err)
	}
	id, _ := res.LastInsertId()
	return id, nil
}

// ListSchemaChanges returns all schema changes, optionally filtered by server.
func (s *Store) ListSchemaChanges(server string) ([]SchemaChange, error) {
	where := "WHERE 1=1"
	args := []interface{}{}
	if server != "" {
		where += " AND server_name = ?"
		args = append(args, server)
	}

	rows, err := s.db.Query(
		"SELECT id, server_name, detected_at, tools_added, tools_removed, tools_modified, acknowledged FROM schema_changes "+where+" ORDER BY id DESC",
		args...,
	)
	if err != nil {
		return nil, fmt.Errorf("list schema changes: %w", err)
	}
	defer rows.Close()

	var changes []SchemaChange
	for rows.Next() {
		var c SchemaChange
		var ack int
		if err := rows.Scan(&c.ID, &c.ServerName, &c.DetectedAt, &c.ToolsAdded, &c.ToolsRemoved, &c.ToolsModified, &ack); err != nil {
			return nil, fmt.Errorf("scan schema change: %w", err)
		}
		c.Acknowledged = ack != 0
		changes = append(changes, c)
	}
	if changes == nil {
		changes = []SchemaChange{}
	}
	return changes, nil
}

// GetSchemaChange retrieves a single schema change by ID with full diff.
func (s *Store) GetSchemaChange(id int64) (*SchemaChangeDetail, error) {
	var c SchemaChangeDetail
	var ack int
	var diffStr string
	err := s.db.QueryRow(
		`SELECT id, server_name, detected_at, tools_added, tools_removed, tools_modified, acknowledged, diff_json FROM schema_changes WHERE id = ?`,
		id,
	).Scan(&c.ID, &c.ServerName, &c.DetectedAt, &c.ToolsAdded, &c.ToolsRemoved, &c.ToolsModified, &ack, &diffStr)
	if err != nil {
		return nil, fmt.Errorf("get schema change: %w", err)
	}
	c.Acknowledged = ack != 0
	if err := json.Unmarshal([]byte(diffStr), &c.DiffJSON); err != nil {
		return nil, fmt.Errorf("unmarshal diff: %w", err)
	}
	return &c, nil
}

// AcknowledgeSchemaChange marks a schema change as acknowledged.
func (s *Store) AcknowledgeSchemaChange(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	res, err := s.db.Exec(`UPDATE schema_changes SET acknowledged = 1 WHERE id = ?`, id)
	if err != nil {
		return fmt.Errorf("acknowledge schema change: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("schema change %d not found", id)
	}
	return nil
}

// UnacknowledgedCount returns the number of unacknowledged schema changes.
func (s *Store) UnacknowledgedCount() (int, error) {
	var count int
	err := s.db.QueryRow(`SELECT COUNT(*) FROM schema_changes WHERE acknowledged = 0`).Scan(&count)
	if err != nil {
		return 0, fmt.Errorf("unacknowledged count: %w", err)
	}
	return count, nil
}

// ProfilingSummaryResult holds aggregate latency stats for a time range.
type ProfilingSummaryResult struct {
	TotalCalls       int      `json:"total_calls"`
	AvgLatencyMs     float64  `json:"avg_latency_ms"`
	P95LatencyMs     float64  `json:"p95_latency_ms"`
	ErrorRate        float64  `json:"error_rate"`
	PrevTotalCalls   *int     `json:"prev_total_calls"`
	PrevAvgLatencyMs *float64 `json:"prev_avg_latency_ms"`
	PrevErrorRate    *float64 `json:"prev_error_rate"`
}

// ToolProfile holds per-tool latency stats.
type ToolProfile struct {
	Tool      string  `json:"tool"`
	Server    string  `json:"server"`
	Calls     int     `json:"calls"`
	MinMs     float64 `json:"min_ms"`
	AvgMs     float64 `json:"avg_ms"`
	P50Ms     float64 `json:"p50_ms"`
	P95Ms     float64 `json:"p95_ms"`
	MaxMs     float64 `json:"max_ms"`
	ErrorRate float64 `json:"error_rate"`
}

// parseRange converts a range string like "1h", "24h", "7d", "30d" into a
// SQLite datetime modifier relative to 'now'.
func parseRange(rangeStr string) (string, error) {
	switch rangeStr {
	case "1h":
		return "-1 hour", nil
	case "24h":
		return "-1 day", nil
	case "7d":
		return "-7 days", nil
	case "30d":
		return "-30 days", nil
	default:
		return "", fmt.Errorf("unsupported range: %s", rangeStr)
	}
}

// doubleDuration returns a modifier representing twice the duration, used
// for computing the "previous period" start boundary.
func doubleDuration(rangeStr string) (string, error) {
	switch rangeStr {
	case "1h":
		return "-2 hours", nil
	case "24h":
		return "-2 days", nil
	case "7d":
		return "-14 days", nil
	case "30d":
		return "-60 days", nil
	default:
		return "", fmt.Errorf("unsupported range: %s", rangeStr)
	}
}

// profilingWhere builds the WHERE clause for profiling queries.
func profilingWhere(modifier, server string) (string, []interface{}) {
	where := "WHERE direction = ? AND latency_ms IS NOT NULL AND ts > datetime('now', ?)"
	args := []interface{}{DirectionServerToClient, modifier}
	if server != "" {
		where += " AND server_name = ?"
		args = append(args, server)
	}
	return where, args
}

// ProfilingSummary returns aggregate latency stats for a given time range and
// optional server filter. It also computes deltas from the previous period.
func (s *Store) ProfilingSummary(rangeStr, server string) (*ProfilingSummaryResult, error) {
	modifier, err := parseRange(rangeStr)
	if err != nil {
		return nil, err
	}

	result := &ProfilingSummaryResult{}

	// --- Current period ---
	where, args := profilingWhere(modifier, server)

	// Total calls, avg latency, error rate
	errRateQuery := fmt.Sprintf(
		`SELECT COUNT(*), COALESCE(AVG(latency_ms), 0),
		        COUNT(CASE WHEN status = 'error' THEN 1 END) * 100.0 / MAX(COUNT(*), 1)
		 FROM traffic %s`, where)
	err = s.db.QueryRow(errRateQuery, args...).Scan(
		&result.TotalCalls, &result.AvgLatencyMs, &result.ErrorRate)
	if err != nil {
		return nil, fmt.Errorf("profiling summary current: %w", err)
	}

	// P95 — fetch all latency values sorted, pick the 95th percentile
	p95Query := fmt.Sprintf(
		`SELECT latency_ms FROM traffic %s ORDER BY latency_ms ASC`, where)
	p95Args := make([]interface{}, len(args))
	copy(p95Args, args)
	rows, err := s.db.Query(p95Query, p95Args...)
	if err != nil {
		return nil, fmt.Errorf("profiling p95 query: %w", err)
	}
	var latencies []float64
	for rows.Next() {
		var v float64
		if err := rows.Scan(&v); err != nil {
			rows.Close()
			return nil, fmt.Errorf("profiling p95 scan: %w", err)
		}
		latencies = append(latencies, v)
	}
	rows.Close()
	result.P95LatencyMs = percentile(latencies, 0.95)

	// --- Previous period ---
	dblModifier, err := doubleDuration(rangeStr)
	if err != nil {
		return nil, err
	}

	prevWhere := "WHERE direction = ? AND latency_ms IS NOT NULL AND ts > datetime('now', ?) AND ts <= datetime('now', ?)"
	prevArgs := []interface{}{DirectionServerToClient, dblModifier, modifier}
	if server != "" {
		prevWhere += " AND server_name = ?"
		prevArgs = append(prevArgs, server)
	}

	var prevCalls int
	var prevAvg, prevErr float64
	prevQuery := fmt.Sprintf(
		`SELECT COUNT(*), COALESCE(AVG(latency_ms), 0),
		        COUNT(CASE WHEN status = 'error' THEN 1 END) * 100.0 / MAX(COUNT(*), 1)
		 FROM traffic %s`, prevWhere)
	scanErr := s.db.QueryRow(prevQuery, prevArgs...).Scan(&prevCalls, &prevAvg, &prevErr)
	if scanErr == nil && prevCalls > 0 {
		result.PrevTotalCalls = &prevCalls
		result.PrevAvgLatencyMs = &prevAvg
		result.PrevErrorRate = &prevErr
	}

	return result, nil
}

// ProfilingByTool returns per-tool latency stats grouped by method+server.
func (s *Store) ProfilingByTool(rangeStr, server, sortBy, order string) ([]ToolProfile, error) {
	modifier, err := parseRange(rangeStr)
	if err != nil {
		return nil, err
	}

	where, args := profilingWhere(modifier, server)

	// Get distinct method+server combinations with aggregate stats
	groupQuery := fmt.Sprintf(
		`SELECT method, server_name, COUNT(*),
		        MIN(latency_ms), AVG(latency_ms), MAX(latency_ms),
		        COUNT(CASE WHEN status = 'error' THEN 1 END) * 100.0 / COUNT(*)
		 FROM traffic %s
		 GROUP BY method, server_name`, where)

	rows, err := s.db.Query(groupQuery, args...)
	if err != nil {
		return nil, fmt.Errorf("profiling by tool query: %w", err)
	}
	defer rows.Close()

	type toolKey struct{ method, server string }
	var keys []toolKey
	profiles := map[toolKey]*ToolProfile{}

	for rows.Next() {
		var tp ToolProfile
		if err := rows.Scan(&tp.Tool, &tp.Server, &tp.Calls,
			&tp.MinMs, &tp.AvgMs, &tp.MaxMs, &tp.ErrorRate); err != nil {
			return nil, fmt.Errorf("profiling by tool scan: %w", err)
		}
		k := toolKey{tp.Tool, tp.Server}
		keys = append(keys, k)
		profiles[k] = &tp
	}

	// Compute P50/P95 per tool — fetch sorted latencies for each group
	for _, k := range keys {
		tp := profiles[k]
		pWhere := where + " AND method = ? AND server_name = ?"
		pArgs := append(append([]interface{}{}, args...), k.method, k.server)

		pRows, err := s.db.Query(
			fmt.Sprintf(`SELECT latency_ms FROM traffic %s ORDER BY latency_ms ASC`, pWhere),
			pArgs...)
		if err != nil {
			return nil, fmt.Errorf("profiling percentile query: %w", err)
		}
		var lats []float64
		for pRows.Next() {
			var v float64
			if err := pRows.Scan(&v); err != nil {
				pRows.Close()
				return nil, fmt.Errorf("profiling percentile scan: %w", err)
			}
			lats = append(lats, v)
		}
		pRows.Close()

		tp.P50Ms = percentile(lats, 0.50)
		tp.P95Ms = percentile(lats, 0.95)
	}

	// Build result slice
	result := make([]ToolProfile, 0, len(keys))
	for _, k := range keys {
		result = append(result, *profiles[k])
	}

	// Sort
	sortProfiles(result, sortBy, order)

	return result, nil
}

// percentile computes the p-th percentile from a sorted slice of values.
// Returns 0 for empty slices, the single value for length-1 slices.
func percentile(sorted []float64, p float64) float64 {
	n := len(sorted)
	if n == 0 {
		return 0
	}
	if n == 1 {
		return sorted[0]
	}
	idx := int(float64(n-1) * p)
	if idx >= n {
		idx = n - 1
	}
	return sorted[idx]
}

// sortProfiles sorts a slice of ToolProfile by the given column and order.
func sortProfiles(profiles []ToolProfile, sortBy, order string) {
	var less func(i, j int) bool
	switch sortBy {
	case "calls":
		less = func(i, j int) bool { return profiles[i].Calls < profiles[j].Calls }
	case "min":
		less = func(i, j int) bool { return profiles[i].MinMs < profiles[j].MinMs }
	case "avg":
		less = func(i, j int) bool { return profiles[i].AvgMs < profiles[j].AvgMs }
	case "p50":
		less = func(i, j int) bool { return profiles[i].P50Ms < profiles[j].P50Ms }
	case "max":
		less = func(i, j int) bool { return profiles[i].MaxMs < profiles[j].MaxMs }
	case "error_rate":
		less = func(i, j int) bool { return profiles[i].ErrorRate < profiles[j].ErrorRate }
	default: // "p95"
		less = func(i, j int) bool { return profiles[i].P95Ms < profiles[j].P95Ms }
	}

	// Simple insertion sort (small data sets)
	for i := 1; i < len(profiles); i++ {
		for j := i; j > 0 && less(j, j-1); j-- {
			profiles[j], profiles[j-1] = profiles[j-1], profiles[j]
		}
	}

	if order == "desc" {
		for i, j := 0, len(profiles)-1; i < j; i, j = i+1, j-1 {
			profiles[i], profiles[j] = profiles[j], profiles[i]
		}
	}
}

// Close shuts down the store.
func (s *Store) Close() error {
	s.jsonlF.Close()
	return s.db.Close()
}
