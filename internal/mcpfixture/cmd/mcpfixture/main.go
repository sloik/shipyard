// Command mcpfixture runs Shipyard's MCP fixture server or fixture client for
// the official conformance CLI (scripts/mcp-conformance.sh).
//
//	mcpfixture server [-era modern|legacy] -http host:port
//	mcpfixture client [-era modern|legacy] <server-url>
//
// The client reads MCP_CONFORMANCE_SCENARIO and MCP_CONFORMANCE_CONTEXT, as
// the conformance CLI sets them.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/sloik/shipyard/internal/mcpcore"
	"github.com/sloik/shipyard/internal/mcpfixture"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Getenv, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "mcpfixture:", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, args []string, getenv func(string) string, stderr io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: mcpfixture server|client [flags]")
	}
	fs := flag.NewFlagSet("mcpfixture "+args[0], flag.ContinueOnError)
	fs.SetOutput(stderr)
	eraName := fs.String("era", "legacy", "protocol era: modern or legacy")
	addr := fs.String("http", "", "server: listen address (host:port)")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	era, err := mcpfixture.ParseEra(*eraName)
	if err != nil {
		return err
	}
	switch args[0] {
	case "server":
		if *addr == "" {
			return errors.New("server: -http address is required")
		}
		return serve(ctx, era, *addr, stderr)
	case "client":
		if fs.NArg() != 1 {
			return errors.New("client: exactly one server URL argument is required")
		}
		scenario := getenv("MCP_CONFORMANCE_SCENARIO")
		if scenario == "" {
			return errors.New("client: MCP_CONFORMANCE_SCENARIO is not set")
		}
		var conformance map[string]any
		if raw := getenv("MCP_CONFORMANCE_CONTEXT"); raw != "" {
			if err := json.Unmarshal([]byte(raw), &conformance); err != nil {
				return fmt.Errorf("client: parse MCP_CONFORMANCE_CONTEXT: %w", err)
			}
		}
		return mcpfixture.RunClientScenario(ctx, era, scenario, fs.Arg(0), conformance)
	default:
		return fmt.Errorf("unknown subcommand %q (want server or client)", args[0])
	}
}

func serve(ctx context.Context, era mcpcore.Era, addr string, stderr io.Writer) error {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("server: listen: %w", err)
	}
	srv := &http.Server{Handler: mcpfixture.NewHandler(era, nil), ReadHeaderTimeout: 10 * time.Second}
	fmt.Fprintf(stderr, "mcpfixture %s server listening on %s\n", era, ln.Addr())
	errCh := make(chan error, 1)
	go func() { errCh <- srv.Serve(ln) }()
	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = srv.Shutdown(shutdownCtx)
		return nil
	case err := <-errCh:
		return fmt.Errorf("server: %w", err)
	}
}

type lockedBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *lockedBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *lockedBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}
