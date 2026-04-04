package proxy

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

// Proxy manages a child MCP server process and proxies stdio bidirectionally.
type Proxy struct {
	name    string
	command string
	args    []string
	store   *capture.Store
	hub     *web.Hub
}

// NewProxy creates a new stdio proxy.
func NewProxy(name, command string, args []string, store *capture.Store, hub *web.Hub) *Proxy {
	return &Proxy{
		name:    name,
		command: command,
		args:    args,
		store:   store,
		hub:     hub,
	}
}

// jsonRPCMessage is a minimal representation of a JSON-RPC 2.0 message.
type jsonRPCMessage struct {
	JSONRPC string          `json:"jsonrpc"`
	Method  string          `json:"method,omitempty"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   json.RawMessage `json:"error,omitempty"`
}

// Run starts the child process and proxies stdio. It blocks until the context
// is cancelled or the child exits.
func (p *Proxy) Run(ctx context.Context) error {
	cmd := exec.CommandContext(ctx, p.command, p.args...)

	childStdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("stdin pipe: %w", err)
	}
	childStdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("stdout pipe: %w", err)
	}
	childStderr, err := cmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("stderr pipe: %w", err)
	}

	slog.Info("starting child process", "name", p.name, "command", p.command, "args", p.args)
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start child: %w", err)
	}

	var wg sync.WaitGroup

	// Drain child stderr to prevent deadlock
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(childStderr)
		buf := make([]byte, 64*1024)
		scanner.Buffer(buf, 1024*1024)
		for scanner.Scan() {
			slog.Debug("child stderr", "name", p.name, "line", scanner.Text())
		}
	}()

	// Parent stdin → child stdin (client→server direction)
	wg.Add(1)
	go func() {
		defer wg.Done()
		defer childStdin.Close()
		p.pipeAndTap(ctx, os.Stdin, childStdin, capture.DirectionClientToServer)
	}()

	// Child stdout → parent stdout (server→client direction)
	wg.Add(1)
	go func() {
		defer wg.Done()
		p.pipeAndTap(ctx, childStdout, os.Stdout, capture.DirectionServerToClient)
	}()

	// Wait for child to exit
	err = cmd.Wait()
	if err != nil {
		slog.Warn("child process exited with error", "name", p.name, "error", err)
	} else {
		slog.Info("child process exited normally", "name", p.name)
	}

	// If context is still active (child crashed), stay running
	if ctx.Err() == nil {
		slog.Info("child crashed, proxy remains running — waiting for shutdown signal", "name", p.name)
		<-ctx.Done()
	}

	wg.Wait()
	return err
}

// pipeAndTap reads newline-delimited messages from src, writes them to dst,
// and captures them.
func (p *Proxy) pipeAndTap(ctx context.Context, src io.Reader, dst io.Writer, direction string) {
	scanner := bufio.NewScanner(src)
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 10*1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()

		// Write to destination first (don't delay the proxy)
		_, err := dst.Write(line)
		if err != nil {
			slog.Error("write error", "direction", direction, "error", err)
			return
		}
		// Write the newline delimiter
		_, err = dst.Write([]byte("\n"))
		if err != nil {
			slog.Error("write newline error", "direction", direction, "error", err)
			return
		}
		// Flush if dst supports it (stdout)
		if f, ok := dst.(*os.File); ok {
			f.Sync()
		}

		// Capture the message
		ts := time.Now()
		raw := make([]byte, len(line))
		copy(raw, line)

		go p.captureMessage(raw, direction, ts)
	}

	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		slog.Error("scanner error", "direction", direction, "error", err)
	}
}

// captureMessage parses and stores a captured JSON-RPC message.
func (p *Proxy) captureMessage(raw []byte, direction string, ts time.Time) {
	var msg jsonRPCMessage
	if err := json.Unmarshal(raw, &msg); err != nil {
		slog.Debug("non-JSON message captured", "direction", direction, "error", err)
		return
	}

	// Determine if this is a request, response, or notification
	method := msg.Method
	var msgID string
	if msg.ID != nil {
		msgID = string(msg.ID)
		// Strip quotes from string IDs
		if len(msgID) > 1 && msgID[0] == '"' {
			msgID = msgID[1 : len(msgID)-1]
		}
	}

	isResponse := msg.Result != nil || msg.Error != nil

	// Determine status
	status := "ok"
	if msg.Error != nil {
		status = "error"
	}
	if !isResponse && method != "" {
		status = "request"
	}

	entry := &capture.TrafficEntry{
		Timestamp:  ts,
		Direction:  direction,
		ServerName: p.name,
		Method:     method,
		MessageID:  msgID,
		Payload:    string(raw),
		Status:     status,
		IsResponse: isResponse,
	}

	// Store and correlate
	id, latencyMs := p.store.Insert(entry)

	// Build the broadcast event
	evt := capture.TrafficEvent{
		ID:         id,
		Timestamp:  ts.UnixMilli(),
		Direction:  direction,
		ServerName: p.name,
		Method:     method,
		MessageID:  msgID,
		Status:     status,
		LatencyMs:  latencyMs,
		Payload:    string(raw),
	}

	data, _ := json.Marshal(evt)
	p.hub.Broadcast(data)
}
