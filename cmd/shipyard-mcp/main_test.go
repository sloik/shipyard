package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

func TestRun_InitializeAndToolsList(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/gateway/tools":
			// Simulate what the server returns: Shipyard built-in tools first,
			// then child server tools. (SPEC-044 R8: bridge reads all tools from API)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"tools": []map[string]interface{}{
					{
						"name":        "shipyard__status",
						"server":      "shipyard",
						"tool":        "status",
						"enabled":     true,
						"description": "Get status of the running Shipyard instance",
						"inputSchema": map[string]interface{}{"type": "object", "properties": map[string]interface{}{}},
					},
					{
						"name":        "lmstudio__chat",
						"server":      "lmstudio",
						"tool":        "chat",
						"enabled":     true,
						"description": "Chat with the loaded model",
						"inputSchema": map[string]interface{}{"type": "object", "properties": map[string]interface{}{"message": map[string]string{"type": "string"}}},
					},
				},
			})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer api.Close()

	in := strings.NewReader(
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}` + "\n" +
			`{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}` + "\n" +
			`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}` + "\n",
	)
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", api.URL}); err != nil {
		t.Fatalf("run: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 responses, got %d: %q", len(lines), out.String())
	}

	var initResp map[string]interface{}
	if err := json.Unmarshal([]byte(lines[0]), &initResp); err != nil {
		t.Fatalf("unmarshal init response: %v", err)
	}
	result := initResp["result"].(map[string]interface{})
	if got := result["protocolVersion"]; got != protocolVer {
		t.Fatalf("expected protocolVersion %s, got %v", protocolVer, got)
	}

	var listResp map[string]interface{}
	if err := json.Unmarshal([]byte(lines[1]), &listResp); err != nil {
		t.Fatalf("unmarshal list response: %v", err)
	}
	tools := listResp["result"].(map[string]interface{})["tools"].([]interface{})
	if len(tools) != 2 {
		t.Fatalf("expected 2 tools (shipyard__status + lmstudio__chat), got %d", len(tools))
	}
	names := make([]string, 0, len(tools))
	for _, item := range tools {
		names = append(names, item.(map[string]interface{})["name"].(string))
	}
	// SPEC-044 R8: shipyard__status (double underscore) comes from the API, not hardcoded
	if !contains(names, "shipyard__status") || !contains(names, "lmstudio__chat") {
		t.Fatalf("unexpected tool names: %v", names)
	}
}

func TestRun_ToolCallRoutesToShipyard(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/tools/call":
			var body map[string]interface{}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			if body["server"] != "lmstudio" || body["tool"] != "chat" {
				t.Fatalf("unexpected routed body: %#v", body)
			}
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"result": map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": "hello from lmstudio"}},
				},
			})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer api.Close()

	in := strings.NewReader(
		`{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"lmstudio__chat","arguments":{"message":"hi"}}}` + "\n",
	)
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", api.URL}); err != nil {
		t.Fatalf("run: %v", err)
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	result := resp["result"].(map[string]interface{})
	content := result["content"].([]interface{})
	text := content[0].(map[string]interface{})["text"]
	if text != "hello from lmstudio" {
		t.Fatalf("unexpected tool text: %v", text)
	}
}

func TestRun_ShipyardUnavailableReturnsError(t *testing.T) {
	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}` + "\n")
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", "http://127.0.0.1:9"}); err != nil {
		t.Fatalf("run should handle unavailable Shipyard via MCP error response, got: %v", err)
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	errObj := resp["error"].(map[string]interface{})
	if !strings.Contains(errObj["message"].(string), "Shipyard is not running or unreachable") {
		t.Fatalf("unexpected error message: %v", errObj["message"])
	}
}

func TestRun_ConcurrentToolCallsPreserveIDs(t *testing.T) {
	var mu sync.Mutex
	var seen []string
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/tools/call":
			var body map[string]interface{}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Fatalf("decode request: %v", err)
			}
			arg := body["arguments"].(map[string]interface{})["message"].(string)
			mu.Lock()
			seen = append(seen, arg)
			mu.Unlock()
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"result": map[string]interface{}{
					"content": []map[string]string{{"type": "text", "text": arg}},
				},
			})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer api.Close()

	in := strings.NewReader(
		`{"jsonrpc":"2.0","id":"a","method":"tools/call","params":{"name":"lmstudio__chat","arguments":{"message":"first"}}}` + "\n" +
			`{"jsonrpc":"2.0","id":"b","method":"tools/call","params":{"name":"lmstudio__chat","arguments":{"message":"second"}}}` + "\n",
	)
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", api.URL}); err != nil {
		t.Fatalf("run: %v", err)
	}

	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 responses, got %d", len(lines))
	}
	gotByID := map[string]string{}
	for _, line := range lines {
		var resp map[string]interface{}
		if err := json.Unmarshal([]byte(line), &resp); err != nil {
			t.Fatalf("unmarshal response: %v", err)
		}
		id := resp["id"].(string)
		text := resp["result"].(map[string]interface{})["content"].([]interface{})[0].(map[string]interface{})["text"].(string)
		gotByID[id] = text
	}
	if gotByID["a"] != "first" || gotByID["b"] != "second" {
		t.Fatalf("unexpected id mapping: %#v", gotByID)
	}
	if len(seen) != 2 {
		t.Fatalf("expected 2 backend calls, got %d", len(seen))
	}
}

func TestRun_ToolsListUsesBackendFilteredGatewayCatalog(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/gateway/tools":
			// Simulate the server returning Shipyard tools first, then child tools.
			// The lmstudio__chat tool is absent (filtered out by gateway policy on the server side).
			// (SPEC-044 R8: bridge reads all tools from API, no hardcoded entries)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"tools": []map[string]interface{}{
					{
						"name":        "shipyard__status",
						"server":      "shipyard",
						"tool":        "status",
						"enabled":     true,
						"description": "Get Shipyard status",
						"inputSchema": map[string]interface{}{"type": "object"},
					},
					{
						"name":        "filesystem__read_file",
						"server":      "filesystem",
						"tool":        "read_file",
						"enabled":     true,
						"description": "Read a file",
						"inputSchema": map[string]interface{}{"type": "object"},
					},
				},
			})
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer api.Close()

	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}` + "\n")
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", api.URL}); err != nil {
		t.Fatalf("run: %v", err)
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	tools := resp["result"].(map[string]interface{})["tools"].([]interface{})
	if len(tools) != 2 {
		t.Fatalf("expected shipyard__status + filesystem__read_file from gateway catalog, got %d", len(tools))
	}
	names := make([]string, 0, len(tools))
	for _, item := range tools {
		names = append(names, item.(map[string]interface{})["name"].(string))
	}
	if contains(names, "lmstudio__chat") {
		t.Fatalf("expected disabled/stale tools to stay absent, got %v", names)
	}
	if !contains(names, "filesystem__read_file") {
		t.Fatalf("expected filtered gateway tool in list, got %v", names)
	}
	// SPEC-044 R8: shipyard tools now come from the API, not hardcoded
	if !contains(names, "shipyard__status") {
		t.Fatalf("expected shipyard__status from gateway catalog, got %v", names)
	}
}

func contains(items []string, want string) bool {
	for _, item := range items {
		if item == want {
			return true
		}
	}
	return false
}

// TestSPEC029_BridgeInitializeListChanged verifies AC 8 (bridge path):
// The shipyard-mcp bridge's initialize response declares listChanged: true.
func TestSPEC029_BridgeInitializeListChanged(t *testing.T) {
	srv := newMCPServer("http://127.0.0.1:9999", nil)
	req := rpcRequest{
		JSONRPC: "2.0",
		ID:      json.RawMessage(`1`),
		Method:  "initialize",
		Params:  json.RawMessage(`{"protocolVersion":"2025-11-25","capabilities":{}}`),
	}
	resp := srv.handle(context.Background(), req, 1)

	result, ok := resp.Result.(map[string]interface{})
	if !ok {
		t.Fatalf("SPEC-029 AC 8: expected result map, got: %T", resp.Result)
	}
	caps, ok := result["capabilities"].(map[string]interface{})
	if !ok {
		t.Fatalf("SPEC-029 AC 8: expected capabilities map, got: %v", result["capabilities"])
	}
	tools, ok := caps["tools"].(map[string]bool)
	if !ok {
		t.Fatalf("SPEC-029 AC 8: expected tools capability map, got: %T", caps["tools"])
	}
	if !tools["listChanged"] {
		t.Errorf("SPEC-029 AC 8: expected listChanged=true, got: %v", tools["listChanged"])
	}
}
