package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
)

type trackedWriteCloser struct {
	mu     sync.Mutex
	buf    bytes.Buffer
	closed bool
}

func (w *trackedWriteCloser) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.Write(p)
}

func (w *trackedWriteCloser) Close() error {
	w.mu.Lock()
	w.closed = true
	w.mu.Unlock()
	return nil
}

func (w *trackedWriteCloser) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.String()
}

func (w *trackedWriteCloser) Len() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buf.Len()
}

func (w *trackedWriteCloser) Closed() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.closed
}

func waitForStoreCount(t *testing.T, store *capture.Store, want int) {
	t.Helper()

	deadline := time.Now().Add(10 * time.Second)
	for {
		page, err := store.Query(1, want+10, "", "")
		if err != nil {
			t.Fatalf("Query: %v", err)
		}
		if page.TotalCount >= want {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %d events, got %d", want, page.TotalCount)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestChildInputWriter_WriteLineAndClose(t *testing.T) {
	cw := newChildInputWriter()
	sink := &trackedWriteCloser{}
	cw.attach(sink)

	if err := cw.writeLine(context.Background(), []byte("hello")); err != nil {
		t.Fatalf("writeLine: %v", err)
	}
	if got := sink.String(); got != "hello\n" {
		t.Fatalf("expected newline-delimited write, got %q", got)
	}

	cw.close()
	if err := cw.writeLine(context.Background(), []byte("again")); !errors.Is(err, io.EOF) {
		t.Fatalf("expected io.EOF after close, got %v", err)
	}
}

func TestChildInputWriter_WaitForWriterCanceled(t *testing.T) {
	cw := newChildInputWriter()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if _, err := cw.waitForWriter(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

func TestChildInputWriter_AttachAfterCloseClosesIncomingWriter(t *testing.T) {
	cw := newChildInputWriter()
	cw.close()

	sink := &trackedWriteCloser{}
	cw.attach(sink)

	if !sink.Closed() {
		t.Fatal("expected attached writer to be closed after child writer shutdown")
	}
}

func TestMergeEnv(t *testing.T) {
	base := []string{"B=2", "A=1"}
	got := mergeEnv(base, nil)
	if !reflect.DeepEqual(got, base) {
		t.Fatalf("expected mergeEnv with no overrides to return base env, got %v", got)
	}

	merged := mergeEnv([]string{"B=2", "BROKEN", "A=1"}, map[string]string{
		"A": "3",
		"C": "4",
	})
	want := []string{"A=3", "B=2", "C=4"}
	if !reflect.DeepEqual(merged, want) {
		t.Fatalf("expected merged env %v, got %v", want, merged)
	}
}

func TestExitCodeFromError(t *testing.T) {
	cmd := exec.Command("sh", "-c", "exit 7")
	err := cmd.Run()
	if err == nil {
		t.Fatal("expected non-nil error from failing command")
	}
	if got := exitCodeFromError(err); got != 7 {
		t.Fatalf("expected exit code 7, got %d", got)
	}

	if got := exitCodeFromError(errors.New("boom")); got != -1 {
		t.Fatalf("expected -1 for non-exit error, got %d", got)
	}
}

func TestFilterRecentCrashes(t *testing.T) {
	now := time.Unix(1_000, 0)
	crashes := []time.Time{
		now.Add(-2 * time.Minute),
		now.Add(-30 * time.Second),
		now.Add(-time.Second),
	}

	got := filterRecentCrashes(crashes, now)
	want := []time.Time{
		now.Add(-30 * time.Second),
		now.Add(-time.Second),
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
}

func TestWaitForBackoff(t *testing.T) {
	if err := waitForBackoff(context.Background(), 5*time.Millisecond); err != nil {
		t.Fatalf("waitForBackoff returned error: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := waitForBackoff(ctx, time.Hour); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

func TestRestartBackoff(t *testing.T) {
	cases := []struct {
		crashes int
		want    time.Duration
	}{
		{1, time.Second},
		{2, 2 * time.Second},
		{5, 16 * time.Second},
		{10, maxRestartBackoff},
	}

	for _, tc := range cases {
		if got := restartBackoff(tc.crashes); got != tc.want {
			t.Fatalf("restartBackoff(%d) = %v, want %v", tc.crashes, got, tc.want)
		}
	}
}

func TestWaitForClientInput(t *testing.T) {
	p, _ := newTestProxy(t)

	if err := p.waitForClientInput(make(chan error), 0); err != nil {
		t.Fatalf("expected nil when client channel is not ready, got %v", err)
	}

	cases := []struct {
		name string
		err  error
		want error
	}{
		{name: "eof", err: io.EOF, want: nil},
		{name: "canceled", err: context.Canceled, want: nil},
		{name: "other", err: errors.New("boom"), want: errors.New("boom")},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			done := make(chan error, 1)
			done <- tc.err

			err := p.waitForClientInput(done, 0)
			if tc.want == nil {
				if err != nil {
					t.Fatalf("expected nil, got %v", err)
				}
				return
			}
			if err == nil || err.Error() != tc.want.Error() {
				t.Fatalf("expected %v, got %v", tc.want, err)
			}
		})
	}
}

func TestProxyClientInput(t *testing.T) {
	p, store := newTestProxy(t)
	cw := newChildInputWriter()
	sink := &trackedWriteCloser{}
	cw.attach(sink)

	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("os.Pipe: %v", err)
	}
	t.Cleanup(func() {
		_ = r.Close()
	})

	line := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	if _, err := fmt.Fprintln(w, line); err != nil {
		t.Fatalf("write stdin: %v", err)
	}
	_ = w.Close()

	if err := p.proxyClientInput(context.Background(), cw, r); err != nil {
		t.Fatalf("proxyClientInput: %v", err)
	}
	if got := sink.String(); got != line+"\n" {
		t.Fatalf("expected stdin line to be forwarded, got %q", got)
	}
	waitForStoreCount(t, store, 1)
}

func TestPipeAndTap_ForwardsAndCaptures(t *testing.T) {
	p, store := newTestProxy(t)
	src := strings.NewReader(`{"jsonrpc":"2.0","method":"tools/list","id":1}` + "\n")
	dst := &trackedWriteCloser{}

	p.pipeAndTap(context.Background(), src, dst, capture.DirectionServerToClient)

	if got := dst.String(); got != `{"jsonrpc":"2.0","method":"tools/list","id":1}`+"\n" {
		t.Fatalf("expected forwarded line, got %q", got)
	}
	waitForStoreCount(t, store, 1)
}

func TestPipeAndTap_ClaimsManagedResponse(t *testing.T) {
	p, store := newTestProxy(t)
	manager := NewManager()
	mp := manager.Register("alpha", p)
	p.SetManaged(mp)

	rt := mp.responses
	ch := rt.register("shipyard-1")

	src := strings.NewReader(`{"jsonrpc":"2.0","id":"shipyard-1","result":{"ok":true}}` + "\n")
	dst := &trackedWriteCloser{}

	p.pipeAndTap(context.Background(), src, dst, capture.DirectionServerToClient)

	if got := dst.Len(); got != 0 {
		t.Fatalf("expected managed response to be swallowed, got %q", dst.String())
	}

	select {
	case got := <-ch:
		if string(got) != `{"jsonrpc":"2.0","id":"shipyard-1","result":{"ok":true}}` {
			t.Fatalf("unexpected resolved payload: %s", string(got))
		}
	default:
		t.Fatal("expected managed response to resolve a pending request")
	}

	waitForStoreCount(t, store, 1)
}

func TestManagerSendRequest(t *testing.T) {
	t.Run("unknown server", func(t *testing.T) {
		m := NewManager()
		_, err := m.SendRequest(context.Background(), "missing", "tools/list", nil)
		if err == nil || !strings.Contains(err.Error(), "not found") {
			t.Fatalf("expected not-found error, got %v", err)
		}
	})

	t.Run("missing input writer", func(t *testing.T) {
		m := NewManager()
		p, _ := newTestProxy(t)
		m.Register("alpha", p)

		_, err := m.SendRequest(context.Background(), "alpha", "tools/list", nil)
		if err == nil || !strings.Contains(err.Error(), "no input writer attached") {
			t.Fatalf("expected missing input writer error, got %v", err)
		}
	})

	t.Run("success", func(t *testing.T) {
		m := NewManager()
		p, store := newTestProxy(t)
		mp := m.Register("alpha", p)

		cw := newChildInputWriter()
		sink := &trackedWriteCloser{}
		cw.attach(sink)
		mp.SetInputWriter(cw)
		mp.initReady = true

		type result struct {
			raw json.RawMessage
			err error
		}
		done := make(chan result, 1)
		go func() {
			raw, err := m.SendRequest(context.Background(), "alpha", "tools/list", json.RawMessage(`{"echo":true}`))
			done <- result{raw: raw, err: err}
		}()

		deadline := time.Now().Add(10 * time.Second)
		for sink.Len() == 0 {
			if time.Now().After(deadline) {
				t.Fatal("timed out waiting for request to be written")
			}
			time.Sleep(10 * time.Millisecond)
		}

		var req map[string]json.RawMessage
		if err := json.Unmarshal([]byte(strings.TrimSpace(sink.String())), &req); err != nil {
			t.Fatalf("unmarshal request: %v", err)
		}

		var id string
		if err := json.Unmarshal(req["id"], &id); err != nil {
			t.Fatalf("unmarshal request id: %v", err)
		}

		if !mp.HandleChildOutput([]byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%q,"result":{"tools":[]}}`, id))) {
			t.Fatal("expected response to resolve a pending request")
		}

		select {
		case got := <-done:
			if got.err != nil {
				t.Fatalf("SendRequest returned error: %v", got.err)
			}
			if string(got.raw) != `{"jsonrpc":"2.0","id":"`+id+`","result":{"tools":[]}}` {
				t.Fatalf("unexpected response payload: %s", string(got.raw))
			}
		case <-time.After(10 * time.Second):
			t.Fatal("timed out waiting for SendRequest to return")
		}

		waitForStoreCount(t, store, 1)
		evt := lastEvent(t, store)
		if evt.Method != "tools/list" {
			t.Fatalf("expected captured request method tools/list, got %q", evt.Method)
		}
		if evt.Status != "pending" {
			t.Fatalf("expected pending request status, got %q", evt.Status)
		}
	})
}
