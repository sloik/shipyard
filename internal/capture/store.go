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

var openSQLiteDB = func(path string) (*sql.DB, error) {
	return sql.Open("sqlite3", path)
}

var openJSONLFile = func(path string) (*os.File, error) {
	return os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
}

var queryTrafficRows = func(db *sql.DB, query string, args ...interface{}) (*sql.Rows, error) {
	return db.Query(query, args...)
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

	// Create schema
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
			matched_id  INTEGER
		);
		CREATE INDEX IF NOT EXISTS idx_traffic_ts ON traffic(ts);
		CREATE INDEX IF NOT EXISTS idx_traffic_method ON traffic(method);
		CREATE INDEX IF NOT EXISTS idx_traffic_server ON traffic(server_name);
		CREATE INDEX IF NOT EXISTS idx_traffic_message_id ON traffic(message_id);
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("create schema: %w", err)
	}

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

// Query retrieves paginated traffic entries, optionally filtered.
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

// Close shuts down the store.
func (s *Store) Close() error {
	s.jsonlF.Close()
	return s.db.Close()
}
