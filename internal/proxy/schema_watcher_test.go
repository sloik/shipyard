package proxy

// SPEC-006-003: Schema Change Detection — poller tests
//
// These tests cover:
//   AC 1: polling interval and change detection
//   AC 7: WebSocket push on schema change
//   AC 9: schema change events detected between polls

import (
	"context"
	"encoding/json"
	"sync"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

// toolListFakeWriter intercepts JSON-RPC requests written to the child stdin
// and resolves tools/list requests directly via the manager's response tracker.
type toolListFakeWriter struct {
	manager    *Manager
	serverName string
	toolListFn func() []capture.ToolSchema
}

func (w *toolListFakeWriter) Write(p []byte) (int, error) {
	var req struct {
		ID     json.RawMessage `json:"id"`
		Method string          `json:"method"`
	}
	if err := json.Unmarshal(p, &req); err != nil {
		return len(p), nil // not JSON (e.g. trailing newline written separately)
	}
	if req.Method != "tools/list" {
		return len(p), nil
	}

	tools := w.toolListFn()
	resp := struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  struct {
			Tools []capture.ToolSchema `json:"tools"`
		} `json:"result"`
	}{
		JSONRPC: "2.0",
		ID:      req.ID,
	}
	resp.Result.Tools = tools
	raw, _ := json.Marshal(resp)

	w.manager.mu.RLock()
	mp, ok := w.manager.proxies[w.serverName]
	w.manager.mu.RUnlock()
	if !ok {
		return len(p), nil
	}

	idStr := string(req.ID)
	if len(idStr) > 1 && idStr[0] == '"' {
		idStr = idStr[1 : len(idStr)-1]
	}
	mp.responses.resolve(idStr, raw)
	return len(p), nil
}

func (w *toolListFakeWriter) Close() error { return nil }

// registerFakeSchemaServer adds a managedProxy to the manager with a fake
// tools/list responder. initReady is set to skip the MCP initialization handshake.
// store is passed in so the proxy's internal captureMessage calls don't panic.
func registerFakeSchemaServer(m *Manager, name string, store *capture.Store, toolsFn func() []capture.ToolSchema) {
	inputWriter := newChildInputWriter()
	mp := &managedProxy{
		proxy:       &Proxy{name: name, store: store, hub: web.NewHub()},
		inputWriter: inputWriter,
		responses:   newResponseTracker(),
		status:      "online",
		command:     "fake",
		startedAt:   time.Now(),
		initReady:   true,
	}
	m.mu.Lock()
	m.proxies[name] = mp
	m.mu.Unlock()

	inputWriter.attach(&toolListFakeWriter{
		manager:    m,
		serverName: name,
		toolListFn: toolsFn,
	})
}

// TestSchemaWatcher_CapturesBaseline verifies that captureAllSchemas saves a
// baseline snapshot for each online server (AC 1).
func TestSchemaWatcher_CapturesBaseline(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	tools := []capture.ToolSchema{
		{Name: "tool_a", Description: "Tool A"},
		{Name: "tool_b", Description: "Tool B"},
	}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema { return tools })

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)

	got, id, err := store.GetLatestSnapshot("alpha")
	if err != nil {
		t.Fatalf("GetLatestSnapshot: %v", err)
	}
	if id == 0 {
		t.Fatal("expected snapshot ID > 0 after baseline capture")
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 tools in baseline, got %d", len(got))
	}
}

// TestSchemaWatcher_DetectsAddedTools verifies that a new tool is detected and
// a change event recorded (AC 1, AC 9).
func TestSchemaWatcher_DetectsAddedTools(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	var mu sync.Mutex
	currentTools := []capture.ToolSchema{{Name: "tool_a"}}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema {
		mu.Lock()
		defer mu.Unlock()
		return currentTools
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)

	mu.Lock()
	currentTools = append(currentTools, capture.ToolSchema{Name: "tool_b"})
	mu.Unlock()

	m.checkSchemaChanges(ctx, store)

	changes, err := store.ListSchemaChanges("")
	if err != nil {
		t.Fatalf("ListSchemaChanges: %v", err)
	}
	if len(changes) != 1 {
		t.Fatalf("expected 1 schema change event, got %d", len(changes))
	}
	if changes[0].ToolsAdded != 1 {
		t.Fatalf("expected 1 added tool, got %d", changes[0].ToolsAdded)
	}
	if changes[0].ToolsRemoved != 0 {
		t.Fatalf("expected 0 removed tools, got %d", changes[0].ToolsRemoved)
	}
	if changes[0].ServerName != "alpha" {
		t.Fatalf("expected server 'alpha', got %q", changes[0].ServerName)
	}
}

// TestSchemaWatcher_DetectsRemovedTools verifies removal detection (AC 9).
func TestSchemaWatcher_DetectsRemovedTools(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	var mu sync.Mutex
	currentTools := []capture.ToolSchema{
		{Name: "tool_a"},
		{Name: "tool_b"},
	}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema {
		mu.Lock()
		defer mu.Unlock()
		return currentTools
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)

	mu.Lock()
	currentTools = []capture.ToolSchema{{Name: "tool_a"}}
	mu.Unlock()

	m.checkSchemaChanges(ctx, store)

	changes, err := store.ListSchemaChanges("")
	if err != nil {
		t.Fatalf("ListSchemaChanges: %v", err)
	}
	if len(changes) != 1 {
		t.Fatalf("expected 1 change event, got %d", len(changes))
	}
	if changes[0].ToolsRemoved != 1 {
		t.Fatalf("expected 1 removed tool, got %d", changes[0].ToolsRemoved)
	}
}

// TestSchemaWatcher_NoChangeNoEvent verifies no event when schema is unchanged (AC 1).
func TestSchemaWatcher_NoChangeNoEvent(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	tools := []capture.ToolSchema{{Name: "tool_a"}}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema { return tools })

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)
	m.checkSchemaChanges(ctx, store)

	changes, err := store.ListSchemaChanges("")
	if err != nil {
		t.Fatalf("ListSchemaChanges: %v", err)
	}
	if len(changes) != 0 {
		t.Fatalf("expected 0 change events for unchanged schema, got %d", len(changes))
	}
}

// TestSchemaWatcher_BroadcastsWebSocketEvent verifies that a schema change
// is broadcast via the hub WebSocket (AC 7).
func TestSchemaWatcher_BroadcastsWebSocketEvent(t *testing.T) {
	store := newSchemaTestStore(t)
	hub := web.NewHub()
	m := NewManager()
	m.SetHub(hub)

	// Subscribe to hub broadcasts
	recv := hub.Subscribe()
	defer hub.Unsubscribe(recv)

	var mu sync.Mutex
	currentTools := []capture.ToolSchema{{Name: "tool_a"}}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema {
		mu.Lock()
		defer mu.Unlock()
		return currentTools
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)

	mu.Lock()
	currentTools = append(currentTools, capture.ToolSchema{Name: "tool_b"})
	mu.Unlock()

	m.checkSchemaChanges(ctx, store)

	// Drain messages, looking for the schema_change event
	deadline := time.After(2 * time.Second)
	for {
		select {
		case msg := <-recv:
			var evt map[string]interface{}
			if err := json.Unmarshal(msg, &evt); err != nil {
				continue // skip non-JSON
			}
			if evt["type"] != "schema_change" {
				continue // skip other event types (e.g. server_status)
			}
			if evt["server"] != "alpha" {
				t.Fatalf("expected server 'alpha', got %v", evt["server"])
			}
			added, _ := evt["added"].(float64)
			if int(added) != 1 {
				t.Fatalf("expected 1 added tool in broadcast, got %v", evt["added"])
			}
			return // test passed
		case <-deadline:
			t.Fatal("timed out waiting for schema_change WebSocket broadcast")
		}
	}
}

// TestSchemaWatcher_MultipleServersIndependent verifies that changes in one
// server do not generate events for others (Scenario 5).
func TestSchemaWatcher_MultipleServersIndependent(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	var muA sync.Mutex
	toolsA := []capture.ToolSchema{{Name: "a_tool"}}
	toolsB := []capture.ToolSchema{{Name: "b_tool"}}

	registerFakeSchemaServer(m, "server-a", store, func() []capture.ToolSchema {
		muA.Lock()
		defer muA.Unlock()
		return toolsA
	})
	registerFakeSchemaServer(m, "server-b", store, func() []capture.ToolSchema { return toolsB })

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	m.captureAllSchemas(ctx, store)

	muA.Lock()
	toolsA = append(toolsA, capture.ToolSchema{Name: "a_tool_2"})
	muA.Unlock()

	m.checkSchemaChanges(ctx, store)

	changesA, _ := store.ListSchemaChanges("server-a")
	changesB, _ := store.ListSchemaChanges("server-b")

	if len(changesA) != 1 {
		t.Fatalf("expected 1 change for server-a, got %d", len(changesA))
	}
	if len(changesB) != 0 {
		t.Fatalf("expected 0 changes for server-b, got %d", len(changesB))
	}
}

// TestSchemaWatcher_FirstPollSavesBaseline verifies that if there is no snapshot
// yet, the first checkSchemaChanges call saves a baseline without a change event.
func TestSchemaWatcher_FirstPollSavesBaseline(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())

	tools := []capture.ToolSchema{{Name: "tool_a"}}
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema { return tools })

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Skip captureAllSchemas — call checkSchemaChanges on empty store
	m.checkSchemaChanges(ctx, store)

	got, id, err := store.GetLatestSnapshot("alpha")
	if err != nil {
		t.Fatalf("GetLatestSnapshot: %v", err)
	}
	if id == 0 {
		t.Fatal("expected snapshot to be saved as baseline on first poll")
	}
	if len(got) != 1 || got[0].Name != "tool_a" {
		t.Fatalf("unexpected baseline tools: %v", got)
	}

	changes, _ := store.ListSchemaChanges("")
	if len(changes) != 0 {
		t.Fatalf("expected 0 change events after baseline-only poll, got %d", len(changes))
	}
}

// TestSchemaWatcher_StopsOnContextCancel verifies the watcher goroutine exits
// when the context is cancelled (AC 1: must respect cancellation for shutdown).
func TestSchemaWatcher_StopsOnContextCancel(t *testing.T) {
	store := newSchemaTestStore(t)
	m := NewManager()
	m.SetHub(web.NewHub())
	registerFakeSchemaServer(m, "alpha", store, func() []capture.ToolSchema {
		return []capture.ToolSchema{{Name: "tool_a"}}
	})

	ctx, cancel := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		defer close(done)
		// Very long interval so the watcher blocks on the ticker
		m.StartSchemaWatcher(ctx, store, 10*time.Minute)
	}()

	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case <-done:
		// watcher exited as expected
	case <-time.After(2 * time.Second):
		t.Fatal("StartSchemaWatcher did not exit after context cancellation")
	}
}

// newSchemaTestStore creates an ephemeral capture.Store backed by t.TempDir().
func newSchemaTestStore(t *testing.T) *capture.Store {
	t.Helper()
	dir := t.TempDir()
	s, err := capture.NewStore(
		dir+"/schema.db",
		dir+"/schema.jsonl",
	)
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}
