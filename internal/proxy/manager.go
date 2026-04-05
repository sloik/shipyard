package proxy

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

// Manager holds all running proxies, keyed by server name.
// It enables the web server to send JSON-RPC requests to child servers.
type Manager struct {
	mu      sync.RWMutex
	proxies map[string]*managedProxy
}

type managedProxy struct {
	proxy       *Proxy
	inputWriter *childInputWriter
	responses   *responseTracker
}

// responseTracker correlates JSON-RPC request IDs to response channels.
type responseTracker struct {
	mu      sync.Mutex
	pending map[string]chan json.RawMessage
}

func newResponseTracker() *responseTracker {
	return &responseTracker{
		pending: make(map[string]chan json.RawMessage),
	}
}

func (rt *responseTracker) register(id string) chan json.RawMessage {
	rt.mu.Lock()
	defer rt.mu.Unlock()
	ch := make(chan json.RawMessage, 1)
	rt.pending[id] = ch
	return ch
}

func (rt *responseTracker) resolve(id string, raw json.RawMessage) bool {
	rt.mu.Lock()
	defer rt.mu.Unlock()
	ch, ok := rt.pending[id]
	if !ok {
		return false
	}
	ch <- raw
	delete(rt.pending, id)
	return true
}

func (rt *responseTracker) cancel(id string) {
	rt.mu.Lock()
	defer rt.mu.Unlock()
	delete(rt.pending, id)
}

// NewManager creates a new proxy manager.
func NewManager() *Manager {
	return &Manager{
		proxies: make(map[string]*managedProxy),
	}
}

// Register adds a proxy to the manager. Must be called before the proxy's Run.
func (m *Manager) Register(name string, p *Proxy) *managedProxy {
	m.mu.Lock()
	defer m.mu.Unlock()

	mp := &managedProxy{
		proxy:     p,
		responses: newResponseTracker(),
	}
	m.proxies[name] = mp
	return mp
}

// Servers returns info about all registered servers.
func (m *Manager) Servers() []web.ServerInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := make([]web.ServerInfo, 0, len(m.proxies))
	for name := range m.proxies {
		result = append(result, web.ServerInfo{
			Name:   name,
			Status: "online", // TODO: track actual status per proxy lifecycle
		})
	}
	return result
}

var requestIDCounter int64

// SendRequest sends a JSON-RPC request to a child server and waits for the response.
func (m *Manager) SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error) {
	m.mu.RLock()
	mp, ok := m.proxies[serverName]
	m.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("server %q not found", serverName)
	}

	// Generate a unique request ID
	id := atomic.AddInt64(&requestIDCounter, 1)
	idStr := fmt.Sprintf("shipyard-%d", id)

	// Build JSON-RPC request
	req := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      idStr,
		"method":  method,
		"params":  params,
	}
	reqBytes, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	// Register for response before sending
	ch := mp.responses.register(idStr)
	defer mp.responses.cancel(idStr)

	// Write to child stdin
	if mp.inputWriter == nil {
		return nil, fmt.Errorf("server %q has no input writer attached", serverName)
	}
	if err := mp.inputWriter.writeLine(ctx, reqBytes); err != nil {
		return nil, fmt.Errorf("write to child: %w", err)
	}

	// Capture the outgoing request in the traffic timeline (AC-5)
	go mp.proxy.captureMessage(reqBytes, capture.DirectionClientToServer, time.Now())

	// Wait for response with timeout
	timeout := 30 * time.Second
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	select {
	case raw := <-ch:
		return raw, nil
	case <-timer.C:
		return nil, fmt.Errorf("timeout waiting for response from %q after %s", serverName, timeout)
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

// SetInputWriter sets the child input writer for a managed proxy.
// Called from the proxy's Run method.
func (mp *managedProxy) SetInputWriter(w *childInputWriter) {
	mp.inputWriter = w
}

// HandleChildOutput should be called for every line read from the child's stdout.
// It checks if the line is a response to a pending request.
func (mp *managedProxy) HandleChildOutput(line []byte) bool {
	var msg struct {
		ID     json.RawMessage `json:"id,omitempty"`
		Result json.RawMessage `json:"result,omitempty"`
		Error  json.RawMessage `json:"error,omitempty"`
	}
	if err := json.Unmarshal(line, &msg); err != nil {
		return false
	}

	// Only responses have result or error
	if msg.Result == nil && msg.Error == nil {
		return false
	}
	if msg.ID == nil {
		return false
	}

	idStr := string(msg.ID)
	// Strip quotes from string IDs
	if len(idStr) > 1 && idStr[0] == '"' {
		idStr = idStr[1 : len(idStr)-1]
	}

	return mp.responses.resolve(idStr, line)
}
