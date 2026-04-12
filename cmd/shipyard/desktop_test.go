package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
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
// desktop bridge tests
// ---------------------------------------------------------------------------

func TestDesktopBridge_ServesConfigEndpoint(t *testing.T) {
	handler := newDesktopBridge(9417)

	req := httptest.NewRequest(http.MethodGet, "/_shipyard/desktop-config", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 from config endpoint, got %d", w.Code)
	}
	if ct := w.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("expected Content-Type application/json, got %q", ct)
	}
	if got := strings.TrimSpace(w.Body.String()); got != `{"api_base":"http://127.0.0.1:9417","ws_base":"ws://127.0.0.1:9417"}` {
		t.Fatalf("unexpected desktop config payload: %s", got)
	}
}

func TestDesktopBridge_ProxiesAPIRequestsToLocalhost(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"method":%q,"path":%q,"body":%q}`, r.Method, r.URL.Path, string(body))
	}))
	defer upstream.Close()

	handler := newDesktopBridge(mustPortFromURL(t, upstream.URL))
	req := httptest.NewRequest(http.MethodPost, "/api/servers/alpha/restart", strings.NewReader(`{"force":true}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected proxied API request to return 200, got %d", w.Code)
	}
	body := w.Body.String()
	for _, needle := range []string{`"method":"POST"`, `"path":"/api/servers/alpha/restart"`, `"{\"force\":true}"`} {
		if !strings.Contains(body, needle) {
			t.Fatalf("expected proxied body to contain %s, got %s", needle, body)
		}
	}
}

func TestDesktopBridge_UnknownPathsReturnNotFound(t *testing.T) {
	handler := newDesktopBridge(9417)

	req := httptest.NewRequest(http.MethodGet, "/not-a-real-asset", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected unknown asset-origin path to return 404, got %d", w.Code)
	}
}

func TestDesktopBridge_DifferentPorts(t *testing.T) {
	cases := []struct {
		name string
		port int
	}{
		{"default", 9417},
		{"custom", 8080},
		{"high-port", 65535},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			handler := newDesktopBridge(tc.port)

			req := httptest.NewRequest(http.MethodGet, "/_shipyard/desktop-config", nil)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, req)

			want := fmt.Sprintf(`{"api_base":"http://127.0.0.1:%d","ws_base":"ws://127.0.0.1:%d"}`, tc.port, tc.port)
			if got := strings.TrimSpace(w.Body.String()); got != want {
				t.Fatalf("expected config %s, got %s", want, got)
			}
		})
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

func TestRunProxy_DesktopMode_ManagedProxyErrorPath(t *testing.T) {
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

	// Silence expected error-path logs from the background proxy goroutine.
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
		return errors.New("forced managed proxy failure")
	}

	desktopCalled := make(chan struct{}, 1)
	runDesktopFn = func(port int, cancel context.CancelFunc) {
		desktopCalled <- struct{}{}
		cancel()
	}

	done := make(chan struct{})
	go func() {
		runProxy("test", 0, "ignored", nil, nil, "", false)
		close(done)
	}()

	select {
	case <-desktopCalled:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for desktop runner to be called")
	}

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for runProxy to return")
	}
}

// ---------------------------------------------------------------------------
// Concurrent safety: desktop bridge can serve multiple requests
// ---------------------------------------------------------------------------

func TestDesktopBridge_ConcurrentRequests(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	defer upstream.Close()

	handler := newDesktopBridge(mustPortFromURL(t, upstream.URL))

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req := httptest.NewRequest(http.MethodGet, "/api/servers", nil)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, req)
			if w.Code != http.StatusNoContent {
				t.Errorf("expected 204, got %d", w.Code)
			}
		}()
	}
	wg.Wait()
}

func mustPortFromURL(t *testing.T, rawURL string) int {
	t.Helper()
	parsed, err := url.Parse(rawURL)
	if err != nil {
		t.Fatalf("parse upstream URL: %v", err)
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil {
		t.Fatalf("parse upstream port from %q: %v", rawURL, err)
	}
	return port
}
