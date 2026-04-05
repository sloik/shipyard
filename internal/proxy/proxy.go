package proxy

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

var proxyInputWriteLine = func(cw *childInputWriter, ctx context.Context, line []byte) error {
	return cw.writeLine(ctx, line)
}

var cmdStdinPipe = func(cmd *exec.Cmd) (io.WriteCloser, error) {
	return cmd.StdinPipe()
}

var cmdStdoutPipe = func(cmd *exec.Cmd) (io.ReadCloser, error) {
	return cmd.StdoutPipe()
}

var cmdStderrPipe = func(cmd *exec.Cmd) (io.ReadCloser, error) {
	return cmd.StderrPipe()
}

// Proxy manages a child MCP server process and proxies stdio bidirectionally.
type Proxy struct {
	name    string
	command string
	args    []string
	env     map[string]string
	cwd     string
	store   *capture.Store
	hub     *web.Hub
	managed *managedProxy // set when running under a Manager

	// Narrow test seams for deterministic lifecycle coverage of Run.
	runChildFn         func(context.Context, *childInputWriter) error
	proxyClientInputFn func(context.Context, *childInputWriter) error
	nowFn              func() time.Time
	waitForBackoffFn   func(context.Context, time.Duration) error
}

// NewProxy creates a new stdio proxy.
func NewProxy(name, command string, args []string, env map[string]string, cwd string, store *capture.Store, hub *web.Hub) *Proxy {
	return &Proxy{
		name:    name,
		command: command,
		args:    args,
		env:     env,
		cwd:     cwd,
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

const (
	initialRestartBackoff = time.Second
	maxRestartBackoff     = 30 * time.Second
	maxCrashCount         = 5
	crashWindow           = 60 * time.Second
)

type childInputWriter struct {
	mu     sync.Mutex
	cond   *sync.Cond
	writer io.WriteCloser
	closed bool
}

func newChildInputWriter() *childInputWriter {
	cw := &childInputWriter{}
	cw.cond = sync.NewCond(&cw.mu)
	return cw
}

func (cw *childInputWriter) attach(writer io.WriteCloser) {
	cw.mu.Lock()
	defer cw.mu.Unlock()

	if cw.closed {
		if writer != nil {
			_ = writer.Close()
		}
		return
	}

	cw.writer = writer
	cw.cond.Broadcast()
}

func (cw *childInputWriter) detach(writer io.WriteCloser) {
	cw.mu.Lock()
	defer cw.mu.Unlock()

	if cw.writer == writer {
		cw.writer = nil
		cw.cond.Broadcast()
	}
}

func (cw *childInputWriter) close() {
	cw.mu.Lock()
	defer cw.mu.Unlock()

	cw.closed = true
	cw.writer = nil
	cw.cond.Broadcast()
}

func (cw *childInputWriter) writeLine(ctx context.Context, line []byte) error {
	for {
		writer, err := cw.waitForWriter(ctx)
		if err != nil {
			return err
		}

		if _, err := writer.Write(line); err != nil {
			slog.Warn("child stdin write failed; waiting for restart", "error", err)
			cw.detach(writer)
			continue
		}
		if _, err := writer.Write([]byte("\n")); err != nil {
			slog.Warn("child stdin newline write failed; waiting for restart", "error", err)
			cw.detach(writer)
			continue
		}
		return nil
	}
}

func (cw *childInputWriter) waitForWriter(ctx context.Context) (io.WriteCloser, error) {
	cw.mu.Lock()
	defer cw.mu.Unlock()

	for cw.writer == nil && !cw.closed {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		cw.cond.Wait()
	}

	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if cw.closed {
		return nil, io.EOF
	}

	return cw.writer, nil
}

// SetManaged associates this proxy with a managed proxy entry.
func (p *Proxy) SetManaged(mp *managedProxy) {
	p.managed = mp
}

// Run starts the child process and proxies stdio. It blocks until the context
// is cancelled or the child exits.
func (p *Proxy) Run(ctx context.Context) error {
	inputWriter := newChildInputWriter()
	defer inputWriter.close()

	// If managed, share the input writer so the Manager can send requests
	if p.managed != nil {
		p.managed.SetInputWriter(inputWriter)
	}

	go func() {
		<-ctx.Done()
		inputWriter.close()
	}()

	clientDone := make(chan error, 1)
	go func() {
		clientDone <- p.proxyClientInputWithSeams(ctx, inputWriter)
	}()

	var crashTimes []time.Time

	for {
		runErr := p.runChildWithSeams(ctx, inputWriter)
		if runErr == nil {
			return p.waitForClientInput(clientDone)
		}
		if ctx.Err() != nil {
			return p.waitForClientInput(clientDone)
		}

		exitCode := exitCodeFromError(runErr)
		crashAt := p.now()
		crashTimes = append(crashTimes, crashAt)
		crashTimes = filterRecentCrashes(crashTimes, crashAt)

		slog.Warn("child process crashed", "name", p.name, "exit_code", exitCode, "error", runErr)
		if len(crashTimes) >= maxCrashCount {
			err := fmt.Errorf("fatal: child crashed %d times within %s; stopping restarts", len(crashTimes), crashWindow)
			slog.Error(err.Error(), "name", p.name, "exit_code", exitCode)
			return err
		}

		backoff := restartBackoff(len(crashTimes))
		slog.Info("restarting child process after crash", "name", p.name, "exit_code", exitCode, "backoff", backoff)
		if err := p.waitForBackoffWithSeams(ctx, backoff); err != nil {
			return p.waitForClientInput(clientDone)
		}
	}
}

func (p *Proxy) runChildWithSeams(ctx context.Context, inputWriter *childInputWriter) error {
	if p.runChildFn != nil {
		return p.runChildFn(ctx, inputWriter)
	}
	return p.runChild(ctx, inputWriter)
}

func (p *Proxy) proxyClientInputWithSeams(ctx context.Context, inputWriter *childInputWriter) error {
	if p.proxyClientInputFn != nil {
		return p.proxyClientInputFn(ctx, inputWriter)
	}
	return p.proxyClientInput(ctx, inputWriter)
}

func (p *Proxy) now() time.Time {
	if p.nowFn != nil {
		return p.nowFn()
	}
	return time.Now()
}

func (p *Proxy) waitForBackoffWithSeams(ctx context.Context, backoff time.Duration) error {
	if p.waitForBackoffFn != nil {
		return p.waitForBackoffFn(ctx, backoff)
	}
	return waitForBackoff(ctx, backoff)
}

// pipeAndTap reads newline-delimited messages from src, writes them to dst,
// and captures them.
func (p *Proxy) pipeAndTap(ctx context.Context, src io.Reader, dst io.Writer, direction string) {
	scanner := bufio.NewScanner(src)
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 10*1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()

		// Make a copy for potential interception and capture
		raw := make([]byte, len(line))
		copy(raw, line)

		// If managed and this is from the child (server→client), check if it's
		// a response to a manager-initiated request. If so, route it to the
		// response tracker instead of the parent client's stdout.
		if p.managed != nil && direction == capture.DirectionServerToClient {
			if p.managed.HandleChildOutput(raw) {
				// Response was claimed by the manager; still capture it but
				// don't forward to the parent client.
				ts := time.Now()
				go p.captureMessage(raw, direction, ts)
				continue
			}
		}

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
		go p.captureMessage(raw, direction, ts)
	}

	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		slog.Error("scanner error", "direction", direction, "error", err)
	}
}

func (p *Proxy) proxyClientInput(ctx context.Context, inputWriter *childInputWriter) error {
	scanner := bufio.NewScanner(os.Stdin)
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 10*1024*1024)

	for scanner.Scan() {
			line := append([]byte(nil), scanner.Bytes()...)
			if err := proxyInputWriteLine(inputWriter, ctx, line); err != nil {
			if errors.Is(err, context.Canceled) || errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}

		go p.captureMessage(line, capture.DirectionClientToServer, time.Now())
	}

	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		slog.Error("scanner error", "direction", capture.DirectionClientToServer, "error", err)
		return err
	}

	return nil
}

func (p *Proxy) runChild(ctx context.Context, inputWriter *childInputWriter) error {
	cmd := exec.CommandContext(ctx, p.command, p.args...)
	cmd.Env = mergeEnv(os.Environ(), p.env)
	cmd.Dir = p.cwd

	childStdin, err := cmdStdinPipe(cmd)
	if err != nil {
		return fmt.Errorf("stdin pipe: %w", err)
	}
	childStdout, err := cmdStdoutPipe(cmd)
	if err != nil {
		return fmt.Errorf("stdout pipe: %w", err)
	}
	childStderr, err := cmdStderrPipe(cmd)
	if err != nil {
		return fmt.Errorf("stderr pipe: %w", err)
	}

	slog.Info("starting child process", "name", p.name, "command", p.command, "args", p.args)
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start child: %w", err)
	}

	inputWriter.attach(childStdin)
	defer inputWriter.detach(childStdin)

	var wg sync.WaitGroup

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

	wg.Add(1)
	go func() {
		defer wg.Done()
		p.pipeAndTap(ctx, childStdout, os.Stdout, capture.DirectionServerToClient)
	}()

	err = cmd.Wait()
	inputWriter.detach(childStdin)
	wg.Wait()

	if err == nil {
		slog.Info("child process exited normally", "name", p.name)
	}

	return err
}

func mergeEnv(base []string, overrides map[string]string) []string {
	if len(overrides) == 0 {
		return base
	}

	env := make(map[string]string, len(base)+len(overrides))
	for _, entry := range base {
		parts := strings.SplitN(entry, "=", 2)
		if len(parts) == 2 {
			env[parts[0]] = parts[1]
		}
	}
	for key, value := range overrides {
		env[key] = value
	}

	merged := make([]string, 0, len(env))
	for key, value := range env {
		merged = append(merged, key+"="+value)
	}
	sort.Strings(merged)
	return merged
}

func (p *Proxy) waitForClientInput(clientDone <-chan error) error {
	select {
	case err := <-clientDone:
		if err == nil || errors.Is(err, context.Canceled) || errors.Is(err, io.EOF) {
			return nil
		}
		return err
	default:
		return nil
	}
}

func exitCodeFromError(err error) int {
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return exitErr.ExitCode()
	}
	return -1
}

func filterRecentCrashes(crashTimes []time.Time, now time.Time) []time.Time {
	cutoff := now.Add(-crashWindow)
	kept := crashTimes[:0]
	for _, crashTime := range crashTimes {
		if crashTime.After(cutoff) {
			kept = append(kept, crashTime)
		}
	}
	return kept
}

func waitForBackoff(ctx context.Context, backoff time.Duration) error {
	timer := time.NewTimer(backoff)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func restartBackoff(crashCount int) time.Duration {
	backoff := initialRestartBackoff
	for i := 1; i < crashCount; i++ {
		if backoff >= maxRestartBackoff {
			return maxRestartBackoff
		}
		backoff *= 2
	}
	if backoff > maxRestartBackoff {
		return maxRestartBackoff
	}
	return backoff
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
		status = "pending"
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
