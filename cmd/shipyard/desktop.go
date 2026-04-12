package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/sloik/shipyard/internal/web"
	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

// desktopApp holds lifecycle state for the Wails desktop window.
type desktopApp struct {
	port       int
	cancelFunc context.CancelFunc
}

// runDesktop starts the Wails native window using the bundled Wails frontend.
// It blocks until the window is closed. When the window closes, it calls
// cancelFunc to trigger graceful shutdown of the HTTP server and proxies.
//
// Architecture: In production, Wails serves the bundled frontend from its asset
// origin. The custom AssetServer handler is therefore a desktop bridge for
// backend traffic only: it proxies /api/* requests to the localhost HTTP server
// and exposes a tiny config endpoint that tells the frontend which explicit
// localhost WebSocket URL to use.
var runDesktopFn = runDesktop

func runDesktop(port int, cancel context.CancelFunc) {
	app := &desktopApp{
		port:       port,
		cancelFunc: cancel,
	}

	// Wait for the HTTP server to be ready before opening the window
	if !waitForServer(port, 10*time.Second) {
		slog.Error("HTTP server did not become ready in time", "port", port)
		cancel()
		return
	}

	slog.Info("opening desktop window", "bridge_port", port)

	uiAssets, err := web.UIAssets()
	if err != nil {
		slog.Error("failed to load embedded desktop UI", "error", err)
		cancel()
		return
	}

	err = wails.Run(&options.App{
		Title:     "Shipyard",
		Width:     1280,
		Height:    800,
		MinWidth:  900,
		MinHeight: 600,
		AssetServer: &assetserver.Options{
			Assets:  uiAssets,
			Handler: newDesktopBridge(port),
		},
		BackgroundColour: &options.RGBA{R: 26, G: 26, B: 46, A: 255},
		OnBeforeClose:    app.beforeClose,
		OnShutdown:       app.shutdown,
	})
	if err != nil {
		slog.Error("wails error", "error", err)
	}

	// Ensure shutdown triggers when the window closes
	cancel()
}

// beforeClose is called when the user attempts to close the window.
// Returning false allows the close to proceed.
func (a *desktopApp) beforeClose(ctx context.Context) (preventClose bool) {
	slog.Info("desktop window closing, triggering shutdown")
	return false
}

// shutdown is called after the window has closed.
func (a *desktopApp) shutdown(ctx context.Context) {
	slog.Info("desktop app shutdown complete")
	if a.cancelFunc != nil {
		a.cancelFunc()
	}
}

// waitForServer polls the HTTP server until it responds or timeout is reached.
func waitForServer(port int, timeout time.Duration) bool {
	url := fmt.Sprintf("http://localhost:%d/api/servers", port)
	deadline := time.Now().Add(timeout)
	client := &http.Client{Timeout: 500 * time.Millisecond}

	for time.Now().Before(deadline) {
		resp, err := client.Get(url)
		if err == nil {
			resp.Body.Close()
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return false
}

type desktopBridge struct {
	config []byte
	proxy  *httputil.ReverseProxy
}

func newDesktopBridge(port int) http.Handler {
	target, err := url.Parse(fmt.Sprintf("http://127.0.0.1:%d", port))
	if err != nil {
		panic(fmt.Sprintf("invalid desktop bridge target: %v", err))
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, proxyErr error) {
		slog.Error("desktop bridge proxy error", "path", r.URL.Path, "error", proxyErr)
		http.Error(w, "desktop bridge proxy error", http.StatusBadGateway)
	}

	config, err := json.Marshal(map[string]string{
		"api_base": fmt.Sprintf("http://127.0.0.1:%d", port),
		"ws_base": fmt.Sprintf("ws://127.0.0.1:%d", port),
	})
	if err != nil {
		panic(fmt.Sprintf("marshal desktop bridge config: %v", err))
	}

	return &desktopBridge{
		config: config,
		proxy:  proxy,
	}
}

func (h *desktopBridge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	slog.Debug("desktop bridge request", "method", r.Method, "path", r.URL.Path)

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/_shipyard/desktop-config":
		w.Header().Set("Content-Type", "application/json")
		w.Write(h.config)
	case strings.HasPrefix(r.URL.Path, "/api/") || r.URL.Path == "/ws":
		h.proxy.ServeHTTP(w, r)
	default:
		http.NotFound(w, r)
	}
}
