package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const (
	defaultAPIBase = "http://127.0.0.1:9417"
	protocolVer    = "2025-11-25"
)

var exitFn = os.Exit

func main() {
	if err := run(context.Background(), os.Stdin, os.Stdout, os.Stderr, os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err.Error())
		exitFn(1)
	}
}

func run(ctx context.Context, stdin io.Reader, stdout, stderr io.Writer, args []string) error {
	fs := flag.NewFlagSet("shipyard-mcp", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	apiBase := fs.String("api-base", defaultAPIBase, "Shipyard HTTP API base URL")
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("parse flags: %w", err)
	}

	srv := newMCPServer(strings.TrimRight(*apiBase, "/"), &http.Client{Timeout: 2 * time.Second})
	return srv.serve(ctx, stdin, stdout, stderr)
}

type mcpServer struct {
	apiBase    string
	httpClient *http.Client
	writeMu    sync.Mutex
}

func newMCPServer(apiBase string, httpClient *http.Client) *mcpServer {
	return &mcpServer{apiBase: apiBase, httpClient: httpClient}
}

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	ID      interface{} `json:"id,omitempty"`
	Result  interface{} `json:"result,omitempty"`
	Error   *rpcError   `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type shipyardServer struct {
	Name      string `json:"name"`
	Status    string `json:"status"`
	ToolCount int    `json:"tool_count"`
}

type shipyardTool struct {
	Name         string          `json:"name"`
	Server       string          `json:"server"`
	Tool         string          `json:"tool"`
	Enabled      bool            `json:"enabled"`
	Description  string          `json:"description"`
	InputSchema  json.RawMessage `json:"inputSchema"`
	InputSchema2 json.RawMessage `json:"input_schema"`
}

type toolsEnvelope struct {
	Tools []shipyardTool `json:"tools"`
}

type toolCallRequest struct {
	Server    string          `json:"server"`
	Tool      string          `json:"tool"`
	Arguments json.RawMessage `json:"arguments,omitempty"`
}

type toolCallResponse struct {
	Result json.RawMessage `json:"result"`
	Error  json.RawMessage `json:"error"`
}

func (s *mcpServer) serve(ctx context.Context, stdin io.Reader, stdout, stderr io.Writer) error {
	// SPEC-029 R8/R11: poll gateway policy and send notifications/tools/list_changed when it changes.
	go s.watchPolicyAndNotify(ctx, stdout)

	scanner := bufio.NewScanner(stdin)
	buf := make([]byte, 0, 1024*1024)
	scanner.Buffer(buf, 8*1024*1024)

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			continue
		}
		var req rpcRequest
		if err := json.Unmarshal(line, &req); err != nil {
			s.writeResponse(stdout, rpcResponse{
				JSONRPC: "2.0",
				Error:   &rpcError{Code: -32700, Message: "parse error"},
			})
			continue
		}

		if strings.HasPrefix(req.Method, "notifications/") {
			continue
		}

		id := decodeID(req.ID)
		resp := s.handle(ctx, req, id)
		if req.ID != nil {
			s.writeResponse(stdout, resp)
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read stdin: %w", err)
	}
	return nil
}

// watchPolicyAndNotify polls the Shipyard gateway policy endpoint every 2 seconds.
// When the policy changes, it sends a notifications/tools/list_changed JSON-RPC notification
// to the MCP client (e.g. Claude) via stdout. SPEC-029 R8, R11.
func (s *mcpServer) watchPolicyAndNotify(ctx context.Context, stdout io.Writer) {
	const pollInterval = 2 * time.Second
	var lastHash [32]byte
	first := true

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		policy, err := s.fetchPolicyRaw(ctx)
		if err != nil {
			// Shipyard may not be up yet; silently retry.
			continue
		}

		h := sha256.Sum256(policy)
		if first {
			lastHash = h
			first = false
			continue
		}

		if h != lastHash {
			lastHash = h
			// Send notifications/tools/list_changed to the MCP client.
			s.writeNotification(stdout, "notifications/tools/list_changed")
		}
	}
}

// writeNotification writes a JSON-RPC notification (no id) to stdout.
func (s *mcpServer) writeNotification(stdout io.Writer, method string) {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	enc := json.NewEncoder(stdout)
	_ = enc.Encode(map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  method,
	})
}

// fetchPolicyRaw returns the raw JSON body of GET /api/gateway/policy.
func (s *mcpServer) fetchPolicyRaw(ctx context.Context) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.apiBase+"/api/gateway/policy", nil)
	if err != nil {
		return nil, err
	}
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("gateway policy returned %d", resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

func (s *mcpServer) handle(ctx context.Context, req rpcRequest, id interface{}) rpcResponse {
	switch req.Method {
	case "initialize":
		return rpcResponse{
			JSONRPC: "2.0",
			ID:      id,
			Result: map[string]interface{}{
				"protocolVersion": protocolVer,
				"serverInfo": map[string]string{
					"name":    "shipyard-mcp",
					"version": "0.1.0",
				},
				"capabilities": map[string]interface{}{
					"tools": map[string]bool{"listChanged": true},
				},
			},
		}
	case "tools/list":
		tools, err := s.listTools(ctx)
		if err != nil {
			return rpcResponse{JSONRPC: "2.0", ID: id, Error: &rpcError{Code: -32603, Message: err.Error()}}
		}
		return rpcResponse{JSONRPC: "2.0", ID: id, Result: map[string]interface{}{"tools": tools}}
	case "tools/call":
		result, err := s.callTool(ctx, req.Params)
		if err != nil {
			return rpcResponse{JSONRPC: "2.0", ID: id, Error: &rpcError{Code: -32603, Message: err.Error()}}
		}
		return rpcResponse{JSONRPC: "2.0", ID: id, Result: result}
	default:
		return rpcResponse{JSONRPC: "2.0", ID: id, Error: &rpcError{Code: -32601, Message: "method not found"}}
	}
}

func (s *mcpServer) listTools(ctx context.Context) ([]map[string]interface{}, error) {
	// Shipyard's built-in management tools (shipyard__status, etc.) are now returned
	// by GET /api/gateway/tools as the first entries. No hardcoded entries needed here.
	// (R8: removes the old hardcoded shipyard_status entry — SPEC-044)
	var tools []map[string]interface{}

	envelope, err := s.fetchGatewayTools(ctx)
	if err != nil {
		return nil, err
	}
	for _, tool := range envelope.Tools {
		schema := map[string]interface{}{"type": "object", "properties": map[string]interface{}{}}
		raw := tool.InputSchema
		if len(raw) == 0 {
			raw = tool.InputSchema2
		}
		if len(raw) > 0 && string(raw) != "null" {
			_ = json.Unmarshal(raw, &schema)
		}
		tools = append(tools, map[string]interface{}{
			"name":        tool.Name,
			"description": tool.Description,
			"inputSchema": schema,
		})
	}

	return tools, nil
}

func (s *mcpServer) callTool(ctx context.Context, params json.RawMessage) (map[string]interface{}, error) {
	var req struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(params, &req); err != nil {
		return nil, fmt.Errorf("invalid tools/call params: %w", err)
	}
	if req.Name == "" {
		return nil, errors.New("tool name is required")
	}

	// All tools now flow through the server__tool dispatch pattern.
	// shipyard__* tools are handled by the server's internal dispatcher.
	// (R8: removed hardcoded shipyard_status special-case — SPEC-044)
	parts := strings.SplitN(req.Name, "__", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return nil, fmt.Errorf("tool %q is not namespaced as {server}__{tool}", req.Name)
	}

	backendResp, err := s.invokeTool(ctx, parts[0], parts[1], req.Arguments)
	if err != nil {
		return nil, err
	}
	if len(backendResp.Error) > 0 && string(backendResp.Error) != "null" {
		return map[string]interface{}{
			"isError": true,
			"content": []map[string]string{{"type": "text", "text": compactJSON(backendResp.Error)}},
		}, nil
	}

	result := decodeJSON(backendResp.Result)
	if resultMap, ok := result.(map[string]interface{}); ok {
		if _, hasContent := resultMap["content"]; hasContent {
			return resultMap, nil
		}
		return map[string]interface{}{
			"content":           []map[string]string{{"type": "text", "text": compactJSON(backendResp.Result)}},
			"structuredContent": resultMap,
		}, nil
	}
	if resultArr, ok := result.([]interface{}); ok {
		return map[string]interface{}{
			"content":           []map[string]string{{"type": "text", "text": compactJSON(backendResp.Result)}},
			"structuredContent": resultArr,
		}, nil
	}

	return map[string]interface{}{
		"content": []map[string]string{{"type": "text", "text": compactJSON(backendResp.Result)}},
	}, nil
}

func (s *mcpServer) fetchServers(ctx context.Context) ([]shipyardServer, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.apiBase+"/api/servers", nil)
	if err != nil {
		return nil, fmt.Errorf("build servers request: %w", err)
	}
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Shipyard is not running or unreachable at %s", s.apiBase)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Shipyard returned %d from /api/servers", resp.StatusCode)
	}
	var servers []shipyardServer
	if err := json.NewDecoder(resp.Body).Decode(&servers); err != nil {
		return nil, fmt.Errorf("decode /api/servers: %w", err)
	}
	return servers, nil
}

func (s *mcpServer) fetchGatewayTools(ctx context.Context) (*toolsEnvelope, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.apiBase+"/api/gateway/tools", nil)
	if err != nil {
		return nil, err
	}
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Shipyard is not running or unreachable at %s", s.apiBase)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("/api/gateway/tools returned %d", resp.StatusCode)
	}
	var env toolsEnvelope
	if err := json.NewDecoder(resp.Body).Decode(&env); err != nil {
		return nil, err
	}
	return &env, nil
}

func (s *mcpServer) invokeTool(ctx context.Context, server, tool string, args json.RawMessage) (*toolCallResponse, error) {
	if len(args) == 0 || string(args) == "null" {
		args = json.RawMessage("{}")
	}
	body, err := json.Marshal(toolCallRequest{Server: server, Tool: tool, Arguments: args})
	if err != nil {
		return nil, fmt.Errorf("marshal tool request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.apiBase+"/api/tools/call", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Shipyard is not running or unreachable at %s", s.apiBase)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("Shipyard tool call failed (%d): %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	var result toolCallResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("decode tool call response: %w", err)
	}
	return &result, nil
}

func (s *mcpServer) writeResponse(stdout io.Writer, resp rpcResponse) {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	enc := json.NewEncoder(stdout)
	_ = enc.Encode(resp)
}

func decodeID(raw json.RawMessage) interface{} {
	if len(raw) == 0 {
		return nil
	}
	var v interface{}
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil
	}
	return v
}

func decodeJSON(raw json.RawMessage) interface{} {
	if len(raw) == 0 {
		return nil
	}
	var v interface{}
	if err := json.Unmarshal(raw, &v); err != nil {
		return string(raw)
	}
	return v
}

func compactJSON(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var out bytes.Buffer
	if err := json.Compact(&out, raw); err != nil {
		return string(raw)
	}
	return out.String()
}
