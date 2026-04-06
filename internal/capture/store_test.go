package capture

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func newTestStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "test.db")
	jsonlPath := filepath.Join(dir, "test.jsonl")
	s, err := NewStore(dbPath, jsonlPath)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func TestInsert_BasicEntry(t *testing.T) {
	s := newTestStore(t)

	entry := &TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "test-server",
		Method:     "tools/list",
		MessageID:  "1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/list","id":1}`,
		Status:     "pending",
	}

	id, latency := s.Insert(entry)

	if id == 0 {
		t.Fatal("expected non-zero row ID")
	}
	if latency != nil {
		t.Fatal("expected nil latency for a request")
	}
}

func TestInsert_RequestResponseCorrelation(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	// Insert request
	req := &TrafficEntry{
		Timestamp:  now,
		Direction:  DirectionClientToServer,
		ServerName: "test-server",
		Method:     "tools/call",
		MessageID:  "42",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":42}`,
		Status:     "pending",
	}
	reqID, reqLatency := s.Insert(req)
	if reqID == 0 {
		t.Fatal("expected non-zero request row ID")
	}
	if reqLatency != nil {
		t.Fatal("expected nil latency for request")
	}

	// Insert response 50ms later
	res := &TrafficEntry{
		Timestamp:  now.Add(50 * time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "test-server",
		MessageID:  "42",
		Payload:    `{"jsonrpc":"2.0","id":42,"result":{}}`,
		Status:     "ok",
		IsResponse: true,
	}
	resID, resLatency := s.Insert(res)
	if resID == 0 {
		t.Fatal("expected non-zero response row ID")
	}
	if resLatency == nil {
		t.Fatal("expected non-nil latency for correlated response")
	}
	if *resLatency != 50 {
		t.Fatalf("expected latency ~50ms, got %dms", *resLatency)
	}
}

func TestInsert_UncorrelatedResponse(t *testing.T) {
	s := newTestStore(t)

	res := &TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionServerToClient,
		ServerName: "test-server",
		MessageID:  "999",
		Payload:    `{"jsonrpc":"2.0","id":999,"result":{}}`,
		Status:     "ok",
		IsResponse: true,
	}
	id, latency := s.Insert(res)
	if id == 0 {
		t.Fatal("expected non-zero row ID")
	}
	if latency != nil {
		t.Fatal("expected nil latency for uncorrelated response")
	}
}

func TestQuery_Pagination(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	// Insert 5 entries
	for i := 0; i < 5; i++ {
		s.Insert(&TrafficEntry{
			Timestamp:  now.Add(time.Duration(i) * time.Second),
			Direction:  DirectionClientToServer,
			ServerName: "srv",
			Method:     "test/method",
			Payload:    `{}`,
			Status:     "pending",
		})
	}

	// Page 1 of 2
	page, err := s.Query(1, 3, "", "")
	if err != nil {
		t.Fatalf("Query page 1: %v", err)
	}
	if page.TotalCount != 5 {
		t.Fatalf("expected total_count 5, got %d", page.TotalCount)
	}
	if len(page.Items) != 3 {
		t.Fatalf("expected 3 items on page 1, got %d", len(page.Items))
	}
	if page.Page != 1 {
		t.Fatalf("expected page 1, got %d", page.Page)
	}

	// Page 2
	page2, err := s.Query(2, 3, "", "")
	if err != nil {
		t.Fatalf("Query page 2: %v", err)
	}
	if len(page2.Items) != 2 {
		t.Fatalf("expected 2 items on page 2, got %d", len(page2.Items))
	}
}

func TestQuery_FilterByServer(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "test", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "beta", Method: "test", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "test", Payload: `{}`, Status: "pending",
	})

	page, err := s.Query(1, 10, "alpha", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 2 {
		t.Fatalf("expected 2 alpha entries, got %d", page.TotalCount)
	}
}

func TestQuery_FilterByMethod(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/list", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{}`, Status: "pending",
	})

	page, err := s.Query(1, 10, "", "tools/call")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 tools/call entry, got %d", page.TotalCount)
	}
}

func TestGetByID(t *testing.T) {
	s := newTestStore(t)

	entry := &TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/list",
		MessageID:  "1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/list","id":1}`,
		Status:     "pending",
	}
	id, _ := s.Insert(entry)

	evt, matched, err := s.GetByID(id)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if evt.ID != id {
		t.Fatalf("expected ID %d, got %d", id, evt.ID)
	}
	if evt.Method != "tools/list" {
		t.Fatalf("expected method tools/list, got %s", evt.Method)
	}
	if evt.Direction != DirectionClientToServer {
		t.Fatalf("expected direction %s, got %s", DirectionClientToServer, evt.Direction)
	}
	if matched != nil {
		t.Fatal("expected nil matched for single request")
	}
}

func TestDirectionConstants(t *testing.T) {
	if DirectionClientToServer != "client→server" {
		t.Fatalf("unexpected client→server constant: %s", DirectionClientToServer)
	}
	if DirectionServerToClient != "server→client" {
		t.Fatalf("unexpected server→client constant: %s", DirectionServerToClient)
	}
}

func TestQuery_CombinedFilters(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "tools/list", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "tools/call", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "beta", Method: "tools/call", Payload: `{}`, Status: "pending",
	})

	// Filter by both server and method
	page, err := s.Query(1, 10, "alpha", "tools/call")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 entry matching alpha+tools/call, got %d", page.TotalCount)
	}
	if len(page.Items) != 1 {
		t.Fatalf("expected 1 item, got %d", len(page.Items))
	}
	if page.Items[0].ServerName != "alpha" {
		t.Fatalf("expected server 'alpha', got '%s'", page.Items[0].ServerName)
	}
	if page.Items[0].Method != "tools/call" {
		t.Fatalf("expected method 'tools/call', got '%s'", page.Items[0].Method)
	}
}

func TestQuery_NoResults(t *testing.T) {
	s := newTestStore(t)

	page, err := s.Query(1, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 0 {
		t.Fatalf("expected total_count 0, got %d", page.TotalCount)
	}
	if page.Items != nil {
		// Items may be nil when there are no results — that's acceptable
		if len(page.Items) != 0 {
			t.Fatalf("expected 0 items, got %d", len(page.Items))
		}
	}
}

func TestQuery_ReturnsNewestEntriesFirst(t *testing.T) {
	s := newTestStore(t)

	id1, _ := s.Insert(&TrafficEntry{
		Timestamp:  time.Now().Add(-2 * time.Minute),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "one",
		Payload:    `{}`,
		Status:     "pending",
	})
	id2, _ := s.Insert(&TrafficEntry{
		Timestamp:  time.Now().Add(-time.Minute),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "two",
		Payload:    `{}`,
		Status:     "pending",
	})
	id3, _ := s.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "three",
		Payload:    `{}`,
		Status:     "pending",
	})

	page, err := s.Query(1, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(page.Items) != 3 {
		t.Fatalf("expected 3 items, got %d", len(page.Items))
	}
	if page.Items[0].ID != id3 || page.Items[1].ID != id2 || page.Items[2].ID != id1 {
		t.Fatalf("expected newest-first order %d,%d,%d; got %d,%d,%d", id3, id2, id1, page.Items[0].ID, page.Items[1].ID, page.Items[2].ID)
	}
}

func TestQuery_PageBeyondTotal(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "test", Payload: `{}`, Status: "pending",
	})

	// Page 100 should return no items but correct total
	page, err := s.Query(100, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected total_count 1, got %d", page.TotalCount)
	}
	if len(page.Items) != 0 {
		t.Fatalf("expected 0 items on page 100, got %d", len(page.Items))
	}
}

func TestGetByID_NotFound(t *testing.T) {
	s := newTestStore(t)

	_, _, err := s.GetByID(99999)
	if err == nil {
		t.Fatal("expected error for non-existent ID")
	}
}

func TestGetByID_WithMatchedPair(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	// Insert request
	reqID, _ := s.Insert(&TrafficEntry{
		Timestamp:  now,
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/call",
		MessageID:  "match-1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":"match-1"}`,
		Status:     "pending",
	})

	// Insert correlated response
	resID, lat := s.Insert(&TrafficEntry{
		Timestamp:  now.Add(25 * time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "srv",
		MessageID:  "match-1",
		Payload:    `{"jsonrpc":"2.0","id":"match-1","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})

	if lat == nil {
		t.Fatal("expected non-nil latency for correlated response")
	}

	// GetByID on the response should include the matched request
	evt, matched, err := s.GetByID(resID)
	if err != nil {
		t.Fatalf("GetByID(response): %v", err)
	}
	if evt.ID != resID {
		t.Fatalf("expected ID %d, got %d", resID, evt.ID)
	}
	if matched == nil {
		t.Fatal("expected matched entry for correlated response")
	}
	if matched.ID != reqID {
		t.Fatalf("expected matched ID %d, got %d", reqID, matched.ID)
	}
}

func TestQuery_IncludesLatencyAndMatchedID(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	reqID, _ := s.Insert(&TrafficEntry{
		Timestamp:  now,
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/call",
		MessageID:  "latency-1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":"latency-1"}`,
		Status:     "pending",
	})

	resID, latency := s.Insert(&TrafficEntry{
		Timestamp:  now.Add(25 * time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "srv",
		MessageID:  "latency-1",
		Payload:    `{"jsonrpc":"2.0","id":"latency-1","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})
	if latency == nil {
		t.Fatal("expected response latency to be populated")
	}

	page, err := s.Query(1, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(page.Items) != 2 {
		t.Fatalf("expected 2 items, got %d", len(page.Items))
	}

	var foundResponse bool
	for _, item := range page.Items {
		if item.ID != resID {
			continue
		}
		foundResponse = true
		if item.LatencyMs == nil || *item.LatencyMs != 25 {
			t.Fatalf("expected latency 25ms on response, got %v", item.LatencyMs)
		}
		if item.MatchedID != reqID {
			t.Fatalf("expected matched ID %d, got %d", reqID, item.MatchedID)
		}
	}
	if !foundResponse {
		t.Fatalf("expected to find response row %d in query results", resID)
	}
}

func TestInsert_ConcurrentInserts(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()
	const n = 10

	var wg sync.WaitGroup
	wg.Add(n)

	for i := 0; i < n; i++ {
		i := i
		go func() {
			defer wg.Done()
			s.Insert(&TrafficEntry{
				Timestamp:  now.Add(time.Duration(i) * time.Millisecond),
				Direction:  DirectionClientToServer,
				ServerName: "srv",
				Method:     "concurrent/test",
				Payload:    `{}`,
				Status:     "pending",
			})
		}()
	}

	wg.Wait()

	page, err := s.Query(1, 100, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != n {
		t.Fatalf("expected %d entries after concurrent inserts, got %d", n, page.TotalCount)
	}
}

func TestStore_Close(t *testing.T) {
	dir := t.TempDir()
	s, err := NewStore(
		filepath.Join(dir, "test.db"),
		filepath.Join(dir, "test.jsonl"),
	)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}

	err = s.Close()
	if err != nil {
		t.Fatalf("Close: %v", err)
	}
}

func TestInsert_LargePayload(t *testing.T) {
	s := newTestStore(t)

	// 100KB payload
	largePayload := `{"data":"` + strings.Repeat("x", 100*1024) + `"}`

	id, _ := s.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "large/test",
		Payload:    largePayload,
		Status:     "pending",
	})

	if id == 0 {
		t.Fatal("expected non-zero row ID for large payload")
	}

	// Verify we can retrieve it
	evt, _, err := s.GetByID(id)
	if err != nil {
		t.Fatalf("GetByID: %v", err)
	}
	if len(evt.Payload) != len(largePayload) {
		t.Fatalf("expected payload length %d, got %d", len(largePayload), len(evt.Payload))
	}
}

func TestJSONLAppend(t *testing.T) {
	s := newTestStore(t)

	s.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "test",
		Payload:    `{"test":true}`,
		Status:     "pending",
	})

	// Flush and read the JSONL file
	data, err := os.ReadFile(s.jsonlF.Name())
	if err != nil {
		t.Fatalf("read jsonl: %v", err)
	}
	if len(data) == 0 {
		t.Fatal("expected non-empty JSONL file")
	}
}

func TestNewStore_SQLiteOpenFailure(t *testing.T) {
	orig := openSQLiteDB
	openSQLiteDB = func(path string) (*sql.DB, error) {
		return nil, errors.New("sqlite open failed")
	}
	t.Cleanup(func() { openSQLiteDB = orig })

	_, err := NewStore("ignored.db", "ignored.jsonl")
	if err == nil {
		t.Fatal("expected sqlite open error")
	}
	if !strings.Contains(err.Error(), "open sqlite: sqlite open failed") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestNewStore_JSONLOpenFailure(t *testing.T) {
	orig := openJSONLFile
	openJSONLFile = func(path string) (*os.File, error) {
		return nil, errors.New("jsonl open failed")
	}
	t.Cleanup(func() { openJSONLFile = orig })

	_, err := NewStore(filepath.Join(t.TempDir(), "test.db"), "ignored.jsonl")
	if err == nil {
		t.Fatal("expected jsonl open error")
	}
	if !strings.Contains(err.Error(), "open jsonl: jsonl open failed") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestNewStore_SchemaFailure(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "test.db")
	jsonlPath := filepath.Join(dir, "test.jsonl")

	orig := openSQLiteDB
	openSQLiteDB = func(path string) (*sql.DB, error) {
		db, err := sql.Open("sqlite3", dbPath)
		if err != nil {
			return nil, err
		}
		if _, err := db.Exec(`CREATE TABLE traffic (id TEXT)`); err != nil {
			db.Close()
			return nil, err
		}
		return db, nil
	}
	t.Cleanup(func() { openSQLiteDB = orig })

	_, err := NewStore(dbPath, jsonlPath)
	if err == nil {
		t.Fatal("expected schema creation error")
	}
	if !strings.Contains(err.Error(), "create schema:") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestInsert_ReturnsZeroOnExecFailure(t *testing.T) {
	s := newTestStore(t)

	if err := s.db.Close(); err != nil {
		t.Fatalf("Close db: %v", err)
	}

	id, latency := s.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "broken",
		Payload:    `{}`,
		Status:     "pending",
	})

	if id != 0 {
		t.Fatalf("expected zero row ID on exec failure, got %d", id)
	}
	if latency != nil {
		t.Fatalf("expected nil latency on exec failure, got %v", latency)
	}
}

func TestQuery_CountFailure(t *testing.T) {
	s := newTestStore(t)

	if err := s.db.Close(); err != nil {
		t.Fatalf("Close db: %v", err)
	}

	_, err := s.Query(1, 10, "", "")
	if err == nil {
		t.Fatal("expected count failure")
	}
	if !strings.Contains(err.Error(), "count:") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestQuery_SelectFailureAfterCount(t *testing.T) {
	s := newTestStore(t)

	s.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "test",
		Payload:    `{}`,
		Status:     "pending",
	})

	orig := queryTrafficRows
	queryTrafficRows = func(db *sql.DB, query string, args ...interface{}) (*sql.Rows, error) {
		return nil, errors.New("query rows failed")
	}
	t.Cleanup(func() { queryTrafficRows = orig })

	_, err := s.Query(1, 10, "", "")
	if err == nil {
		t.Fatal("expected query failure after dropping table")
	}
	if !strings.Contains(err.Error(), "query: query rows failed") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestQuery_ScanFailure(t *testing.T) {
	s := newTestStore(t)

	if _, err := s.db.Exec(`DROP TABLE traffic`); err != nil {
		t.Fatalf("drop traffic table: %v", err)
	}
	if _, err := s.db.Exec(`
		CREATE TABLE traffic (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			ts BLOB NOT NULL,
			direction TEXT NOT NULL,
			server_name TEXT NOT NULL,
			method TEXT NOT NULL DEFAULT '',
			message_id TEXT NOT NULL DEFAULT '',
			payload TEXT NOT NULL,
			status TEXT NOT NULL DEFAULT 'ok',
			latency_ms TEXT,
			matched_id TEXT
		)
	`); err != nil {
		t.Fatalf("create malformed traffic table: %v", err)
	}
	if _, err := s.db.Exec(
		`INSERT INTO traffic (ts, direction, server_name, method, message_id, payload, status, latency_ms, matched_id)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		time.Now().UTC().Format(time.RFC3339Nano),
		DirectionClientToServer,
		"srv",
		"test",
		"1",
		`{}`,
		"pending",
		"not-an-int",
		"also-not-an-int",
	); err != nil {
		t.Fatalf("insert malformed row: %v", err)
	}

	_, err := s.Query(1, 10, "", "")
	if err == nil {
		t.Fatal("expected scan failure")
	}
	if !strings.Contains(err.Error(), "scan:") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// --- SPEC-003 AC-3: History persists across restarts ---

func TestStore_PersistsAcrossRestarts(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "test.db")
	jsonlPath := filepath.Join(dir, "test.jsonl")

	// First "session" — create store and insert data
	s1, err := NewStore(dbPath, jsonlPath)
	if err != nil {
		t.Fatalf("NewStore (session 1): %v", err)
	}
	s1.Insert(&TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/call",
		Payload:    `{"persistent":true}`,
		Status:     "pending",
	})
	s1.Close()

	// Second "session" — re-open the same DB
	s2, err := NewStore(dbPath, jsonlPath)
	if err != nil {
		t.Fatalf("NewStore (session 2): %v", err)
	}
	t.Cleanup(func() { s2.Close() })

	page, err := s2.QueryFiltered(QueryFilter{Page: 1, PageSize: 50})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 persisted entry after restart, got %d", page.TotalCount)
	}
	if !strings.Contains(page.Items[0].Payload, "persistent") {
		t.Fatalf("expected payload to contain 'persistent', got %s", page.Items[0].Payload)
	}
}

// --- QueryFiltered tests (SPEC-003 AC-4: search, direction, time range) ---

func TestQueryFiltered_SearchByPayload(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{"name":"read_file","arguments":{"path":"/tmp/foo"}}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{"name":"write_file","arguments":{"path":"/tmp/bar"}}`, Status: "pending",
	})

	page, err := s.QueryFiltered(QueryFilter{Page: 1, PageSize: 50, Search: "read_file"})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 entry matching 'read_file', got %d", page.TotalCount)
	}
}

func TestQueryFiltered_FilterByDirection(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now.Add(10 * time.Millisecond), Direction: DirectionServerToClient,
		ServerName: "srv", Method: "tools/call", Payload: `{"result":{}}`, Status: "ok", IsResponse: true,
	})

	page, err := s.QueryFiltered(QueryFilter{Page: 1, PageSize: 50, Direction: DirectionClientToServer})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 request entry, got %d", page.TotalCount)
	}
}

func TestQueryFiltered_TimeRange(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now.Add(-2 * time.Hour), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "old", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now.Add(-30 * time.Minute), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "recent", Payload: `{}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "srv", Method: "now", Payload: `{}`, Status: "pending",
	})

	fromTs := now.Add(-1 * time.Hour).UnixMilli()
	toTs := now.Add(time.Minute).UnixMilli()
	page, err := s.QueryFiltered(QueryFilter{Page: 1, PageSize: 50, FromTs: &fromTs, ToTs: &toTs})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 2 {
		t.Fatalf("expected 2 entries in time range, got %d", page.TotalCount)
	}
}

func TestQueryFiltered_CombinedFilters(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "tools/call", Payload: `{"name":"read_file"}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "beta", Method: "tools/call", Payload: `{"name":"read_file"}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp: now, Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "tools/list", Payload: `{}`, Status: "pending",
	})

	page, err := s.QueryFiltered(QueryFilter{
		Page: 1, PageSize: 50,
		Server: "alpha", Method: "tools/call", Search: "read_file",
	})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 combined-filter entry, got %d", page.TotalCount)
	}
}

func TestQueryFiltered_DefaultPagination(t *testing.T) {
	s := newTestStore(t)
	now := time.Now()

	for i := 0; i < 3; i++ {
		s.Insert(&TrafficEntry{
			Timestamp: now.Add(time.Duration(i) * time.Second), Direction: DirectionClientToServer,
			ServerName: "srv", Method: "test", Payload: `{}`, Status: "pending",
		})
	}

	page, err := s.QueryFiltered(QueryFilter{Page: 1, PageSize: 50})
	if err != nil {
		t.Fatalf("QueryFiltered: %v", err)
	}
	if page.TotalCount != 3 {
		t.Fatalf("expected 3, got %d", page.TotalCount)
	}
	if len(page.Items) != 3 {
		t.Fatalf("expected 3 items, got %d", len(page.Items))
	}
}

// --- SPEC-008: Latency Profiling ---

// seedProfilingData inserts response traffic with known latencies for profiling tests.
func seedProfilingData(t *testing.T, s *Store) {
	t.Helper()
	now := time.Now()

	// tools/call on server "alpha" — 3 calls: 50ms, 100ms, 200ms
	for i, lat := range []int64{50, 100, 200} {
		reqID := fmt.Sprintf("alpha-call-%d", i)
		s.Insert(&TrafficEntry{
			Timestamp: now.Add(-time.Duration(i) * time.Minute), Direction: DirectionClientToServer,
			ServerName: "alpha", Method: "tools/call", MessageID: reqID,
			Payload: `{"jsonrpc":"2.0","method":"tools/call","id":"` + reqID + `"}`, Status: "pending",
		})
		s.Insert(&TrafficEntry{
			Timestamp:  now.Add(-time.Duration(i)*time.Minute + time.Duration(lat)*time.Millisecond),
			Direction:  DirectionServerToClient,
			ServerName: "alpha", Method: "tools/call", MessageID: reqID,
			Payload:    `{"jsonrpc":"2.0","id":"` + reqID + `","result":{}}`,
			Status:     "ok",
			IsResponse: true,
		})
	}

	// tools/list on server "alpha" — 1 call: 10ms
	s.Insert(&TrafficEntry{
		Timestamp: now.Add(-5 * time.Minute), Direction: DirectionClientToServer,
		ServerName: "alpha", Method: "tools/list", MessageID: "alpha-list-0",
		Payload: `{"jsonrpc":"2.0","method":"tools/list","id":"alpha-list-0"}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp:  now.Add(-5*time.Minute + 10*time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "alpha", Method: "tools/list", MessageID: "alpha-list-0",
		Payload:    `{"jsonrpc":"2.0","id":"alpha-list-0","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})

	// tools/call on server "beta" — 2 calls: 500ms (ok), 800ms (error)
	s.Insert(&TrafficEntry{
		Timestamp: now.Add(-10 * time.Minute), Direction: DirectionClientToServer,
		ServerName: "beta", Method: "tools/call", MessageID: "beta-call-0",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":"beta-call-0"}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp:  now.Add(-10*time.Minute + 500*time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "beta", Method: "tools/call", MessageID: "beta-call-0",
		Payload:    `{"jsonrpc":"2.0","id":"beta-call-0","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})
	s.Insert(&TrafficEntry{
		Timestamp: now.Add(-11 * time.Minute), Direction: DirectionClientToServer,
		ServerName: "beta", Method: "tools/call", MessageID: "beta-call-1",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":"beta-call-1"}`, Status: "pending",
	})
	s.Insert(&TrafficEntry{
		Timestamp:  now.Add(-11*time.Minute + 800*time.Millisecond),
		Direction:  DirectionServerToClient,
		ServerName: "beta", Method: "tools/call", MessageID: "beta-call-1",
		Payload:    `{"jsonrpc":"2.0","id":"beta-call-1","error":{"code":-1,"message":"fail"}}`,
		Status:     "error",
		IsResponse: true,
	})
}

func TestProfilingSummary_Basic(t *testing.T) {
	s := newTestStore(t)
	seedProfilingData(t, s)

	summary, err := s.ProfilingSummary("1h", "")
	if err != nil {
		t.Fatalf("ProfilingSummary: %v", err)
	}
	// 6 response entries total (3 alpha-call + 1 alpha-list + 2 beta-call)
	if summary.TotalCalls != 6 {
		t.Fatalf("expected 6 total calls, got %d", summary.TotalCalls)
	}
	// Avg: (50+100+200+10+500+800)/6 = 276.67
	if summary.AvgLatencyMs < 276 || summary.AvgLatencyMs > 277 {
		t.Fatalf("expected avg ~276.67ms, got %.2f", summary.AvgLatencyMs)
	}
	// P95 should be 800 (highest or near-highest value)
	if summary.P95LatencyMs < 500 {
		t.Fatalf("expected P95 >= 500ms, got %.2f", summary.P95LatencyMs)
	}
	// Error rate: 1 error out of 6 = 16.67%
	if summary.ErrorRate < 16 || summary.ErrorRate > 17 {
		t.Fatalf("expected error rate ~16.67%%, got %.2f", summary.ErrorRate)
	}
}

func TestProfilingSummary_ServerFilter(t *testing.T) {
	s := newTestStore(t)
	seedProfilingData(t, s)

	summary, err := s.ProfilingSummary("1h", "alpha")
	if err != nil {
		t.Fatalf("ProfilingSummary: %v", err)
	}
	if summary.TotalCalls != 4 {
		t.Fatalf("expected 4 alpha calls, got %d", summary.TotalCalls)
	}
	if summary.ErrorRate != 0 {
		t.Fatalf("expected 0%% error rate for alpha, got %.2f", summary.ErrorRate)
	}
}

func TestProfilingSummary_InvalidRange(t *testing.T) {
	s := newTestStore(t)
	_, err := s.ProfilingSummary("invalid", "")
	if err == nil {
		t.Fatal("expected error for invalid range")
	}
}

func TestProfilingSummary_NoData(t *testing.T) {
	s := newTestStore(t)

	summary, err := s.ProfilingSummary("1h", "")
	if err != nil {
		t.Fatalf("ProfilingSummary: %v", err)
	}
	if summary.TotalCalls != 0 {
		t.Fatalf("expected 0 calls, got %d", summary.TotalCalls)
	}
	if summary.PrevTotalCalls != nil {
		t.Fatal("expected nil prev_total_calls when no prior data")
	}
}

func TestProfilingByTool_Basic(t *testing.T) {
	s := newTestStore(t)
	seedProfilingData(t, s)

	tools, err := s.ProfilingByTool("1h", "", "p95", "desc")
	if err != nil {
		t.Fatalf("ProfilingByTool: %v", err)
	}
	if len(tools) != 3 {
		t.Fatalf("expected 3 tool groups, got %d", len(tools))
	}
	// First should be beta/tools/call (highest P95 = 800ms)
	if tools[0].Server != "beta" || tools[0].Tool != "tools/call" {
		t.Fatalf("expected beta/tools/call first, got %s/%s", tools[0].Server, tools[0].Tool)
	}
	if tools[0].Calls != 2 {
		t.Fatalf("expected 2 calls for beta/tools/call, got %d", tools[0].Calls)
	}
	if tools[0].MinMs != 500 {
		t.Fatalf("expected min 500ms for beta/tools/call, got %.2f", tools[0].MinMs)
	}
	if tools[0].MaxMs != 800 {
		t.Fatalf("expected max 800ms for beta/tools/call, got %.2f", tools[0].MaxMs)
	}
	if tools[0].ErrorRate != 50 {
		t.Fatalf("expected 50%% error rate, got %.2f", tools[0].ErrorRate)
	}
}

func TestProfilingByTool_ServerFilter(t *testing.T) {
	s := newTestStore(t)
	seedProfilingData(t, s)

	tools, err := s.ProfilingByTool("1h", "alpha", "avg", "asc")
	if err != nil {
		t.Fatalf("ProfilingByTool: %v", err)
	}
	if len(tools) != 2 {
		t.Fatalf("expected 2 tool groups for alpha, got %d", len(tools))
	}
	if tools[0].Tool != "tools/list" {
		t.Fatalf("expected tools/list first (lowest avg), got %s", tools[0].Tool)
	}
}

func TestProfilingByTool_SortCalls(t *testing.T) {
	s := newTestStore(t)
	seedProfilingData(t, s)

	tools, err := s.ProfilingByTool("1h", "", "calls", "desc")
	if err != nil {
		t.Fatalf("ProfilingByTool: %v", err)
	}
	if tools[0].Calls != 3 {
		t.Fatalf("expected highest calls=3, got %d", tools[0].Calls)
	}
	if tools[len(tools)-1].Calls != 1 {
		t.Fatalf("expected lowest calls=1, got %d", tools[len(tools)-1].Calls)
	}
}

func TestProfilingByTool_NoData(t *testing.T) {
	s := newTestStore(t)

	tools, err := s.ProfilingByTool("24h", "", "p95", "desc")
	if err != nil {
		t.Fatalf("ProfilingByTool: %v", err)
	}
	if len(tools) != 0 {
		t.Fatalf("expected 0 tools, got %d", len(tools))
	}
}

func TestPercentile_EdgeCases(t *testing.T) {
	if v := percentile(nil, 0.95); v != 0 {
		t.Fatalf("expected 0 for nil, got %f", v)
	}
	if v := percentile([]float64{42}, 0.50); v != 42 {
		t.Fatalf("expected 42, got %f", v)
	}
	if v := percentile([]float64{42}, 0.95); v != 42 {
		t.Fatalf("expected 42, got %f", v)
	}
	if v := percentile([]float64{10, 20}, 0.50); v != 10 {
		t.Fatalf("expected 10 for P50 of [10,20], got %f", v)
	}
	// With 2 values, P95 index = int(1 * 0.95) = 0, returns first value
	if v := percentile([]float64{10, 20}, 0.95); v != 10 {
		t.Fatalf("expected 10 for P95 of [10,20], got %f", v)
	}
	// With 3+ values P95 picks a higher index
	if v := percentile([]float64{10, 20, 30}, 0.95); v != 20 {
		t.Fatalf("expected 20 for P95 of [10,20,30], got %f", v)
	}
}

func TestProfilingByTool_InvalidRange(t *testing.T) {
	s := newTestStore(t)
	_, err := s.ProfilingByTool("bad", "", "p95", "desc")
	if err == nil {
		t.Fatal("expected error for invalid range")
	}
}

// --- SPEC-007: Session Recording ---

func TestStartSession(t *testing.T) {
	s := newTestStore(t)

	id, err := s.StartSession("test-session", "filesystem")
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}
	if id == 0 {
		t.Fatal("expected non-zero session ID")
	}

	sess, err := s.GetSession(id)
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if sess.Name != "test-session" {
		t.Fatalf("expected name 'test-session', got %q", sess.Name)
	}
	if sess.Server != "filesystem" {
		t.Fatalf("expected server 'filesystem', got %q", sess.Server)
	}
	if sess.Status != "recording" {
		t.Fatalf("expected status 'recording', got %q", sess.Status)
	}
	if sess.RequestCount != 0 {
		t.Fatalf("expected request_count 0, got %d", sess.RequestCount)
	}
}

func TestStopSession(t *testing.T) {
	s := newTestStore(t)

	id, err := s.StartSession("stop-test", "srv")
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}

	// Insert some traffic tagged to this session
	s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now(), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{"test":"data"}`, Status: "pending",
	}, id)

	if err := s.StopSession(id); err != nil {
		t.Fatalf("StopSession: %v", err)
	}

	sess, err := s.GetSession(id)
	if err != nil {
		t.Fatalf("GetSession: %v", err)
	}
	if sess.Status != "complete" {
		t.Fatalf("expected status 'complete', got %q", sess.Status)
	}
	if sess.DurationMs == nil {
		t.Fatal("expected non-nil duration_ms")
	}
	if sess.RequestCount != 1 {
		t.Fatalf("expected request_count 1, got %d", sess.RequestCount)
	}
	if sess.SizeBytes == 0 {
		t.Fatal("expected non-zero size_bytes")
	}
	if sess.StoppedAt == "" {
		t.Fatal("expected non-empty stopped_at")
	}
}

func TestStopSession_AlreadyStopped(t *testing.T) {
	s := newTestStore(t)

	id, _ := s.StartSession("already-stopped", "srv")
	s.StopSession(id)

	err := s.StopSession(id)
	if err == nil {
		t.Fatal("expected error stopping already-stopped session")
	}
	if !strings.Contains(err.Error(), "not recording") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestStopSession_NotFound(t *testing.T) {
	s := newTestStore(t)

	err := s.StopSession(99999)
	if err == nil {
		t.Fatal("expected error for non-existent session")
	}
}

func TestGetSession_NotFound(t *testing.T) {
	s := newTestStore(t)

	_, err := s.GetSession(99999)
	if err == nil {
		t.Fatal("expected error for non-existent session")
	}
}

func TestListSessions(t *testing.T) {
	s := newTestStore(t)

	s.StartSession("s1", "alpha")
	s.StartSession("s2", "beta")
	s.StartSession("s3", "alpha")

	// List all
	sessions, err := s.ListSessions("", "")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 3 {
		t.Fatalf("expected 3 sessions, got %d", len(sessions))
	}

	// Filter by server
	sessions, err = s.ListSessions("alpha", "")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 2 {
		t.Fatalf("expected 2 alpha sessions, got %d", len(sessions))
	}

	// Filter by status
	sessions, err = s.ListSessions("", "recording")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if len(sessions) != 3 {
		t.Fatalf("expected 3 recording sessions, got %d", len(sessions))
	}
}

func TestListSessions_Empty(t *testing.T) {
	s := newTestStore(t)

	sessions, err := s.ListSessions("", "")
	if err != nil {
		t.Fatalf("ListSessions: %v", err)
	}
	if sessions == nil {
		t.Fatal("expected non-nil empty slice")
	}
	if len(sessions) != 0 {
		t.Fatalf("expected 0 sessions, got %d", len(sessions))
	}
}

func TestDeleteSession(t *testing.T) {
	s := newTestStore(t)

	id, _ := s.StartSession("delete-me", "srv")

	// Insert traffic tagged to session
	s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now(), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{}`, Status: "pending",
	}, id)

	if err := s.DeleteSession(id); err != nil {
		t.Fatalf("DeleteSession: %v", err)
	}

	// Session should be gone
	_, err := s.GetSession(id)
	if err == nil {
		t.Fatal("expected error after deleting session")
	}

	// Traffic should still exist but unlinked
	page, _ := s.Query(1, 50, "", "")
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 traffic entry after session delete, got %d", page.TotalCount)
	}
}

func TestDeleteSession_NotFound(t *testing.T) {
	s := newTestStore(t)

	err := s.DeleteSession(99999)
	if err == nil {
		t.Fatal("expected error deleting non-existent session")
	}
}

func TestExportSession(t *testing.T) {
	s := newTestStore(t)

	id, _ := s.StartSession("export-test", "srv")

	// Insert a request and response
	s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now(), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "tools/call",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read_file"}}`,
		Status: "pending",
	}, id)
	s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now().Add(50 * time.Millisecond), Direction: DirectionServerToClient,
		ServerName: "srv", Method: "tools/call",
		Payload: `{"jsonrpc":"2.0","id":1,"result":{"content":"hello"}}`,
		Status: "ok", IsResponse: true,
	}, id)

	s.StopSession(id)

	cassette, err := s.ExportSession(id)
	if err != nil {
		t.Fatalf("ExportSession: %v", err)
	}
	if cassette.Version != 1 {
		t.Fatalf("expected version 1, got %d", cassette.Version)
	}
	if cassette.Name != "export-test" {
		t.Fatalf("expected name 'export-test', got %q", cassette.Name)
	}
	if cassette.Server != "srv" {
		t.Fatalf("expected server 'srv', got %q", cassette.Server)
	}
	if len(cassette.Requests) != 2 {
		t.Fatalf("expected 2 cassette entries, got %d", len(cassette.Requests))
	}
}

func TestExportSession_Empty(t *testing.T) {
	s := newTestStore(t)

	id, _ := s.StartSession("empty-session", "srv")
	s.StopSession(id)

	cassette, err := s.ExportSession(id)
	if err != nil {
		t.Fatalf("ExportSession: %v", err)
	}
	if len(cassette.Requests) != 0 {
		t.Fatalf("expected 0 entries, got %d", len(cassette.Requests))
	}
}

func TestExportSession_NotFound(t *testing.T) {
	s := newTestStore(t)

	_, err := s.ExportSession(99999)
	if err == nil {
		t.Fatal("expected error exporting non-existent session")
	}
}

func TestInsertWithSession_TagsTraffic(t *testing.T) {
	s := newTestStore(t)

	id, _ := s.StartSession("tag-test", "srv")

	// Insert with session
	rowID, _ := s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now(), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "test", Payload: `{}`, Status: "pending",
	}, id)

	if rowID == 0 {
		t.Fatal("expected non-zero row ID")
	}

	// Verify session request_count was incremented
	sess, _ := s.GetSession(id)
	if sess.RequestCount != 1 {
		t.Fatalf("expected request_count 1, got %d", sess.RequestCount)
	}
}

func TestInsertWithSession_ZeroSessionID(t *testing.T) {
	s := newTestStore(t)

	// Insert with session ID 0 should not tag
	rowID, _ := s.InsertWithSession(&TrafficEntry{
		Timestamp: time.Now(), Direction: DirectionClientToServer,
		ServerName: "srv", Method: "test", Payload: `{}`, Status: "pending",
	}, 0)

	if rowID == 0 {
		t.Fatal("expected non-zero row ID")
	}
}

func TestListSessions_OrderedNewestFirst(t *testing.T) {
	s := newTestStore(t)

	id1, _ := s.StartSession("first", "srv")
	id2, _ := s.StartSession("second", "srv")
	id3, _ := s.StartSession("third", "srv")

	sessions, _ := s.ListSessions("", "")
	if len(sessions) != 3 {
		t.Fatalf("expected 3, got %d", len(sessions))
	}
	if sessions[0].ID != id3 || sessions[1].ID != id2 || sessions[2].ID != id1 {
		t.Fatalf("expected newest-first order %d,%d,%d; got %d,%d,%d",
			id3, id2, id1, sessions[0].ID, sessions[1].ID, sessions[2].ID)
	}
}

// --- SPEC-009: Schema Snapshots & Changes ---

func TestSaveSnapshot_And_GetLatest(t *testing.T) {
	s := newTestStore(t)

	tools := []ToolSchema{
		{Name: "read_file", Description: "Read", InputSchema: json.RawMessage(`{"type":"object"}`)},
	}
	id, err := s.SaveSnapshot("alpha", tools)
	if err != nil {
		t.Fatalf("SaveSnapshot: %v", err)
	}
	if id == 0 {
		t.Fatal("expected non-zero snapshot ID")
	}

	got, gotID, err := s.GetLatestSnapshot("alpha")
	if err != nil {
		t.Fatalf("GetLatestSnapshot: %v", err)
	}
	if gotID != id {
		t.Fatalf("expected snapshot ID %d, got %d", id, gotID)
	}
	if len(got) != 1 || got[0].Name != "read_file" {
		t.Fatalf("unexpected snapshot content: %+v", got)
	}
}

func TestGetLatestSnapshot_NoSnapshot(t *testing.T) {
	s := newTestStore(t)

	tools, id, err := s.GetLatestSnapshot("nonexistent")
	if err != nil {
		t.Fatalf("GetLatestSnapshot: %v", err)
	}
	if tools != nil {
		t.Fatalf("expected nil tools, got %+v", tools)
	}
	if id != 0 {
		t.Fatalf("expected 0 id, got %d", id)
	}
}

func TestGetLatestSnapshot_ReturnsNewest(t *testing.T) {
	s := newTestStore(t)

	tools1 := []ToolSchema{{Name: "tool_v1"}}
	s.SaveSnapshot("alpha", tools1)

	tools2 := []ToolSchema{{Name: "tool_v2"}}
	id2, _ := s.SaveSnapshot("alpha", tools2)

	got, gotID, err := s.GetLatestSnapshot("alpha")
	if err != nil {
		t.Fatalf("GetLatestSnapshot: %v", err)
	}
	if gotID != id2 {
		t.Fatalf("expected latest snapshot ID %d, got %d", id2, gotID)
	}
	if got[0].Name != "tool_v2" {
		t.Fatalf("expected tool_v2, got %s", got[0].Name)
	}
}

// saveTestSnapshots creates two snapshot IDs for use in schema change tests.
func saveTestSnapshots(t *testing.T, s *Store, server string) (int64, int64) {
	t.Helper()
	id1, err := s.SaveSnapshot(server, []ToolSchema{{Name: "before_tool"}})
	if err != nil {
		t.Fatalf("SaveSnapshot before: %v", err)
	}
	id2, err := s.SaveSnapshot(server, []ToolSchema{{Name: "after_tool"}})
	if err != nil {
		t.Fatalf("SaveSnapshot after: %v", err)
	}
	return id1, id2
}

func TestInsertSchemaChange_And_List(t *testing.T) {
	s := newTestStore(t)
	beforeID, afterID := saveTestSnapshots(t, s, "alpha")

	diff := SchemaDiff{
		Added:   []ToolSchema{{Name: "new_tool"}},
		Removed: []ToolSchema{{Name: "old_tool"}},
	}

	id, err := s.InsertSchemaChange("alpha", diff, beforeID, afterID)
	if err != nil {
		t.Fatalf("InsertSchemaChange: %v", err)
	}
	if id == 0 {
		t.Fatal("expected non-zero change ID")
	}

	changes, err := s.ListSchemaChanges("")
	if err != nil {
		t.Fatalf("ListSchemaChanges: %v", err)
	}
	if len(changes) != 1 {
		t.Fatalf("expected 1 change, got %d", len(changes))
	}
	if changes[0].ToolsAdded != 1 {
		t.Fatalf("expected tools_added=1, got %d", changes[0].ToolsAdded)
	}
	if changes[0].ToolsRemoved != 1 {
		t.Fatalf("expected tools_removed=1, got %d", changes[0].ToolsRemoved)
	}
	if changes[0].Acknowledged {
		t.Fatal("expected not acknowledged")
	}
}

func TestListSchemaChanges_FilterByServer(t *testing.T) {
	s := newTestStore(t)
	aB, aA := saveTestSnapshots(t, s, "alpha")
	bB, bA := saveTestSnapshots(t, s, "beta")

	s.InsertSchemaChange("alpha", SchemaDiff{Added: []ToolSchema{{Name: "a"}}}, aB, aA)
	s.InsertSchemaChange("beta", SchemaDiff{Added: []ToolSchema{{Name: "b"}}}, bB, bA)

	changes, err := s.ListSchemaChanges("alpha")
	if err != nil {
		t.Fatalf("ListSchemaChanges: %v", err)
	}
	if len(changes) != 1 {
		t.Fatalf("expected 1 change for alpha, got %d", len(changes))
	}
	if changes[0].ServerName != "alpha" {
		t.Fatalf("expected server alpha, got %s", changes[0].ServerName)
	}
}

func TestGetSchemaChange(t *testing.T) {
	s := newTestStore(t)
	bID, aID := saveTestSnapshots(t, s, "alpha")

	diff := SchemaDiff{
		Added: []ToolSchema{{Name: "new_tool", Description: "desc"}},
	}
	id, _ := s.InsertSchemaChange("alpha", diff, bID, aID)

	detail, err := s.GetSchemaChange(id)
	if err != nil {
		t.Fatalf("GetSchemaChange: %v", err)
	}
	if detail.ServerName != "alpha" {
		t.Fatalf("expected server alpha, got %s", detail.ServerName)
	}
	if len(detail.DiffJSON.Added) != 1 {
		t.Fatalf("expected 1 added in diff, got %d", len(detail.DiffJSON.Added))
	}
}

func TestGetSchemaChange_NotFound(t *testing.T) {
	s := newTestStore(t)

	_, err := s.GetSchemaChange(99999)
	if err == nil {
		t.Fatal("expected error for nonexistent change")
	}
}

func TestAcknowledgeSchemaChange(t *testing.T) {
	s := newTestStore(t)
	bID, aID := saveTestSnapshots(t, s, "alpha")

	id, _ := s.InsertSchemaChange("alpha", SchemaDiff{Added: []ToolSchema{{Name: "x"}}}, bID, aID)

	err := s.AcknowledgeSchemaChange(id)
	if err != nil {
		t.Fatalf("AcknowledgeSchemaChange: %v", err)
	}

	detail, _ := s.GetSchemaChange(id)
	if !detail.Acknowledged {
		t.Fatal("expected acknowledged after AcknowledgeSchemaChange")
	}
}

func TestAcknowledgeSchemaChange_NotFound(t *testing.T) {
	s := newTestStore(t)

	err := s.AcknowledgeSchemaChange(99999)
	if err == nil {
		t.Fatal("expected error for nonexistent change")
	}
}

func TestUnacknowledgedCount(t *testing.T) {
	s := newTestStore(t)

	count, err := s.UnacknowledgedCount()
	if err != nil {
		t.Fatalf("UnacknowledgedCount: %v", err)
	}
	if count != 0 {
		t.Fatalf("expected 0, got %d", count)
	}

	aB, aA := saveTestSnapshots(t, s, "alpha")
	bB, bA := saveTestSnapshots(t, s, "beta")

	s.InsertSchemaChange("alpha", SchemaDiff{Added: []ToolSchema{{Name: "a"}}}, aB, aA)
	id2, _ := s.InsertSchemaChange("beta", SchemaDiff{Added: []ToolSchema{{Name: "b"}}}, bB, bA)

	count, _ = s.UnacknowledgedCount()
	if count != 2 {
		t.Fatalf("expected 2, got %d", count)
	}

	s.AcknowledgeSchemaChange(id2)
	count, _ = s.UnacknowledgedCount()
	if count != 1 {
		t.Fatalf("expected 1 after acknowledging one, got %d", count)
	}
}
