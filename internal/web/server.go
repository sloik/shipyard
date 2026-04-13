package web

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/coder/websocket"
	"github.com/sloik/shipyard/internal/auth"
	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/gateway"
)

//go:embed ui
var uiFS embed.FS

type wsConn interface {
	Read(context.Context) (websocket.MessageType, []byte, error)
	Write(context.Context, websocket.MessageType, []byte) error
	CloseNow() error
}

var subUIFS = fs.Sub

var acceptWebSocket = func(w http.ResponseWriter, r *http.Request, opts *websocket.AcceptOptions) (wsConn, error) {
	return websocket.Accept(w, r, opts)
}

// UIAssets returns the embedded dashboard UI files rooted at the ui/ folder.
func UIAssets() (fs.FS, error) {
	uiContent, err := subUIFS(uiFS, "ui")
	if err != nil {
		return nil, fmt.Errorf("embed ui: %w", err)
	}
	return uiContent, nil
}

// ProxyManager defines the interface the web server uses to interact with proxies.
type ProxyManager interface {
	Servers() []ServerInfo
	SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error)
	RestartServer(name string) error
	StopServer(name string) error
	StartRecording(server string, sessionID int64)
	StopRecording(server string)
	ActiveSessionID(server string) int64
	ServersForAuth() []string
}

// ServerInfo describes a running server for the API.
type ServerInfo struct {
	Name         string `json:"name"`
	Status       string `json:"status"`
	Command      string `json:"command,omitempty"`
	ToolCount    int    `json:"tool_count"`
	Uptime       int64  `json:"uptime_ms"`
	RestartCount int    `json:"restart_count"`
	ErrorMessage string `json:"error_message,omitempty"`
}

type toolsEnvelope struct {
	Tools []shipyardTool `json:"tools"`
}

type shipyardTool struct {
	Name         string          `json:"name"`
	Description  string          `json:"description,omitempty"`
	InputSchema  json.RawMessage `json:"inputSchema,omitempty"`
	InputSchema2 json.RawMessage `json:"input_schema,omitempty"`
}

// Server is the HTTP + WebSocket server for the web dashboard.
type Server struct {
	port          int
	store         *capture.Store
	hub           *Hub
	proxies       ProxyManager
	gateway       *gateway.Store
	authStore     *auth.Store
	authLimiter   *auth.RateLimiter
	authEnabled   bool
	toolLogLevels map[string]map[string]string // server → tool → log_level
}

// NewServer creates a new web server.
func NewServer(port int, store *capture.Store, hub *Hub) *Server {
	return &Server{port: port, store: store, hub: hub}
}

// SetProxyManager sets the proxy manager for tool invocation APIs.
func (s *Server) SetProxyManager(pm ProxyManager) {
	s.proxies = pm
}

func (s *Server) SetGatewayPolicyStore(gs *gateway.Store) {
	s.gateway = gs
}

// SetAuthStore enables bearer token authentication with the given store.
func (s *Server) SetAuthStore(as *auth.Store, limiter *auth.RateLimiter, enabled bool) {
	s.authStore = as
	s.authLimiter = limiter
	s.authEnabled = enabled
}

// SetToolLogLevels sets per-tool log level overrides for access logging.
func (s *Server) SetToolLogLevels(levels map[string]map[string]string) {
	s.toolLogLevels = levels
}

// Start runs the HTTP server. It blocks until the context is cancelled.
func (s *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()

	// Serve embedded UI
	uiAssets, err := UIAssets()
	if err != nil {
		return err
	}
	mux.Handle("GET /", noCache(http.FileServer(http.FS(uiAssets))))

	// API endpoints
	mux.HandleFunc("GET /api/traffic", s.handleTraffic)
	mux.HandleFunc("GET /api/traffic/{id}", s.handleTrafficDetail)
	mux.HandleFunc("GET /api/servers", s.handleServers)
	mux.HandleFunc("POST /api/servers/{name}/restart", s.handleServerRestart)
	mux.HandleFunc("POST /api/servers/{name}/stop", s.handleServerStop)
	mux.HandleFunc("GET /api/auto-import", s.handleAutoImportScan)
	mux.HandleFunc("GET /api/tools", s.handleTools)
	mux.HandleFunc("GET /api/tools/conflicts", s.handleToolConflicts)
	mux.HandleFunc("POST /api/tools/call", s.handleToolCall)
	mux.HandleFunc("GET /api/gateway/tools", s.handleGatewayTools)
	mux.HandleFunc("GET /api/gateway/policy", s.handleGatewayPolicy)
	mux.HandleFunc("POST /api/gateway/servers/{name}/enable", s.handleGatewayServerEnable)
	mux.HandleFunc("POST /api/gateway/servers/{name}/disable", s.handleGatewayServerDisable)
	mux.HandleFunc("POST /api/gateway/tools/{server}/{tool}/enable", s.handleGatewayToolEnable)
	mux.HandleFunc("POST /api/gateway/tools/{server}/{tool}/disable", s.handleGatewayToolDisable)
	mux.HandleFunc("POST /api/replay", s.handleReplay)
	mux.HandleFunc("POST /api/sessions/start", s.handleSessionStart)
	mux.HandleFunc("GET /api/sessions", s.handleSessionList)
	mux.HandleFunc("GET /api/sessions/{id}", s.handleSessionDetail)
	mux.HandleFunc("GET /api/sessions/{id}/export", s.handleSessionExport)
	mux.HandleFunc("POST /api/sessions/{id}/stop", s.handleSessionStop)
	mux.HandleFunc("POST /api/sessions/{id}/replay", s.handleSessionReplay)
	mux.HandleFunc("DELETE /api/sessions/{id}", s.handleSessionDelete)
	mux.HandleFunc("GET /api/schema/changes", s.handleSchemaChanges)
	mux.HandleFunc("GET /api/schema/changes/{id}", s.handleSchemaChangeDetail)
	mux.HandleFunc("POST /api/schema/changes/{id}/ack", s.handleSchemaAcknowledge)
	mux.HandleFunc("GET /api/schema/current/{server}", s.handleSchemaCurrentTools)
	mux.HandleFunc("GET /api/schema/unacknowledged-count", s.handleSchemaUnackCount)
	mux.HandleFunc("GET /api/profiling/summary", s.handleProfilingSummary)
	mux.HandleFunc("GET /api/profiling/tools", s.handleProfilingTools)
	mux.HandleFunc("GET /ws", s.handleWebSocket)

	// Token admin API (auth required via bootstrap or admin token)
	mux.HandleFunc("POST /api/tokens", s.handleTokenCreate)
	mux.HandleFunc("GET /api/tokens", s.handleTokenList)
	mux.HandleFunc("DELETE /api/tokens/{id}", s.handleTokenDelete)
	mux.HandleFunc("PUT /api/tokens/{id}/scopes", s.handleTokenUpdateScopes)
	mux.HandleFunc("GET /api/tokens/{id}/stats", s.handleTokenStats)

	// Access log endpoints
	mux.HandleFunc("GET /api/access-log", s.handleAccessLog)
	mux.HandleFunc("GET /api/access-log/stats", s.handleAccessLogStats)

	// MCP proxy endpoint — auth-gated when auth.enabled: true
	if s.authEnabled && s.authStore != nil {
		mcpH := auth.NewMCPHandler(s.authStore, s.authLimiter, s.proxies)
		mcpH.SetCaptureStore(s.store)
		if s.toolLogLevels != nil {
			mcpH.SetToolLogLevels(s.toolLogLevels)
		}
		mux.Handle("POST /mcp", mcpH)
		mux.Handle("POST /mcp/{token}", mcpH)
	} else {
		// Auth disabled: passthrough MCP proxy (no auth check)
		mux.HandleFunc("POST /mcp", s.handleMCPPassthrough)
		mux.Handle("POST /mcp/{token}", http.HandlerFunc(s.handleMCPPassthrough))
	}

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", s.port),
		Handler: withCORS(mux),
		BaseContext: func(_ net.Listener) context.Context {
			return ctx
		},
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutdownCtx)
	}()

	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		return err
	}
	return nil
}

func noCache(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate")
		w.Header().Set("Pragma", "no-cache")
		w.Header().Set("Expires", "0")
		next.ServeHTTP(w, r)
	})
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

func (s *Server) handleTraffic(w http.ResponseWriter, r *http.Request) {
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if page < 1 {
		page = 1
	}
	pageSize, _ := strconv.Atoi(r.URL.Query().Get("page_size"))
	if pageSize < 1 || pageSize > 200 {
		pageSize = 50
	}

	f := capture.QueryFilter{
		Page:      page,
		PageSize:  pageSize,
		Server:    r.URL.Query().Get("server"),
		Method:    r.URL.Query().Get("method"),
		Direction: r.URL.Query().Get("direction"),
		Search:    r.URL.Query().Get("search"),
	}

	if fromStr := r.URL.Query().Get("from_ts"); fromStr != "" {
		if v, err := strconv.ParseInt(fromStr, 10, 64); err == nil {
			f.FromTs = &v
		}
	}
	if toStr := r.URL.Query().Get("to_ts"); toStr != "" {
		if v, err := strconv.ParseInt(toStr, 10, 64); err == nil {
			f.ToTs = &v
		}
	}

	result, err := s.store.QueryFiltered(f)
	if err != nil {
		slog.Error("query traffic", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleReplay(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		ID int64 `json:"id"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	// Fetch the original traffic entry
	entry, _, err := s.store.GetByID(req.ID)
	if err != nil {
		http.Error(w, "traffic entry not found", http.StatusNotFound)
		return
	}

	// Parse the original payload to extract params
	var rpcMsg struct {
		Method string          `json:"method"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal([]byte(entry.Payload), &rpcMsg); err != nil {
		http.Error(w, "invalid payload in traffic entry", http.StatusBadRequest)
		return
	}

	// Use the method from the traffic entry if not in payload
	method := rpcMsg.Method
	if method == "" {
		method = entry.Method
	}

	params := rpcMsg.Params
	if params == nil {
		params = json.RawMessage("{}")
	}

	start := time.Now()
	result, err := s.proxies.SendRequest(r.Context(), entry.ServerName, method, params)
	elapsed := time.Since(start)

	if err != nil {
		slog.Error("replay failed", "server", entry.ServerName, "method", method, "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error":      err.Error(),
			"latency_ms": elapsed.Milliseconds(),
		})
		return
	}

	// Parse the JSON-RPC response
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		http.Error(w, "invalid response from server", http.StatusBadGateway)
		return
	}

	resp := map[string]interface{}{
		"latency_ms": elapsed.Milliseconds(),
	}
	if rpcResp.Error != nil {
		resp["error"] = json.RawMessage(rpcResp.Error)
	} else {
		resp["result"] = json.RawMessage(rpcResp.Result)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) handleTrafficDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	entry, matched, err := s.store.GetByID(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	resp := map[string]interface{}{
		"entry": entry,
	}
	if matched != nil {
		resp["matched"] = matched
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) handleServers(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]interface{}{})
		return
	}

	servers := s.proxies.Servers()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(servers)
}

func (s *Server) handleServerRestart(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	if err := s.proxies.RestartServer(name); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "restarting"})
}

func (s *Server) handleServerStop(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	if err := s.proxies.StopServer(name); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
}

// DiscoveredServer describes a server found via auto-import scanning.
type DiscoveredServer struct {
	Name    string            `json:"name"`
	Command string            `json:"command"`
	Args    []string          `json:"args,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
	Source  string            `json:"source"`
	Status  string            `json:"status"` // "new", "duplicate", "already_imported"
}

// autoImportScanner can be overridden in tests.
var autoImportScanner = scanForServers

type gatewayToolInfo struct {
	Name          string          `json:"name"`
	Server        string          `json:"server"`
	Tool          string          `json:"tool"`
	Description   string          `json:"description,omitempty"`
	InputSchema   json.RawMessage `json:"inputSchema,omitempty"`
	ServerEnabled bool            `json:"server_enabled"`
	ToolEnabled   bool            `json:"tool_enabled"`
	Enabled       bool            `json:"enabled"`
}

func (s *Server) handleAutoImportScan(w http.ResponseWriter, r *http.Request) {
	var existing map[string]bool
	if s.proxies != nil {
		servers := s.proxies.Servers()
		existing = make(map[string]bool, len(servers))
		for _, srv := range servers {
			existing[srv.Name] = true
		}
	} else {
		existing = map[string]bool{}
	}

	discovered := autoImportScanner(existing)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(discovered)
}

func (s *Server) handleToolConflicts(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]interface{}{})
		return
	}

	servers := s.proxies.Servers()
	if len(servers) == 0 {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]interface{}{})
		return
	}

	// Collect tools from each server by sending tools/list
	type toolEntry struct {
		Name   string `json:"name"`
		Server string `json:"server"`
	}

	toolMap := make(map[string][]string) // toolName -> []serverName
	for _, srv := range servers {
		if srv.Status != "online" {
			continue
		}
		result, err := s.proxies.SendRequest(r.Context(), srv.Name, "tools/list", json.RawMessage("{}"))
		if err != nil {
			continue
		}
		var rpcResp struct {
			Result struct {
				Tools []struct {
					Name string `json:"name"`
				} `json:"tools"`
			} `json:"result"`
		}
		if err := json.Unmarshal(result, &rpcResp); err != nil {
			continue
		}
		for _, t := range rpcResp.Result.Tools {
			toolMap[t.Name] = append(toolMap[t.Name], srv.Name)
		}
	}

	// Filter to only duplicates
	type conflict struct {
		ToolName string   `json:"tool_name"`
		Servers  []string `json:"servers"`
	}
	var conflicts []conflict
	for name, servers := range toolMap {
		if len(servers) > 1 {
			conflicts = append(conflicts, conflict{ToolName: name, Servers: servers})
		}
	}

	if conflicts == nil {
		conflicts = []conflict{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(conflicts)
}

func (s *Server) handleTools(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	serverName := r.URL.Query().Get("server")
	if serverName == "" {
		http.Error(w, "server parameter required", http.StatusBadRequest)
		return
	}

	result, err := s.fetchToolsResult(r.Context(), serverName)
	if err != nil {
		slog.Error("tools/list failed", "server", serverName, "error", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	// Parse the JSON-RPC response to extract the result
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		http.Error(w, "invalid response from server", http.StatusBadGateway)
		return
	}
	if rpcResp.Error != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error": json.RawMessage(rpcResp.Error),
		})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write(rpcResp.Result)
}

func (s *Server) handleToolCall(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB limit
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Server    string          `json:"server"`
		Tool      string          `json:"tool"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	if req.Server == "" || req.Tool == "" {
		http.Error(w, "server and tool fields required", http.StatusBadRequest)
		return
	}
	if s.gateway != nil {
		if !s.gateway.ServerEnabled(req.Server) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      fmt.Sprintf("server %q is disabled by Shipyard gateway policy", req.Server),
				"latency_ms": int64(0),
			})
			return
		}
		if !s.gateway.ToolEnabled(req.Server, req.Tool) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      fmt.Sprintf("tool %q on server %q is disabled by Shipyard gateway policy", req.Tool, req.Server),
				"latency_ms": int64(0),
			})
			return
		}
	}

	// Build tools/call params
	params := map[string]interface{}{
		"name": req.Tool,
	}
	if req.Arguments != nil {
		params["arguments"] = json.RawMessage(req.Arguments)
	}
	paramsBytes, _ := json.Marshal(params)

	start := time.Now()
	result, err := s.proxies.SendRequest(r.Context(), req.Server, "tools/call", paramsBytes)
	elapsed := time.Since(start)

	if err != nil {
		slog.Error("tools/call failed", "server", req.Server, "tool", req.Tool, "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error":      err.Error(),
			"latency_ms": elapsed.Milliseconds(),
		})
		return
	}

	// Parse the JSON-RPC response
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		http.Error(w, "invalid response from server", http.StatusBadGateway)
		return
	}

	resp := map[string]interface{}{
		"latency_ms": elapsed.Milliseconds(),
	}
	if rpcResp.Error != nil {
		resp["error"] = json.RawMessage(rpcResp.Error)
	} else {
		resp["result"] = json.RawMessage(rpcResp.Result)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) handleGatewayTools(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	includeDisabled := r.URL.Query().Get("include_disabled") == "1"
	tools, err := s.gatewayCatalog(r.Context(), includeDisabled)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"tools": tools})
}

func (s *Server) handleGatewayPolicy(w http.ResponseWriter, r *http.Request) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.gateway.Snapshot())
}

func (s *Server) handleGatewayServerEnable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayServerToggle(w, r, true)
}

func (s *Server) handleGatewayServerDisable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayServerToggle(w, r, false)
}

func (s *Server) handleGatewayToolEnable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayToolToggle(w, r, true)
}

func (s *Server) handleGatewayToolDisable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayToolToggle(w, r, false)
}

func (s *Server) handleGatewayServerToggle(w http.ResponseWriter, r *http.Request, enabled bool) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetServerEnabled(name, enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"server": name, "enabled": enabled})
}

func (s *Server) handleGatewayToolToggle(w http.ResponseWriter, r *http.Request, enabled bool) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	serverName := r.PathValue("server")
	toolName := r.PathValue("tool")
	if serverName == "" || toolName == "" {
		http.Error(w, "server and tool required", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetToolEnabled(serverName, toolName, enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"server":  serverName,
		"tool":    toolName,
		"enabled": enabled,
	})
}

func (s *Server) gatewayCatalog(ctx context.Context, includeDisabled bool) ([]gatewayToolInfo, error) {
	servers := s.proxies.Servers()
	result := make([]gatewayToolInfo, 0)
	for _, srv := range servers {
		if srv.Status != "online" {
			continue
		}
		tools, err := s.fetchRawTools(ctx, srv.Name)
		if err != nil {
			continue
		}
		for _, tool := range tools {
			serverEnabled := true
			toolEnabled := true
			effectiveEnabled := true
			if s.gateway != nil {
				serverEnabled = s.gateway.ServerEnabled(srv.Name)
				toolEnabled = s.gateway.ToolEnabled(srv.Name, tool.Name)
				effectiveEnabled = serverEnabled && toolEnabled
			}
			if !includeDisabled && !effectiveEnabled {
				continue
			}
			result = append(result, gatewayToolInfo{
				Name:          srv.Name + "__" + tool.Name,
				Server:        srv.Name,
				Tool:          tool.Name,
				Description:   tool.Description,
				InputSchema:   tool.InputSchema,
				ServerEnabled: serverEnabled,
				ToolEnabled:   toolEnabled,
				Enabled:       effectiveEnabled,
			})
		}
	}
	return result, nil
}

func (s *Server) fetchToolsResult(ctx context.Context, serverName string) (json.RawMessage, error) {
	return s.proxies.SendRequest(ctx, serverName, "tools/list", json.RawMessage("{}"))
}

func (s *Server) fetchRawTools(ctx context.Context, serverName string) ([]shipyardTool, error) {
	result, err := s.fetchToolsResult(ctx, serverName)
	if err != nil {
		return nil, err
	}

	var rpcResp struct {
		Result toolsEnvelope   `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		return nil, fmt.Errorf("invalid response from server")
	}
	if rpcResp.Error != nil {
		return nil, fmt.Errorf("server returned error: %s", string(rpcResp.Error))
	}
	for i := range rpcResp.Result.Tools {
		if len(rpcResp.Result.Tools[i].InputSchema) == 0 && len(rpcResp.Result.Tools[i].InputSchema2) > 0 {
			rpcResp.Result.Tools[i].InputSchema = rpcResp.Result.Tools[i].InputSchema2
		}
	}
	return rpcResp.Result.Tools, nil
}

// --- Session Recording Handlers (SPEC-007) ---

func (s *Server) handleSessionStart(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Name   string `json:"name"`
		Server string `json:"server"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	id, err := s.store.StartSession(req.Name, req.Server)
	if err != nil {
		slog.Error("start session", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	// Tell the manager to tag traffic for this server
	if s.proxies != nil {
		s.proxies.StartRecording(req.Server, id)
	}

	sess, err := s.store.GetSession(id)
	if err != nil {
		slog.Error("get session after start", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionStop(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	// Get session to find server name before stopping
	sess, err := s.store.GetSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	if err := s.store.StopSession(id); err != nil {
		http.Error(w, err.Error(), http.StatusConflict)
		return
	}

	// Stop recording in manager
	if s.proxies != nil {
		s.proxies.StopRecording(sess.Server)
	}

	sess, _ = s.store.GetSession(id)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionList(w http.ResponseWriter, r *http.Request) {
	server := r.URL.Query().Get("server")
	status := r.URL.Query().Get("status")

	sessions, err := s.store.ListSessions(server, status)
	if err != nil {
		slog.Error("list sessions", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sessions)
}

func (s *Server) handleSessionDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	sess, err := s.store.GetSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionExport(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	cassette, err := s.store.ExportSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="session-%d.json"`, id))
	json.NewEncoder(w).Encode(cassette)
}

func (s *Server) handleSessionReplay(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	cassette, err := s.store.ExportSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	var results []map[string]interface{}
	for _, entry := range cassette.Requests {
		if entry.Params == nil {
			continue // skip responses
		}
		params := entry.Params
		start := time.Now()
		result, sendErr := s.proxies.SendRequest(r.Context(), cassette.Server, entry.Method, params)
		elapsed := time.Since(start)

		res := map[string]interface{}{
			"method":     entry.Method,
			"latency_ms": elapsed.Milliseconds(),
		}
		if sendErr != nil {
			res["error"] = sendErr.Error()
		} else {
			res["result"] = json.RawMessage(result)
		}
		results = append(results, res)
	}

	if results == nil {
		results = []map[string]interface{}{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"session_id": id,
		"results":    results,
	})
}

func (s *Server) handleSessionDelete(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.store.DeleteSession(id); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "deleted"})
}

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := acceptWebSocket(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		slog.Error("websocket accept", "error", err)
		return
	}

	client := &Client{
		conn: conn,
		send: make(chan []byte, 256),
	}

	s.hub.Register(client)
	defer s.hub.Unregister(client)

	ctx := r.Context()

	// Writer goroutine
	go func() {
		defer conn.CloseNow()
		for {
			select {
			case msg, ok := <-client.send:
				if !ok {
					return
				}
				err := conn.Write(ctx, websocket.MessageText, msg)
				if err != nil {
					return
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	// Reader goroutine (just drain to detect close)
	for {
		_, _, err := conn.Read(ctx)
		if err != nil {
			break
		}
	}
}

// --- Latency Profiling Handlers ---

func (s *Server) handleProfilingSummary(w http.ResponseWriter, r *http.Request) {
	rangeStr := r.URL.Query().Get("range")
	if rangeStr == "" {
		rangeStr = "24h"
	}
	server := r.URL.Query().Get("server")

	result, err := s.store.ProfilingSummary(rangeStr, server)
	if err != nil {
		slog.Error("profiling summary", "error", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleProfilingTools(w http.ResponseWriter, r *http.Request) {
	rangeStr := r.URL.Query().Get("range")
	if rangeStr == "" {
		rangeStr = "24h"
	}
	server := r.URL.Query().Get("server")
	sortBy := r.URL.Query().Get("sort")
	if sortBy == "" {
		sortBy = "p95"
	}
	order := r.URL.Query().Get("order")
	if order == "" {
		order = "desc"
	}

	result, err := s.store.ProfilingByTool(rangeStr, server, sortBy, order)
	if err != nil {
		slog.Error("profiling tools", "error", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if result == nil {
		result = []capture.ToolProfile{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

// --- Schema Change Detection Handlers ---

func (s *Server) handleSchemaChanges(w http.ResponseWriter, r *http.Request) {
	server := r.URL.Query().Get("server")
	changes, err := s.store.ListSchemaChanges(server)
	if err != nil {
		slog.Error("list schema changes", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(changes)
}

func (s *Server) handleSchemaChangeDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	detail, err := s.store.GetSchemaChange(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(detail)
}

func (s *Server) handleSchemaAcknowledge(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.store.AcknowledgeSchemaChange(id); err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "acknowledged"})
}

func (s *Server) handleSchemaCurrentTools(w http.ResponseWriter, r *http.Request) {
	server := r.PathValue("server")
	if server == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	tools, _, err := s.store.GetLatestSnapshot(server)
	if err != nil {
		slog.Error("get latest snapshot", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if tools == nil {
		tools = []capture.ToolSchema{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tools)
}

func (s *Server) handleSchemaUnackCount(w http.ResponseWriter, r *http.Request) {
	count, err := s.store.UnacknowledgedCount()
	if err != nil {
		slog.Error("unacknowledged count", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]int{"count": count})
}

// --- Token Admin API ---

// requireAdminAuth checks that the request carries a valid bootstrap token or admin token.
// Returns false and writes an error response if auth fails.
func (s *Server) requireAdminAuth(w http.ResponseWriter, r *http.Request) bool {
	if s.authStore == nil {
		// Auth not configured — allow
		return true
	}
	v := r.Header.Get("Authorization")
	if !strings.HasPrefix(v, "Bearer ") {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return false
	}
	tok := strings.TrimPrefix(v, "Bearer ")

	// Check bootstrap token first
	if s.authStore.AuthenticateBootstrap(tok) {
		return true
	}
	// Then check admin token (any valid stored token can manage tokens)
	_, err := s.authStore.Authenticate(tok)
	if err != nil {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return false
	}
	return true
}

func (s *Server) handleTokenCreate(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<16))
	if err != nil {
		http.Error(w, "read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Name           string   `json:"name"`
		Scopes         []string `json:"scopes"`
		RateLimitPerMin int     `json:"rate_limit_per_minute"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Name == "" {
		http.Error(w, "name required", http.StatusBadRequest)
		return
	}
	if req.Scopes == nil {
		req.Scopes = []string{}
	}

	plaintext, id, err := s.authStore.GenerateToken(req.Name, req.RateLimitPerMin, req.Scopes)
	if err != nil {
		slog.Error("generate token", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"id":    id,
		"token": plaintext, // shown exactly once
		"name":  req.Name,
	})
}

func (s *Server) handleTokenList(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	tokens, err := s.authStore.ListTokens()
	if err != nil {
		slog.Error("list tokens", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if tokens == nil {
		tokens = []auth.TokenRecord{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tokens)
}

func (s *Server) handleTokenDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.authStore.DeleteToken(id); err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("delete token", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleTokenUpdateScopes(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<16))
	if err != nil {
		http.Error(w, "read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Scopes []string `json:"scopes"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Scopes == nil {
		req.Scopes = []string{}
	}

	if err := s.authStore.UpdateScopes(id, req.Scopes); err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("update scopes", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "updated"})
}

func (s *Server) handleTokenStats(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	stats, err := s.authStore.GetStats(id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("get token stats", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

// handleMCPPassthrough forwards MCP JSON-RPC to the appropriate child server without auth.
// Used when auth.enabled is false. Expects tool names in "server__tool" format for tools/call.
func (s *Server) handleMCPPassthrough(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		writeJSONRPCError(w, nil, -32603, "no proxy manager configured")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		writeJSONRPCError(w, nil, -32700, "failed to read request body")
		return
	}

	var rpcReq struct {
		ID     json.RawMessage `json:"id"`
		Method string          `json:"method"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal(body, &rpcReq); err != nil {
		writeJSONRPCError(w, nil, -32700, "parse error")
		return
	}

	// For passthrough we forward to the server named in params, or "default".
	serverName := extractPassthroughServer(rpcReq.Params)
	if serverName == "" {
		// Try to find any online server
		names := s.proxies.ServersForAuth()
		if len(names) == 0 {
			writeJSONRPCError(w, rpcReq.ID, -32603, "no servers available")
			return
		}
		serverName = names[0]
	}

	result, err := s.proxies.SendRequest(r.Context(), serverName, rpcReq.Method, rpcReq.Params)
	if err != nil {
		writeJSONRPCError(w, rpcReq.ID, -32603, fmt.Sprintf("upstream error: %v", err))
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write(result)
}

func extractPassthroughServer(params json.RawMessage) string {
	if len(params) == 0 {
		return ""
	}
	var p struct {
		Server string `json:"server"`
	}
	_ = json.Unmarshal(params, &p)
	return p.Server
}

func writeJSONRPCError(w http.ResponseWriter, id json.RawMessage, code int, message string) {
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

// handleAccessLog handles GET /api/access-log with optional filters and pagination.
func (s *Server) handleAccessLog(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}

	q := r.URL.Query()
	filter := capture.AccessLogFilter{
		TokenName:  q.Get("token_name"),
		ServerName: q.Get("server_name"),
		ToolName:   q.Get("tool_name"),
		Status:     q.Get("status"),
	}

	if fromStr := q.Get("from"); fromStr != "" {
		if t, err := time.Parse(time.RFC3339, fromStr); err == nil {
			filter.From = t
		}
	}
	if toStr := q.Get("to"); toStr != "" {
		if t, err := time.Parse(time.RFC3339, toStr); err == nil {
			filter.To = t
		}
	}

	if offsetStr := q.Get("offset"); offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil && v >= 0 {
			filter.Offset = v
		}
	}
	if limitStr := q.Get("limit"); limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			filter.Limit = v
		}
	}

	page, err := s.store.GetAccessLog(filter)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(page)
}

// handleAccessLogStats handles GET /api/access-log/stats.
func (s *Server) handleAccessLogStats(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}

	stats, err := s.store.GetAccessLogStats()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}
