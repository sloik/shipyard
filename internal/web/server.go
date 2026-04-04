package web

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
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

// Server is the HTTP + WebSocket server for the web dashboard.
type Server struct {
	port  int
	store *capture.Store
	hub   *Hub
}

// NewServer creates a new web server.
func NewServer(port int, store *capture.Store, hub *Hub) *Server {
	return &Server{port: port, store: store, hub: hub}
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
