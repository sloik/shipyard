package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/web"
)

type lineObserverWriteCloser struct {
	mu    sync.Mutex
	buf   bytes.Buffer
	lines chan string
}

func newLineObserverWriteCloser() *lineObserverWriteCloser {
	return &lineObserverWriteCloser{lines: make(chan string, 16)}
}

func (w *lineObserverWriteCloser) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()

	n, err := w.buf.Write(p)
	for {
		data := w.buf.Bytes()
		idx := bytes.IndexByte(data, '\n')
		if idx == -1 {
			break
		}
		line := string(data[:idx])
		rest := append([]byte(nil), data[idx+1:]...)
		w.buf.Reset()
		w.buf.Write(rest)
		w.lines <- line
	}
	return n, err
}

func (w *lineObserverWriteCloser) Close() error { return nil }

func TestNewResponseTracker(t *testing.T) {
	rt := newResponseTracker()
	if rt == nil {
		t.Fatal("expected non-nil response tracker")
	}
	if rt.pending == nil {
		t.Fatal("expected non-nil pending map")
	}
}

func TestResponseTracker_Register(t *testing.T) {
	rt := newResponseTracker()
	ch := rt.register("req-1")
	if ch == nil {
		t.Fatal("expected non-nil channel from register")
	}

	// Channel should be buffered with capacity 1
	select {
	case ch <- json.RawMessage(`{}`):
		// ok, buffered send succeeded
	default:
		t.Fatal("expected buffered channel (cap 1)")
	}
}

func TestResponseTracker_Resolve(t *testing.T) {
	rt := newResponseTracker()
	ch := rt.register("req-1")

	msg := json.RawMessage(`{"jsonrpc":"2.0","id":"req-1","result":{}}`)
	ok := rt.resolve("req-1", msg)
	if !ok {
		t.Fatal("expected resolve to return true")
	}

	select {
	case got := <-ch:
		if string(got) != string(msg) {
			t.Fatalf("expected %s, got %s", string(msg), string(got))
		}
	default:
		t.Fatal("expected message on channel after resolve")
	}
}

func TestResponseTracker_Cancel(t *testing.T) {
	rt := newResponseTracker()
	rt.register("req-1")

	rt.cancel("req-1")

	// After cancel, resolve should return false
	ok := rt.resolve("req-1", json.RawMessage(`{}`))
	if ok {
		t.Fatal("expected resolve to return false after cancel")
	}
}

func TestResponseTracker_ResolveUnknownID(t *testing.T) {
	rt := newResponseTracker()

	ok := rt.resolve("nonexistent", json.RawMessage(`{}`))
	if ok {
		t.Fatal("expected resolve to return false for unknown ID")
	}
}

func TestResponseTracker_ConcurrentRegisterResolve(t *testing.T) {
	rt := newResponseTracker()
	const n = 100

	var wg sync.WaitGroup
	wg.Add(n * 2) // n registers + n resolves

	channels := make([]chan json.RawMessage, n)

	// Register n IDs concurrently
	for i := 0; i < n; i++ {
		i := i
		go func() {
			defer wg.Done()
			id := "id-" + string(rune('A'+i%26)) + "-" + itoa(i)
			channels[i] = rt.register(id)
		}()
	}

	// Resolve n IDs concurrently (some may not exist yet, that's fine)
	for i := 0; i < n; i++ {
		i := i
		go func() {
			defer wg.Done()
			id := "id-" + string(rune('A'+i%26)) + "-" + itoa(i)
			rt.resolve(id, json.RawMessage(`{}`))
		}()
	}

	wg.Wait()
	// No panics or data races means success (run with -race)
}

// itoa is a simple int-to-string helper to avoid importing strconv.
func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	s := ""
	for i > 0 {
		s = string(rune('0'+i%10)) + s
		i /= 10
	}
	return s
}

func TestNewManager(t *testing.T) {
	m := NewManager()
	if m == nil {
		t.Fatal("expected non-nil manager")
	}
	if m.proxies == nil {
		t.Fatal("expected non-nil proxies map")
	}
	if len(m.proxies) != 0 {
		t.Fatalf("expected empty proxies map, got %d entries", len(m.proxies))
	}
}

func TestManager_Register(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)

	mp := m.Register("test-server", p)
	if mp == nil {
		t.Fatal("expected non-nil managedProxy")
	}
	if mp.proxy != p {
		t.Fatal("expected managedProxy to reference the registered proxy")
	}
	if mp.responses == nil {
		t.Fatal("expected non-nil response tracker on managedProxy")
	}

	// Verify the manager now knows about it
	m.mu.RLock()
	stored, ok := m.proxies["test-server"]
	m.mu.RUnlock()
	if !ok {
		t.Fatal("expected proxy to be stored in manager")
	}
	if stored != mp {
		t.Fatal("expected stored proxy to match returned managedProxy")
	}
}

func TestManager_Servers(t *testing.T) {
	m := NewManager()
	p1, _ := newTestProxy(t)
	p2, _ := newTestProxy(t)

	m.Register("alpha", p1)
	m.Register("beta", p2)

	servers := m.Servers()
	if len(servers) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(servers))
	}

	names := map[string]bool{}
	for _, s := range servers {
		names[s.Name] = true
		if s.Status != "online" {
			t.Fatalf("expected status 'online', got '%s'", s.Status)
		}
	}
	if !names["alpha"] || !names["beta"] {
		t.Fatalf("expected servers alpha and beta, got %v", names)
	}
}

func TestManager_Servers_Empty(t *testing.T) {
	m := NewManager()
	servers := m.Servers()
	if servers == nil {
		t.Fatal("expected non-nil slice from Servers()")
	}
	if len(servers) != 0 {
		t.Fatalf("expected 0 servers, got %d", len(servers))
	}
}

func TestHandleChildOutput_ValidResponse(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	ch := rt.register("shipyard-1")

	line := []byte(`{"jsonrpc":"2.0","id":"shipyard-1","result":{"tools":[]}}`)
	ok := mp.HandleChildOutput(line)
	if !ok {
		t.Fatal("expected HandleChildOutput to return true for a valid response")
	}

	select {
	case msg := <-ch:
		if string(msg) != string(line) {
			t.Fatalf("expected resolved message to equal input line")
		}
	default:
		t.Fatal("expected message on channel")
	}
}

func TestHandleChildOutput_ValidError(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	ch := rt.register("shipyard-2")

	line := []byte(`{"jsonrpc":"2.0","id":"shipyard-2","error":{"code":-32601,"message":"not found"}}`)
	ok := mp.HandleChildOutput(line)
	if !ok {
		t.Fatal("expected HandleChildOutput to return true for an error response")
	}

	select {
	case msg := <-ch:
		if string(msg) != string(line) {
			t.Fatalf("expected resolved message to equal input line")
		}
	default:
		t.Fatal("expected message on channel")
	}
}

func TestHandleChildOutput_Request(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	// A request has method but no result/error — should not be treated as a response
	line := []byte(`{"jsonrpc":"2.0","id":"1","method":"tools/list"}`)
	ok := mp.HandleChildOutput(line)
	if ok {
		t.Fatal("expected HandleChildOutput to return false for a request (no result/error)")
	}
}

func TestHandleChildOutput_Notification(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	// Notification: no id
	line := []byte(`{"jsonrpc":"2.0","method":"notifications/initialized"}`)
	ok := mp.HandleChildOutput(line)
	if ok {
		t.Fatal("expected HandleChildOutput to return false for a notification (no id)")
	}
}

func TestHandleChildOutput_ResponseWithoutID(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	line := []byte(`{"jsonrpc":"2.0","result":{"tools":[]}}`)
	ok := mp.HandleChildOutput(line)
	if ok {
		t.Fatal("expected HandleChildOutput to return false when response has no id")
	}
}

func TestHandleChildOutput_MalformedJSON(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	ok := mp.HandleChildOutput([]byte(`not valid json`))
	if ok {
		t.Fatal("expected HandleChildOutput to return false for malformed JSON")
	}
}

func TestHandleChildOutput_QuotedStringID(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	ch := rt.register("shipyard-1")

	// ID is a quoted string in the JSON
	line := []byte(`{"jsonrpc":"2.0","id":"shipyard-1","result":{}}`)
	ok := mp.HandleChildOutput(line)
	if !ok {
		t.Fatal("expected HandleChildOutput to return true for quoted string ID")
	}

	select {
	case <-ch:
		// success
	default:
		t.Fatal("expected message on channel for quoted string ID")
	}
}

func TestHandleChildOutput_NumericID(t *testing.T) {
	rt := newResponseTracker()
	mp := &managedProxy{responses: rt}

	// Register with the string "42" (numeric IDs are stored as raw JSON "42")
	ch := rt.register("42")

	// Numeric ID in JSON (no quotes around the value)
	line := []byte(`{"jsonrpc":"2.0","id":42,"result":{}}`)
	ok := mp.HandleChildOutput(line)
	if !ok {
		t.Fatal("expected HandleChildOutput to return true for numeric ID")
	}

	select {
	case <-ch:
		// success
	default:
		t.Fatal("expected message on channel for numeric ID")
	}
}

func TestManagerSendRequest_ContextCanceled(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)

	cw := newChildInputWriter()
	cw.attach(&trackedWriteCloser{})
	mp.SetInputWriter(cw)
	mp.initReady = true

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := m.SendRequest(ctx, "alpha", "tools/list", nil)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
}

func TestManagerSendRequest_ContextCanceledWhileWaiting(t *testing.T) {
	origTimeout := requestTimeout
	requestTimeout = 5 * time.Second
	t.Cleanup(func() { requestTimeout = origTimeout })

	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)

	cw := newChildInputWriter()
	cw.attach(&trackedWriteCloser{})
	mp.SetInputWriter(cw)
	mp.initReady = true

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		_, err := m.SendRequest(ctx, "alpha", "tools/list", nil)
		errCh <- err
	}()

	time.Sleep(20 * time.Millisecond)
	cancel()

	select {
	case err := <-errCh:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("expected context.Canceled, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for canceled SendRequest")
	}
}

func TestManagerSendRequest_Timeout(t *testing.T) {
	origTimeout := requestTimeout
	requestTimeout = 10 * time.Millisecond
	t.Cleanup(func() { requestTimeout = origTimeout })

	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)

	cw := newChildInputWriter()
	cw.attach(&trackedWriteCloser{})
	mp.SetInputWriter(cw)
	mp.initReady = true

	_, err := m.SendRequest(context.Background(), "alpha", "tools/list", nil)
	if err == nil {
		t.Fatal("expected timeout error")
	}
	if got := err.Error(); got == "" || got[:7] != "timeout" {
		t.Fatalf("expected timeout error, got %v", err)
	}
}

func TestManagerSendRequest_MarshalFailure(t *testing.T) {
	origMarshal := marshalRequest
	marshalRequest = func(v any) ([]byte, error) {
		return nil, errors.New("marshal failed")
	}
	t.Cleanup(func() { marshalRequest = origMarshal })

	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)
	mp.initReady = true

	_, err := m.SendRequest(context.Background(), "alpha", "tools/list", nil)
	if err == nil {
		t.Fatal("expected marshal failure")
	}
	if got := err.Error(); got != "marshal request: marshal failed" {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestManagerSendRequest_WriteFailure(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)

	cw := newChildInputWriter()
	cw.close()
	mp.SetInputWriter(cw)
	mp.initReady = true

	_, err := m.SendRequest(context.Background(), "alpha", "tools/list", nil)
	if err == nil {
		t.Fatal("expected write failure")
	}
	if got := err.Error(); !strings.Contains(got, "write to child: EOF") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// --- Manager status tracking (SPEC-004 AC-2/AC-3) ---

func TestManager_SetStatus(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	m.SetStatus("alpha", "crashed", "exit code 1")

	servers := m.Servers()
	if len(servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(servers))
	}
	if servers[0].Status != "crashed" {
		t.Fatalf("expected status crashed, got %q", servers[0].Status)
	}
	if servers[0].ErrorMessage != "exit code 1" {
		t.Fatalf("expected error message, got %q", servers[0].ErrorMessage)
	}
}

func TestManager_SetStatus_Online_ResetsStartTime(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	m.SetStatus("alpha", "crashed", "oops")
	m.SetStatus("alpha", "online", "")

	servers := m.Servers()
	if servers[0].Status != "online" {
		t.Fatalf("expected online, got %q", servers[0].Status)
	}
	// Uptime may be 0ms if checked immediately — just verify it's non-negative
	if servers[0].Uptime < 0 {
		t.Fatalf("expected non-negative uptime, got %d", servers[0].Uptime)
	}
}

func TestManager_SetStatus_UnknownServer(t *testing.T) {
	m := NewManager()
	// Should not panic
	m.SetStatus("nonexistent", "online", "")
}

func TestManager_SetToolCount(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	m.SetToolCount("alpha", 7)

	servers := m.Servers()
	if servers[0].ToolCount != 7 {
		t.Fatalf("expected tool count 7, got %d", servers[0].ToolCount)
	}
}

func TestManager_ServerStatus(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	if got := m.ServerStatus("alpha"); got != "online" {
		t.Fatalf("expected online, got %q", got)
	}
	if got := m.ServerStatus("nonexistent"); got != "" {
		t.Fatalf("expected empty string for unknown server, got %q", got)
	}
}

func TestManager_RestartServer(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	var cancelled bool
	m.SetCancelFn("alpha", func() { cancelled = true })

	err := m.RestartServer("alpha")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cancelled {
		t.Fatal("expected cancel function to be called")
	}
	if got := m.ServerStatus("alpha"); got != "restarting" {
		t.Fatalf("expected restarting, got %q", got)
	}
}

func TestManager_RestartServer_NotFound(t *testing.T) {
	m := NewManager()
	err := m.RestartServer("nonexistent")
	if err == nil {
		t.Fatal("expected error for nonexistent server")
	}
}

func TestManager_StopServer(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("beta", p)

	var cancelled bool
	m.SetCancelFn("beta", func() { cancelled = true })

	err := m.StopServer("beta")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !cancelled {
		t.Fatal("expected cancel function to be called")
	}
	if got := m.ServerStatus("beta"); got != "stopped" {
		t.Fatalf("expected stopped, got %q", got)
	}
}

func TestManager_StopServer_NotFound(t *testing.T) {
	m := NewManager()
	err := m.StopServer("nonexistent")
	if err == nil {
		t.Fatal("expected error for nonexistent server")
	}
}

func TestManager_Servers_EnrichedFields(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)
	m.SetToolCount("alpha", 3)

	servers := m.Servers()
	if len(servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(servers))
	}
	s := servers[0]
	if s.Name != "alpha" {
		t.Fatalf("expected name alpha, got %q", s.Name)
	}
	if s.Command == "" {
		t.Fatal("expected non-empty command")
	}
	if s.ToolCount != 3 {
		t.Fatalf("expected tool count 3, got %d", s.ToolCount)
	}
	if s.Uptime < 0 {
		t.Fatalf("expected non-negative uptime for online server, got %d", s.Uptime)
	}
}

func TestManager_SetHub_BroadcastOnStatusChange(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	m.Register("alpha", p)

	// Create a hub and start it briefly
	hub := newTestHub(t)
	m.SetHub(hub)

	// This should not panic even with hub set
	m.SetStatus("alpha", "crashed", "boom")
}

func newTestHub(t *testing.T) *web.Hub {
	t.Helper()
	return web.NewHub()
}

func TestManagerSendRequest_ConcurrentResponsesOutOfOrder(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
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
	responses := map[string]chan result{
		"tools/list": make(chan result, 1),
		"tools/call": make(chan result, 1),
	}

	send := func(method string, params json.RawMessage) {
		raw, err := m.SendRequest(context.Background(), "alpha", method, params)
		responses[method] <- result{raw: raw, err: err}
	}

	go send("tools/list", json.RawMessage(`{"kind":"list"}`))

	deadline := time.Now().Add(2 * time.Second)
	for strings.Count(sink.String(), "\n") < 1 {
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for first request write")
		}
		time.Sleep(10 * time.Millisecond)
	}

	go send("tools/call", json.RawMessage(`{"kind":"call"}`))

	deadline = time.Now().Add(2 * time.Second)
	for strings.Count(sink.String(), "\n") < 2 {
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for second request write")
		}
		time.Sleep(10 * time.Millisecond)
	}

	lines := strings.Split(strings.TrimSpace(sink.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 request lines, got %d: %q", len(lines), sink.String())
	}

	type reqInfo struct {
		id string
	}
	reqs := make(map[string]reqInfo)
	for _, line := range lines {
		var req map[string]json.RawMessage
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			t.Fatalf("unmarshal request: %v", err)
		}
		var method string
		if err := json.Unmarshal(req["method"], &method); err != nil {
			t.Fatalf("unmarshal method: %v", err)
		}
		reqs[method] = reqInfo{id: string(req["id"])}
	}

	if reqs["tools/list"].id == "" || reqs["tools/call"].id == "" {
		t.Fatalf("expected request IDs, got %+v", reqs)
	}

	if !mp.HandleChildOutput([]byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"ok":"call"}}`, reqs["tools/call"].id))) {
		t.Fatal("expected second response to resolve")
	}
	if !mp.HandleChildOutput([]byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"ok":"list"}}`, reqs["tools/list"].id))) {
		t.Fatal("expected first response to resolve")
	}

	select {
	case got := <-responses["tools/call"]:
		if got.err != nil {
			t.Fatalf("tools/call returned error: %v", got.err)
		}
		want := fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"ok":"call"}}`, reqs["tools/call"].id)
		if string(got.raw) != want {
			t.Fatalf("unexpected tools/call response: %s", string(got.raw))
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for tools/call response")
	}

	select {
	case got := <-responses["tools/list"]:
		if got.err != nil {
			t.Fatalf("tools/list returned error: %v", got.err)
		}
		want := fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"ok":"list"}}`, reqs["tools/list"].id)
		if string(got.raw) != want {
			t.Fatalf("unexpected tools/list response: %s", string(got.raw))
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for tools/list response")
	}
}

func TestManagerSendRequest_BootstrapsManagedChildBeforeToolsList(t *testing.T) {
	m := NewManager()
	p, store := newTestProxy(t)
	mp := m.Register("alpha", p)

	cw := newChildInputWriter()
	sink := newLineObserverWriteCloser()
	cw.attach(sink)
	mp.SetInputWriter(cw)

	resultCh := make(chan struct {
		raw json.RawMessage
		err error
	}, 1)
	go func() {
		raw, err := m.SendRequest(context.Background(), "alpha", "tools/list", json.RawMessage(`{}`))
		resultCh <- struct {
			raw json.RawMessage
			err error
		}{raw: raw, err: err}
	}()

	for handled := 0; handled < 3; handled++ {
		select {
		case line := <-sink.lines:
			var req map[string]json.RawMessage
			if err := json.Unmarshal([]byte(line), &req); err != nil {
				t.Fatalf("unmarshal request: %v", err)
			}

			var method string
			if err := json.Unmarshal(req["method"], &method); err != nil {
				t.Fatalf("unmarshal method: %v", err)
			}

			switch handled {
			case 0:
				if method != "initialize" {
					t.Fatalf("expected first request initialize, got %q", method)
				}
				if !mp.HandleChildOutput([]byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"protocolVersion":"%s"}}`, req["id"], managedChildProtocolVersion))) {
					t.Fatal("expected initialize response to resolve")
				}
			case 1:
				if method != "notifications/initialized" {
					t.Fatalf("expected second message notifications/initialized, got %q", method)
				}
			case 2:
				if method != "tools/list" {
					t.Fatalf("expected third request tools/list, got %q", method)
				}
				if !mp.HandleChildOutput([]byte(fmt.Sprintf(`{"jsonrpc":"2.0","id":%s,"result":{"tools":[{"name":"lms_status"},{"name":"lms_chat"}]}}`, req["id"]))) {
					t.Fatal("expected tools/list response to resolve")
				}
			}
		case <-time.After(2 * time.Second):
			t.Fatal("timed out waiting for bootstrap writes")
		}
	}

	select {
	case got := <-resultCh:
		if got.err != nil {
			t.Fatalf("SendRequest returned error: %v", got.err)
		}
		if !strings.Contains(string(got.raw), `"tools":[{"name":"lms_status"},{"name":"lms_chat"}]`) {
			t.Fatalf("unexpected tools/list payload: %s", string(got.raw))
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for tools/list result")
	}

	if servers := m.Servers(); len(servers) != 1 || servers[0].ToolCount != 2 {
		t.Fatalf("expected cached tool count 2 after bootstrap, got %+v", servers)
	}
	waitForStoreCount(t, store, 3)
}

// --- SPEC-007: Session Recording ---

func TestManager_StartRecording(t *testing.T) {
	m := NewManager()

	m.StartRecording("test-server", 42)
	if id := m.ActiveSessionID("test-server"); id != 42 {
		t.Fatalf("expected active session 42, got %d", id)
	}
}

func TestManager_StopRecording(t *testing.T) {
	m := NewManager()

	m.StartRecording("test-server", 42)
	m.StopRecording("test-server")
	if id := m.ActiveSessionID("test-server"); id != 0 {
		t.Fatalf("expected no active session, got %d", id)
	}
}

func TestManager_ActiveSessionID_NoSession(t *testing.T) {
	m := NewManager()

	if id := m.ActiveSessionID("nonexistent"); id != 0 {
		t.Fatalf("expected 0 for no active session, got %d", id)
	}
}

func TestManager_MultipleServerSessions(t *testing.T) {
	m := NewManager()

	m.StartRecording("alpha", 10)
	m.StartRecording("beta", 20)

	if id := m.ActiveSessionID("alpha"); id != 10 {
		t.Fatalf("expected alpha session 10, got %d", id)
	}
	if id := m.ActiveSessionID("beta"); id != 20 {
		t.Fatalf("expected beta session 20, got %d", id)
	}

	m.StopRecording("alpha")
	if id := m.ActiveSessionID("alpha"); id != 0 {
		t.Fatalf("expected alpha cleared, got %d", id)
	}
	if id := m.ActiveSessionID("beta"); id != 20 {
		t.Fatalf("expected beta still 20, got %d", id)
	}
}

func TestManager_StartRecording_OverwritesPrevious(t *testing.T) {
	m := NewManager()

	m.StartRecording("srv", 1)
	m.StartRecording("srv", 2)

	if id := m.ActiveSessionID("srv"); id != 2 {
		t.Fatalf("expected session 2 to overwrite, got %d", id)
	}
}
