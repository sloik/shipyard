package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"time"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

// desktopApp holds lifecycle state for the Wails desktop window.
type desktopApp struct {
	port       int
	cancelFunc context.CancelFunc
}

// runDesktop starts the Wails native window pointing at the localhost HTTP server.
// It blocks until the window is closed. When the window closes, it calls cancelFunc
// to trigger graceful shutdown of the HTTP server and proxies.
//
// Architecture: The Wails AssetServer handler serves a tiny redirector page that
// navigates the webview to http://localhost:{port}. Once there, all relative URLs
// (fetch, WebSocket) resolve against localhost — zero frontend changes needed.
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

	url := fmt.Sprintf("http://localhost:%d", port)
	slog.Info("opening desktop window", "url", url)

	err := wails.Run(&options.App{
		Title:     "Shipyard",
		Width:     1280,
		Height:    800,
		MinWidth:  900,
		MinHeight: 600,
		AssetServer: &assetserver.Options{
			Handler: newRedirector(url),
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

// redirector serves a tiny HTML page that navigates the webview to the
// localhost HTTP server. This is the Wails AssetServer handler for Option B
// (window loads from localhost). After the redirect, the webview's origin is
// http://localhost:{port} and all relative fetch/WebSocket URLs resolve correctly.
type redirector struct {
	page []byte
}

func newRedirector(targetURL string) *redirector {
	html := fmt.Sprintf(`<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body{background:#1a1a2e;margin:0}</style>
<script>window.location.replace(%q);</script>
</head><body></body></html>`, targetURL)
	return &redirector{page: []byte(html)}
}

func (h *redirector) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(h.page)
}
