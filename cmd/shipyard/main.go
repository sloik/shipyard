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
	"syscall"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/proxy"
	"github.com/sloik/shipyard/internal/web"
)

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

	dec := json.NewDecoder(bytes.NewReader(raw.Servers))
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
		c.ServerOrder = append(c.ServerOrder, name)

		var discard json.RawMessage
		if err := dec.Decode(&discard); err != nil {
			return fmt.Errorf("read server %q: %w", name, err)
		}
	}

	if _, err := dec.Token(); err != nil {
		return fmt.Errorf("close servers object: %w", err)
	}

	return nil
}

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelDebug})))

	global := flag.NewFlagSet("shipyard", flag.ContinueOnError)
	global.SetOutput(io.Discard)
	configPath := global.String("config", "", "path to JSON config file")

	if err := global.Parse(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		fmt.Fprintln(os.Stderr, "   or: shipyard --config <servers.json>")
		os.Exit(1)
	}

	if *configPath != "" {
		runConfig(*configPath)
		return
	}

	args := global.Args()
	if len(args) == 0 {
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		fmt.Fprintln(os.Stderr, "   or: shipyard --config <servers.json>")
		os.Exit(1)
	}

	switch args[0] {
	case "wrap":
		runWrap(args[1:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", args[0])
		os.Exit(1)
	}
}

func runConfig(configPath string) {
	cfg, err := loadConfig(configPath)
	if err != nil {
		slog.Error("failed to load config", "path", configPath, "error", err)
		os.Exit(1)
	}

	if len(cfg.ServerOrder) == 0 {
		slog.Error("config does not define any servers", "path", configPath)
		os.Exit(1)
	}

	serverName := cfg.ServerOrder[0]
	server := cfg.Servers[serverName]
	if len(cfg.ServerOrder) > 1 {
		slog.Warn("multi-server config not yet supported; using first server only", "server", serverName, "configured_servers", len(cfg.ServerOrder))
	}

	port := cfg.Web.Port
	if port == 0 {
		port = 9417
	}

	if server.Command == "" {
		slog.Error("config server is missing command", "server", serverName, "path", configPath)
		os.Exit(1)
	}

	runProxy(serverName, port, server.Command, server.Args, server.Env, server.Cwd)
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

func runProxy(name string, port int, command string, args []string, env map[string]string, cwd string) {
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
	store, err := capture.NewStore("shipyard.db", "shipyard.jsonl")
	if err != nil {
		slog.Error("failed to initialize capture store", "error", err)
		os.Exit(1)
	}
	defer store.Close()

	// Start web dashboard
	hub := web.NewHub()
	go hub.Run(ctx)

	// Create proxy manager
	mgr := proxy.NewManager()

	srv := web.NewServer(port, store, hub)
	srv.SetProxyManager(mgr)
	go func() {
		slog.Info("web dashboard starting", "url", fmt.Sprintf("http://localhost:%d", port))
		if err := srv.Start(ctx); err != nil {
			slog.Error("web server error", "error", err)
		}
	}()

	// Start proxy with manager
	p := proxy.NewProxy(name, command, args, env, cwd, store, hub)
	mp := mgr.Register(name, p)
	p.SetManaged(mp)
	if err := p.Run(ctx); err != nil {
		slog.Error("proxy error", "error", err)
	}
}

func runWrap(args []string) {
	fs := flag.NewFlagSet("wrap", flag.ExitOnError)
	name := fs.String("name", "child", "server name for display")
	port := fs.Int("port", 9417, "web dashboard port")
	fs.Parse(args)

	remaining := fs.Args()

	// Find the command after "--"
	var childCmd []string
	for i, a := range remaining {
		if a == "--" {
			childCmd = remaining[i+1:]
			break
		}
	}
	// If no "--" found, treat all remaining as the command
	if childCmd == nil {
		childCmd = remaining
	}

	if len(childCmd) == 0 {
		fmt.Fprintln(os.Stderr, "error: no child command specified")
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		os.Exit(1)
	}

	runProxy(*name, *port, childCmd[0], childCmd[1:], nil, "")
}
