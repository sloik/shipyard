package proxy

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
)

const (
	proxyRunHelperEnv     = "SHIPYARD_PROXY_RUN_HELPER"
	proxyRunScenarioEnv   = "SHIPYARD_PROXY_RUN_SCENARIO"
	proxyRunStateDirEnv   = "SHIPYARD_PROXY_RUN_STATE_DIR"
	proxyRunReadyFileName = "ready"
	proxyRunCountFileName = "launch-count"
	proxyRunInputFileName = "stdin.json"
)

func TestProxyRunHelperProcess(t *testing.T) {
	if os.Getenv(proxyRunHelperEnv) != "1" {
		return
	}

	os.Exit(runProxyRunHelper())
}

func runProxyRunHelper() int {
	stateDir := os.Getenv(proxyRunStateDirEnv)
	scenario := os.Getenv(proxyRunScenarioEnv)
	if stateDir == "" || scenario == "" {
		_, _ = io.WriteString(os.Stderr, "missing helper process configuration\n")
		return 2
	}

	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		_, _ = io.WriteString(os.Stderr, "mkdir state dir: "+err.Error()+"\n")
		return 3
	}

	launchCount, err := bumpProxyRunLaunchCount(filepath.Join(stateDir, proxyRunCountFileName))
	if err != nil {
		_, _ = io.WriteString(os.Stderr, "launch count: "+err.Error()+"\n")
		return 4
	}

	switch scenario {
	case "clean-exchange":
		return runProxyRunCleanExchangeHelper(stateDir, launchCount)
	case "crash-once-then-clean":
		if launchCount == 1 {
			_, _ = io.WriteString(os.Stderr, "intentional crash before restart\n")
			return 7
		}
		_, _ = io.WriteString(os.Stderr, "restarted cleanly\n")
		_, _ = io.WriteString(os.Stdout, `{"jsonrpc":"2.0","id":1,"result":{"restarted":true,"launch":`+itoa(launchCount)+`}}`+"\n")
		return 0
	case "crash-always":
		_, _ = io.WriteString(os.Stderr, "intentional repeated crash\n")
		return 9
	case "block-until-killed":
		if err := os.WriteFile(filepath.Join(stateDir, proxyRunReadyFileName), []byte("ready"), 0o644); err != nil {
			_, _ = io.WriteString(os.Stderr, "write ready file: "+err.Error()+"\n")
			return 5
		}
		select {}
	default:
		_, _ = io.WriteString(os.Stderr, "unknown helper scenario\n")
		return 6
	}
}

func runProxyRunCleanExchangeHelper(stateDir string, launchCount int) int {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	if !scanner.Scan() {
		if err := scanner.Err(); err != nil {
			_, _ = io.WriteString(os.Stderr, "scan stdin: "+err.Error()+"\n")
			return 10
		}
		_, _ = io.WriteString(os.Stderr, "expected one client request on stdin\n")
		return 11
	}

	line := strings.TrimSpace(scanner.Text())
	if err := os.WriteFile(filepath.Join(stateDir, proxyRunInputFileName), []byte(line), 0o644); err != nil {
		_, _ = io.WriteString(os.Stderr, "write input file: "+err.Error()+"\n")
		return 12
	}

	_, _ = io.WriteString(os.Stderr, "clean exchange helper emitted stderr\n")
	_, _ = io.WriteString(os.Stdout, `{"jsonrpc":"2.0","id":1,"result":{"ok":true,"launch":`+itoa(launchCount)+`}}`+"\n")
	return 0
}

func bumpProxyRunLaunchCount(path string) (int, error) {
	count := 0
	if data, err := os.ReadFile(path); err == nil {
		trimmed := strings.TrimSpace(string(data))
		if trimmed != "" {
			parsed, parseErr := strconv.Atoi(trimmed)
			if parseErr != nil {
				return 0, parseErr
			}
			count = parsed
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return 0, err
	}

	count++
	if err := os.WriteFile(path, []byte(itoa(count)), 0o644); err != nil {
		return 0, err
	}
	return count, nil
}

func configureProxyRunHelper(t *testing.T, p *Proxy, scenario, stateDir string) {
	t.Helper()

	p.command = os.Args[0]
	p.args = []string{"-test.run=TestProxyRunHelperProcess"}
	p.env = map[string]string{
		proxyRunHelperEnv:   "1",
		proxyRunScenarioEnv: scenario,
		proxyRunStateDirEnv: stateDir,
	}
}

func replaceProxyStdin(t *testing.T) *os.File {
	t.Helper()

	oldStdin := os.Stdin
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe stdin: %v", err)
	}
	os.Stdin = r
	t.Cleanup(func() {
		os.Stdin = oldStdin
		_ = r.Close()
		_ = w.Close()
	})
	return w
}

func captureProxyStdout(t *testing.T) func() string {
	t.Helper()

	oldStdout := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe stdout: %v", err)
	}
	os.Stdout = w

	var (
		once   sync.Once
		output string
	)

	t.Cleanup(func() {
		once.Do(func() {
			os.Stdout = oldStdout
			_ = w.Close()
			data, readErr := io.ReadAll(r)
			if readErr == nil {
				output = string(data)
			}
			_ = r.Close()
		})
	})

	return func() string {
		once.Do(func() {
			os.Stdout = oldStdout
			_ = w.Close()
			data, readErr := io.ReadAll(r)
			if readErr != nil {
				t.Fatalf("read captured stdout: %v", readErr)
			}
			output = string(data)
			_ = r.Close()
		})
		return output
	}
}

func waitForFile(t *testing.T, path string) {
	t.Helper()

	deadline := time.Now().Add(2 * time.Second)
	for {
		if _, err := os.Stat(path); err == nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for file %s", path)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func readLaunchCount(t *testing.T, stateDir string) int {
	t.Helper()

	data, err := os.ReadFile(filepath.Join(stateDir, proxyRunCountFileName))
	if err != nil {
		t.Fatalf("read launch count: %v", err)
	}

	count, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		t.Fatalf("parse launch count: %v", err)
	}
	return count
}

func queryTrafficEvents(t *testing.T, store *capture.Store, limit int) []capture.TrafficEvent {
	t.Helper()

	page, err := store.Query(1, limit, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	return page.Items
}

func hasTrafficEvent(events []capture.TrafficEvent, direction, method, status, messageID string) bool {
	for _, evt := range events {
		if evt.Direction != direction {
			continue
		}
		if method != "" && evt.Method != method {
			continue
		}
		if status != "" && evt.Status != status {
			continue
		}
		if messageID != "" && evt.MessageID != messageID {
			continue
		}
		return true
	}
	return false
}

func exitStatusError(t *testing.T, code int) error {
	t.Helper()

	cmd := exec.Command("sh", "-c", "exit "+itoa(code))
	err := cmd.Run()
	if err == nil {
		t.Fatalf("expected exit status %d error", code)
	}
	return err
}

func TestRun_ManagedCleanExitReturnsNil(t *testing.T) {
	p, _ := newTestProxy(t)
	mgr := NewManager()
	mp := mgr.Register("alpha", p)
	p.SetManaged(mp)

	var calls atomic.Int32
	runStarted := make(chan struct{})

	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		<-ctx.Done()
		return context.Canceled
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		calls.Add(1)
		if mp.inputWriter != inputWriter {
			t.Fatal("managed proxy did not receive shared input writer")
		}
		close(runStarted)
		return nil
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		errCh <- p.Run(ctx)
	}()

	select {
	case <-runStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for runChild to execute")
	}

	cancel()

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("Run returned error: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after clean exit")
	}

	if got := calls.Load(); got != 1 {
		t.Fatalf("expected runChild to be called once, got %d", got)
	}
}

func TestRun_RealSubprocessCleanExchange(t *testing.T) {
	p, store := newTestProxy(t)
	stateDir := t.TempDir()
	configureProxyRunHelper(t, p, "clean-exchange", stateDir)

	stdinWriter := replaceProxyStdin(t)
	finishStdout := captureProxyStdout(t)

	request := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	if _, err := io.WriteString(stdinWriter, request+"\n"); err != nil {
		t.Fatalf("write stdin: %v", err)
	}
	_ = stdinWriter.Close()

	if err := p.Run(context.Background()); err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	output := finishStdout()
	if !strings.Contains(output, `"launch":1`) {
		t.Fatalf("expected helper response on stdout, got %q", output)
	}

	waitForStoreCount(t, store, 2)
	events := queryTrafficEvents(t, store, 10)
	if !hasTrafficEvent(events, capture.DirectionClientToServer, "tools/list", "pending", "1") {
		t.Fatalf("expected captured client request, got %+v", events)
	}
	if !hasTrafficEvent(events, capture.DirectionServerToClient, "", "ok", "1") {
		t.Fatalf("expected captured server response, got %+v", events)
	}

	gotInput, err := os.ReadFile(filepath.Join(stateDir, proxyRunInputFileName))
	if err != nil {
		t.Fatalf("read helper input: %v", err)
	}
	if strings.TrimSpace(string(gotInput)) != request {
		t.Fatalf("expected helper stdin %q, got %q", request, strings.TrimSpace(string(gotInput)))
	}

	if got := readLaunchCount(t, stateDir); got != 1 {
		t.Fatalf("expected one helper launch, got %d", got)
	}
}

func TestRun_RealSubprocessRestartsAfterCrash(t *testing.T) {
	p, store := newTestProxy(t)
	stateDir := t.TempDir()
	configureProxyRunHelper(t, p, "crash-once-then-clean", stateDir)

	stdinWriter := replaceProxyStdin(t)
	_ = stdinWriter.Close()
	finishStdout := captureProxyStdout(t)

	var backoffs []time.Duration
	p.waitForBackoffFn = func(ctx context.Context, backoff time.Duration) error {
		backoffs = append(backoffs, backoff)
		return nil
	}

	if err := p.Run(context.Background()); err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	output := finishStdout()
	if !strings.Contains(output, `"restarted":true`) {
		t.Fatalf("expected restarted helper response on stdout, got %q", output)
	}
	if got := readLaunchCount(t, stateDir); got != 2 {
		t.Fatalf("expected two helper launches, got %d", got)
	}
	if len(backoffs) != 1 || backoffs[0] != time.Second {
		t.Fatalf("expected one 1s backoff, got %v", backoffs)
	}

	waitForStoreCount(t, store, 1)
	events := queryTrafficEvents(t, store, 10)
	if !hasTrafficEvent(events, capture.DirectionServerToClient, "", "ok", "1") {
		t.Fatalf("expected captured server response after restart, got %+v", events)
	}
}

func TestRun_RestartsAfterCrash(t *testing.T) {
	p, _ := newTestProxy(t)

	var (
		runCalls      atomic.Int32
		backoffCalls  atomic.Int32
		backoffValues []time.Duration
		mu            sync.Mutex
	)

	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		return nil
	}
	p.nowFn = func() time.Time {
		return time.Unix(1_000, 0)
	}
	p.waitForBackoffFn = func(ctx context.Context, backoff time.Duration) error {
		backoffCalls.Add(1)
		mu.Lock()
		backoffValues = append(backoffValues, backoff)
		mu.Unlock()
		return nil
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		switch runCalls.Add(1) {
		case 1:
			return exitStatusError(t, 7)
		case 2:
			return nil
		default:
			t.Fatalf("unexpected extra runChild call")
			return nil
		}
	}

	if err := p.Run(context.Background()); err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	if got := runCalls.Load(); got != 2 {
		t.Fatalf("expected two runChild calls, got %d", got)
	}
	if got := backoffCalls.Load(); got != 1 {
		t.Fatalf("expected one backoff call, got %d", got)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(backoffValues) != 1 || backoffValues[0] != time.Second {
		t.Fatalf("expected one 1s backoff, got %v", backoffValues)
	}
}

func TestRun_RealSubprocessStopsAfterCrashThreshold(t *testing.T) {
	p, _ := newTestProxy(t)
	stateDir := t.TempDir()
	configureProxyRunHelper(t, p, "crash-always", stateDir)

	stdinWriter := replaceProxyStdin(t)
	_ = stdinWriter.Close()

	var tick atomic.Int32
	base := time.Unix(1_000, 0)
	p.nowFn = func() time.Time {
		return base.Add(time.Duration(tick.Add(1)-1) * time.Second)
	}
	p.waitForBackoffFn = func(ctx context.Context, backoff time.Duration) error {
		return nil
	}

	err := p.Run(context.Background())
	if err == nil {
		t.Fatal("expected fatal crash threshold error")
	}
	if !strings.Contains(err.Error(), "stopping restarts") {
		t.Fatalf("expected fatal restart error, got %v", err)
	}
	if got := readLaunchCount(t, stateDir); got != maxCrashCount {
		t.Fatalf("expected %d helper launches, got %d", maxCrashCount, got)
	}
}

func TestRun_StopsAfterCrashThreshold(t *testing.T) {
	p, _ := newTestProxy(t)

	var runCalls atomic.Int32
	nowValues := []time.Time{
		time.Unix(1_000, 0),
		time.Unix(1_001, 0),
		time.Unix(1_002, 0),
		time.Unix(1_003, 0),
		time.Unix(1_004, 0),
	}
	var nowIdx atomic.Int32

	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		return nil
	}
	p.nowFn = func() time.Time {
		idx := int(nowIdx.Add(1) - 1)
		if idx >= len(nowValues) {
			return nowValues[len(nowValues)-1]
		}
		return nowValues[idx]
	}
	p.waitForBackoffFn = func(ctx context.Context, backoff time.Duration) error {
		return nil
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		runCalls.Add(1)
		return exitStatusError(t, 7)
	}

	err := p.Run(context.Background())
	if err == nil {
		t.Fatal("expected fatal crash threshold error")
	}
	if !strings.Contains(err.Error(), "stopping restarts") {
		t.Fatalf("expected fatal restart error, got %v", err)
	}
	if got := runCalls.Load(); got != maxCrashCount {
		t.Fatalf("expected %d runChild calls, got %d", maxCrashCount, got)
	}
}

func TestRun_RealSubprocessContextCancellationStopsBlockedChild(t *testing.T) {
	p, _ := newTestProxy(t)
	stateDir := t.TempDir()
	configureProxyRunHelper(t, p, "block-until-killed", stateDir)

	stdinWriter := replaceProxyStdin(t)
	finishStdout := captureProxyStdout(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		errCh <- p.Run(ctx)
	}()

	waitForFile(t, filepath.Join(stateDir, proxyRunReadyFileName))
	cancel()
	_ = stdinWriter.Close()

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("expected nil on context cancellation, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after context cancellation")
	}

	if got := strings.TrimSpace(finishStdout()); got != "" {
		t.Fatalf("expected no stdout from blocked helper, got %q", got)
	}
	if got := readLaunchCount(t, stateDir); got != 1 {
		t.Fatalf("expected one helper launch before cancellation, got %d", got)
	}
}

func TestRun_ContextCancellationDuringBackoffReturnsNil(t *testing.T) {
	p, _ := newTestProxy(t)

	backoffStarted := make(chan struct{})
	var runCalls atomic.Int32

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		<-ctx.Done()
		return context.Canceled
	}
	p.nowFn = func() time.Time {
		return time.Unix(1_000, 0)
	}
	p.waitForBackoffFn = func(ctx context.Context, backoff time.Duration) error {
		close(backoffStarted)
		<-ctx.Done()
		return ctx.Err()
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		runCalls.Add(1)
		return exitStatusError(t, 7)
	}

	errCh := make(chan error, 1)
	go func() {
		errCh <- p.Run(ctx)
	}()

	select {
	case <-backoffStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for backoff to start")
	}

	cancel()

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("expected nil on context cancellation during backoff, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after context cancellation")
	}

	if got := runCalls.Load(); got != 1 {
		t.Fatalf("expected one runChild call before cancellation, got %d", got)
	}
}

func TestRun_ContextCancellationDuringActiveChildReturnsNil(t *testing.T) {
	p, _ := newTestProxy(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	childStarted := make(chan struct{})
	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		<-ctx.Done()
		return context.Canceled
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		close(childStarted)
		<-ctx.Done()
		return ctx.Err()
	}

	errCh := make(chan error, 1)
	go func() {
		errCh <- p.Run(ctx)
	}()

	select {
	case <-childStarted:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for child run to start")
	}

	cancel()

	select {
	case err := <-errCh:
		if err != nil {
			t.Fatalf("expected nil on active-child cancellation, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return after active-child cancellation")
	}
}

func TestRun_ReturnsClientInputErrorsOnCleanExitWhenReady(t *testing.T) {
	p, _ := newTestProxy(t)
	wantErr := errors.New("client input failed")
	clientDone := make(chan struct{})

	p.proxyClientInputFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		close(clientDone)
		return wantErr
	}
	p.runChildFn = func(ctx context.Context, inputWriter *childInputWriter) error {
		select {
		case <-clientDone:
		case <-time.After(2 * time.Second):
			t.Fatal("timed out waiting for client input to finish")
		}
		return nil
	}

	err := p.Run(context.Background())
	if !errors.Is(err, wantErr) {
		t.Fatalf("expected %v, got %v", wantErr, err)
	}
}
