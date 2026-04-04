package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/proxy"
	"github.com/sloik/shipyard/internal/web"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelDebug})))

	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: shipyard wrap [--name NAME] [--port PORT] -- <command> [args...]")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "wrap":
		runWrap(os.Args[2:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		os.Exit(1)
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

	srv := web.NewServer(*port, store, hub)
	go func() {
		slog.Info("web dashboard starting", "url", fmt.Sprintf("http://localhost:%d", *port))
		if err := srv.Start(ctx); err != nil {
			slog.Error("web server error", "error", err)
		}
	}()

	// Start proxy
	p := proxy.NewProxy(*name, childCmd[0], childCmd[1:], store, hub)
	if err := p.Run(ctx); err != nil {
		slog.Error("proxy error", "error", err)
	}
}
