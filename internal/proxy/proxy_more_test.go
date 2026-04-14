package proxy

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
)

type flakyWriteCloser struct {
	mu                sync.Mutex
	buf               bytes.Buffer
	failErr           error
	remainingFailures int
	attempts          int
	failedCh          chan struct{}
	notifyOnce        sync.Once
}

func (w *flakyWriteCloser) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.attempts++
	if w.remainingFailures > 0 {
		w.remainingFailures--
		w.notifyOnce.Do(func() {
			if w.failedCh != nil {
				close(w.failedCh)
			}
		})
		return 0, w.failErr
	}
	return w.buf.Write(p)
}

func (w *flakyWriteCloser) Close() error {
	return nil
}

func (w *flakyWriteCloser) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.String()
}

func (w *flakyWriteCloser) Attempts() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.attempts
}

type failSecondWriteCloser struct {
	mu       sync.Mutex
	writes   int
	buf      bytes.Buffer
	failErr  error
	failedCh chan struct{}
}

func (w *failSecondWriteCloser) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.writes++
	if w.writes == 2 {
		if w.failedCh != nil {
			close(w.failedCh)
			w.failedCh = nil
		}
		return 0, w.failErr
	}
	return w.buf.Write(p)
}

func (w *failSecondWriteCloser) Close() error { return nil }

func (w *failSecondWriteCloser) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.String()
}

type errWriter struct{ err error }

func (w errWriter) Write(p []byte) (int, error) { return 0, w.err }

func TestChildInputWriter_Detach(t *testing.T) {
	cw := newChildInputWriter()
	first := &trackedWriteCloser{}
	second := &trackedWriteCloser{}

	cw.attach(first)
	cw.detach(second)
	if cw.writer != first {
		t.Fatal("detach with a different writer should leave the current writer intact")
	}

	cw.detach(first)
	if cw.writer != nil {
		t.Fatal("detach with the current writer should clear the writer")
	}
}

func TestChildInputWriter_WriteLineRetriesAfterFailure(t *testing.T) {
	cw := newChildInputWriter()
	failing := &flakyWriteCloser{
		failErr:           errors.New("write failed"),
		remainingFailures: 1,
		failedCh:          make(chan struct{}),
	}
	recovery := &trackedWriteCloser{}
	cw.attach(failing)

	done := make(chan error, 1)
	go func() {
		done <- cw.writeLine(context.Background(), []byte("hello"))
	}()

	select {
	case <-failing.failedCh:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for initial write failure")
	}

	cw.attach(recovery)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("writeLine: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for retry to succeed")
	}

	if got := recovery.String(); got != "hello\n" {
		t.Fatalf("expected retried write to reach recovery writer, got %q", got)
	}
	if got := failing.Attempts(); got != 1 {
		t.Fatalf("expected one failed attempt, got %d", got)
	}
}

func TestChildInputWriter_WriteLineRetriesAfterNewlineFailure(t *testing.T) {
	cw := newChildInputWriter()
	failedCh := make(chan struct{})
	failing := &failSecondWriteCloser{
		failErr:  errors.New("newline failed"),
		failedCh: failedCh,
	}
	recovery := &trackedWriteCloser{}
	cw.attach(failing)

	done := make(chan error, 1)
	go func() {
		done <- cw.writeLine(context.Background(), []byte("hello"))
	}()

	select {
	case <-failedCh:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for newline failure")
	}

	cw.attach(recovery)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("writeLine: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for newline retry to succeed")
	}

	if got := recovery.String(); got != "hello\n" {
		t.Fatalf("expected retried line to reach recovery writer, got %q", got)
	}
}

func TestWaitForWriter_WaitsUntilAttached(t *testing.T) {
	cw := newChildInputWriter()
	sink := &trackedWriteCloser{}

	done := make(chan io.WriteCloser, 1)
	go func() {
		writer, err := cw.waitForWriter(context.Background())
		if err != nil {
			t.Errorf("waitForWriter: %v", err)
			return
		}
		done <- writer
	}()

	time.Sleep(20 * time.Millisecond)
	cw.attach(sink)

	select {
	case got := <-done:
		if got != sink {
			t.Fatalf("expected attached writer, got %v", got)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for writer attachment")
	}
}

func TestWaitForWriter_ContextCanceledAfterWake(t *testing.T) {
	cw := newChildInputWriter()
	ctx, cancel := context.WithCancel(context.Background())

	done := make(chan error, 1)
	go func() {
		_, err := cw.waitForWriter(ctx)
		done <- err
	}()

	time.Sleep(20 * time.Millisecond)
	cancel()
	cw.close()

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("expected context.Canceled, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for canceled waitForWriter")
	}
}

func TestProxyClientInput_LongLineReturnsScannerError(t *testing.T) {
	p, _ := newTestProxy(t)
	cw := newChildInputWriter()

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	t.Cleanup(func() {
		_ = r.Close()
		_ = w.Close()
	})

	hugeLine := strings.Repeat("a", 10*1024*1024+1)
	go func() {
		_, _ = io.WriteString(w, hugeLine)
		_ = w.Close()
	}()

	err = p.proxyClientInput(context.Background(), cw, r)
	if !errors.Is(err, bufio.ErrTooLong) {
		t.Fatalf("expected bufio.ErrTooLong, got %v", err)
	}
}

func TestProxyClientInput_EOFAndCanceledWriteReturnNil(t *testing.T) {
	tests := []struct {
		name  string
		setup func(*childInputWriter, context.CancelFunc)
	}{
		{
			name: "eof",
			setup: func(cw *childInputWriter, cancel context.CancelFunc) {
				cw.close()
			},
		},
		{
			name: "canceled",
			setup: func(cw *childInputWriter, cancel context.CancelFunc) {
				cancel()
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			p, _ := newTestProxy(t)
			cw := newChildInputWriter()

			r, w, err := os.Pipe()
			if err != nil {
				t.Fatalf("os.Pipe: %v", err)
			}
			t.Cleanup(func() {
				_ = r.Close()
				_ = w.Close()
			})

			ctx, cancel := context.WithCancel(context.Background())
			tc.setup(cw, cancel)

			if _, err := io.WriteString(w, `{"jsonrpc":"2.0","method":"tools/list","id":1}`+"\n"); err != nil {
				t.Fatalf("write stdin: %v", err)
			}
			_ = w.Close()

			if err := p.proxyClientInput(ctx, cw, r); err != nil {
				t.Fatalf("expected nil, got %v", err)
			}
		})
	}
}

func TestProxyClientInput_WriteErrorReturnsError(t *testing.T) {
	p, _ := newTestProxy(t)
	cw := newChildInputWriter()

	origWrite := proxyInputWriteLine
	proxyInputWriteLine = func(cw *childInputWriter, ctx context.Context, line []byte) error {
		return errors.New("write failed hard")
	}
	t.Cleanup(func() { proxyInputWriteLine = origWrite })

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	t.Cleanup(func() {
		_ = r.Close()
		_ = w.Close()
	})

	if _, err := io.WriteString(w, `{"jsonrpc":"2.0","method":"tools/list","id":1}`+"\n"); err != nil {
		t.Fatalf("write stdin: %v", err)
	}
	_ = w.Close()

	err = p.proxyClientInput(context.Background(), cw, r)
	if err == nil || err.Error() != "write failed hard" {
		t.Fatalf("expected hard write error, got %v", err)
	}
}

func TestRunChild_SuccessCapturesOutput(t *testing.T) {
	p, store := newTestProxy(t)
	p.command = "sh"
	p.args = []string{"-c", `printf '%s\n' '{"jsonrpc":"2.0","method":"tools/list","id":1}'; printf '%s\n' 'stderr line' >&2; exit 0`}

	ctx := context.Background()
	inputWriter := newChildInputWriter()

	oldStdout := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	os.Stdout = w
	t.Cleanup(func() {
		os.Stdout = oldStdout
		_ = r.Close()
		_ = w.Close()
	})

	if err := p.runChild(ctx, inputWriter); err != nil {
		t.Fatalf("runChild: %v", err)
	}

	_ = w.Close()
	output, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("read stdout: %v", err)
	}
	if !strings.Contains(string(output), `{"jsonrpc":"2.0","method":"tools/list","id":1}`) {
		t.Fatalf("expected child stdout to be forwarded, got %q", string(output))
	}

	waitForStoreCount(t, store, 1)
	evt := lastEvent(t, store)
	if evt.Method != "tools/list" {
		t.Fatalf("expected captured method tools/list, got %q", evt.Method)
	}
}

func TestRunChild_NonZeroExitReturnsError(t *testing.T) {
	p, store := newTestProxy(t)
	p.command = "sh"
	p.args = []string{"-c", `printf '%s\n' '{"jsonrpc":"2.0","method":"tools/list","id":1}'; exit 7`}

	err := p.runChild(context.Background(), newChildInputWriter())
	if err == nil {
		t.Fatal("expected runChild to return an error for non-zero exit")
	}
	if !strings.Contains(err.Error(), "exit status 7") {
		t.Fatalf("expected exit status error, got %v", err)
	}

	waitForStoreCount(t, store, 1)
}

func TestRunChild_StartError(t *testing.T) {
	p, _ := newTestProxy(t)
	p.command = "definitely-not-a-real-command-shipyard"
	p.args = nil

	err := p.runChild(context.Background(), newChildInputWriter())
	if err == nil {
		t.Fatal("expected runChild to fail when the command cannot start")
	}
	if !strings.Contains(err.Error(), "start child:") {
		t.Fatalf("expected start child error, got %v", err)
	}
}

func TestRunChild_PipeFailures(t *testing.T) {
	tests := []struct {
		name string
		patch func()
		want string
	}{
		{
			name: "stdin pipe",
			patch: func() {
				cmdStdinPipe = func(cmd *exec.Cmd) (io.WriteCloser, error) {
					return nil, errors.New("stdin failed")
				}
			},
			want: "stdin pipe: stdin failed",
		},
		{
			name: "stdout pipe",
			patch: func() {
				cmdStdoutPipe = func(cmd *exec.Cmd) (io.ReadCloser, error) {
					return nil, errors.New("stdout failed")
				}
			},
			want: "stdout pipe: stdout failed",
		},
		{
			name: "stderr pipe",
			patch: func() {
				cmdStderrPipe = func(cmd *exec.Cmd) (io.ReadCloser, error) {
					return nil, errors.New("stderr failed")
				}
			},
			want: "stderr pipe: stderr failed",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			origStdin := cmdStdinPipe
			origStdout := cmdStdoutPipe
			origStderr := cmdStderrPipe
			t.Cleanup(func() {
				cmdStdinPipe = origStdin
				cmdStdoutPipe = origStdout
				cmdStderrPipe = origStderr
			})

			p, _ := newTestProxy(t)
			p.command = "sh"
			p.args = []string{"-c", "exit 0"}
			tc.patch()

			err := p.runChild(context.Background(), newChildInputWriter())
			if err == nil || err.Error() != tc.want {
				t.Fatalf("expected %q, got %v", tc.want, err)
			}
		})
	}
}

func TestSeamHelpers_DefaultPassthrough(t *testing.T) {
	p, _ := newTestProxy(t)

	if got := p.now(); got.IsZero() {
		t.Fatal("expected now() to return a non-zero time")
	}
	if err := p.waitForBackoffWithSeams(context.Background(), time.Millisecond); err != nil {
		t.Fatalf("waitForBackoffWithSeams: %v", err)
	}

	cw := newChildInputWriter()
	sink := &trackedWriteCloser{}
	cw.attach(sink)

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	t.Cleanup(func() {
		_ = r.Close()
		_ = w.Close()
	})
	if _, err := io.WriteString(w, `{"jsonrpc":"2.0","method":"tools/list","id":1}`+"\n"); err != nil {
		t.Fatalf("write stdin: %v", err)
	}
	_ = w.Close()

	if err := p.proxyClientInputWithSeams(context.Background(), cw, r); err != nil {
		t.Fatalf("proxyClientInputWithSeams: %v", err)
	}
	if got := sink.String(); got == "" {
		t.Fatal("expected passthrough write to child input writer")
	}

	p.command = "sh"
	p.args = []string{"-c", `exit 0`}
	if err := p.runChildWithSeams(context.Background(), newChildInputWriter()); err != nil {
		t.Fatalf("runChildWithSeams: %v", err)
	}
}

func TestPipeAndTap_WriteFailuresAndScannerError(t *testing.T) {
	t.Run("write failure", func(t *testing.T) {
		p, _ := newTestProxy(t)
		p.pipeAndTap(context.Background(), strings.NewReader(`{"jsonrpc":"2.0","id":1}`+"\n"), errWriter{err: errors.New("write failed")}, capture.DirectionServerToClient)
	})

	t.Run("newline write failure", func(t *testing.T) {
		p, _ := newTestProxy(t)
		p.pipeAndTap(context.Background(), strings.NewReader(`{"jsonrpc":"2.0","id":1}`+"\n"), &failSecondWriteCloser{failErr: errors.New("newline failed")}, capture.DirectionServerToClient)
	})

	t.Run("scanner error", func(t *testing.T) {
		p, _ := newTestProxy(t)
		huge := strings.Repeat("a", 10*1024*1024+1)
		p.pipeAndTap(context.Background(), strings.NewReader(huge), io.Discard, capture.DirectionServerToClient)
	})
}

func TestRestartBackoff_CappedAfterMultiplication(t *testing.T) {
	if got := restartBackoff(6); got != maxRestartBackoff {
		t.Fatalf("restartBackoff(6) = %v, want %v", got, maxRestartBackoff)
	}
}
