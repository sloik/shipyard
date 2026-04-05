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
	servers  []ServerInfo
	sendFunc func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error)
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
