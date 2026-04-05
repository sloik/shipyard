package capture

import (
	"database/sql"
	"errors"
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
