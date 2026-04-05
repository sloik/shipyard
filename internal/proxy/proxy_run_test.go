package proxy

import (
	"context"
	"errors"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

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
