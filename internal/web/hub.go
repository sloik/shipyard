package web

import (
	"context"
	"sync"

	"github.com/coder/websocket"
)

// Client represents a connected WebSocket client.
type Client struct {
	conn *websocket.Conn
	send chan []byte
}

// Hub manages WebSocket client connections and broadcasts messages.
type Hub struct {
	mu      sync.RWMutex
	clients map[*Client]bool
}

// NewHub creates a new WebSocket hub.
func NewHub() *Hub {
	return &Hub{
		clients: make(map[*Client]bool),
	}
}

// Run keeps the hub alive until the context is cancelled.
func (h *Hub) Run(ctx context.Context) {
	<-ctx.Done()
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		close(c.send)
		delete(h.clients, c)
	}
}

// Register adds a client to the hub.
func (h *Hub) Register(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c] = true
}

// Unregister removes a client from the hub.
func (h *Hub) Unregister(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.clients[c]; ok {
		close(c.send)
		delete(h.clients, c)
	}
}

// Broadcast sends a message to all connected clients.
func (h *Hub) Broadcast(msg []byte) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for c := range h.clients {
		select {
		case c.send <- msg:
		default:
			// Client too slow, skip
		}
	}
}
