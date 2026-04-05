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

// ProxyManager defines the interface the web server uses to interact with proxies.
type ProxyManager interface {
	Servers() []ServerInfo
	SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error)
}

// ServerInfo describes a running server for the API.
type ServerInfo struct {
	Name   string `json:"name"`
	Status string `json:"status"`
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
	uiContent, err := fs.Sub(uiFS, "ui")
	if err != nil {
		return fmt.Errorf("embed ui: %w", err)
	}
	mux.Handle("GET /", http.FileServer(http.FS(uiContent)))

	// API endpoints
	mux.HandleFunc("GET /api/traffic", s.handleTraffic)
	mux.HandleFunc("GET /api/traffic/{id}", s.handleTrafficDetail)
	mux.HandleFunc("GET /api/servers", s.handleServers)
	mux.HandleFunc("GET /api/tools", s.handleTools)
	mux.HandleFunc("POST /api/tools/call", s.handleToolCall)
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

	serverFilter := r.URL.Query().Get("server")
	methodFilter := r.URL.Query().Get("method")

	result, err := s.store.Query(page, pageSize, serverFilter, methodFilter)
	if err != nil {
		slog.Error("query traffic", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
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

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
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
