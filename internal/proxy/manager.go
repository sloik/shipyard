package proxy

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/web"
)

// Manager holds all running proxies, keyed by server name.
// It enables the web server to send JSON-RPC requests to child servers.
type Manager struct {
	mu             sync.RWMutex
	proxies        map[string]*managedProxy
	hub            *web.Hub         // for broadcasting status changes
	activeSessions map[string]int64 // server name → session ID
}

type managedProxy struct {
	proxy        *Proxy
	inputWriter  *childInputWriter
	responses    *responseTracker
	status       string             // "online", "crashed", "stopped", "restarting"
	command      string             // the command string for display
	startedAt    time.Time          // when the proxy was last started
	restartCount int                // how many times it has been restarted
	toolCount    int                // cached tool count
	errorMessage string             // last error message if crashed
	cancelFn     context.CancelFunc // cancel function for stopping the proxy
	initMu       sync.Mutex
	initReady    bool
	initRunning  bool
	initWait     chan struct{}
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
		proxies:        make(map[string]*managedProxy),
		activeSessions: make(map[string]int64),
	}
}

// SetHub sets the WebSocket hub for broadcasting status updates.
func (m *Manager) SetHub(hub *web.Hub) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.hub = hub
}

// Register adds a proxy to the manager. Must be called before the proxy's Run.
func (m *Manager) Register(name string, p *Proxy) *managedProxy {
	m.mu.Lock()
	defer m.mu.Unlock()

	cmd := p.command
	if len(p.args) > 0 {
		cmd += " " + strings.Join(p.args, " ")
	}

	mp := &managedProxy{
		proxy:     p,
		responses: newResponseTracker(),
		status:    "online",
		command:   cmd,
		startedAt: time.Now(),
	}
	m.proxies[name] = mp
	return mp
}

// Servers returns info about all registered servers.
func (m *Manager) Servers() []web.ServerInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := make([]web.ServerInfo, 0, len(m.proxies))
	for name, mp := range m.proxies {
		uptime := int64(0)
		if mp.status == "online" && !mp.startedAt.IsZero() {
			uptime = time.Since(mp.startedAt).Milliseconds()
		}
		result = append(result, web.ServerInfo{
			Name:         name,
			Status:       mp.status,
			Command:      mp.command,
			ToolCount:    mp.toolCount,
			Uptime:       uptime,
			RestartCount: mp.restartCount,
			ErrorMessage: mp.errorMessage,
		})
	}
	return result
}

// SetStatus updates the status of a managed proxy and broadcasts via WebSocket.
func (m *Manager) SetStatus(name, status, errorMsg string) {
	m.mu.Lock()
	mp, ok := m.proxies[name]
	if !ok {
		m.mu.Unlock()
		return
	}
	mp.status = status
	mp.errorMessage = errorMsg
	if status == "online" {
		mp.startedAt = time.Now()
	}
	hub := m.hub
	m.mu.Unlock()

	// Broadcast status change
	if hub != nil {
		evt := map[string]interface{}{
			"type":   "server_status",
			"server": name,
			"status": status,
		}
		if errorMsg != "" {
			evt["error"] = errorMsg
		}
		data, _ := json.Marshal(evt)
		hub.Broadcast(data)
	}
}

// SetToolCount updates the cached tool count for a server.
func (m *Manager) SetToolCount(name string, count int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if mp, ok := m.proxies[name]; ok {
		mp.toolCount = count
	}
}

// SetCancelFn stores the context cancel function for a server's proxy goroutine.
func (m *Manager) SetCancelFn(name string, cancel context.CancelFunc) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if mp, ok := m.proxies[name]; ok {
		mp.cancelFn = cancel
	}
}

// RestartServer stops and restarts a specific server.
func (m *Manager) RestartServer(name string) error {
	m.mu.Lock()
	mp, ok := m.proxies[name]
	if !ok {
		m.mu.Unlock()
		return fmt.Errorf("server %q not found", name)
	}
	cancel := mp.cancelFn
	mp.status = "restarting"
	mp.restartCount++
	mp.errorMessage = ""
	m.mu.Unlock()

	// Broadcast restarting status
	m.SetStatus(name, "restarting", "")

	// Cancel the running proxy — the run loop in main.go will detect this
	// and restart the proxy.
	if cancel != nil {
		cancel()
	}

	return nil
}

// StopServer stops a specific server.
func (m *Manager) StopServer(name string) error {
	m.mu.Lock()
	mp, ok := m.proxies[name]
	if !ok {
		m.mu.Unlock()
		return fmt.Errorf("server %q not found", name)
	}
	cancel := mp.cancelFn
	mp.status = "stopped"
	mp.errorMessage = ""
	m.mu.Unlock()

	m.SetStatus(name, "stopped", "")

	if cancel != nil {
		cancel()
	}

	return nil
}

// ServerStatus returns the status of a specific server.
func (m *Manager) ServerStatus(name string) string {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if mp, ok := m.proxies[name]; ok {
		return mp.status
	}
	return ""
}

// StartRecording begins recording traffic for a server.
func (m *Manager) StartRecording(server string, sessionID int64) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.activeSessions[server] = sessionID
}

// StopRecording stops recording traffic for a server.
func (m *Manager) StopRecording(server string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.activeSessions, server)
}

// ActiveSessionID returns the active session ID for a server, or 0 if not recording.
func (m *Manager) ActiveSessionID(server string) int64 {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.activeSessions[server]
}

var requestIDCounter int64
var requestTimeout = 30 * time.Second
var marshalRequest = json.Marshal

const managedChildProtocolVersion = "2025-03-26"

// SendRequest sends a JSON-RPC request to a child server and waits for the response.
func (m *Manager) SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error) {
	m.mu.RLock()
	mp, ok := m.proxies[serverName]
	m.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("server %q not found", serverName)
	}

	if method != "initialize" && method != "notifications/initialized" {
		if err := m.ensureInitialized(ctx, serverName, mp); err != nil {
			return nil, err
		}
	}

	return m.sendRequestRaw(ctx, serverName, mp, method, params)
}

func (m *Manager) sendRequestRaw(ctx context.Context, serverName string, mp *managedProxy, method string, params json.RawMessage) (json.RawMessage, error) {
	if len(params) == 0 {
		params = json.RawMessage("{}")
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
	reqBytes, err := marshalRequest(req)
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
	timeout := requestTimeout
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	select {
	case raw := <-ch:
		if method == "tools/list" {
			m.updateToolCountFromResponse(serverName, raw)
		}
		return raw, nil
	case <-timer.C:
		return nil, fmt.Errorf("timeout waiting for response from %q after %s", serverName, timeout)
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}

func (m *Manager) ensureInitialized(ctx context.Context, serverName string, mp *managedProxy) error {
	for {
		mp.initMu.Lock()
		if mp.initReady {
			mp.initMu.Unlock()
			return nil
		}
		if mp.initRunning {
			wait := mp.initWait
			mp.initMu.Unlock()

			select {
			case <-wait:
				if ctx.Err() != nil {
					return ctx.Err()
				}
				continue
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		wait := make(chan struct{})
		mp.initRunning = true
		mp.initWait = wait
		mp.initMu.Unlock()

		err := m.initializeChildSession(ctx, serverName, mp)

		mp.initMu.Lock()
		if err == nil {
			mp.initReady = true
		}
		mp.initRunning = false
		close(wait)
		mp.initWait = nil
		mp.initMu.Unlock()

		return err
	}
}

func (m *Manager) initializeChildSession(ctx context.Context, serverName string, mp *managedProxy) error {
	initParams := map[string]interface{}{
		"protocolVersion": managedChildProtocolVersion,
		"capabilities":    map[string]interface{}{},
		"clientInfo": map[string]interface{}{
			"name":    "shipyard",
			"version": "dev",
		},
	}
	paramsBytes, err := marshalRequest(initParams)
	if err != nil {
		return fmt.Errorf("marshal initialize params: %w", err)
	}

	raw, err := m.sendRequestRaw(ctx, serverName, mp, "initialize", json.RawMessage(paramsBytes))
	if err != nil {
		return fmt.Errorf("initialize %q: %w", serverName, err)
	}

	var rpcResp struct {
		Error json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(raw, &rpcResp); err != nil {
		return fmt.Errorf("parse initialize response from %q: %w", serverName, err)
	}
	if rpcResp.Error != nil {
		return fmt.Errorf("initialize %q returned error: %s", serverName, string(rpcResp.Error))
	}

	if err := m.sendNotificationRaw(ctx, serverName, mp, "notifications/initialized", json.RawMessage("{}")); err != nil {
		return fmt.Errorf("notifications/initialized %q: %w", serverName, err)
	}

	return nil
}

func (m *Manager) sendNotificationRaw(ctx context.Context, serverName string, mp *managedProxy, method string, params json.RawMessage) error {
	if len(params) == 0 {
		params = json.RawMessage("{}")
	}

	req := map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  method,
		"params":  params,
	}
	reqBytes, err := marshalRequest(req)
	if err != nil {
		return fmt.Errorf("marshal notification: %w", err)
	}
	if mp.inputWriter == nil {
		return fmt.Errorf("server %q has no input writer attached", serverName)
	}
	if err := mp.inputWriter.writeLine(ctx, reqBytes); err != nil {
		return fmt.Errorf("write to child: %w", err)
	}

	go mp.proxy.captureMessage(reqBytes, capture.DirectionClientToServer, time.Now())
	return nil
}

func (m *Manager) updateToolCountFromResponse(serverName string, raw json.RawMessage) {
	var rpcResp struct {
		Result struct {
			Tools []json.RawMessage `json:"tools"`
		} `json:"result"`
	}
	if err := json.Unmarshal(raw, &rpcResp); err != nil {
		return
	}

	m.SetToolCount(serverName, len(rpcResp.Result.Tools))
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

// StartSchemaWatcher polls all online servers for tools/list and detects schema changes.
// It captures a baseline on startup, then polls at the given interval.
// It blocks until ctx is cancelled.
func (m *Manager) StartSchemaWatcher(ctx context.Context, store *capture.Store, interval time.Duration) {
	// Initial baseline capture
	m.captureAllSchemas(ctx, store)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			m.checkSchemaChanges(ctx, store)
		}
	}
}

// captureAllSchemas captures a baseline snapshot for each online server.
func (m *Manager) captureAllSchemas(ctx context.Context, store *capture.Store) {
	m.mu.RLock()
	var names []string
	for name, mp := range m.proxies {
		if mp.status == "online" {
			names = append(names, name)
		}
	}
	m.mu.RUnlock()

	for _, name := range names {
		tools, err := m.fetchToolsList(ctx, name)
		if err != nil {
			slog.Warn("schema baseline: failed to fetch tools/list", "server", name, "error", err)
			continue
		}
		if _, err := store.SaveSnapshot(name, tools); err != nil {
			slog.Warn("schema baseline: failed to save snapshot", "server", name, "error", err)
		} else {
			slog.Info("schema baseline captured", "server", name, "tools", len(tools))
		}
	}
}

// checkSchemaChanges polls all online servers and compares to last snapshot.
func (m *Manager) checkSchemaChanges(ctx context.Context, store *capture.Store) {
	m.mu.RLock()
	var names []string
	for name, mp := range m.proxies {
		if mp.status == "online" {
			names = append(names, name)
		}
	}
	m.mu.RUnlock()

	for _, name := range names {
		tools, err := m.fetchToolsList(ctx, name)
		if err != nil {
			slog.Debug("schema poll: failed to fetch tools/list", "server", name, "error", err)
			continue
		}

		// Get last snapshot
		lastTools, lastID, err := store.GetLatestSnapshot(name)
		if err != nil {
			slog.Warn("schema poll: failed to get snapshot", "server", name, "error", err)
			continue
		}

		// If no previous snapshot, this is a baseline
		if lastTools == nil {
			if _, err := store.SaveSnapshot(name, tools); err != nil {
				slog.Warn("schema poll: failed to save baseline", "server", name, "error", err)
			}
			continue
		}

		// Compare
		diff := capture.DiffSchemas(lastTools, tools)
		if diff.IsEmpty() {
			continue
		}

		// Save new snapshot
		newID, err := store.SaveSnapshot(name, tools)
		if err != nil {
			slog.Warn("schema poll: failed to save new snapshot", "server", name, "error", err)
			continue
		}

		// Insert change record
		changeID, err := store.InsertSchemaChange(name, diff, lastID, newID)
		if err != nil {
			slog.Warn("schema poll: failed to insert change", "server", name, "error", err)
			continue
		}

		slog.Info("schema change detected",
			"server", name,
			"added", len(diff.Added),
			"removed", len(diff.Removed),
			"modified", len(diff.Modified),
			"change_id", changeID,
		)

		// Broadcast WS event
		m.mu.RLock()
		hub := m.hub
		m.mu.RUnlock()

		if hub != nil {
			evt := map[string]interface{}{
				"type":      "schema_change",
				"server":    name,
				"added":     len(diff.Added),
				"removed":   len(diff.Removed),
				"modified":  len(diff.Modified),
				"change_id": changeID,
			}
			data, _ := json.Marshal(evt)
			hub.Broadcast(data)
		}
	}
}

// fetchToolsList calls tools/list on a server with a 5s timeout and parses the response.
func (m *Manager) fetchToolsList(ctx context.Context, serverName string) ([]capture.ToolSchema, error) {
	callCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	raw, err := m.SendRequest(callCtx, serverName, "tools/list", nil)
	if err != nil {
		return nil, err
	}

	// Parse JSON-RPC response envelope
	var rpcResp struct {
		Result struct {
			Tools []capture.ToolSchema `json:"tools"`
		} `json:"result"`
	}
	if err := json.Unmarshal(raw, &rpcResp); err != nil {
		return nil, fmt.Errorf("parse tools/list response: %w", err)
	}

	return rpcResp.Result.Tools, nil
}
