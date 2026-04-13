package auth

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

// mockProxy implements ProxyManager for testing.
type mockProxy struct {
	servers  []string
	sendFunc func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error)
}

func (m *mockProxy) ServersForAuth() []string { return m.servers }

func (m *mockProxy) SendRequest(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
	if m.sendFunc != nil {
		return m.sendFunc(ctx, server, method, params)
	}
	// Default: return empty tools/list response
	return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}`), nil
}

func newTestMCPHandler(t *testing.T, bootstrapToken string) (*MCPHandler, *Store) {
	t.Helper()
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), bootstrapToken)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	limiter := NewRateLimiter()
	proxy := &mockProxy{servers: []string{"fs", "cortex"}}
	h := NewMCPHandler(store, limiter, proxy)
	return h, store
}

func mcpPOST(t *testing.T, h http.Handler, body string, token string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	return w
}

// AC-1: With auth.enabled, POST /mcp without valid bearer → -32001.
func TestMCPHandler_NoToken_Unauthorized(t *testing.T) {
	h, _ := newTestMCPHandler(t, "bootstrap")

	w := mcpPOST(t, h, `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, "")
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)

	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error in response, got: %v", resp)
	}
	code, _ := errObj["code"].(float64)
	if int(code) != -32001 {
		t.Errorf("expected -32001, got %v", code)
	}
}

// AC-2 is tested at the server level (passthrough route when auth disabled).
// Here we just verify a valid token works.
func TestMCPHandler_ValidToken_Allowed(t *testing.T) {
	h, store := newTestMCPHandler(t, "bootstrap")

	// Create a token with *:* scope
	plaintext, _, err := store.GenerateToken("admin", 0, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	w := mcpPOST(t, h, `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, plaintext)
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	if _, hasError := resp["error"]; hasError {
		t.Errorf("unexpected error: %v", resp["error"])
	}
}

// AC-7: POST /mcp/{token} with valid path token authenticates (no header needed).
func TestMCPHandler_PathToken_Authenticates(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	plaintext, _, err := store.GenerateToken("path-token", 0, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{servers: []string{}}
	h := NewMCPHandler(store, limiter, proxy)

	req := httptest.NewRequest(http.MethodPost, "/mcp/"+plaintext, bytes.NewBufferString(
		`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`,
	))
	req.SetPathValue("token", plaintext)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	if _, hasError := resp["error"]; hasError {
		t.Errorf("unexpected error with path token: %v", resp["error"])
	}
}

// AC-8: POST /mcp/{token} with invalid path token → -32001.
func TestMCPHandler_PathToken_Invalid(t *testing.T) {
	h, _ := newTestMCPHandler(t, "bootstrap")

	req := httptest.NewRequest(http.MethodPost, "/mcp/badtoken", bytes.NewBufferString(
		`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`,
	))
	req.SetPathValue("token", "badtoken")
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error, got: %v", resp)
	}
	code, _ := errObj["code"].(float64)
	if int(code) != -32001 {
		t.Errorf("expected -32001, got %v", code)
	}
}

// AC-5: tools/list response filtered to token's scope patterns.
func TestMCPHandler_ToolsList_ScopeFiltered(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	// Token only has access to filesystem:*
	plaintext, _, err := store.GenerateToken("scoped", 0, []string{"filesystem:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{
		servers: []string{"filesystem", "cortex"},
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			if server == "filesystem" {
				return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"read_file"},{"name":"write_file"}]}}`), nil
			}
			return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"cortex_search"}]}}`), nil
		},
	}
	h := NewMCPHandler(store, limiter, proxy)

	w := mcpPOST(t, h, `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, plaintext)

	var resp struct {
		Result struct {
			Tools []map[string]interface{} `json:"tools"`
		} `json:"result"`
	}
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}

	for _, tool := range resp.Result.Tools {
		name, _ := tool["name"].(string)
		// All returned tools should be from the filesystem server
		if len(name) == 0 {
			t.Error("tool has no name")
		}
		// cortex_search must not appear
		if name == "cortex__cortex_search" {
			t.Errorf("cortex_search should be filtered out (AC-5)")
		}
	}

	// filesystem tools should appear
	found := false
	for _, tool := range resp.Result.Tools {
		if tool["name"] == "filesystem__read_file" {
			found = true
		}
	}
	if !found {
		t.Error("filesystem__read_file should be in tools list")
	}
}

// AC-6: tools/call for out-of-scope tool → -32001.
func TestMCPHandler_ToolsCall_OutOfScope(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	// Token only has filesystem:*
	plaintext, _, err := store.GenerateToken("fs-only", 0, []string{"filesystem:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{servers: []string{"filesystem", "cortex"}}
	h := NewMCPHandler(store, limiter, proxy)

	// Try to call cortex tool (out of scope)
	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"cortex__cortex_search","arguments":{}}}`
	w := mcpPOST(t, h, body, plaintext)

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error for out-of-scope tool call, got: %v", resp)
	}
	code, _ := errObj["code"].(float64)
	if int(code) != -32001 {
		t.Errorf("expected -32001, got %v", code)
	}
	msg, _ := errObj["message"].(string)
	if msg == "" {
		t.Error("expected non-empty error message")
	}
}

// AC-3: Token with filesystem:* can call filesystem:read_file.
func TestMCPHandler_ToolsCall_InScope(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	plaintext, _, err := store.GenerateToken("fs-only", 0, []string{"filesystem:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{
		servers: []string{"filesystem"},
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}`), nil
		},
	}
	h := NewMCPHandler(store, limiter, proxy)

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"filesystem__read_file","arguments":{"path":"/tmp/x"}}}`
	w := mcpPOST(t, h, body, plaintext)

	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	if _, hasError := resp["error"]; hasError {
		t.Errorf("unexpected error for in-scope call: %v", resp["error"])
	}
}

// AC-13: Rate limit exceeded returns -32000.
func TestMCPHandler_RateLimit(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	// Rate limit of 2 per minute
	plaintext, _, err := store.GenerateToken("rl-token", 2, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{servers: []string{}}
	h := NewMCPHandler(store, limiter, proxy)

	body := `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`

	// First two calls should succeed (well, they may get JSON-RPC errors due to proxy
	// returning empty list, but the auth layer should not reject them)
	for i := 0; i < 2; i++ {
		w := mcpPOST(t, h, body, plaintext)
		var resp map[string]interface{}
		json.NewDecoder(w.Body).Decode(&resp)
		if errObj, hasErr := resp["error"].(map[string]interface{}); hasErr {
			if code, _ := errObj["code"].(float64); int(code) == -32000 {
				t.Fatalf("call %d unexpectedly rate-limited", i+1)
			}
		}
	}

	// 3rd call must be rate-limited
	w := mcpPOST(t, h, body, plaintext)
	var resp map[string]interface{}
	json.NewDecoder(w.Body).Decode(&resp)
	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error for 3rd call, got: %v", resp)
	}
	code, _ := errObj["code"].(float64)
	if int(code) != -32000 {
		t.Errorf("expected -32000 rate limit, got %v", code)
	}
}

// R14: initialize response includes Mcp-Session-Id header.
func TestMCPHandler_Initialize_SessionID(t *testing.T) {
	dir := t.TempDir()
	store, err := NewStore(filepath.Join(dir, "auth.db"), "bootstrap")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	defer store.Close()

	plaintext, _, err := store.GenerateToken("init-token", 0, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}

	limiter := NewRateLimiter()
	proxy := &mockProxy{servers: []string{}}
	h := NewMCPHandler(store, limiter, proxy)

	body := `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{}}}`
	w := mcpPOST(t, h, body, plaintext)

	sessionID := w.Header().Get("Mcp-Session-Id")
	if sessionID == "" {
		t.Error("expected Mcp-Session-Id header on initialize response (R14)")
	}
}
