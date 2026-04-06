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
	"time"

	"github.com/coder/websocket"
	"github.com/sloik/shipyard/internal/capture"
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

// ProxyManager defines the interface the web server uses to interact with proxies.
type ProxyManager interface {
	Servers() []ServerInfo
	SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error)
	RestartServer(name string) error
	StopServer(name string) error
	StartRecording(server string, sessionID int64)
	StopRecording(server string)
	ActiveSessionID(server string) int64
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

// Server is the HTTP + WebSocket server for the web dashboard.
type Server struct {
	port    int
	store   *capture.Store
	hub     *Hub
	proxies ProxyManager
}

// NewServer creates a new web server.
func NewServer(port int, store *capture.Store, hub *Hub) *Server {
	return &Server{port: port, store: store, hub: hub}
}

// SetProxyManager sets the proxy manager for tool invocation APIs.
func (s *Server) SetProxyManager(pm ProxyManager) {
	s.proxies = pm
}

// Start runs the HTTP server. It blocks until the context is cancelled.
func (s *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()

	// Serve embedded UI
	uiContent, err := subUIFS(uiFS, "ui")
	if err != nil {
		return fmt.Errorf("embed ui: %w", err)
	}
	mux.Handle("GET /", http.FileServer(http.FS(uiContent)))

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

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", s.port),
		Handler: mux,
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
	Name    string `json:"name"`
	Command string `json:"command"`
	Args    []string `json:"args,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
	Source  string `json:"source"`
	Status  string `json:"status"` // "new", "duplicate", "already_imported"
}

// autoImportScanner can be overridden in tests.
var autoImportScanner = scanForServers

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

	// Send tools/list to the child server
	result, err := s.proxies.SendRequest(r.Context(), serverName, "tools/list", json.RawMessage("{}"))
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
