package web

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
)

// mockProxyManager implements ProxyManager for testing.
type mockProxyManager struct {
	servers        []ServerInfo
	sendFunc       func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error)
	restartFunc    func(name string) error
	stopFunc       func(name string) error
	activeSessions map[string]int64
}

func (m *mockProxyManager) Servers() []ServerInfo {
	return m.servers
}

func (m *mockProxyManager) SendRequest(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
	if m.sendFunc != nil {
		return m.sendFunc(ctx, server, method, params)
	}
	return nil, fmt.Errorf("sendFunc not configured")
}

func (m *mockProxyManager) RestartServer(name string) error {
	if m.restartFunc != nil {
		return m.restartFunc(name)
	}
	return fmt.Errorf("server %q not found", name)
}

func (m *mockProxyManager) StopServer(name string) error {
	if m.stopFunc != nil {
		return m.stopFunc(name)
	}
	return fmt.Errorf("server %q not found", name)
}

func (m *mockProxyManager) StartRecording(server string, sessionID int64) {
	if m.activeSessions == nil {
		m.activeSessions = make(map[string]int64)
	}
	m.activeSessions[server] = sessionID
}

func (m *mockProxyManager) StopRecording(server string) {
	if m.activeSessions != nil {
		delete(m.activeSessions, server)
	}
}

func (m *mockProxyManager) ActiveSessionID(server string) int64 {
	if m.activeSessions != nil {
		return m.activeSessions[server]
	}
	return 0
}

// newTestServer creates a Server with a real Store for testing HTTP handlers.
func newTestServer(t *testing.T) *Server {
	t.Helper()
	dir := t.TempDir()
	store, err := capture.NewStore(
		filepath.Join(dir, "test.db"),
		filepath.Join(dir, "test.jsonl"),
	)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })

	hub := NewHub()
	return NewServer(9999, store, hub)
}

// --- GET /api/servers ---

func TestHandleServers_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/servers", nil)
	w := httptest.NewRecorder()
	srv.handleServers(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected empty array, got %d items", len(result))
	}
}

func TestHandleServers_WithServers(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{
			{Name: "alpha", Status: "online"},
			{Name: "beta", Status: "online"},
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/servers", nil)
	w := httptest.NewRecorder()
	srv.handleServers(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []ServerInfo
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result))
	}
}

func TestHandleServers_Empty(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/servers", nil)
	w := httptest.NewRecorder()
	srv.handleServers(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []ServerInfo
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected 0 servers, got %d", len(result))
	}
}

// --- GET /api/tools ---

func TestHandleTools_MissingServerParam(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	req := httptest.NewRequest(http.MethodGet, "/api/tools", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleTools_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)
	// proxies is nil

	req := httptest.NewRequest(http.MethodGet, "/api/tools?server=test", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", w.Code)
	}
}

func TestHandleTools_Success(t *testing.T) {
	srv := newTestServer(t)

	// The handler sends tools/list, gets back a JSON-RPC envelope, extracts result
	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","result":{"tools":[{"name":"read_file"}]}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			if method != "tools/list" {
				t.Fatalf("expected method tools/list, got %s", method)
			}
			return json.RawMessage(rpcResponse), nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools?server=test", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	// The handler extracts "result" from the RPC envelope
	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	tools, ok := result["tools"]
	if !ok {
		t.Fatal("expected 'tools' key in response")
	}
	toolList, ok := tools.([]interface{})
	if !ok || len(toolList) != 1 {
		t.Fatalf("expected 1 tool, got %v", tools)
	}
}

func TestHandleTools_SendRequestError(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return nil, fmt.Errorf("connection refused")
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools?server=test", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}
}

func TestHandleTools_InvalidRPCResponse(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`not valid json`), nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools?server=test", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}
}

func TestHandleTools_RPCError(t *testing.T) {
	srv := newTestServer(t)

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","error":{"code":-32601,"message":"method not found"}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(rpcResponse), nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools?server=test", nil)
	w := httptest.NewRecorder()
	srv.handleTools(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["error"]; !ok {
		t.Fatal("expected 'error' key in response body")
	}
}

// --- POST /api/tools/call ---

func TestHandleToolCall_Success(t *testing.T) {
	srv := newTestServer(t)

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","result":{"content":[{"type":"text","text":"hello"}]}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			if method != "tools/call" {
				t.Fatalf("expected method tools/call, got %s", method)
			}
			return json.RawMessage(rpcResponse), nil
		},
	})

	body := `{"server":"test","tool":"read_file","arguments":{"path":"/tmp/x"}}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["result"]; !ok {
		t.Fatal("expected 'result' key")
	}
	if _, ok := result["latency_ms"]; !ok {
		t.Fatal("expected 'latency_ms' key")
	}
}

func TestHandleToolCall_MissingFields(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	tests := []struct {
		name string
		body string
	}{
		{"missing server", `{"tool":"read_file"}`},
		{"missing tool", `{"server":"test"}`},
		{"both empty", `{"server":"","tool":""}`},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(tc.body))
			w := httptest.NewRecorder()
			srv.handleToolCall(w, req)

			if w.Code != http.StatusBadRequest {
				t.Fatalf("expected 400, got %d", w.Code)
			}
		})
	}
}

func TestHandleToolCall_InvalidJSON(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(`not json`))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleToolCall_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	body := `{"server":"test","tool":"read_file"}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", w.Code)
	}
}

func TestHandleToolCall_SendRequestError(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return nil, fmt.Errorf("timeout")
		},
	})

	body := `{"server":"test","tool":"read_file"}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["latency_ms"]; !ok {
		t.Fatal("expected 'latency_ms' in error response")
	}
	if _, ok := result["error"]; !ok {
		t.Fatal("expected 'error' in error response")
	}
}

func TestHandleToolCall_RPCError(t *testing.T) {
	srv := newTestServer(t)

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","error":{"code":-32000,"message":"tool failed"}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(rpcResponse), nil
		},
	})

	body := `{"server":"test","tool":"read_file"}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	// RPC error still returns 200 (the HTTP request succeeded, the tool errored)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["error"]; !ok {
		t.Fatal("expected 'error' key for RPC error response")
	}
	if _, ok := result["latency_ms"]; !ok {
		t.Fatal("expected 'latency_ms' key")
	}
}

func TestHandleToolCall_NullArguments(t *testing.T) {
	srv := newTestServer(t)

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","result":{}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(rpcResponse), nil
		},
	})

	// arguments is null
	body := `{"server":"test","tool":"ping","arguments":null}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

// --- GET /api/traffic ---

func TestHandleTraffic_DefaultPagination(t *testing.T) {
	srv := newTestServer(t)

	// Insert a few entries
	now := time.Now()
	for i := 0; i < 3; i++ {
		srv.store.Insert(&capture.TrafficEntry{
			Timestamp:  now.Add(time.Duration(i) * time.Second),
			Direction:  capture.DirectionClientToServer,
			ServerName: "srv",
			Method:     "test",
			Payload:    `{}`,
			Status:     "pending",
		})
	}

	req := httptest.NewRequest(http.MethodGet, "/api/traffic", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.Page != 1 {
		t.Fatalf("expected page 1, got %d", page.Page)
	}
	if page.PageSize != 50 {
		t.Fatalf("expected page_size 50, got %d", page.PageSize)
	}
	if page.TotalCount != 3 {
		t.Fatalf("expected total_count 3, got %d", page.TotalCount)
	}
	if len(page.Items) != 3 {
		t.Fatalf("expected 3 items, got %d", len(page.Items))
	}
}

func TestHandleTraffic_CustomPagination(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	for i := 0; i < 5; i++ {
		srv.store.Insert(&capture.TrafficEntry{
			Timestamp:  now.Add(time.Duration(i) * time.Second),
			Direction:  capture.DirectionClientToServer,
			ServerName: "srv",
			Method:     "test",
			Payload:    `{}`,
			Status:     "pending",
		})
	}

	req := httptest.NewRequest(http.MethodGet, "/api/traffic?page=2&page_size=2", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.Page != 2 {
		t.Fatalf("expected page 2, got %d", page.Page)
	}
	if page.PageSize != 2 {
		t.Fatalf("expected page_size 2, got %d", page.PageSize)
	}
	if len(page.Items) != 2 {
		t.Fatalf("expected 2 items, got %d", len(page.Items))
	}
}

func TestHandleTraffic_InvalidPage(t *testing.T) {
	srv := newTestServer(t)

	// Invalid page should default to 1
	req := httptest.NewRequest(http.MethodGet, "/api/traffic?page=abc&page_size=-5", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.Page != 1 {
		t.Fatalf("expected page 1 (default), got %d", page.Page)
	}
	if page.PageSize != 50 {
		t.Fatalf("expected page_size 50 (default), got %d", page.PageSize)
	}
}

func TestHandleTraffic_Filters(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "alpha", Method: "tools/list", Payload: `{}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "beta", Method: "tools/call", Payload: `{}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "alpha", Method: "tools/call", Payload: `{}`, Status: "pending",
	})

	// Filter by server
	req := httptest.NewRequest(http.MethodGet, "/api/traffic?server=alpha", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.TotalCount != 2 {
		t.Fatalf("expected 2 alpha entries, got %d", page.TotalCount)
	}

	// Filter by method
	req2 := httptest.NewRequest(http.MethodGet, "/api/traffic?method=tools/call", nil)
	w2 := httptest.NewRecorder()
	srv.handleTraffic(w2, req2)

	var page2 capture.TrafficPage
	if err := json.Unmarshal(w2.Body.Bytes(), &page2); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page2.TotalCount != 2 {
		t.Fatalf("expected 2 tools/call entries, got %d", page2.TotalCount)
	}
}

// --- GET /api/traffic/{id} ---

func TestHandleTrafficDetail_Success(t *testing.T) {
	srv := newTestServer(t)

	id, _ := srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  capture.DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/list",
		MessageID:  "1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/list","id":1}`,
		Status:     "pending",
	})

	// Use the mux pattern /api/traffic/{id} — we need to set the path value
	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/traffic/%d", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleTrafficDetail(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["entry"]; !ok {
		t.Fatal("expected 'entry' key in response")
	}
}

// --- POST /api/replay (SPEC-003 AC-1) ---

func TestHandleReplay_Success(t *testing.T) {
	srv := newTestServer(t)

	// Insert a request traffic entry (tools/call for "read_file" on server "alpha")
	id, _ := srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  capture.DirectionClientToServer,
		ServerName: "alpha",
		Method:     "tools/call",
		MessageID:  "1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read_file","arguments":{"path":"/tmp/x"}}}`,
		Status:     "pending",
	})

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","result":{"content":[{"type":"text","text":"hello"}]}}`
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{{Name: "alpha", Status: "online"}},
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			if server != "alpha" {
				t.Fatalf("expected server alpha, got %s", server)
			}
			if method != "tools/call" {
				t.Fatalf("expected method tools/call, got %s", method)
			}
			return json.RawMessage(rpcResponse), nil
		},
	})

	body := fmt.Sprintf(`{"id":%d}`, id)
	req := httptest.NewRequest(http.MethodPost, "/api/replay", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleReplay(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", w.Code, w.Body.String())
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := result["result"]; !ok {
		t.Fatal("expected 'result' key")
	}
	if _, ok := result["latency_ms"]; !ok {
		t.Fatal("expected 'latency_ms' key")
	}
}

func TestHandleReplay_NotFound(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	body := `{"id":99999}`
	req := httptest.NewRequest(http.MethodPost, "/api/replay", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleReplay(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleReplay_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	body := `{"id":1}`
	req := httptest.NewRequest(http.MethodPost, "/api/replay", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleReplay(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", w.Code)
	}
}

func TestHandleReplay_InvalidJSON(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	req := httptest.NewRequest(http.MethodPost, "/api/replay", strings.NewReader(`not json`))
	w := httptest.NewRecorder()
	srv.handleReplay(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleReplay_SendRequestError(t *testing.T) {
	srv := newTestServer(t)

	id, _ := srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  capture.DirectionClientToServer,
		ServerName: "alpha",
		Method:     "tools/call",
		MessageID:  "1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read_file","arguments":{"path":"/tmp/x"}}}`,
		Status:     "pending",
	})

	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return nil, fmt.Errorf("connection refused")
		},
	})

	body := fmt.Sprintf(`{"id":%d}`, id)
	req := httptest.NewRequest(http.MethodPost, "/api/replay", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleReplay(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}
}

// --- GET /api/traffic with extended filters (SPEC-003 AC-4) ---

func TestHandleTraffic_SearchFilter(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{"name":"read_file"}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{"name":"write_file"}`, Status: "pending",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/traffic?search=read_file", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 result for search=read_file, got %d", page.TotalCount)
	}
}

func TestHandleTraffic_DirectionFilter(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "tools/call", Payload: `{}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now.Add(10 * time.Millisecond), Direction: capture.DirectionServerToClient,
		ServerName: "srv", Method: "", Payload: `{"result":{}}`, Status: "ok", IsResponse: true,
	})

	req := httptest.NewRequest(http.MethodGet, "/api/traffic?direction="+capture.DirectionClientToServer, nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 request entry, got %d", page.TotalCount)
	}
}

func TestHandleTraffic_TimeRangeFilter(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now.Add(-2 * time.Hour), Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "old", Payload: `{}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "new", Payload: `{}`, Status: "pending",
	})

	fromTs := now.Add(-1 * time.Hour).UnixMilli()
	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/traffic?from_ts=%d", fromTs), nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.TotalCount != 1 {
		t.Fatalf("expected 1 recent entry, got %d", page.TotalCount)
	}
}

func TestHandleTrafficDetail_InvalidID(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/traffic/abc", nil)
	req.SetPathValue("id", "abc")
	w := httptest.NewRecorder()
	srv.handleTrafficDetail(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleTrafficDetail_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/traffic/99999", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleTrafficDetail(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

// --- POST /api/servers/{name}/restart (SPEC-004 AC-4) ---

func TestHandleServerRestart_Success(t *testing.T) {
	srv := newTestServer(t)
	var restarted string
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{{Name: "alpha", Status: "online"}},
		restartFunc: func(name string) error {
			restarted = name
			return nil
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/api/servers/alpha/restart", nil)
	req.SetPathValue("name", "alpha")
	w := httptest.NewRecorder()
	srv.handleServerRestart(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", w.Code, w.Body.String())
	}
	if restarted != "alpha" {
		t.Fatalf("expected restart of alpha, got %q", restarted)
	}

	var result map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if result["status"] != "restarting" {
		t.Fatalf("expected status restarting, got %q", result["status"])
	}
}

func TestHandleServerRestart_NotFound(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		restartFunc: func(name string) error {
			return fmt.Errorf("server %q not found", name)
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/api/servers/nonexistent/restart", nil)
	req.SetPathValue("name", "nonexistent")
	w := httptest.NewRecorder()
	srv.handleServerRestart(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleServerRestart_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodPost, "/api/servers/alpha/restart", nil)
	req.SetPathValue("name", "alpha")
	w := httptest.NewRecorder()
	srv.handleServerRestart(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", w.Code)
	}
}

// --- POST /api/servers/{name}/stop (SPEC-004 AC-4) ---

func TestHandleServerStop_Success(t *testing.T) {
	srv := newTestServer(t)
	var stopped string
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{{Name: "beta", Status: "online"}},
		stopFunc: func(name string) error {
			stopped = name
			return nil
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/api/servers/beta/stop", nil)
	req.SetPathValue("name", "beta")
	w := httptest.NewRecorder()
	srv.handleServerStop(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", w.Code, w.Body.String())
	}
	if stopped != "beta" {
		t.Fatalf("expected stop of beta, got %q", stopped)
	}
}

func TestHandleServerStop_NotFound(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		stopFunc: func(name string) error {
			return fmt.Errorf("server %q not found", name)
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/api/servers/nonexistent/stop", nil)
	req.SetPathValue("name", "nonexistent")
	w := httptest.NewRecorder()
	srv.handleServerStop(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

// --- GET /api/servers with enriched info (SPEC-004 AC-2) ---

func TestHandleServers_EnrichedInfo(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{
			{Name: "alpha", Status: "online", Command: "node server.js", ToolCount: 5, Uptime: 60000, RestartCount: 1},
			{Name: "beta", Status: "crashed", Command: "python mcp.py", ErrorMessage: "exit code 1"},
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/servers", nil)
	w := httptest.NewRecorder()
	srv.handleServers(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []ServerInfo
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result))
	}

	// Check enriched fields
	for _, s := range result {
		if s.Name == "alpha" {
			if s.Command != "node server.js" {
				t.Fatalf("expected command 'node server.js', got %q", s.Command)
			}
			if s.ToolCount != 5 {
				t.Fatalf("expected tool_count 5, got %d", s.ToolCount)
			}
			if s.RestartCount != 1 {
				t.Fatalf("expected restart_count 1, got %d", s.RestartCount)
			}
		}
		if s.Name == "beta" {
			if s.Status != "crashed" {
				t.Fatalf("expected status crashed, got %q", s.Status)
			}
			if s.ErrorMessage != "exit code 1" {
				t.Fatalf("expected error message, got %q", s.ErrorMessage)
			}
		}
	}
}

// --- GET /api/auto-import (SPEC-004 AC-5) ---

func TestHandleAutoImportScan(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{{Name: "existing-server", Status: "online"}},
	})

	orig := autoImportScanner
	t.Cleanup(func() { autoImportScanner = orig })

	autoImportScanner = func(existing map[string]bool) []DiscoveredServer {
		if !existing["existing-server"] {
			t.Fatal("expected existing-server in existing map")
		}
		return []DiscoveredServer{
			{Name: "new-server", Command: "node mcp.js", Source: "claude-code", Status: "new"},
			{Name: "existing-server", Command: "python srv.py", Source: "claude-desktop", Status: "already_imported"},
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/api/auto-import", nil)
	w := httptest.NewRecorder()
	srv.handleAutoImportScan(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []DiscoveredServer
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 2 {
		t.Fatalf("expected 2 discovered servers, got %d", len(result))
	}
	if result[0].Status != "new" {
		t.Fatalf("expected first server status 'new', got %q", result[0].Status)
	}
	if result[1].Status != "already_imported" {
		t.Fatalf("expected second server status 'already_imported', got %q", result[1].Status)
	}
}

func TestHandleAutoImportScan_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)
	// proxies is nil

	orig := autoImportScanner
	t.Cleanup(func() { autoImportScanner = orig })

	autoImportScanner = func(existing map[string]bool) []DiscoveredServer {
		if len(existing) != 0 {
			t.Fatalf("expected empty existing map when no proxy manager, got %v", existing)
		}
		return []DiscoveredServer{
			{Name: "new-server", Command: "node mcp.js", Source: "claude-code", Status: "new"},
		}
	}

	req := httptest.NewRequest(http.MethodGet, "/api/auto-import", nil)
	w := httptest.NewRecorder()
	srv.handleAutoImportScan(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

// --- GET /api/tools/conflicts (SPEC-004 AC-6) ---

func TestHandleToolConflicts_NoConflicts(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{
			{Name: "alpha", Status: "online"},
			{Name: "beta", Status: "online"},
		},
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			if server == "alpha" {
				return json.RawMessage(`{"jsonrpc":"2.0","id":"1","result":{"tools":[{"name":"read_file"}]}}`), nil
			}
			return json.RawMessage(`{"jsonrpc":"2.0","id":"1","result":{"tools":[{"name":"write_file"}]}}`), nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools/conflicts", nil)
	w := httptest.NewRecorder()
	srv.handleToolConflicts(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected 0 conflicts, got %d", len(result))
	}
}

func TestHandleToolConflicts_WithConflicts(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{
			{Name: "alpha", Status: "online"},
			{Name: "beta", Status: "online"},
		},
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			// Both servers have "read_file" tool
			return json.RawMessage(`{"jsonrpc":"2.0","id":"1","result":{"tools":[{"name":"read_file"},{"name":"write_file"}]}}`), nil
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/tools/conflicts", nil)
	w := httptest.NewRecorder()
	srv.handleToolConflicts(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []struct {
		ToolName string   `json:"tool_name"`
		Servers  []string `json:"servers"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	// Both read_file and write_file should be conflicts
	if len(result) != 2 {
		t.Fatalf("expected 2 conflicts, got %d: %s", len(result), w.Body.String())
	}
	for _, c := range result {
		if len(c.Servers) != 2 {
			t.Fatalf("expected 2 servers for conflict %q, got %d", c.ToolName, len(c.Servers))
		}
	}
}

func TestHandleToolConflicts_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/tools/conflicts", nil)
	w := httptest.NewRecorder()
	srv.handleToolConflicts(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected empty array, got %d", len(result))
	}
}

// --- SPEC-008: Latency Profiling Handlers ---

func seedProfilingTraffic(t *testing.T, srv *Server) {
	t.Helper()
	now := time.Now()
	// Insert a request+response pair with known latency
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp: now.Add(-5 * time.Minute), Direction: capture.DirectionClientToServer,
		ServerName: "alpha", Method: "tools/call", MessageID: "prof-1",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":"prof-1"}`, Status: "pending",
	})
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  now.Add(-5*time.Minute + 120*time.Millisecond),
		Direction:  capture.DirectionServerToClient,
		ServerName: "alpha", Method: "tools/call", MessageID: "prof-1",
		Payload:    `{"jsonrpc":"2.0","id":"prof-1","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})
}

func TestHandleProfilingSummary_Default(t *testing.T) {
	srv := newTestServer(t)
	seedProfilingTraffic(t, srv)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/summary", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingSummary(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result capture.ProfilingSummaryResult
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if result.TotalCalls != 1 {
		t.Fatalf("expected 1 call, got %d", result.TotalCalls)
	}
	if result.AvgLatencyMs < 100 {
		t.Fatalf("expected avg >= 100ms, got %.2f", result.AvgLatencyMs)
	}
}

func TestHandleProfilingSummary_WithRange(t *testing.T) {
	srv := newTestServer(t)
	seedProfilingTraffic(t, srv)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/summary?range=1h", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingSummary(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestHandleProfilingSummary_InvalidRange(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/summary?range=invalid", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingSummary(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleProfilingSummary_EmptyData(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/summary?range=1h", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingSummary(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result capture.ProfilingSummaryResult
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if result.TotalCalls != 0 {
		t.Fatalf("expected 0 calls, got %d", result.TotalCalls)
	}
}

func TestHandleProfilingTools_Default(t *testing.T) {
	srv := newTestServer(t)
	seedProfilingTraffic(t, srv)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/tools", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []capture.ToolProfile
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 1 {
		t.Fatalf("expected 1 tool, got %d", len(result))
	}
	if result[0].Tool != "tools/call" {
		t.Fatalf("expected tools/call, got %s", result[0].Tool)
	}
}

func TestHandleProfilingTools_WithParams(t *testing.T) {
	srv := newTestServer(t)
	seedProfilingTraffic(t, srv)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/tools?range=1h&server=alpha&sort=avg&order=asc", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestHandleProfilingTools_EmptyData(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/tools?range=1h", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result []capture.ToolProfile
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(result) != 0 {
		t.Fatalf("expected 0 tools, got %d", len(result))
	}
}

func TestHandleProfilingTools_InvalidRange(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/profiling/tools?range=bad", nil)
	w := httptest.NewRecorder()
	srv.handleProfilingTools(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

// --- SPEC-007: Session Recording Handlers ---

func TestHandleSessionStart(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	body := `{"name":"test-session","server":"filesystem"}`
	req := httptest.NewRequest(http.MethodPost, "/api/sessions/start", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleSessionStart(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var sess capture.Session
	if err := json.Unmarshal(w.Body.Bytes(), &sess); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if sess.ID == 0 {
		t.Fatal("expected non-zero session ID")
	}
	if sess.Name != "test-session" {
		t.Fatalf("expected name 'test-session', got %q", sess.Name)
	}
	if sess.Status != "recording" {
		t.Fatalf("expected status 'recording', got %q", sess.Status)
	}
}

func TestHandleSessionStart_InvalidJSON(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodPost, "/api/sessions/start", strings.NewReader(`not json`))
	w := httptest.NewRecorder()
	srv.handleSessionStart(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleSessionStop(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	// Start a session first
	id, _ := srv.store.StartSession("stop-test", "srv")

	req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/sessions/%d/stop", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionStop(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var sess capture.Session
	if err := json.Unmarshal(w.Body.Bytes(), &sess); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if sess.Status != "complete" {
		t.Fatalf("expected status 'complete', got %q", sess.Status)
	}
}

func TestHandleSessionStop_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodPost, "/api/sessions/99999/stop", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSessionStop(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSessionStop_AlreadyStopped(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	id, _ := srv.store.StartSession("already-stopped", "srv")
	srv.store.StopSession(id)

	req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/sessions/%d/stop", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionStop(w, req)

	if w.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d", w.Code)
	}
}

func TestHandleSessionList(t *testing.T) {
	srv := newTestServer(t)

	srv.store.StartSession("s1", "alpha")
	srv.store.StartSession("s2", "beta")

	req := httptest.NewRequest(http.MethodGet, "/api/sessions", nil)
	w := httptest.NewRecorder()
	srv.handleSessionList(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var sessions []capture.Session
	if err := json.Unmarshal(w.Body.Bytes(), &sessions); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(sessions) != 2 {
		t.Fatalf("expected 2 sessions, got %d", len(sessions))
	}
}

func TestHandleSessionList_FilterByServer(t *testing.T) {
	srv := newTestServer(t)

	srv.store.StartSession("s1", "alpha")
	srv.store.StartSession("s2", "beta")

	req := httptest.NewRequest(http.MethodGet, "/api/sessions?server=alpha", nil)
	w := httptest.NewRecorder()
	srv.handleSessionList(w, req)

	var sessions []capture.Session
	json.Unmarshal(w.Body.Bytes(), &sessions)
	if len(sessions) != 1 {
		t.Fatalf("expected 1 alpha session, got %d", len(sessions))
	}
}

func TestHandleSessionDetail(t *testing.T) {
	srv := newTestServer(t)

	id, _ := srv.store.StartSession("detail-test", "srv")

	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/sessions/%d", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionDetail(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var sess capture.Session
	json.Unmarshal(w.Body.Bytes(), &sess)
	if sess.Name != "detail-test" {
		t.Fatalf("expected name 'detail-test', got %q", sess.Name)
	}
}

func TestHandleSessionDetail_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/sessions/99999", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSessionDetail(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSessionExport(t *testing.T) {
	srv := newTestServer(t)

	id, _ := srv.store.StartSession("export-test", "srv")
	srv.store.InsertWithSession(&capture.TrafficEntry{
		Timestamp: time.Now(), Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "tools/call",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read_file"}}`,
		Status: "pending",
	}, id)
	srv.store.StopSession(id)

	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/sessions/%d/export", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionExport(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	if ct := w.Header().Get("Content-Disposition"); ct == "" {
		t.Fatal("expected Content-Disposition header")
	}

	var cassette capture.SessionCassette
	if err := json.Unmarshal(w.Body.Bytes(), &cassette); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if cassette.Version != 1 {
		t.Fatalf("expected version 1, got %d", cassette.Version)
	}
	if len(cassette.Requests) != 1 {
		t.Fatalf("expected 1 request, got %d", len(cassette.Requests))
	}
}

func TestHandleSessionExport_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/sessions/99999/export", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSessionExport(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSessionReplay(t *testing.T) {
	srv := newTestServer(t)

	rpcResponse := `{"jsonrpc":"2.0","id":"shipyard-1","result":{"ok":true}}`
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(rpcResponse), nil
		},
	})

	id, _ := srv.store.StartSession("replay-test", "srv")
	srv.store.InsertWithSession(&capture.TrafficEntry{
		Timestamp: time.Now(), Direction: capture.DirectionClientToServer,
		ServerName: "srv", Method: "tools/call",
		Payload: `{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read_file"}}`,
		Status: "pending",
	}, id)
	srv.store.StopSession(id)

	req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/sessions/%d/replay", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionReplay(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}

	var result map[string]interface{}
	json.Unmarshal(w.Body.Bytes(), &result)
	if _, ok := result["results"]; !ok {
		t.Fatal("expected 'results' key in response")
	}
}

func TestHandleSessionReplay_NoProxyManager(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodPost, "/api/sessions/1/replay", nil)
	req.SetPathValue("id", "1")
	w := httptest.NewRecorder()
	srv.handleSessionReplay(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", w.Code)
	}
}

func TestHandleSessionReplay_NotFound(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	req := httptest.NewRequest(http.MethodPost, "/api/sessions/99999/replay", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSessionReplay(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSessionDelete(t *testing.T) {
	srv := newTestServer(t)

	id, _ := srv.store.StartSession("delete-test", "srv")

	req := httptest.NewRequest(http.MethodDelete, fmt.Sprintf("/api/sessions/%d", id), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", id))
	w := httptest.NewRecorder()
	srv.handleSessionDelete(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]string
	json.Unmarshal(w.Body.Bytes(), &result)
	if result["status"] != "deleted" {
		t.Fatalf("expected status 'deleted', got %q", result["status"])
	}
}

func TestHandleSessionDelete_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodDelete, "/api/sessions/99999", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSessionDelete(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

// --- SPEC-009: Schema Change Detection Handlers ---

func TestHandleSchemaChanges_Empty(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/changes", nil)
	w := httptest.NewRecorder()
	srv.handleSchemaChanges(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var changes []capture.SchemaChange
	if err := json.Unmarshal(w.Body.Bytes(), &changes); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if len(changes) != 0 {
		t.Fatalf("expected 0 changes, got %d", len(changes))
	}
}

func TestHandleSchemaChanges_WithData(t *testing.T) {
	srv := newTestServer(t)

	bID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "before"}})
	aID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "after"}})
	srv.store.InsertSchemaChange("alpha", capture.SchemaDiff{Added: []capture.ToolSchema{{Name: "new"}}}, bID, aID)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/changes", nil)
	w := httptest.NewRecorder()
	srv.handleSchemaChanges(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var changes []capture.SchemaChange
	json.Unmarshal(w.Body.Bytes(), &changes)
	if len(changes) != 1 {
		t.Fatalf("expected 1 change, got %d", len(changes))
	}
}

func TestHandleSchemaChanges_FilterByServer(t *testing.T) {
	srv := newTestServer(t)

	aB, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "x"}})
	aA, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "y"}})
	bB, _ := srv.store.SaveSnapshot("beta", []capture.ToolSchema{{Name: "x"}})
	bA, _ := srv.store.SaveSnapshot("beta", []capture.ToolSchema{{Name: "y"}})
	srv.store.InsertSchemaChange("alpha", capture.SchemaDiff{Added: []capture.ToolSchema{{Name: "a"}}}, aB, aA)
	srv.store.InsertSchemaChange("beta", capture.SchemaDiff{Added: []capture.ToolSchema{{Name: "b"}}}, bB, bA)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/changes?server=alpha", nil)
	w := httptest.NewRecorder()
	srv.handleSchemaChanges(w, req)

	var changes []capture.SchemaChange
	json.Unmarshal(w.Body.Bytes(), &changes)
	if len(changes) != 1 {
		t.Fatalf("expected 1 change for alpha, got %d", len(changes))
	}
}

func TestHandleSchemaChangeDetail(t *testing.T) {
	srv := newTestServer(t)

	bID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "before"}})
	aID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "after"}})
	changeID, _ := srv.store.InsertSchemaChange("alpha", capture.SchemaDiff{
		Added: []capture.ToolSchema{{Name: "new_tool"}},
	}, bID, aID)

	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/schema/changes/%d", changeID), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", changeID))
	w := httptest.NewRecorder()
	srv.handleSchemaChangeDetail(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var detail capture.SchemaChangeDetail
	json.Unmarshal(w.Body.Bytes(), &detail)
	if len(detail.DiffJSON.Added) != 1 {
		t.Fatalf("expected 1 added tool in diff, got %d", len(detail.DiffJSON.Added))
	}
}

func TestHandleSchemaChangeDetail_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/changes/99999", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSchemaChangeDetail(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSchemaChangeDetail_InvalidID(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/changes/abc", nil)
	req.SetPathValue("id", "abc")
	w := httptest.NewRecorder()
	srv.handleSchemaChangeDetail(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleSchemaAcknowledge(t *testing.T) {
	srv := newTestServer(t)

	bID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "x"}})
	aID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "y"}})
	changeID, _ := srv.store.InsertSchemaChange("alpha", capture.SchemaDiff{
		Added: []capture.ToolSchema{{Name: "new"}},
	}, bID, aID)

	req := httptest.NewRequest(http.MethodPost, fmt.Sprintf("/api/schema/changes/%d/ack", changeID), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", changeID))
	w := httptest.NewRecorder()
	srv.handleSchemaAcknowledge(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	detail, _ := srv.store.GetSchemaChange(changeID)
	if !detail.Acknowledged {
		t.Fatal("expected change to be acknowledged")
	}
}

func TestHandleSchemaAcknowledge_NotFound(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodPost, "/api/schema/changes/99999/ack", nil)
	req.SetPathValue("id", "99999")
	w := httptest.NewRecorder()
	srv.handleSchemaAcknowledge(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}
}

func TestHandleSchemaCurrentTools(t *testing.T) {
	srv := newTestServer(t)

	srv.store.SaveSnapshot("alpha", []capture.ToolSchema{
		{Name: "read_file", Description: "Read a file"},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/schema/current/alpha", nil)
	req.SetPathValue("server", "alpha")
	w := httptest.NewRecorder()
	srv.handleSchemaCurrentTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var tools []capture.ToolSchema
	json.Unmarshal(w.Body.Bytes(), &tools)
	if len(tools) != 1 {
		t.Fatalf("expected 1 tool, got %d", len(tools))
	}
	if tools[0].Name != "read_file" {
		t.Fatalf("expected read_file, got %s", tools[0].Name)
	}
}

func TestHandleSchemaCurrentTools_NoSnapshot(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/current/nonexistent", nil)
	req.SetPathValue("server", "nonexistent")
	w := httptest.NewRecorder()
	srv.handleSchemaCurrentTools(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var tools []capture.ToolSchema
	json.Unmarshal(w.Body.Bytes(), &tools)
	if len(tools) != 0 {
		t.Fatalf("expected 0 tools, got %d", len(tools))
	}
}

func TestHandleSchemaUnackCount(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/unacknowledged-count", nil)
	w := httptest.NewRecorder()
	srv.handleSchemaUnackCount(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]int
	json.Unmarshal(w.Body.Bytes(), &result)
	if result["count"] != 0 {
		t.Fatalf("expected count 0, got %d", result["count"])
	}
}

func TestHandleSchemaUnackCount_WithChanges(t *testing.T) {
	srv := newTestServer(t)

	bID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "x"}})
	aID, _ := srv.store.SaveSnapshot("alpha", []capture.ToolSchema{{Name: "y"}})
	srv.store.InsertSchemaChange("alpha", capture.SchemaDiff{Added: []capture.ToolSchema{{Name: "a"}}}, bID, aID)

	req := httptest.NewRequest(http.MethodGet, "/api/schema/unacknowledged-count", nil)
	w := httptest.NewRecorder()
	srv.handleSchemaUnackCount(w, req)

	var result map[string]int
	json.Unmarshal(w.Body.Bytes(), &result)
	if result["count"] != 1 {
		t.Fatalf("expected count 1, got %d", result["count"])
	}
}
