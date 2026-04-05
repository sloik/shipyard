package web

import (
	"testing"
)

func TestNewHub(t *testing.T) {
	h := NewHub()
	if h == nil {
		t.Fatal("expected non-nil hub")
	}
	if h.clients == nil {
		t.Fatal("expected non-nil clients map")
	}
	if len(h.clients) != 0 {
		t.Fatalf("expected empty clients map, got %d", len(h.clients))
	}
}

func TestHub_RegisterUnregister(t *testing.T) {
	h := NewHub()

	client := &Client{
		send: make(chan []byte, 256),
	}

	h.Register(client)

	h.mu.RLock()
	if _, ok := h.clients[client]; !ok {
		h.mu.RUnlock()
		t.Fatal("expected client to be registered")
	}
	h.mu.RUnlock()

	h.Unregister(client)

	h.mu.RLock()
	if _, ok := h.clients[client]; ok {
		h.mu.RUnlock()
		t.Fatal("expected client to be unregistered")
	}
	h.mu.RUnlock()

	// Double unregister should not panic
	h.Unregister(client)
}

func TestHub_Broadcast(t *testing.T) {
	h := NewHub()

	c1 := &Client{send: make(chan []byte, 256)}
	c2 := &Client{send: make(chan []byte, 256)}

	h.Register(c1)
	h.Register(c2)

	msg := []byte(`{"event":"test"}`)
	h.Broadcast(msg)

	select {
	case got := <-c1.send:
		if string(got) != string(msg) {
			t.Fatalf("c1: expected %s, got %s", string(msg), string(got))
		}
	default:
		t.Fatal("c1: expected message from broadcast")
	}

	select {
	case got := <-c2.send:
		if string(got) != string(msg) {
			t.Fatalf("c2: expected %s, got %s", string(msg), string(got))
		}
	default:
		t.Fatal("c2: expected message from broadcast")
	}

	// After unregistering c1, only c2 should get messages
	h.Unregister(c1)
	msg2 := []byte(`{"event":"second"}`)
	h.Broadcast(msg2)

	select {
	case got := <-c2.send:
		if string(got) != string(msg2) {
			t.Fatalf("c2: expected %s, got %s", string(msg2), string(got))
		}
	default:
		t.Fatal("c2: expected message from second broadcast")
	}
}
