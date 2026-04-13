package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/sloik/shipyard/internal/capture"
)

// ProxyManager is the interface the MCP handler needs.
type ProxyManager interface {
	SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error)
	// ServersForAuth returns the names of all registered servers.
	// It is used by tools/list to enumerate targets.
	ServersForAuth() []string
}

// MCPHandler handles POST /mcp and POST /mcp/{token} requests.
// It enforces bearer token auth, scope filtering, and rate limiting.
type MCPHandler struct {
	store         *Store
	limiter       *RateLimiter
	proxies       ProxyManager
	captureLog    *capture.Store
	toolLogLevels map[string]map[string]string // server → tool → log_level
}

// NewMCPHandler creates a new MCPHandler.
func NewMCPHandler(store *Store, limiter *RateLimiter, proxies ProxyManager) *MCPHandler {
	return &MCPHandler{store: store, limiter: limiter, proxies: proxies}
}

// SetCaptureStore sets the capture store used for access logging.
func (h *MCPHandler) SetCaptureStore(store *capture.Store) {
	h.captureLog = store
}

// SetToolLogLevels sets per-tool log level overrides.
func (h *MCPHandler) SetToolLogLevels(levels map[string]map[string]string) {
	h.toolLogLevels = levels
}

// getToolLogLevel returns the log level for the given server/tool combination.
func (h *MCPHandler) getToolLogLevel(server, tool string) string {
	if h.toolLogLevels != nil {
		if serverLevels, ok := h.toolLogLevels[server]; ok {
			if lvl, ok := serverLevels[tool]; ok {
				return lvl
			}
		}
	}
	return "full"
}

// rpcError writes a JSON-RPC error response.
func writeRPCError(w http.ResponseWriter, id json.RawMessage, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	resp := map[string]interface{}{
		"jsonrpc": "2.0",
		"error": map[string]interface{}{
			"code":    code,
			"message": message,
		},
	}
	if id != nil {
		resp["id"] = json.RawMessage(id)
	} else {
		resp["id"] = nil
	}
	json.NewEncoder(w).Encode(resp)
}

// extractBearer parses "Authorization: Bearer <token>" header.
func extractBearer(r *http.Request) string {
	v := r.Header.Get("Authorization")
	if !strings.HasPrefix(v, "Bearer ") {
		return ""
	}
	return strings.TrimPrefix(v, "Bearer ")
}

// ServeHTTP implements http.Handler. It dispatches to the auth check then routes the MCP call.
func (h *MCPHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Try to read ID from the body early so error responses can include it.
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		writeRPCError(w, nil, -32700, "failed to read request body")
		return
	}

	var rpcReq struct {
		ID     json.RawMessage `json:"id"`
		Method string          `json:"method"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal(body, &rpcReq); err != nil {
		writeRPCError(w, nil, -32700, "parse error")
		return
	}

	// Determine token plaintext — path-based takes precedence over header.
	var tokenPlaintext string
	if pathToken := r.PathValue("token"); pathToken != "" {
		tokenPlaintext = pathToken
	} else {
		tokenPlaintext = extractBearer(r)
	}

	// Auth check
	rec, err := h.store.Authenticate(tokenPlaintext)
	if err != nil {
		// Also try bootstrap token for admin operations
		writeRPCError(w, rpcReq.ID, -32001, "Unauthorized")
		return
	}

	// Rate limit check
	if !h.limiter.Allow(rec.ID, rec.RateLimitPerMin) {
		writeRPCError(w, rpcReq.ID, -32000, "Rate limit exceeded")
		return
	}

	// Route the MCP method
	h.routeMethod(w, r, rec, rpcReq.ID, rpcReq.Method, rpcReq.Params)
}

// routeMethod dispatches a validated JSON-RPC request.
func (h *MCPHandler) routeMethod(
	w http.ResponseWriter,
	r *http.Request,
	token *TokenRecord,
	id json.RawMessage,
	method string,
	params json.RawMessage,
) {
	if h.proxies == nil {
		writeRPCError(w, id, -32603, "no proxy manager configured")
		return
	}

	switch method {
	case "initialize":
		h.handleInitialize(w, r, token, id, params)
	case "tools/list":
		h.handleToolsList(w, r, token, id, params)
	case "tools/call":
		h.handleToolsCall(w, r, token, id, params)
	default:
		// For other methods, find the target server from params or forward to all.
		// Per spec this is a passthrough to an appropriate child server.
		// We need a server name to route — check params for it.
		serverName := extractServerFromParams(params)
		if serverName == "" {
			writeRPCError(w, id, -32602, "missing server parameter for method "+method)
			return
		}
		raw, err := h.proxies.SendRequest(r.Context(), serverName, method, params)
		if err != nil {
			writeRPCError(w, id, -32603, fmt.Sprintf("upstream error: %v", err))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(raw)
	}
}

// handleInitialize handles the MCP initialize method.
// It returns a gateway-level initialize response and issues an Mcp-Session-Id header
// (workaround for Claude Code bug CC#27142 — we issue but never validate it).
func (h *MCPHandler) handleInitialize(w http.ResponseWriter, r *http.Request, token *TokenRecord, id json.RawMessage, params json.RawMessage) {
	sessionID := uuid.New().String()
	w.Header().Set("Mcp-Session-Id", sessionID)
	w.Header().Set("Content-Type", "application/json")

	resp := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      json.RawMessage(id),
		"result": map[string]interface{}{
			"protocolVersion": "2025-11-25",
			"serverInfo": map[string]string{
				"name":    "shipyard-relay",
				"version": "0.1.0",
			},
			"capabilities": map[string]interface{}{
				"tools": map[string]bool{"listChanged": false},
			},
		},
	}
	json.NewEncoder(w).Encode(resp)
}

// handleToolsList proxies tools/list to all online servers and filters by scope.
func (h *MCPHandler) handleToolsList(w http.ResponseWriter, r *http.Request, token *TokenRecord, id json.RawMessage, params json.RawMessage) {
	serverNames := h.proxies.ServersForAuth()

	var allTools []map[string]interface{}

	for _, serverName := range serverNames {
		result, err := h.proxies.SendRequest(r.Context(), serverName, "tools/list", json.RawMessage("{}"))
		if err != nil {
			slog.Warn("tools/list failed for server", "server", serverName, "error", err)
			continue
		}

		var rpcResp struct {
			Result struct {
				Tools []json.RawMessage `json:"tools"`
			} `json:"result"`
		}
		if err := json.Unmarshal(result, &rpcResp); err != nil {
			continue
		}

		for _, rawTool := range rpcResp.Result.Tools {
			var toolObj map[string]interface{}
			if err := json.Unmarshal(rawTool, &toolObj); err != nil {
				continue
			}
			toolName, _ := toolObj["name"].(string)
			if toolName == "" {
				continue
			}

			// Apply scope filter
			if len(token.Scopes) > 0 {
				if !MatchScope(token.Scopes, serverName, toolName) {
					continue
				}
			}

			// Prefix tool name with server__tool for disambiguation (matches shipyard-mcp convention)
			toolObj["name"] = serverName + "__" + toolName
			allTools = append(allTools, toolObj)
		}
	}

	if allTools == nil {
		allTools = []map[string]interface{}{}
	}

	w.Header().Set("Content-Type", "application/json")
	resp := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      json.RawMessage(id),
		"result": map[string]interface{}{
			"tools": allTools,
		},
	}
	json.NewEncoder(w).Encode(resp)
}

// handleToolsCall proxies a tools/call, enforcing scope on the called tool.
func (h *MCPHandler) handleToolsCall(w http.ResponseWriter, r *http.Request, token *TokenRecord, id json.RawMessage, params json.RawMessage) {
	var p struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		writeRPCError(w, id, -32602, "invalid tools/call params")
		return
	}

	// Tool name format: "server__tool"
	parts := strings.SplitN(p.Name, "__", 2)
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		writeRPCError(w, id, -32602, fmt.Sprintf("tool name %q must be in server__tool format", p.Name))
		return
	}
	serverName, toolName := parts[0], parts[1]

	// Scope enforcement
	if len(token.Scopes) > 0 {
		if !MatchScope(token.Scopes, serverName, toolName) {
			if h.captureLog != nil {
				go h.captureLog.RecordAccess(capture.AccessLogEntry{
					Timestamp:  time.Now(),
					TokenName:  token.Name,
					ServerName: serverName,
					ToolName:   toolName,
					Status:     "denied",
					LogLevel:   "full", // always full for denied
				})
			}
			writeRPCError(w, id, -32001, "Tool not permitted by token scope")
			return
		}
	}

	// Build downstream params (strip server prefix from name)
	downstreamParams, err := json.Marshal(map[string]interface{}{
		"name":      toolName,
		"arguments": p.Arguments,
	})
	if err != nil {
		writeRPCError(w, id, -32603, "failed to build params")
		return
	}

	start := time.Now()
	result, err := h.proxies.SendRequest(r.Context(), serverName, "tools/call", json.RawMessage(downstreamParams))
	latMs := time.Since(start).Milliseconds()

	if h.captureLog != nil {
		entry := capture.AccessLogEntry{
			Timestamp:  time.Now(),
			TokenName:  token.Name,
			ServerName: serverName,
			ToolName:   toolName,
			LatencyMs:  &latMs,
			LogLevel:   h.getToolLogLevel(serverName, toolName),
		}
		if err != nil {
			entry.Status = "error"
			entry.ErrorMsg = err.Error()
		} else {
			// Check if downstream returned an error
			var ds struct {
				Error json.RawMessage `json:"error"`
			}
			if json.Unmarshal(result, &ds) == nil && ds.Error != nil && string(ds.Error) != "null" {
				entry.Status = "error"
				entry.ErrorMsg = string(ds.Error)
			} else {
				entry.Status = "ok"
			}
		}
		if entry.LogLevel == "full" || entry.LogLevel == "args_only" {
			entry.ArgsJSON = string(p.Arguments)
		}
		go h.captureLog.RecordAccess(entry)
	}

	if err != nil {
		writeRPCError(w, id, -32603, fmt.Sprintf("upstream error: %v", err))
		return
	}

	// Wrap the raw result back into a proper JSON-RPC response
	var downstream struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &downstream); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.Write(result)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	if downstream.Error != nil && string(downstream.Error) != "null" {
		resp := map[string]interface{}{
			"jsonrpc": "2.0",
			"id":      json.RawMessage(id),
			"error":   json.RawMessage(downstream.Error),
		}
		json.NewEncoder(w).Encode(resp)
		return
	}

	resp := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      json.RawMessage(id),
		"result":  json.RawMessage(downstream.Result),
	}
	json.NewEncoder(w).Encode(resp)
}

// extractServerFromParams tries to extract a "server" field from JSON params.
func extractServerFromParams(params json.RawMessage) string {
	if len(params) == 0 {
		return ""
	}
	var p struct {
		Server string `json:"server"`
	}
	_ = json.Unmarshal(params, &p)
	return p.Server
}
