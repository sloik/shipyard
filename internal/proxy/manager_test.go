package proxy

import (
	"encoding/json"
	"sync"
	"testing"
)

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
