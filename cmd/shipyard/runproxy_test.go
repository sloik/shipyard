package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/proxy"
	"github.com/sloik/shipyard/internal/web"
)

type logBuffer struct {
	mu  sync.Mutex
	buf strings.Builder
}

func (b *logBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *logBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

func newEphemeralStore(t *testing.T) *capture.Store {
	t.Helper()
	dir := t.TempDir()
	s, err := capture.NewStore(dir+"/shipyard.db", dir+"/shipyard.jsonl")
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func TestRunProxy_StoreInitFailureExits(t *testing.T) {
	origStore := captureNewStore
	origExit := exitFn
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return nil, errors.New("boom")
	}
	var code int
	exitFn = func(c int) { code = c }
	t.Cleanup(func() {
		captureNewStore = origStore
		exitFn = origExit
	})

	runProxy("alpha", 0, "ignored", nil, nil, "")

	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
}

func TestRunConfig_DefaultPortAndMultiServerForwarding(t *testing.T) {
	origRunMulti := runMultiServerFn
	t.Cleanup(func() { runMultiServerFn = origRunMulti })

	var got struct {
		cfg  *Config
		port int
	}
	runMultiServerFn = func(cfg *Config, port int, schemaPoll time.Duration) {
		got.cfg = cfg
		got.port = port
	}

	dir := t.TempDir()
	path := dir + "/servers.json"
	data := `{
		"servers": {
			"alpha": {"command":"echo","args":["one"],"env":{"A":"1"},"cwd":"/tmp/alpha"},
			"beta": {"command":"printf","args":["two"]}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	runConfig(path, 60*time.Second)

	if got.cfg == nil {
		t.Fatal("expected runMultiServer to be called")
	}
	if got.port != 9417 {
		t.Fatalf("expected default port 9417, got %d", got.port)
	}
	if len(got.cfg.ServerOrder) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(got.cfg.ServerOrder))
	}
	if got.cfg.ServerOrder[0] != "alpha" {
		t.Fatalf("expected first server alpha, got %q", got.cfg.ServerOrder[0])
	}
	srv := got.cfg.Servers["alpha"]
	if srv.Command != "echo" || len(srv.Args) != 1 || srv.Args[0] != "one" {
		t.Fatalf("unexpected alpha command/args: %q %v", srv.Command, srv.Args)
	}
	if srv.Cwd != "/tmp/alpha" {
		t.Fatalf("expected cwd /tmp/alpha, got %q", srv.Cwd)
	}
	if srv.Env["A"] != "1" {
		t.Fatalf("expected env to be forwarded, got %v", srv.Env)
	}
}

func TestRunConfig_MultiServerAllStarted(t *testing.T) {
	origRunMulti := runMultiServerFn
	t.Cleanup(func() { runMultiServerFn = origRunMulti })

	var got struct {
		cfg  *Config
		port int
	}
	runMultiServerFn = func(cfg *Config, port int, schemaPoll time.Duration) {
		got.cfg = cfg
		got.port = port
	}

	dir := t.TempDir()
	path := dir + "/servers.json"
	data := `{
		"servers": {
			"alpha": {"command":"echo"},
			"beta": {"command":"printf"}
		},
		"web": {"port": 8080}
	}`
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	runConfig(path, 60*time.Second)

	if got.cfg == nil {
		t.Fatal("expected runMultiServer to be called")
	}
	if got.port != 8080 {
		t.Fatalf("expected explicit port 8080, got %d", got.port)
	}
	// Both servers should be present — no longer drops second server
	if len(got.cfg.ServerOrder) != 2 {
		t.Fatalf("expected 2 servers in config, got %d", len(got.cfg.ServerOrder))
	}
}

func TestRunConfig_SecondServerMissingCommand(t *testing.T) {
	origRunMulti := runMultiServerFn
	origExit := exitFn
	t.Cleanup(func() {
		runMultiServerFn = origRunMulti
		exitFn = origExit
	})

	var exitCode int
	exitFn = func(c int) { exitCode = c }
	runMultiServerFn = func(cfg *Config, port int, schemaPoll time.Duration) {
		t.Fatal("should not reach runMultiServer when a server has no command")
	}

	dir := t.TempDir()
	path := dir + "/servers.json"
	data := `{
		"servers": {
			"alpha": {"command":"echo"},
			"beta": {}
		}
	}`
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatalf("write config: %v", err)
	}

	runConfig(path, 60*time.Second)

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
}

func TestRunConfig_LoadFailureExits(t *testing.T) {
	origExit := exitFn
	defer func() { exitFn = origExit }()

	var code int
	exitFn = func(c int) { code = c }

	runConfig("/definitely/missing/config.json", 60*time.Second)

	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
}

func TestRunProxy_LogsWebServerAndProxyErrors(t *testing.T) {
	origStore := captureNewStore
	origHub := webNewHub
	origMgr := proxyNewManager
	origStartWeb := startWebServer
	origRunManaged := runManagedProxy
	origDefault := slog.Default()

	t.Cleanup(func() {
		captureNewStore = origStore
		webNewHub = origHub
		proxyNewManager = origMgr
		startWebServer = origStartWeb
		runManagedProxy = origRunManaged
		slog.SetDefault(origDefault)
	})

	store := newEphemeralStore(t)
	captureNewStore = func(dbPath, jsonlPath string) (*capture.Store, error) {
		return store, nil
	}
	webNewHub = func() *web.Hub { return web.NewHub() }
	proxyNewManager = func() *proxy.Manager { return proxy.NewManager() }

	logs := &logBuffer{}
	slog.SetDefault(slog.New(slog.NewTextHandler(logs, nil)))

	webStarted := make(chan struct{})
	startWebServer = func(ctx context.Context, srv *web.Server) error {
		close(webStarted)
		return errors.New("web exploded")
	}
	runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
		<-webStarted
		return errors.New("proxy exploded")
	}

	runProxy("alpha", 0, "ignored", nil, nil, "")

	out := logs.String()
	if !strings.Contains(out, "web server error") {
		t.Fatalf("expected web server error log, got %q", out)
	}
	if !strings.Contains(out, "proxy error") {
		t.Fatalf("expected proxy error log, got %q", out)
	}
}

func TestMain_InvalidFlagShowsUsage(t *testing.T) {
	code, output := runShipyardMain(t, "--definitely-invalid")
	if code != 1 {
		t.Fatalf("expected exit code 1, got %d", code)
	}
	if !strings.Contains(output, "usage: shipyard wrap") {
		t.Fatalf("expected usage output, got %q", output)
	}
}

func TestRunWrap_UsesSeparatorBranch(t *testing.T) {
	origRunProxy := runProxyFn
	t.Cleanup(func() { runProxyFn = origRunProxy })

	var got struct {
		name    string
		port    int
		command string
		args    []string
	}
	runProxyFn = func(name string, port int, command string, args []string, env map[string]string, cwd string) {
		got.name = name
		got.port = port
		got.command = command
		got.args = append([]string(nil), args...)
	}

	runWrap([]string{"--name", "sep", "--port", "1234", "--", "echo", "hello"})

	if got.name != "sep" || got.port != 1234 || got.command != "echo" {
		t.Fatalf("unexpected forwarded values: %+v", got)
	}
	if len(got.args) != 1 || got.args[0] != "hello" {
		t.Fatalf("unexpected forwarded args: %v", got.args)
	}
}
