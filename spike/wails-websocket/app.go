package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/coder/websocket"
)

// App struct holds lifecycle state for the Wails application.
type App struct {
	ctx        context.Context
	cancel     context.CancelFunc
	httpServer *http.Server
	wg         sync.WaitGroup
}

// NewApp creates a new App instance.
func NewApp() *App {
	return &App{}
}

// startup is called when the Wails app starts. The context is saved
// so we can call runtime methods.
func (a *App) startup(ctx context.Context) {
	a.ctx, a.cancel = context.WithCancel(ctx)
	a.startHTTPServer()
}

// shutdown is called when the Wails app is closing.
func (a *App) shutdown(ctx context.Context) {
	log.Println("[spike] shutting down HTTP server...")
	a.cancel()

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer shutdownCancel()

	if a.httpServer != nil {
		_ = a.httpServer.Shutdown(shutdownCtx)
	}
	a.wg.Wait()
	log.Println("[spike] HTTP server stopped")
}

// startHTTPServer starts the sidecar HTTP server on :9417.
func (a *App) startHTTPServer() {
	mux := http.NewServeMux()

	// REST endpoint
	mux.HandleFunc("/api/ping", a.handlePing)

	// WebSocket endpoint
	mux.HandleFunc("/ws", a.handleWS)

	// Simple HTML page (for testing outside Wails)
	mux.HandleFunc("/", a.handleIndex)

	a.httpServer = &http.Server{
		Addr:    ":9417",
		Handler: mux,
	}

	a.wg.Add(1)
	go func() {
		defer a.wg.Done()
		ln, err := net.Listen("tcp", ":9417")
		if err != nil {
			log.Printf("[spike] failed to listen on :9417: %v", err)
			return
		}
		log.Println("[spike] HTTP server listening on :9417")
		if err := a.httpServer.Serve(ln); err != nil && err != http.ErrServerClosed {
			log.Printf("[spike] HTTP server error: %v", err)
		}
	}()
}

// handlePing returns a simple JSON status response.
func (a *App) handlePing(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	resp := map[string]string{
		"status": "ok",
		"time":   time.Now().UTC().Format(time.RFC3339),
	}
	json.NewEncoder(w).Encode(resp)
}

// handleWS upgrades to WebSocket and sends tick messages every second.
func (a *App) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		// Allow connections from any origin (spike — not production)
		InsecureSkipVerify: true,
	})
	if err != nil {
		log.Printf("[spike] websocket accept error: %v", err)
		return
	}
	defer conn.CloseNow()

	log.Println("[spike] WebSocket client connected")

	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()

	count := 0
	for {
		select {
		case <-a.ctx.Done():
			conn.Close(websocket.StatusNormalClosure, "server shutting down")
			return
		case <-ticker.C:
			count++
			msg := map[string]interface{}{
				"type":  "tick",
				"count": count,
				"time":  time.Now().UTC().Format(time.RFC3339Nano),
			}
			data, _ := json.Marshal(msg)
			err := conn.Write(a.ctx, websocket.MessageText, data)
			if err != nil {
				log.Printf("[spike] websocket write error: %v", err)
				return
			}
		}
	}
}

// handleIndex serves a minimal HTML page for browser-based testing.
func (a *App) handleIndex(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, `<!DOCTYPE html>
<html><head><title>Shipyard WS Spike (browser)</title></head>
<body>
<h1>Shipyard WebSocket Spike — Browser Mode</h1>
<p>Open the Wails app for the real test. This page is for quick browser checks.</p>
<pre id="log"></pre>
<script>
const log = document.getElementById('log');
const ws = new WebSocket('ws://localhost:9417/ws');
ws.onmessage = (e) => { log.textContent = e.data + '\n' + log.textContent; };
ws.onerror = (e) => { log.textContent = 'ERROR: ' + e + '\n' + log.textContent; };
</script>
</body></html>`)
}
