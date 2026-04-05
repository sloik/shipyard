package web

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/sloik/shipyard/internal/capture"
)

type errReadCloser struct{ err error }

func (r errReadCloser) Read(p []byte) (int, error) { return 0, r.err }
func (r errReadCloser) Close() error               { return nil }

type stubWSConn struct {
	writeErr    error
	writeCalled chan struct{}
	writeOnce   sync.Once
}

func (c *stubWSConn) Read(ctx context.Context) (websocket.MessageType, []byte, error) {
	<-ctx.Done()
	return websocket.MessageText, nil, ctx.Err()
}

func (c *stubWSConn) Write(ctx context.Context, typ websocket.MessageType, msg []byte) error {
	c.writeOnce.Do(func() {
		if c.writeCalled != nil {
			close(c.writeCalled)
		}
	})
	return c.writeErr
}

func (c *stubWSConn) CloseNow() error { return nil }

func TestHub_RunClosesClientsOnCancel(t *testing.T) {
	h := NewHub()
	client := &Client{send: make(chan []byte, 1)}
	h.Register(client)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		h.Run(ctx)
		close(done)
	}()

	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("hub did not stop after context cancellation")
	}

	select {
	case _, ok := <-client.send:
		if ok {
			t.Fatal("expected client send channel to be closed")
		}
	default:
		t.Fatal("expected closed client send channel to be readable")
	}

	h.mu.RLock()
	remaining := len(h.clients)
	h.mu.RUnlock()
	if remaining != 0 {
		t.Fatalf("expected no remaining clients, got %d", remaining)
	}
}

func TestHub_BroadcastSkipsFullChannel(t *testing.T) {
	h := NewHub()
	client := &Client{send: make(chan []byte, 1)}
	client.send <- []byte("existing")
	h.Register(client)

	h.Broadcast([]byte("new"))

	select {
	case got := <-client.send:
		if string(got) != "existing" {
			t.Fatalf("expected original message to remain queued, got %q", got)
		}
	default:
		t.Fatal("expected queued message to remain available")
	}

	select {
	case got := <-client.send:
		t.Fatalf("unexpected extra broadcast message %q", got)
	default:
	}
}

func TestServerStart_InvalidPort(t *testing.T) {
	srv := NewServer(65536, newTestServer(t).store, NewHub())

	err := srv.Start(context.Background())
	if err == nil {
		t.Fatal("expected Start to fail for an invalid port")
	}
}

func TestServerStart_EmbedUIFailure(t *testing.T) {
	oldSubUIFS := subUIFS
	subUIFS = func(fsys fs.FS, dir string) (fs.FS, error) {
		return nil, errors.New("broken embed")
	}
	t.Cleanup(func() { subUIFS = oldSubUIFS })

	srv := NewServer(0, newTestServer(t).store, NewHub())

	err := srv.Start(context.Background())
	if err == nil || !strings.Contains(err.Error(), "embed ui: broken embed") {
		t.Fatalf("expected embed ui failure, got %v", err)
	}
}

func TestServerStart_ShutsDownCleanlyOnContextCancel(t *testing.T) {
	srv := NewServer(0, newTestServer(t).store, NewHub())

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		done <- srv.Start(ctx)
	}()

	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("expected clean shutdown, got %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for clean server shutdown")
	}
}

func TestHandleTrafficDetail_WithMatchedPair(t *testing.T) {
	srv := newTestServer(t)

	now := time.Now()
	reqID, _ := srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  now,
		Direction:  capture.DirectionClientToServer,
		ServerName: "srv",
		Method:     "tools/call",
		MessageID:  "match-1",
		Payload:    `{"jsonrpc":"2.0","method":"tools/call","id":"match-1"}`,
		Status:     "pending",
	})
	resID, _ := srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  now.Add(10 * time.Millisecond),
		Direction:  capture.DirectionServerToClient,
		ServerName: "srv",
		MessageID:  "match-1",
		Payload:    `{"jsonrpc":"2.0","id":"match-1","result":{}}`,
		Status:     "ok",
		IsResponse: true,
	})

	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/traffic/%d", resID), nil)
	req.SetPathValue("id", fmt.Sprintf("%d", resID))
	w := httptest.NewRecorder()
	srv.handleTrafficDetail(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var result map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	matched, ok := result["matched"]
	if !ok {
		t.Fatal("expected matched entry in response")
	}

	matchedMap, ok := matched.(map[string]interface{})
	if !ok {
		t.Fatalf("expected matched entry map, got %T", matched)
	}
	if got := int64(matchedMap["id"].(float64)); got != reqID {
		t.Fatalf("expected matched id %d, got %d", reqID, got)
	}
}

func TestHandleTraffic_QueryFailure(t *testing.T) {
	srv := newTestServer(t)
	if err := srv.store.Close(); err != nil {
		t.Fatalf("Close store: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/traffic?page=2&page_size=20", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", w.Code)
	}
}

func TestHandleTraffic_ValidPaginationParameters(t *testing.T) {
	srv := newTestServer(t)
	srv.store.Insert(&capture.TrafficEntry{
		Timestamp:  time.Now(),
		Direction:  capture.DirectionClientToServer,
		ServerName: "srv",
		Method:     "list",
		Payload:    `{}`,
		Status:     "pending",
	})

	req := httptest.NewRequest(http.MethodGet, "/api/traffic?page=2&page_size=1", nil)
	w := httptest.NewRecorder()
	srv.handleTraffic(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var page capture.TrafficPage
	if err := json.Unmarshal(w.Body.Bytes(), &page); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if page.Page != 2 || page.PageSize != 1 {
		t.Fatalf("expected page=2 page_size=1, got page=%d size=%d", page.Page, page.PageSize)
	}
}

func TestHandleWebSocket_InvalidUpgradeRequest(t *testing.T) {
	srv := newTestServer(t)

	req := httptest.NewRequest(http.MethodGet, "/ws", nil)
	w := httptest.NewRecorder()
	srv.handleWebSocket(w, req)

	srv.hub.mu.RLock()
	clients := len(srv.hub.clients)
	srv.hub.mu.RUnlock()
	if clients != 0 {
		t.Fatalf("expected no websocket clients to be registered, got %d", clients)
	}
}

func TestHandleToolCall_ReadBodyFailure(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{})

	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", nil)
	req.Body = errReadCloser{err: errors.New("read failed")}
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleToolCall_InvalidRPCResponse(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		sendFunc: func(ctx context.Context, server, method string, params json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`not valid json`), nil
		},
	})

	body := `{"server":"test","tool":"read_file","arguments":{"path":"/tmp/x"}}`
	req := httptest.NewRequest(http.MethodPost, "/api/tools/call", strings.NewReader(body))
	w := httptest.NewRecorder()
	srv.handleToolCall(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected 502, got %d", w.Code)
	}
}

func TestHandleWebSocket_HandshakeBroadcastAndClose(t *testing.T) {
	srv := newTestServer(t)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /ws", srv.handleWebSocket)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("dial websocket: %v", err)
	}
	defer conn.CloseNow()

	deadline := time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client registration")
		}
		time.Sleep(10 * time.Millisecond)
	}

	want := []byte(`{"event":"broadcast"}`)
	srv.hub.Broadcast(want)

	readCtx, readCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer readCancel()

	typ, got, err := conn.Read(readCtx)
	if err != nil {
		t.Fatalf("read websocket message: %v", err)
	}
	if typ != websocket.MessageText {
		t.Fatalf("expected text message, got %v", typ)
	}
	if string(got) != string(want) {
		t.Fatalf("expected %q, got %q", string(want), string(got))
	}

	if err := conn.CloseNow(); err != nil {
		t.Fatalf("close websocket: %v", err)
	}

	deadline = time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client unregister")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestHandleWebSocket_WriterStopsOnContextDone(t *testing.T) {
	srv := newTestServer(t)
	conn := &stubWSConn{}
	oldAcceptWebSocket := acceptWebSocket
	acceptWebSocket = func(w http.ResponseWriter, r *http.Request, opts *websocket.AcceptOptions) (wsConn, error) {
		return conn, nil
	}
	t.Cleanup(func() { acceptWebSocket = oldAcceptWebSocket })

	ctx, cancel := context.WithCancel(context.Background())
	req := httptest.NewRequest(http.MethodGet, "/ws", nil).WithContext(ctx)
	w := httptest.NewRecorder()

	done := make(chan struct{})
	go func() {
		srv.handleWebSocket(w, req)
		close(done)
	}()

	deadline := time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client registration")
		}
		time.Sleep(10 * time.Millisecond)
	}

	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for websocket handler shutdown")
	}
}

func TestHandleWebSocket_WriterStopsOnWriteFailure(t *testing.T) {
	srv := newTestServer(t)
	conn := &stubWSConn{
		writeErr:    errors.New("write failed"),
		writeCalled: make(chan struct{}),
	}
	oldAcceptWebSocket := acceptWebSocket
	acceptWebSocket = func(w http.ResponseWriter, r *http.Request, opts *websocket.AcceptOptions) (wsConn, error) {
		return conn, nil
	}
	t.Cleanup(func() { acceptWebSocket = oldAcceptWebSocket })

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/ws", nil).WithContext(ctx)
	w := httptest.NewRecorder()

	done := make(chan struct{})
	go func() {
		srv.handleWebSocket(w, req)
		close(done)
	}()

	deadline := time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client registration")
		}
		time.Sleep(10 * time.Millisecond)
	}

	srv.hub.Broadcast([]byte(`{"event":"broadcast"}`))

	select {
	case <-conn.writeCalled:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for websocket write attempt")
	}

	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for websocket handler shutdown")
	}
}

func TestHandleWebSocket_WriteFailureOnClosedConnection(t *testing.T) {
	srv := newTestServer(t)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /ws", srv.handleWebSocket)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("dial websocket: %v", err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client registration")
		}
		time.Sleep(10 * time.Millisecond)
	}

	if err := conn.Close(websocket.StatusNormalClosure, "bye"); err != nil {
		t.Fatalf("close websocket: %v", err)
	}

	deadline = time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 0 {
			break
		}
		srv.hub.Broadcast([]byte(`{"event":"after-close"}`))
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client unregister after write failure")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestHandleWebSocket_ClientCloseEventuallyUnregisters(t *testing.T) {
	srv := newTestServer(t)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /ws", srv.handleWebSocket)
	ts := httptest.NewServer(mux)
	t.Cleanup(ts.Close)

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/ws"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	conn, _, err := websocket.Dial(ctx, wsURL, nil)
	if err != nil {
		t.Fatalf("dial websocket: %v", err)
	}

	deadline := time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client registration")
		}
		time.Sleep(10 * time.Millisecond)
	}

	if err := conn.Close(websocket.StatusNormalClosure, "bye"); err != nil {
		t.Fatalf("close websocket: %v", err)
	}

	deadline = time.Now().Add(2 * time.Second)
	for {
		srv.hub.mu.RLock()
		clients := len(srv.hub.clients)
		srv.hub.mu.RUnlock()
		if clients == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for websocket client unregister after server-side close")
		}
		time.Sleep(10 * time.Millisecond)
	}
}
