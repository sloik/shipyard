package proxy

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

// newTestProxy creates a Proxy with a real Store and Hub for testing captureMessage.
func newTestProxy(t *testing.T) (*Proxy, *capture.Store) {
	t.Helper()
	dir := t.TempDir()
	store, err := capture.NewStore(
		filepath.Join(dir, "test.db"),
		filepath.Join(dir, "test.jsonl"),
	)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })

	hub := web.NewHub()
	p := NewProxy("test-server", "echo", nil, nil, "", store, hub)
	return p, store
}

// lastEvent queries the store for the most recent traffic event.
func lastEvent(t *testing.T, store *capture.Store) capture.TrafficEvent {
	t.Helper()
	page, err := store.Query(1, 1, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if len(page.Items) == 0 {
		t.Fatal("no events in store")
	}
	return page.Items[0]
}

func TestCaptureMessage_RequestStatus(t *testing.T) {
	p, store := newTestProxy(t)

	// A JSON-RPC request (has method, no result/error)
	msg := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())

	evt := lastEvent(t, store)
	if evt.Status != "pending" {
		t.Fatalf("expected status 'pending' for request, got '%s'", evt.Status)
	}
	if evt.Method != "tools/list" {
		t.Fatalf("expected method 'tools/list', got '%s'", evt.Method)
	}
}

func TestCaptureMessage_SuccessResponseStatus(t *testing.T) {
	p, store := newTestProxy(t)

	msg := `{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}`
	p.captureMessage([]byte(msg), capture.DirectionServerToClient, time.Now())

	evt := lastEvent(t, store)
	if evt.Status != "ok" {
		t.Fatalf("expected status 'ok' for success response, got '%s'", evt.Status)
	}
}

func TestCaptureMessage_ErrorResponseStatus(t *testing.T) {
	p, store := newTestProxy(t)

	msg := `{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"method not found"}}`
	p.captureMessage([]byte(msg), capture.DirectionServerToClient, time.Now())

	evt := lastEvent(t, store)
	if evt.Status != "error" {
		t.Fatalf("expected status 'error' for error response, got '%s'", evt.Status)
	}
}

func TestCaptureMessage_NotificationStatus(t *testing.T) {
	p, store := newTestProxy(t)

	// Notification: has method, no id, no result/error
	msg := `{"jsonrpc":"2.0","method":"notifications/initialized"}`
	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())

	evt := lastEvent(t, store)
	// Notifications are requests without an ID — status should be "pending"
	if evt.Status != "pending" {
		t.Fatalf("expected status 'pending' for notification, got '%s'", evt.Status)
	}
}

func TestCaptureMessage_DirectionPreserved(t *testing.T) {
	p, store := newTestProxy(t)

	msg := `{"jsonrpc":"2.0","method":"tools/list","id":1}`

	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())
	evt := lastEvent(t, store)
	if evt.Direction != capture.DirectionClientToServer {
		t.Fatalf("expected direction '%s', got '%s'", capture.DirectionClientToServer, evt.Direction)
	}
}

func TestCaptureMessage_InvalidJSON(t *testing.T) {
	p, store := newTestProxy(t)

	// Non-JSON message should be silently skipped
	p.captureMessage([]byte("not json"), capture.DirectionClientToServer, time.Now())

	page, err := store.Query(1, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 0 {
		t.Fatalf("expected 0 events for invalid JSON, got %d", page.TotalCount)
	}
}

// TestCaptureMessage_TagsSessionIDWhenRecording verifies that when sessionIDFn
// returns a non-zero ID, captureMessage inserts traffic tagged with that session.
func TestCaptureMessage_TagsSessionIDWhenRecording(t *testing.T) {
	p, store := newTestProxy(t)

	// Start a recording session in the store
	sessionID, err := store.StartSession("test-recording", "test-server")
	if err != nil {
		t.Fatalf("StartSession: %v", err)
	}

	// Attach the session ID function
	p.SetSessionIDFn(func() int64 { return sessionID })

	msg := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())

	// Export the session — should contain the captured message
	cassette, err := store.ExportSession(sessionID)
	if err != nil {
		t.Fatalf("ExportSession: %v", err)
	}
	if len(cassette.Requests) == 0 {
		t.Fatal("expected session to contain at least one captured request")
	}
}

// TestCaptureMessage_NoSessionTagWhenIdle verifies that when sessionIDFn returns
// 0, traffic is inserted without a session tag (normal capture path).
func TestCaptureMessage_NoSessionTagWhenIdle(t *testing.T) {
	p, store := newTestProxy(t)

	// sessionIDFn returns 0 — no active recording
	p.SetSessionIDFn(func() int64 { return 0 })

	msg := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())

	// Traffic should exist in store
	evt := lastEvent(t, store)
	if evt.Method != "tools/list" {
		t.Fatalf("expected method 'tools/list', got '%s'", evt.Method)
	}
}

// TestCaptureMessage_NilSessionIDFn verifies that captureMessage works correctly
// when no sessionIDFn is set (default behavior, no session tracking).
func TestCaptureMessage_NilSessionIDFn(t *testing.T) {
	p, store := newTestProxy(t)
	// No SetSessionIDFn call — sessionIDFn is nil

	msg := `{"jsonrpc":"2.0","method":"tools/list","id":1}`
	p.captureMessage([]byte(msg), capture.DirectionClientToServer, time.Now())

	evt := lastEvent(t, store)
	if evt.Status != "pending" {
		t.Fatalf("expected status 'pending', got '%s'", evt.Status)
	}
}

func TestCaptureMessage_StatusNeverRequest(t *testing.T) {
	// SPEC-BUG-006 AC-4: status must never be "request" - it should be "pending"
	p, store := newTestProxy(t)

	// Insert various message types and verify none produce "request" status
	messages := []struct {
		name      string
		msg       string
		direction string
		wantNot   string
	}{
		{
			"request with method",
			`{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"read"}}`,
			capture.DirectionClientToServer,
			"request",
		},
		{
			"notification",
			`{"jsonrpc":"2.0","method":"notifications/initialized"}`,
			capture.DirectionClientToServer,
			"request",
		},
	}

	for _, tc := range messages {
		p.captureMessage([]byte(tc.msg), tc.direction, time.Now())
		evt := lastEvent(t, store)
		if evt.Status == tc.wantNot {
			t.Fatalf("%s: status must not be '%s'", tc.name, tc.wantNot)
		}
	}
}
