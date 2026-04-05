package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"strings"
	"sync"
	"testing"

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
	origRunProxy := runProxyFn
	t.Cleanup(func() { runProxyFn = origRunProxy })

	var got struct {
		name    string
		port    int
		command string
		args    []string
		env     map[string]string
		cwd     string
	}
	runProxyFn = func(name string, port int, command string, args []string, env map[string]string, cwd string) {
		got.name = name
		got.port = port
		got.command = command
		got.args = append([]string(nil), args...)
		got.env = env
		got.cwd = cwd
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

	runConfig(path)

	if got.name != "alpha" {
		t.Fatalf("expected first server alpha, got %q", got.name)
	}
	if got.port != 9417 {
		t.Fatalf("expected default port 9417, got %d", got.port)
	}
	if got.command != "echo" || len(got.args) != 1 || got.args[0] != "one" {
		t.Fatalf("unexpected forwarded command/args: %q %v", got.command, got.args)
	}
	if got.cwd != "/tmp/alpha" {
		t.Fatalf("expected cwd /tmp/alpha, got %q", got.cwd)
	}
	if got.env["A"] != "1" {
		t.Fatalf("expected env to be forwarded, got %v", got.env)
	}
}

func TestRunConfig_MultiServerLogsWarning(t *testing.T) {
	origRunProxy := runProxyFn
	t.Cleanup(func() { runProxyFn = origRunProxy })

	origDefault := slog.Default()
	t.Cleanup(func() { slog.SetDefault(origDefault) })

	logs := &logBuffer{}
	slog.SetDefault(slog.New(slog.NewTextHandler(logs, nil)))

	var got struct {
		name string
		port int
	}
	runProxyFn = func(name string, port int, command string, args []string, env map[string]string, cwd string) {
		got.name = name
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

	runConfig(path)

	if got.name != "alpha" {
		t.Fatalf("expected first server alpha, got %q", got.name)
	}
	if got.port != 8080 {
		t.Fatalf("expected explicit port 8080, got %d", got.port)
	}
	if !strings.Contains(logs.String(), "multi-server config not yet supported") {
		t.Fatalf("expected multi-server warning, got %q", logs.String())
	}
}

func TestRunConfig_LoadFailureExits(t *testing.T) {
	origExit := exitFn
	defer func() { exitFn = origExit }()

	var code int
	exitFn = func(c int) { code = c }

	runConfig("/definitely/missing/config.json")

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
