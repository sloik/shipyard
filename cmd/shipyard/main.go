package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/proxy"
	"github.com/sloik/shipyard/internal/web"
)

var (
	version = "dev"
	commit  = "none"
)

var parseServerOrder = func(raw json.RawMessage, appendName func(string), consumeValue func(*json.Decoder, string) error) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	tok, err := dec.Token()
	if err != nil {
		return fmt.Errorf("read servers object: %w", err)
	}
	delim, ok := tok.(json.Delim)
	if !ok || delim != '{' {
		return fmt.Errorf("servers must be a JSON object")
	}

	for dec.More() {
		keyTok, err := dec.Token()
		if err != nil {
			return fmt.Errorf("read server name: %w", err)
		}
		name, ok := keyTok.(string)
		if !ok {
			return fmt.Errorf("server name must be a string")
		}
		appendName(name)
		if err := consumeValue(dec, name); err != nil {
			return err
		}
	}

	if _, err := dec.Token(); err != nil {
		return fmt.Errorf("close servers object: %w", err)
	}

	return nil
}

var captureNewStore = capture.NewStore
var webNewHub = web.NewHub
var proxyNewManager = proxy.NewManager
var exitFn = os.Exit
var startWebServer = func(ctx context.Context, srv *web.Server) error {
	return srv.Start(ctx)
}
var runManagedProxy = func(ctx context.Context, mgr *proxy.Manager, name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) error {
	p := proxy.NewProxy(name, command, args, env, cwd, store, hub)
	mp := mgr.Register(name, p)
	p.SetManaged(mp)
	return p.Run(ctx)
}
var runProxyFn = runProxy
var runMultiServerFn = runMultiServer
var runNoServersFn = runNoServers

// dataDir returns a writable directory for Shipyard's database and logs.
// On macOS .app launch, cwd is "/" (read-only), so we use a platform-appropriate
// data directory. Falls back to cwd if home directory is unavailable.
var dataDirFn = dataDir

func dataDir() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return "."
	}
	var dir string
	switch runtime.GOOS {
	case "darwin":
		dir = filepath.Join(home, "Library", "Application Support", "Shipyard")
	case "windows":
		if appData := os.Getenv("APPDATA"); appData != "" {
			dir = filepath.Join(appData, "Shipyard")
		} else {
			dir = filepath.Join(home, "Shipyard")
		}
	default:
		dir = filepath.Join(home, ".shipyard")
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		slog.Warn("failed to create data directory, using cwd", "dir", dir, "error", err)
		return "."
	}
	return dir
}

type Config struct {
	Servers     map[string]ServerConfig `json:"servers"`
	ServerOrder []string                `json:"-"`
	Web         WebConfig               `json:"web"`
}

type ServerConfig struct {
	Command string            `json:"command"`
	Args    []string          `json:"args"`
	Env     map[string]string `json:"env"`
	Cwd     string            `json:"cwd"`
}

type WebConfig struct {
	Port int `json:"port"`
}

func (c *Config) UnmarshalJSON(data []byte) error {
	var raw struct {
		Servers json.RawMessage `json:"servers"`
		Web     WebConfig       `json:"web"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	c.Web = raw.Web
	if len(raw.Servers) == 0 {
		return nil
	}

	if err := json.Unmarshal(raw.Servers, &c.Servers); err != nil {
		return fmt.Errorf("parse servers: %w", err)
	}

	if err := parseServerOrder(raw.Servers, func(name string) {
		c.ServerOrder = append(c.ServerOrder, name)
	}, func(dec *json.Decoder, name string) error {
		var discard json.RawMessage
		if err := dec.Decode(&discard); err != nil {
			return fmt.Errorf("read server %q: %w", name, err)
		}
		return nil
	}); err != nil {
		return err
	}

	return nil
}

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelDebug})))

	global := flag.NewFlagSet("shipyard", flag.ContinueOnError)
	global.SetOutput(io.Discard)
	configPath := global.String("config", "", "path to JSON config file")
	schemaPoll := global.Duration("schema-poll", 60*time.Second, "schema change polling interval")
	showVersion := global.Bool("version", false, "print version and exit")
	headless := global.Bool("headless", false, "run without desktop window (CLI/server mode)")

	if err := global.Parse(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		fmt.Fprintln(os.Stderr, "   or: shipyard --config <servers.json>")
		exitFn(1)
		return
	}

	if *showVersion {
		fmt.Fprintf(os.Stdout, "shipyard v%s (%s)\n", version, commit)
		return
	}

	if *configPath != "" {
		runConfig(*configPath, *schemaPoll, *headless)
		return
	}

	args := global.Args()
	if len(args) == 0 {
		if *headless {
			fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
			fmt.Fprintln(os.Stderr, "   or: shipyard --config <servers.json>")
			exitFn(1)
			return
		}
		// Desktop mode with no servers — open empty dashboard
		runNoServersFn(9417, *headless)
		return
	}

	switch args[0] {
	case "wrap":
		runWrap(args[1:], *headless)
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", args[0])
		exitFn(1)
		return
	}
}

func runConfig(configPath string, schemaPoll time.Duration, headless bool) {
	cfg, err := loadConfig(configPath)
	if err != nil {
		slog.Error("failed to load config", "path", configPath, "error", err)
		exitFn(1)
		return
	}

	if len(cfg.ServerOrder) == 0 {
		slog.Error("config does not define any servers", "path", configPath)
		exitFn(1)
		return
	}

	port := cfg.Web.Port
	if port == 0 {
		port = 9417
	}

	// Validate all servers have commands
	for _, name := range cfg.ServerOrder {
		srv := cfg.Servers[name]
		if srv.Command == "" {
			slog.Error("config server is missing command", "server", name, "path", configPath)
			exitFn(1)
			return
		}
	}

	runMultiServerFn(cfg, port, schemaPoll, headless)
}

func loadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, fmt.Errorf("config file not found: %s", path)
		}
		return nil, fmt.Errorf("read config file %s: %w", path, err)
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("parse config file %s: %w", path, err)
	}

	return &cfg, nil
}

func seedConfiguredServers(cfg *Config, mgr *proxy.Manager, store *capture.Store, hub *web.Hub) {
	for _, name := range cfg.ServerOrder {
		server := cfg.Servers[name]
		p := proxy.NewProxy(name, server.Command, server.Args, server.Env, server.Cwd, store, hub)
		mgr.Register(name, p)
		mgr.SetStatus(name, "starting", "")
	}
}

func runProxy(name string, port int, command string, args []string, env map[string]string, cwd string, headless bool) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		sig := <-sigCh
		slog.Info("received signal, shutting down", "signal", sig)
		cancel()
	}()

	// Initialize capture store
	dir := dataDirFn()
	store, err := captureNewStore(filepath.Join(dir, "shipyard.db"), filepath.Join(dir, "shipyard.jsonl"))
	if err != nil {
		slog.Error("failed to initialize capture store", "error", err)
		exitFn(1)
		return
	}
	defer store.Close()

	// Start web dashboard
	hub := webNewHub()
	go hub.Run(ctx)

	// Create proxy manager
	mgr := proxyNewManager()

	srv := web.NewServer(port, store, hub)
	srv.SetProxyManager(mgr)
	go func() {
		slog.Info("web dashboard starting", "url", fmt.Sprintf("http://localhost:%d", port))
		if err := startWebServer(ctx, srv); err != nil {
			slog.Error("web server error", "error", err)
		}
	}()

	if !headless {
		// Desktop mode: start proxy in background, open Wails window
		go func() {
			if err := runManagedProxy(ctx, mgr, name, command, args, env, cwd, store, hub); err != nil {
				slog.Error("proxy error", "error", err)
			}
		}()
		// runDesktop blocks until the window closes, then triggers cancel()
		runDesktopFn(port, cancel)
	} else {
		// Headless mode: start proxy (blocks until child exits or context cancelled)
		if err := runManagedProxy(ctx, mgr, name, command, args, env, cwd, store, hub); err != nil {
			slog.Error("proxy error", "error", err)
		}
	}
}

func runWrap(args []string, headless bool) {
	fs := flag.NewFlagSet("wrap", flag.ExitOnError)
	name := fs.String("name", "child", "server name for display")
	port := fs.Int("port", 9417, "web dashboard port")
	fs.Parse(args)

	remaining := fs.Args()
	childCmd := remaining

	if len(childCmd) == 0 {
		fmt.Fprintln(os.Stderr, "error: no child command specified")
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		exitFn(1)
		return
	}

	runProxyFn(*name, *port, childCmd[0], childCmd[1:], nil, "", headless)
}

func runMultiServer(cfg *Config, port int, schemaPoll time.Duration, headless bool) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		sig := <-sigCh
		slog.Info("received signal, shutting down", "signal", sig)
		cancel()
	}()

	// Initialize capture store
	dir := dataDirFn()
	store, err := captureNewStore(filepath.Join(dir, "shipyard.db"), filepath.Join(dir, "shipyard.jsonl"))
	if err != nil {
		slog.Error("failed to initialize capture store", "error", err)
		exitFn(1)
		return
	}
	defer store.Close()

	// Start web dashboard
	hub := webNewHub()
	go hub.Run(ctx)

	// Create proxy manager
	mgr := proxyNewManager()
	mgr.SetHub(hub)
	seedConfiguredServers(cfg, mgr, store, hub)

	srv := web.NewServer(port, store, hub)
	srv.SetProxyManager(mgr)
	go func() {
		slog.Info("web dashboard starting", "url", fmt.Sprintf("http://localhost:%d", port))
		if err := startWebServer(ctx, srv); err != nil {
			slog.Error("web server error", "error", err)
		}
	}()

	// Start all servers concurrently
	var wg sync.WaitGroup
	for _, name := range cfg.ServerOrder {
		server := cfg.Servers[name]
		wg.Add(1)
		go func(name string, server ServerConfig) {
			defer wg.Done()
			runServerWithRestart(ctx, mgr, name, server, store, hub)
		}(name, server)
	}

	slog.Info("all servers started", "count", len(cfg.ServerOrder))

	// Start schema change watcher
	if schemaPoll > 0 {
		go func() {
			// Give servers a moment to initialize before first baseline capture
			select {
			case <-time.After(3 * time.Second):
			case <-ctx.Done():
				return
			}
			slog.Info("schema watcher starting", "interval", schemaPoll)
			mgr.StartSchemaWatcher(ctx, store, schemaPoll)
		}()
	}

	if !headless {
		// Desktop mode: open Wails window (blocks until closed)
		// When the window closes, cancel() triggers shutdown of all servers
		runDesktopFn(port, cancel)
		// After window closes, wait for servers to finish
		wg.Wait()
	} else {
		// Headless mode: block until all servers exit
		wg.Wait()
	}
}

// runServerWithRestart runs a single server proxy with restart support.
// It respects manager status to decide whether to restart after exit.
func runServerWithRestart(parentCtx context.Context, mgr *proxy.Manager, name string, server ServerConfig, store *capture.Store, hub *web.Hub) {
	for {
		if parentCtx.Err() != nil {
			return
		}

		// Check if the server is stopped (user requested stop)
		status := mgr.ServerStatus(name)
		if status == "stopped" {
			return
		}

		// Create a per-proxy cancelable context
		proxyCtx, proxyCancel := context.WithCancel(parentCtx)

		p := proxy.NewProxy(name, server.Command, server.Args, server.Env, server.Cwd, store, hub)
		mp := mgr.Register(name, p)
		p.SetManaged(mp)
		mgr.SetCancelFn(name, proxyCancel)
		mgr.SetStatus(name, "online", "")

		err := p.Run(proxyCtx)
		proxyCancel()

		if parentCtx.Err() != nil {
			// Parent context cancelled — shutting down entirely
			return
		}

		// Check the current status set by the manager
		status = mgr.ServerStatus(name)
		switch status {
		case "stopped":
			// User requested stop — don't restart
			return
		case "restarting":
			// User requested restart — loop and start again
			slog.Info("restarting server per user request", "server", name)
			continue
		default:
			// Unexpected exit — mark as crashed
			errMsg := ""
			if err != nil {
				errMsg = err.Error()
			}
			mgr.SetStatus(name, "crashed", errMsg)
			slog.Warn("server crashed", "server", name, "error", err)
			return
		}
	}
}

// runNoServers starts the HTTP server and desktop window with no child proxies.
// This is the default when double-clicking the .app with no config file.
func runNoServers(port int, headless bool) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	go func() {
		sig := <-sigCh
		slog.Info("received signal, shutting down", "signal", sig)
		cancel()
	}()

	dir := dataDirFn()
	store, err := captureNewStore(filepath.Join(dir, "shipyard.db"), filepath.Join(dir, "shipyard.jsonl"))
	if err != nil {
		slog.Error("failed to initialize capture store", "error", err)
		exitFn(1)
		return
	}
	defer store.Close()

	hub := webNewHub()
	go hub.Run(ctx)

	mgr := proxyNewManager()
	mgr.SetHub(hub)

	srv := web.NewServer(port, store, hub)
	srv.SetProxyManager(mgr)
	go func() {
		slog.Info("web dashboard starting", "url", fmt.Sprintf("http://localhost:%d", port))
		if err := startWebServer(ctx, srv); err != nil {
			slog.Error("web server error", "error", err)
		}
	}()

	if !headless {
		runDesktopFn(port, cancel)
	} else {
		<-ctx.Done()
	}
}
