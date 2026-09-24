package proxy

import (
	"bytes"
	"context"
	"strings"
	"sync"
	"testing"
	"time"
)

// slowWriter delays every write, so the proxy's stdout reader lags behind a
// child that writes and exits immediately.
type slowWriter struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (w *slowWriter) Write(p []byte) (int, error) {
	time.Sleep(2 * time.Millisecond)
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.Write(p)
}

func (w *slowWriter) lines() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return strings.Count(w.buf.String(), "\n")
}

// TestSPECBUG177_ChildOutputDrainedAfterImmediateExit verifies that every
// line a child writes before exiting is forwarded and captured, even when the
// reader is still behind when the process exits. Before the fix, cmd.Wait()
// closed the stdout pipe on exit and the unread lines were lost.
func TestSPECBUG177_ChildOutputDrainedAfterImmediateExit(t *testing.T) {
	const n = 40
	p, store := newTestProxy(t)
	out := &slowWriter{}
	p.output = out
	p.command = "sh"
	p.args = []string{"-c", `i=1; while [ $i -le 40 ]; do printf '{"jsonrpc":"2.0","method":"tools/list","id":%d}\n' $i; i=$((i+1)); done; exit 3`}

	err := p.runChild(context.Background(), newChildInputWriter())
	if err == nil || !strings.Contains(err.Error(), "exit status 3") {
		t.Fatalf("expected exit status 3, got %v", err)
	}
	if got := out.lines(); got != n {
		t.Fatalf("forwarded %d of %d child lines before runChild returned", got, n)
	}
	waitForStoreCount(t, store, n)
}

// TestSPECBUG177_OrphanHoldingStdoutDoesNotHang verifies that a grandchild
// which inherits stdout and outlives the child cannot keep runChild from
// returning once the child has exited.
func TestSPECBUG177_OrphanHoldingStdoutDoesNotHang(t *testing.T) {
	p, store := newTestProxy(t)
	p.output = &bytes.Buffer{}
	p.command = "sh"
	p.args = []string{"-c", `sleep 30 & printf '%s\n' '{"jsonrpc":"2.0","method":"tools/list","id":1}'; exit 0`}

	done := make(chan error, 1)
	start := time.Now()
	go func() { done <- p.runChild(context.Background(), newChildInputWriter()) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("expected clean exit, got %v", err)
		}
		if elapsed := time.Since(start); elapsed > childOutputWaitDelay+3*time.Second {
			t.Fatalf("runChild took %v with an orphan holding stdout", elapsed)
		}
	case <-time.After(childOutputWaitDelay + 10*time.Second):
		t.Fatal("runChild hung while an orphaned grandchild held stdout open")
	}
	waitForStoreCount(t, store, 1)
}

// TestSPECBUG177_ContextCancelStopsSilentChild verifies that cancelling the
// context still kills a child that never exits or closes its stdout.
func TestSPECBUG177_ContextCancelStopsSilentChild(t *testing.T) {
	p, _ := newTestProxy(t)
	p.output = &bytes.Buffer{}
	p.command = "sh"
	p.args = []string{"-c", "exec sleep 30"}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- p.runChild(ctx, newChildInputWriter()) }()
	time.Sleep(200 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expected an error from a killed child")
		}
	case <-time.After(childOutputWaitDelay + 10*time.Second):
		t.Fatal("runChild did not return after context cancellation")
	}
}
