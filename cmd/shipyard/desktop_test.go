package main

import (
	"context"
	"errors"
	"fmt"
	"html"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/proxy"
	"github.com/sloik/shipyard/internal/web"
)

// ---------------------------------------------------------------------------
// waitForServer tests
// ---------------------------------------------------------------------------

func TestWaitForServer_HappyPath(t *testing.T) {
	// Start a real HTTP server on a random port, verify waitForServer returns true.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})}
	go srv.Serve(ln)
	t.Cleanup(func() { srv.Close() })

	if !waitForServer(port, 2*time.Second) {
		t.Fatal("expected waitForServer to return true for a running server")
	}
}

func TestWaitForServer_Timeout(t *testing.T) {
	// Grab a port that nothing is listening on.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close() // close immediately so nothing is listening

	if waitForServer(port, 100*time.Millisecond) {
		t.Fatal("expected waitForServer to return false when nothing is listening")
	}
}

func TestWaitForServer_DelayedStart(t *testing.T) {
	// Reserve a port, start a server after a delay, verify waitForServer still succeeds.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close() // release so we can re-bind after delay

	go func() {
		time.Sleep(200 * time.Millisecond)
		delayed, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
		if err != nil {
			return // port was reused — test will fail on the assertion
		}
		srv := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusOK)
		})}
		go srv.Serve(delayed)
		// cleaned up when test process exits
	}()

	if !waitForServer(port, 2*time.Second) {
		t.Fatal("expected waitForServer to succeed after delayed server start")
	}
}

func TestWaitForServer_PortZero(t *testing.T) {
	// Port 0 is not a real port — should timeout quickly.
	if waitForServer(0, 100*time.Millisecond) {
		t.Fatal("expected waitForServer to return false for port 0")
	}
}

// ---------------------------------------------------------------------------
// redirector tests
// ---------------------------------------------------------------------------

func TestRedirector_ServesHTMLWithTargetURL(t *testing.T) {
	target := "http://localhost:9417"
	handler := newRedirector(target)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	body := w.Body.String()
	if !strings.Contains(body, fmt.Sprintf("window.location.replace(%q)", target)) {
		t.Fatalf("expected body to contain redirect to %s, got:\n%s", target, body)
	}
}

func TestRedirector_ContentType(t *testing.T) {
	handler := newRedirector("http://localhost:9417")

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	ct := w.Header().Get("Content-Type")
	if ct != "text/html; charset=utf-8" {
		t.Fatalf("expected Content-Type %q, got %q", "text/html; charset=utf-8", ct)
	}
}

func TestRedirector_ValidHTML(t *testing.T) {
	handler := newRedirector("http://localhost:9417")

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	body := w.Body.String()
	if !strings.HasPrefix(body, "<!DOCTYPE html>") {
		t.Fatalf("expected body to start with <!DOCTYPE html>, got:\n%s", body)
	}
	if !strings.Contains(body, "</html>") {
		t.Fatalf("expected body to contain closing </html> tag, got:\n%s", body)
	}
}

func TestRedirector_DifferentPorts(t *testing.T) {
	cases := []struct {
		name string
		url  string
	}{
		{"default", "http://localhost:9417"},
		{"custom", "http://localhost:8080"},
		{"high-port", "http://localhost:65535"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			handler := newRedirector(tc.url)

			req := httptest.NewRequest(http.MethodGet, "/", nil)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, req)

			body := w.Body.String()
			if !strings.Contains(body, fmt.Sprintf("window.location.replace(%q)", tc.url)) {
				t.Fatalf("expected redirect to %s in body, got:\n%s", tc.url, body)
			}
		})
	}
}

func TestRedirector_SpecialCharactersEscaped(t *testing.T) {
	// URL with special chars — %q in fmt.Sprintf should escape them in the Go
	// string, and the HTML should not contain unescaped angle brackets.
	target := `http://localhost:9417/path?foo=bar&baz=<script>`
	handler := newRedirector(target)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	body := w.Body.String()

	// The URL should appear in the body (possibly with Go %q escaping of special chars)
	// but raw unquoted <script> must not appear outside the quoted string
	if strings.Contains(body, "<script>") && !strings.Contains(body, html.EscapeString("<script>")) {
		// Check that the angle brackets are inside the quoted string from %q,
		// which would render them as \u003c / \u003e or keep them inside quotes.
		// fmt.Sprintf(%q, ...) wraps the whole URL in Go-style double quotes and
		// escapes control chars. Verify the body contains the %q-escaped form.
		escaped := fmt.Sprintf("%q", target)
		if !strings.Contains(body, escaped) {
			t.Fatalf("expected special characters to be properly quoted in body, got:\n%s", body)
		}
	}
}

// ---------------------------------------------------------------------------
// runDesktopFn mockability
// ---------------------------------------------------------------------------

func TestRunDesktopFn_IsFunctionVariable(t *testing.T) {
	// Verify runDesktopFn can be replaced — this is the mockability contract.
	orig := runDesktopFn
	t.Cleanup(func() { runDesktopFn = orig })

	var calledPort int
	var calledCancel context.CancelFunc
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		calledPort = port
		calledCancel = cancel
	}

	_, cancel := context.WithCancel(context.Background())
	defer cancel()

	runDesktopFn(4242, cancel)

	if calledPort != 4242 {
		t.Fatalf("expected mock called with port 4242, got %d", calledPort)
	}
	if calledCancel == nil {
		t.Fatal("expected mock to receive a non-nil cancel function")
	}
}

// ---------------------------------------------------------------------------
// --headless flag integration: runProxy
// ---------------------------------------------------------------------------

func TestRunProxy_HeadlessTrue_DoesNotCallDesktop(t *testing.T) {
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDesktop := runDesktopFn
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		runDesktopFn = origDesktop
		slog.SetDefault(origDefault)
	})

	// Suppress logs
	slog.SetDefault(slog.New(slog.NewTextHandler(&strings.Builder{}, nil)))

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		<-ctx.Done()
		return nil
	}
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		return nil // exit immediately
	}

	var desktopCalled atomic.Bool
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		desktopCalled.Store(true)
	}

	runProxy("test", 0, "ignored", nil, nil, "", true)

	if desktopCalled.Load() {
		t.Fatal("expected runDesktopFn NOT to be called in headless mode")
	}
}

func TestRunProxy_HeadlessFalse_CallsDesktop(t *testing.T) {
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDesktop := runDesktopFn
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		runDesktopFn = origDesktop
		slog.SetDefault(origDefault)
	})

	slog.SetDefault(slog.New(slog.NewTextHandler(&strings.Builder{}, nil)))

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		<-ctx.Done()
		return nil
	}
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		<-ctx.Done()
		return nil
	}

	var gotPort int
	var gotCancel context.CancelFunc
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		gotPort = port
		gotCancel = cancel
		// Simulate window close — call cancel to unblock runProxy
		cancel()
	}

	runProxy("test", 7777, "ignored", nil, nil, "", false)

	if gotCancel == nil {
		t.Fatal("expected runDesktopFn to be called in non-headless mode")
	}
	if gotPort != 7777 {
		t.Fatalf("expected runDesktopFn called with port 7777, got %d", gotPort)
	}
}

// ---------------------------------------------------------------------------
// --headless flag integration: runMultiServer
// ---------------------------------------------------------------------------

func TestRunMultiServer_HeadlessTrue_DoesNotCallDesktop(t *testing.T) {
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDesktop := runDesktopFn
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		runDesktopFn = origDesktop
		slog.SetDefault(origDefault)
	})

	slog.SetDefault(slog.New(slog.NewTextHandler(&strings.Builder{}, nil)))

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		<-ctx.Done()
		return nil
	}
	// runManagedProxy is called inside runServerWithRestart — we need it to
	// exit quickly so the WaitGroup completes. Stub it to return immediately.
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		return nil
	}

	var desktopCalled atomic.Bool
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		desktopCalled.Store(true)
	}

	cfg := &Config{
		Servers: map[string]ServerConfig{
			"alpha": {Command: "echo"},
		},
		ServerOrder: []string{"alpha"},
	}

	runMultiServer(cfg, 0, 0, true)

	if desktopCalled.Load() {
		t.Fatal("expected runDesktopFn NOT to be called in headless mode")
	}
}

func TestRunMultiServer_HeadlessFalse_CallsDesktop(t *testing.T) {
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDesktop := runDesktopFn
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		runDesktopFn = origDesktop
		slog.SetDefault(origDefault)
	})

	slog.SetDefault(slog.New(slog.NewTextHandler(&strings.Builder{}, nil)))

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		<-ctx.Done()
		return nil
	}
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		<-ctx.Done()
		return nil
	}

	var gotPort int
	var gotCancel context.CancelFunc
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		gotPort = port
		gotCancel = cancel
		// Simulate window close
		cancel()
	}

	cfg := &Config{
		Servers: map[string]ServerConfig{
			"alpha": {Command: "echo"},
		},
		ServerOrder: []string{"alpha"},
	}

	runMultiServer(cfg, 8888, 0, false)

	if gotCancel == nil {
		t.Fatal("expected runDesktopFn to be called in non-headless mode")
	}
	if gotPort != 8888 {
		t.Fatalf("expected runDesktopFn called with port 8888, got %d", gotPort)
	}
}

// ---------------------------------------------------------------------------
// desktopApp lifecycle tests
// ---------------------------------------------------------------------------

func TestDesktopApp_BeforeClose_ReturnsFalse(t *testing.T) {
	app := &desktopApp{
		port:       9417,
		cancelFunc: func() {},
	}
	if app.beforeClose(context.Background()) {
		t.Fatal("expected beforeClose to return false (allow close)")
	}
}

func TestDesktopApp_Shutdown_CallsCancel(t *testing.T) {
	var called atomic.Bool
	app := &desktopApp{
		port: 9417,
		cancelFunc: func() {
			called.Store(true)
		},
	}
	app.shutdown(context.Background())
	if !called.Load() {
		t.Fatal("expected shutdown to call cancelFunc")
	}
}

func TestDesktopApp_Shutdown_NilCancel(t *testing.T) {
	// shutdown with nil cancelFunc should not panic
	app := &desktopApp{
		port:       9417,
		cancelFunc: nil,
	}
	app.shutdown(context.Background()) // should not panic
}

// ---------------------------------------------------------------------------
// Edge cases
// ---------------------------------------------------------------------------

func TestDesktopApp_MultipleCancelCalls_NoPanic(t *testing.T) {
	// context.CancelFunc is idempotent — calling it multiple times must not panic.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	app := &desktopApp{
		port:       9417,
		cancelFunc: cancel,
	}

	// Call shutdown multiple times (simulates both shutdown callback and runDesktop's deferred cancel)
	app.shutdown(ctx)
	app.shutdown(ctx)
	cancel() // one more direct call

	// If we get here without panic, the test passes.
}

func TestRunProxy_HeadlessFalse_DesktopReceivesCorrectCancel(t *testing.T) {
	// Verify that when runDesktopFn calls cancel, the context used by
	// runManagedProxy is actually cancelled.
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDesktop := runDesktopFn
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		runDesktopFn = origDesktop
		slog.SetDefault(origDefault)
	})

	slog.SetDefault(slog.New(slog.NewTextHandler(&strings.Builder{}, nil)))

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		<-ctx.Done()
		return nil
	}

	proxyCancelled := make(chan struct{})
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		<-ctx.Done()
		close(proxyCancelled)
		return nil
	}

	runDesktopFn = func(port int, cancel context.CancelFunc) {
		// Simulate window close — cancel the context
		cancel()
	}

	done := make(chan struct{})
	go func() {
		runProxy("test", 0, "ignored", nil, nil, "", false)
		close(done)
	}()

	select {
	case <-proxyCancelled:
		// Good — proxy context was cancelled when desktop called cancel()
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for proxy context to be cancelled after desktop close")
	}

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for runProxy to return")
	}
}

func TestRunProxy_StoreInitFailure_HeadlessDoesNotCallDesktop(t *testing.T) {
	// Even when headless=false, if store init fails we should exit before
	// reaching the desktop branch.
	origStore := captureNewStore
	origExit := exitFn
	origDesktop := runDesktopFn

	t.Cleanup(func() {
		captureNewStore = origStore
		exitFn = origExit
		runDesktopFn = origDesktop
	})

	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return nil, errors.New("boom")
	}
	var code int
	exitFn = func(c int) { code = c }

	var desktopCalled atomic.Bool
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		desktopCalled.Store(true)
	}

	runProxy("test", 0, "ignored", nil, nil, "", false)

	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if desktopCalled.Load() {
		t.Fatal("expected runDesktopFn NOT to be called when store init fails")
	}
}

// ---------------------------------------------------------------------------
// Concurrent safety: redirector can serve multiple requests
// ---------------------------------------------------------------------------

func TestRedirector_ConcurrentRequests(t *testing.T) {
	handler := newRedirector("http://localhost:9417")

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodGet, "/", nil)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, req)
			if w.Code != http.StatusOK {
				t.Errorf("expected 200, got %d", w.Code)
			}
		}()
	}
	wg.Wait()
}
