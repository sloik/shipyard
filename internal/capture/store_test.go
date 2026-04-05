package capture

import (
	"os"
	"path/filepath"
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
