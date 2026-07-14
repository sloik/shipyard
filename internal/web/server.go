package web

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"os"
	"regexp"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
	"github.com/sloik/shipyard/internal/auth"
	"github.com/sloik/shipyard/internal/capture"
	"github.com/sloik/shipyard/internal/gateway"
	"github.com/sloik/shipyard/internal/performance"
)

//go:embed ui
var uiFS embed.FS

// secretKeyPattern matches env key names that are likely to hold secrets.
var secretKeyPattern = regexp.MustCompile(`(?i)(KEY|TOKEN|SECRET|PASSWORD|API)`)

// hasPlainTextSecrets returns true if any entry in env has a key matching a
// common secret-name pattern and a value that is NOT a known secret reference
// (@keychain:, op://, or ${).  It must be called with the ORIGINAL (unresolved)
// env map from the config — not with resolved secret values.
func hasPlainTextSecrets(env map[string]string) bool {
	for k, v := range env {
		if !secretKeyPattern.MatchString(k) {
			continue
		}
		if strings.HasPrefix(v, "@keychain:") ||
			strings.HasPrefix(v, "op://") ||
			strings.HasPrefix(v, "${") {
			continue
		}
		return true
	}
	return false
}

// SettingsStore holds runtime-mutable application settings.
// It is safe for concurrent use.
type SettingsStore struct {
	mu             sync.RWMutex
	secretsBackend string
}

// NewSettingsStore creates a SettingsStore initialised with the given secrets backend.
func NewSettingsStore(backend string) *SettingsStore {
	return &SettingsStore{secretsBackend: backend}
}

// SecretsBackend returns the current secrets backend value.
func (ss *SettingsStore) SecretsBackend() string {
	ss.mu.RLock()
	defer ss.mu.RUnlock()
	return ss.secretsBackend
}

// SetSecretsBackend updates the secrets backend value.
func (ss *SettingsStore) SetSecretsBackend(backend string) {
	ss.mu.Lock()
	defer ss.mu.Unlock()
	ss.secretsBackend = backend
}

type wsConn interface {
	Read(context.Context) (websocket.MessageType, []byte, error)
	Write(context.Context, websocket.MessageType, []byte) error
	CloseNow() error
}

var subUIFS = fs.Sub

var acceptWebSocket = func(w http.ResponseWriter, r *http.Request, opts *websocket.AcceptOptions) (wsConn, error) {
	return websocket.Accept(w, r, opts)
}

// UIAssets returns the embedded dashboard UI files rooted at the ui/ folder.
func UIAssets() (fs.FS, error) {
	uiContent, err := subUIFS(uiFS, "ui")
	if err != nil {
		return nil, fmt.Errorf("embed ui: %w", err)
	}
	return uiContent, nil
}

// ProxyManager defines the interface the web server uses to interact with proxies.
type ProxyManager interface {
	Servers() []ServerInfo
	SendRequest(ctx context.Context, serverName, method string, params json.RawMessage) (json.RawMessage, error)
	RestartServer(name string) error
	StopServer(name string) error
	StartRecording(server string, sessionID int64)
	StopRecording(server string)
	ActiveSessionID(server string) int64
	ServersForAuth() []string
}

type rpcPerformanceProvider interface {
	RPCPerformanceSnapshot() []performance.RPCSample
}

// ServerInfo describes a running server for the API.
type ServerInfo struct {
	Name         string `json:"name"`
	Status       string `json:"status"`
	Command      string `json:"command,omitempty"`
	ToolCount    int    `json:"tool_count"`
	Uptime       int64  `json:"uptime_ms"`
	RestartCount int    `json:"restart_count"`
	ErrorMessage string `json:"error_message,omitempty"`
	IsSelf       bool   `json:"is_self,omitempty"` // true for the built-in Shipyard entry
	Enabled      bool   `json:"enabled"`           // false when server is disabled by gateway policy (SPEC-028)
}

// shipyardManagementTool describes one of Shipyard's built-in management tools.
type shipyardManagementTool struct {
	Name        string
	Description string
	InputSchema json.RawMessage
}

// shipyardTools is the static catalog of Shipyard's built-in management tools.
var shipyardTools = []shipyardManagementTool{
	{
		Name:        "status",
		Description: "Get status of the running Shipyard instance and its managed servers",
		InputSchema: json.RawMessage(`{"type":"object","properties":{}}`),
	},
	{
		Name:        "list_servers",
		Description: "List all servers managed by Shipyard, including their status and tool counts",
		InputSchema: json.RawMessage(`{"type":"object","properties":{}}`),
	},
	{
		Name:        "restart",
		Description: "Restart a named child server managed by Shipyard",
		InputSchema: json.RawMessage(`{"type":"object","properties":{"name":{"type":"string","description":"Name of the server to restart"}},"required":["name"]}`),
	},
	{
		Name:        "stop",
		Description: "Stop a named child server managed by Shipyard",
		InputSchema: json.RawMessage(`{"type":"object","properties":{"name":{"type":"string","description":"Name of the server to stop"}},"required":["name"]}`),
	},
}

// Server is the HTTP + WebSocket server for the web dashboard.
type Server struct {
	port          int
	store         *capture.Store
	hub           *Hub
	proxies       ProxyManager
	gateway       *gateway.Store
	authStore     *auth.Store
	authLimiter   *auth.RateLimiter
	authEnabled   bool
	toolLogLevels map[string]map[string]string // server → tool → log_level
	settingsStore *SettingsStore
	rawServerEnvs map[string]map[string]string // server name → original (unresolved) env
	startedAt     time.Time
	perf          *performance.Recorder
	buildInfo     DiagnosticBuildInfo
	configPath    string
	configShape   DiagnosticConfigShape
}

// NewServer creates a new web server.
func NewServer(port int, store *capture.Store, hub *Hub) *Server {
	return &Server{
		port:      port,
		store:     store,
		hub:       hub,
		startedAt: time.Now(),
		perf:      performance.NewRecorder(performance.DefaultMaxSamples),
	}
}

// SetProxyManager sets the proxy manager for tool invocation APIs.
func (s *Server) SetProxyManager(pm ProxyManager) {
	s.proxies = pm
}

func (s *Server) SetGatewayPolicyStore(gs *gateway.Store) {
	s.gateway = gs
}

// SetAuthStore enables bearer token authentication with the given store.
func (s *Server) SetAuthStore(as *auth.Store, limiter *auth.RateLimiter, enabled bool) {
	s.authStore = as
	s.authLimiter = limiter
	s.authEnabled = enabled
}

// SetToolLogLevels sets per-tool log level overrides for access logging.
func (s *Server) SetToolLogLevels(levels map[string]map[string]string) {
	s.toolLogLevels = levels
}

// SetSettingsStore attaches a SettingsStore for the settings API.
func (s *Server) SetSettingsStore(ss *SettingsStore) {
	s.settingsStore = ss
}

// SetRawServerEnvs stores the original (unresolved) env maps for each server,
// used by the plain-text secrets detection logic.
func (s *Server) SetRawServerEnvs(envs map[string]map[string]string) {
	s.rawServerEnvs = envs
}

type DiagnosticBuildInfo struct {
	Version     string `json:"version"`
	GitRevision string `json:"git_revision"`
	GitModified bool   `json:"git_modified"`
}

type DiagnosticConfigShape struct {
	HasConfig      bool                             `json:"has_config"`
	AuthEnabled    bool                             `json:"auth_enabled"`
	SecretsBackend string                           `json:"secrets_backend,omitempty"`
	ServerCount    int                              `json:"server_count"`
	Servers        map[string]DiagnosticServerShape `json:"servers,omitempty"`
}

type DiagnosticServerShape struct {
	CommandPresent bool `json:"command_present"`
	ArgsCount      int  `json:"args_count"`
	EnvKeyCount    int  `json:"env_key_count"`
	CwdPresent     bool `json:"cwd_present"`
	ToolCount      int  `json:"tool_count"`
}

func (s *Server) SetDiagnostics(build DiagnosticBuildInfo, configPath string, configShape DiagnosticConfigShape) {
	s.buildInfo = build
	s.configPath = configPath
	s.configShape = configShape
}

// Start runs the HTTP server. It blocks until the context is cancelled.
func (s *Server) Start(ctx context.Context) error {
	mux := http.NewServeMux()

	// Serve embedded UI
	uiAssets, err := UIAssets()
	if err != nil {
		return err
	}
	mux.Handle("GET /", noCache(http.FileServer(http.FS(uiAssets))))

	// API endpoints
	mux.HandleFunc("GET /api/traffic", s.handleTraffic)
	mux.HandleFunc("GET /api/traffic/{id}", s.handleTrafficDetail)
	mux.HandleFunc("GET /api/servers", s.handleServers)
	mux.HandleFunc("POST /api/servers/{name}/restart", s.handleServerRestart)
	mux.HandleFunc("POST /api/servers/{name}/stop", s.handleServerStop)
	mux.HandleFunc("GET /api/auto-import", s.handleAutoImportScan)
	mux.HandleFunc("GET /api/tools", s.handleTools)
	mux.HandleFunc("GET /api/tools/conflicts", s.handleToolConflicts)
	mux.HandleFunc("POST /api/tools/call", s.handleToolCall)
	mux.HandleFunc("GET /api/gateway/tools", s.handleGatewayTools)
	mux.HandleFunc("GET /api/gateway/policy", s.handleGatewayPolicy)
	mux.HandleFunc("POST /api/gateway/servers/{name}/enable", s.handleGatewayServerEnable)
	mux.HandleFunc("POST /api/gateway/servers/{name}/disable", s.handleGatewayServerDisable)
	mux.HandleFunc("POST /api/gateway/tools/{server}/{tool}/enable", s.handleGatewayToolEnable)
	mux.HandleFunc("POST /api/gateway/tools/{server}/{tool}/disable", s.handleGatewayToolDisable)
	// SPEC-028: REST-style PUT endpoints for toggle state
	mux.HandleFunc("PUT /api/servers/{name}/enabled", s.handleServerEnabledPUT)
	mux.HandleFunc("PUT /api/tools/{server}/{tool}/enabled", s.handleToolEnabledPUT)
	mux.HandleFunc("POST /api/replay", s.handleReplay)
	mux.HandleFunc("POST /api/sessions/start", s.handleSessionStart)
	mux.HandleFunc("GET /api/sessions", s.handleSessionList)
	mux.HandleFunc("GET /api/sessions/{id}", s.handleSessionDetail)
	mux.HandleFunc("GET /api/sessions/{id}/export", s.handleSessionExport)
	mux.HandleFunc("POST /api/sessions/{id}/stop", s.handleSessionStop)
	mux.HandleFunc("POST /api/sessions/{id}/replay", s.handleSessionReplay)
	mux.HandleFunc("DELETE /api/sessions/{id}", s.handleSessionDelete)
	mux.HandleFunc("GET /api/schema/changes", s.handleSchemaChanges)
	mux.HandleFunc("GET /api/schema/changes/{id}", s.handleSchemaChangeDetail)
	mux.HandleFunc("POST /api/schema/changes/{id}/ack", s.handleSchemaAcknowledge)
	mux.HandleFunc("GET /api/schema/current/{server}", s.handleSchemaCurrentTools)
	mux.HandleFunc("GET /api/schema/unacknowledged-count", s.handleSchemaUnackCount)
	mux.HandleFunc("GET /api/profiling/summary", s.handleProfilingSummary)
	mux.HandleFunc("GET /api/profiling/tools", s.handleProfilingTools)
	mux.HandleFunc("GET /api/performance/runtime", s.handlePerformanceRuntime)
	mux.HandleFunc("GET /api/performance/http", s.handlePerformanceHTTP)
	mux.HandleFunc("GET /api/performance/rpc", s.handlePerformanceRPC)
	mux.HandleFunc("GET /api/performance/history", s.handlePerformanceHistory)
	mux.HandleFunc("POST /api/performance/frontend", s.handlePerformanceFrontend)
	mux.HandleFunc("GET /api/performance/debug-bundle", s.handlePerformanceDebugBundle)
	mux.HandleFunc("GET /ws", s.handleWebSocket)

	// Token admin API (auth required via bootstrap or admin token)
	mux.HandleFunc("POST /api/tokens", s.handleTokenCreate)
	mux.HandleFunc("GET /api/tokens", s.handleTokenList)
	mux.HandleFunc("DELETE /api/tokens/{id}", s.handleTokenDelete)
	mux.HandleFunc("PUT /api/tokens/{id}/scopes", s.handleTokenUpdateScopes)
	mux.HandleFunc("GET /api/tokens/{id}/stats", s.handleTokenStats)

	// Access log endpoints
	mux.HandleFunc("GET /api/access-log", s.handleAccessLog)
	mux.HandleFunc("GET /api/access-log/stats", s.handleAccessLogStats)

	// Settings API
	mux.HandleFunc("GET /api/settings", s.handleSettingsGet)
	mux.HandleFunc("POST /api/settings", s.handleSettingsPost)

	// MCP proxy endpoint — auth-gated when auth.enabled: true
	if s.authEnabled && s.authStore != nil {
		mcpH := auth.NewMCPHandler(s.authStore, s.authLimiter, s.proxies)
		mcpH.SetCaptureStore(s.store)
		mcpH.SetSelfDispatcher(s)
		if s.toolLogLevels != nil {
			mcpH.SetToolLogLevels(s.toolLogLevels)
		}
		if s.gateway != nil {
			mcpH.SetGatewayPolicy(s.gateway) // SPEC-028: filter disabled tools
		}
		mux.Handle("POST /mcp", mcpH)
		mux.Handle("POST /mcp/{token}", mcpH)
	} else {
		// Auth disabled: passthrough MCP proxy (no auth check)
		mux.HandleFunc("POST /mcp", s.handleMCPPassthrough)
		mux.Handle("POST /mcp/{token}", http.HandlerFunc(s.handleMCPPassthrough))
	}

	srv := &http.Server{
		Addr:    fmt.Sprintf(":%d", s.port),
		Handler: withCORS(s.instrumentHTTP(mux)),
		BaseContext: func(_ net.Listener) context.Context {
			return ctx
		},
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutdownCtx)
	}()

	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		return err
	}
	return nil
}

func (s *Server) instrumentHTTP(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := performance.NewResponseRecorder(w)
		next.ServeHTTP(rw, r)
		route := r.Pattern
		if route == "" {
			route = r.URL.Path
		}
		s.perf.RecordHTTP(performance.HTTPSample{
			Timestamp:    time.Now().UTC(),
			Method:       r.Method,
			Route:        route,
			StatusCode:   rw.StatusCode,
			DurationMs:   time.Since(start).Milliseconds(),
			ResponseSize: rw.Size,
		})
		s.recordPerformanceRollup(capture.PerformanceRollupSample{
			Timestamp:      time.Now().UTC(),
			HTTPDurationMs: time.Since(start).Milliseconds(),
		})
	})
}

func noCache(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate")
		w.Header().Set("Pragma", "no-cache")
		w.Header().Set("Expires", "0")
		next.ServeHTTP(w, r)
	})
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

type runtimePerformanceResponse struct {
	UptimeMs       int64                    `json:"uptime_ms"`
	Goroutines     int                      `json:"goroutines"`
	Memory         runtimeMemoryStats       `json:"memory"`
	Store          capture.PerformanceStats `json:"store"`
	TelemetryLimit int                      `json:"telemetry_limit"`
}

type runtimeMemoryStats struct {
	HeapAllocBytes uint64 `json:"heap_alloc_bytes"`
	HeapSysBytes   uint64 `json:"heap_sys_bytes"`
	HeapObjects    uint64 `json:"heap_objects"`
	AllocBytes     uint64 `json:"alloc_bytes"`
	SysBytes       uint64 `json:"sys_bytes"`
	NumGC          uint32 `json:"num_gc"`
}

type frontendPerformanceRequest struct {
	Name          string                 `json:"name"`
	DurationMs    int64                  `json:"duration_ms"`
	ActiveDOMRows int64                  `json:"active_dom_rows"`
	Meta          map[string]interface{} `json:"meta,omitempty"`
}

type performanceHistoryResponse struct {
	Window  string                      `json:"window"`
	Limit   int                         `json:"limit"`
	Rollups []capture.PerformanceRollup `json:"rollups"`
	Current runtimePerformanceResponse  `json:"current"`
}

type performanceDebugBundle struct {
	GeneratedAt time.Time                   `json:"generated_at"`
	Build       performanceDebugBuild       `json:"build"`
	Runtime     runtimePerformanceResponse  `json:"runtime"`
	Config      performanceDebugConfig      `json:"config"`
	TableCounts capture.PerformanceStats    `json:"table_counts"`
	History     []capture.PerformanceRollup `json:"performance_rollups"`
	HTTP        []performance.HTTPSample    `json:"http_samples"`
	RPC         []performance.RPCSample     `json:"rpc_samples"`
	Redaction   []string                    `json:"redaction"`
}

type performanceDebugBuild struct {
	Version     string `json:"version"`
	GitRevision string `json:"git_revision"`
	GitModified bool   `json:"git_modified"`
	BinaryPath  string `json:"binary_path"`
	UptimeMs    int64  `json:"uptime_ms"`
	GoVersion   string `json:"go_version"`
	GOOS        string `json:"goos"`
	GOARCH      string `json:"goarch"`
}

type performanceDebugConfig struct {
	Path  string                `json:"path"`
	Shape DiagnosticConfigShape `json:"shape"`
}

func (s *Server) handlePerformanceRuntime(w http.ResponseWriter, r *http.Request) {
	resp, err := s.currentRuntimePerformance()
	if err != nil {
		http.Error(w, "runtime stats unavailable", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) currentRuntimePerformance() (runtimePerformanceResponse, error) {
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	storeStats := capture.PerformanceStats{}
	if s.store != nil {
		stats, err := s.store.PerformanceStats()
		if err != nil {
			return runtimePerformanceResponse{}, err
		}
		storeStats = stats
	}

	return runtimePerformanceResponse{
		UptimeMs:   time.Since(s.startedAt).Milliseconds(),
		Goroutines: runtime.NumGoroutine(),
		Memory: runtimeMemoryStats{
			HeapAllocBytes: mem.HeapAlloc,
			HeapSysBytes:   mem.HeapSys,
			HeapObjects:    mem.HeapObjects,
			AllocBytes:     mem.Alloc,
			SysBytes:       mem.Sys,
			NumGC:          mem.NumGC,
		},
		Store:          storeStats,
		TelemetryLimit: performance.DefaultMaxSamples,
	}, nil
}

func (s *Server) recordPerformanceRollup(sample capture.PerformanceRollupSample) {
	if s.store == nil {
		return
	}
	current, err := s.currentRuntimePerformance()
	if err != nil {
		return
	}
	sample.Goroutines = int64(current.Goroutines)
	sample.HeapAllocBytes = int64(current.Memory.HeapAllocBytes)
	sample.DBFileSizeBytes = current.Store.DBFileSizeBytes
	sample.TrafficRows = current.Store.TrafficRows
	sample.SchemaSnapshotRows = current.Store.SchemaSnapshotRows
	sample.AccessLogRows = current.Store.AccessLogRows
	if err := s.store.UpsertPerformanceRollup(sample); err != nil {
		slog.Debug("performance rollup skipped", "error", err)
	}
}

func (s *Server) handlePerformanceHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"samples": s.perf.HTTP(),
		"limit":   performance.DefaultMaxSamples,
	})
}

func (s *Server) handlePerformanceRPC(w http.ResponseWriter, r *http.Request) {
	samples := []performance.RPCSample{}
	if provider, ok := s.proxies.(rpcPerformanceProvider); ok {
		samples = provider.RPCPerformanceSnapshot()
	}
	if samples == nil {
		samples = []performance.RPCSample{}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"samples": samples,
		"limit":   performance.DefaultMaxSamples,
	})
}

func (s *Server) handlePerformanceFrontend(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}
	defer r.Body.Close()
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16*1024))
	var req frontendPerformanceRequest
	if err := dec.Decode(&req); err != nil {
		http.Error(w, "invalid frontend telemetry", http.StatusBadRequest)
		return
	}
	if req.DurationMs < 0 {
		req.DurationMs = 0
	}
	s.recordPerformanceRollup(capture.PerformanceRollupSample{
		Timestamp:          time.Now().UTC(),
		FrontendDurationMs: req.DurationMs,
		ActiveDOMRows:      req.ActiveDOMRows,
	})
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handlePerformanceHistory(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}
	s.recordLatestRPCRollup()
	window := r.URL.Query().Get("window")
	if window == "" {
		window = r.URL.Query().Get("range")
	}
	since := time.Now().UTC().Add(-parsePerformanceWindow(window))
	rollups, err := s.store.ListPerformanceRollups(since, capture.PerformanceRollupRetentionMax)
	if err != nil {
		http.Error(w, "performance history unavailable", http.StatusInternalServerError)
		return
	}
	current, err := s.currentRuntimePerformance()
	if err != nil {
		http.Error(w, "runtime stats unavailable", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(performanceHistoryResponse{
		Window:  windowOrDefault(window),
		Limit:   capture.PerformanceRollupRetentionMax,
		Rollups: rollups,
		Current: current,
	})
}

func (s *Server) recordLatestRPCRollup() {
	samples := s.rpcSamples()
	if len(samples) == 0 {
		return
	}
	latest := samples[len(samples)-1]
	s.recordPerformanceRollup(capture.PerformanceRollupSample{
		Timestamp:     latest.Timestamp,
		RPCDurationMs: latest.DurationMs,
	})
}

func (s *Server) rpcSamples() []performance.RPCSample {
	if provider, ok := s.proxies.(rpcPerformanceProvider); ok {
		if samples := provider.RPCPerformanceSnapshot(); samples != nil {
			return samples
		}
	}
	return []performance.RPCSample{}
}

func parsePerformanceWindow(raw string) time.Duration {
	switch raw {
	case "1h":
		return time.Hour
	case "7d":
		return 7 * 24 * time.Hour
	case "30d":
		return 30 * 24 * time.Hour
	default:
		return 24 * time.Hour
	}
}

func windowOrDefault(raw string) string {
	if raw == "" {
		return "24h"
	}
	return raw
}

func (s *Server) handlePerformanceDebugBundle(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}
	s.recordLatestRPCRollup()
	current, err := s.currentRuntimePerformance()
	if err != nil {
		http.Error(w, "runtime stats unavailable", http.StatusInternalServerError)
		return
	}
	rollups, err := s.store.ListPerformanceRollups(time.Now().UTC().Add(-30*24*time.Hour), capture.PerformanceRollupRetentionMax)
	if err != nil {
		http.Error(w, "performance history unavailable", http.StatusInternalServerError)
		return
	}
	binaryPath, _ := os.Executable()
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Disposition", `attachment; filename="shipyard-debug-bundle.json"`)
	json.NewEncoder(w).Encode(performanceDebugBundle{
		GeneratedAt: time.Now().UTC(),
		Build: performanceDebugBuild{
			Version:     s.diagnosticBuild().Version,
			GitRevision: s.diagnosticBuild().GitRevision,
			GitModified: s.diagnosticBuild().GitModified,
			BinaryPath:  binaryPath,
			UptimeMs:    current.UptimeMs,
			GoVersion:   runtime.Version(),
			GOOS:        runtime.GOOS,
			GOARCH:      runtime.GOARCH,
		},
		Runtime:     current,
		Config:      performanceDebugConfig{Path: s.configPath, Shape: s.configShape},
		TableCounts: current.Store,
		History:     rollups,
		HTTP:        s.perf.HTTP(),
		RPC:         s.rpcSamples(),
		Redaction: []string{
			"config includes shape only; env names and values are omitted",
			"tokens, token hashes, request bodies, tool arguments, and payloads are omitted",
			"runtime environment variables are omitted",
		},
	})
}

func (s *Server) diagnosticBuild() DiagnosticBuildInfo {
	info := s.buildInfo
	if bi, ok := debug.ReadBuildInfo(); ok {
		for _, setting := range bi.Settings {
			switch setting.Key {
			case "vcs.revision":
				if info.GitRevision == "" || info.GitRevision == "none" {
					info.GitRevision = setting.Value
				}
			case "vcs.modified":
				info.GitModified = setting.Value == "true"
			}
		}
	}
	if info.Version == "" {
		info.Version = "dev"
	}
	if info.GitRevision == "" {
		info.GitRevision = "unknown"
	}
	return info
}

func (s *Server) handleTraffic(w http.ResponseWriter, r *http.Request) {
	page, _ := strconv.Atoi(r.URL.Query().Get("page"))
	if page < 1 {
		page = 1
	}
	pageSize, _ := strconv.Atoi(r.URL.Query().Get("page_size"))
	if pageSize < 1 || pageSize > 200 {
		pageSize = 50
	}

	f := capture.QueryFilter{
		Page:      page,
		PageSize:  pageSize,
		Server:    r.URL.Query().Get("server"),
		Method:    r.URL.Query().Get("method"),
		Direction: r.URL.Query().Get("direction"),
		Search:    r.URL.Query().Get("search"),
	}

	// Support offset-based pagination for infinite scroll.
	// If ?offset= is provided, it takes precedence over ?page=.
	if offsetStr := r.URL.Query().Get("offset"); offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil && v >= 0 {
			f.Offset = v
			f.UseOffset = true
		}
	}

	if fromStr := r.URL.Query().Get("from_ts"); fromStr != "" {
		if v, err := strconv.ParseInt(fromStr, 10, 64); err == nil {
			f.FromTs = &v
		}
	}
	if toStr := r.URL.Query().Get("to_ts"); toStr != "" {
		if v, err := strconv.ParseInt(toStr, 10, 64); err == nil {
			f.ToTs = &v
		}
	}

	result, err := s.store.QueryFiltered(f)
	if err != nil {
		slog.Error("query traffic", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleReplay(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		ID int64 `json:"id"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	// Fetch the original traffic entry
	entry, _, err := s.store.GetByID(req.ID)
	if err != nil {
		http.Error(w, "traffic entry not found", http.StatusNotFound)
		return
	}

	// Parse the original payload to extract params
	var rpcMsg struct {
		Method string          `json:"method"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal([]byte(entry.Payload), &rpcMsg); err != nil {
		http.Error(w, "invalid payload in traffic entry", http.StatusBadRequest)
		return
	}

	// Use the method from the traffic entry if not in payload
	method := rpcMsg.Method
	if method == "" {
		method = entry.Method
	}

	params := rpcMsg.Params
	if params == nil {
		params = json.RawMessage("{}")
	}

	start := time.Now()
	result, err := s.proxies.SendRequest(r.Context(), entry.ServerName, method, params)
	elapsed := time.Since(start)

	if err != nil {
		slog.Error("replay failed", "server", entry.ServerName, "method", method, "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error":      err.Error(),
			"latency_ms": elapsed.Milliseconds(),
		})
		return
	}

	// Parse the JSON-RPC response
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		http.Error(w, "invalid response from server", http.StatusBadGateway)
		return
	}

	resp := map[string]interface{}{
		"latency_ms": elapsed.Milliseconds(),
	}
	if rpcResp.Error != nil {
		resp["error"] = json.RawMessage(rpcResp.Error)
	} else {
		resp["result"] = json.RawMessage(rpcResp.Result)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) handleTrafficDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	entry, matched, err := s.store.GetByID(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	resp := map[string]interface{}{
		"entry": entry,
	}
	if matched != nil {
		resp["matched"] = matched
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// serverInfoResponse extends ServerInfo with gateway policy state for the API response.
// Env is explicitly suppressed (json:"-") to prevent accidental credential leakage.
type serverInfoResponse struct {
	ServerInfo
	GatewayDisabled     bool              `json:"gateway_disabled"`
	HasPlainTextSecrets bool              `json:"has_plain_text_secrets"`
	Env                 map[string]string `json:"-"` // never expose env values in API responses
}

func (s *Server) handleServers(w http.ResponseWriter, r *http.Request) {
	// Synthetic Shipyard self-entry — always first, regardless of child servers.
	selfEntry := serverInfoResponse{
		ServerInfo: ServerInfo{
			Name:      "shipyard",
			Status:    "running",
			ToolCount: len(shipyardTools),
			IsSelf:    true,
			Enabled:   true, // Shipyard cannot be disabled
		},
		GatewayDisabled: false, // Shipyard cannot be disabled
	}

	if s.proxies == nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]serverInfoResponse{selfEntry})
		return
	}

	servers := s.proxies.Servers()
	result := make([]serverInfoResponse, len(servers))
	for i, srv := range servers {
		resp := serverInfoResponse{ServerInfo: srv}
		enabled := true
		if s.gateway != nil && !s.gateway.ServerEnabled(srv.Name) {
			resp.GatewayDisabled = true
			enabled = false
		}
		resp.ServerInfo.Enabled = enabled
		if s.rawServerEnvs != nil {
			resp.Env = s.rawServerEnvs[srv.Name]
		}
		resp.HasPlainTextSecrets = hasPlainTextSecrets(resp.Env)
		result[i] = resp
	}
	// Prepend self-entry as the first item.
	result = append([]serverInfoResponse{selfEntry}, result...)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleServerRestart(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	if err := s.proxies.RestartServer(name); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "restarting"})
}

func (s *Server) handleServerStop(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	if err := s.proxies.StopServer(name); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
}

// DiscoveredServer describes a server found via auto-import scanning.
type DiscoveredServer struct {
	Name    string            `json:"name"`
	Command string            `json:"command"`
	Args    []string          `json:"args,omitempty"`
	Env     map[string]string `json:"env,omitempty"`
	Source  string            `json:"source"`
	Status  string            `json:"status"` // "new", "duplicate", "already_imported"
}

// autoImportScanner can be overridden in tests.
var autoImportScanner = scanForServers

type gatewayToolInfo struct {
	Name          string          `json:"name"`
	Server        string          `json:"server"`
	Tool          string          `json:"tool"`
	Description   string          `json:"description,omitempty"`
	InputSchema   json.RawMessage `json:"inputSchema,omitempty"`
	ServerEnabled bool            `json:"server_enabled"`
	ToolEnabled   bool            `json:"tool_enabled"`
	Enabled       bool            `json:"enabled"`
}

type toolsAPIResponse struct {
	Tools              []map[string]interface{} `json:"tools"`
	Source             string                   `json:"source"`
	CacheStatus        string                   `json:"cache_status"`
	StatusMessage      string                   `json:"status_message,omitempty"`
	SnapshotID         int64                    `json:"snapshot_id,omitempty"`
	SnapshotCapturedAt string                   `json:"snapshot_captured_at,omitempty"`
}

func (s *Server) handleAutoImportScan(w http.ResponseWriter, r *http.Request) {
	var existing map[string]bool
	if s.proxies != nil {
		servers := s.proxies.Servers()
		existing = make(map[string]bool, len(servers))
		for _, srv := range servers {
			existing[srv.Name] = true
		}
	} else {
		existing = map[string]bool{}
	}

	discovered := autoImportScanner(existing)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(discovered)
}

func (s *Server) handleToolConflicts(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]interface{}{})
		return
	}

	servers := s.proxies.Servers()
	if len(servers) == 0 {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode([]interface{}{})
		return
	}

	toolMap := make(map[string][]string) // toolName -> []serverName
	for _, srv := range servers {
		if srv.Status != "online" {
			continue
		}
		snapTools, _, err := s.store.GetLatestSnapshot(srv.Name)
		if err != nil {
			slog.Warn("tool conflicts: snapshot error", "server", srv.Name, "err", err)
			continue
		}
		for _, t := range snapTools {
			toolMap[t.Name] = append(toolMap[t.Name], srv.Name)
		}
	}

	// Filter to only duplicates
	type conflict struct {
		ToolName string   `json:"tool_name"`
		Servers  []string `json:"servers"`
	}
	var conflicts []conflict
	for name, servers := range toolMap {
		if len(servers) > 1 {
			conflicts = append(conflicts, conflict{ToolName: name, Servers: servers})
		}
	}

	if conflicts == nil {
		conflicts = []conflict{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(conflicts)
}

func (s *Server) handleTools(w http.ResponseWriter, r *http.Request) {
	serverName := r.URL.Query().Get("server")
	if serverName == "" {
		http.Error(w, "server parameter required", http.StatusBadRequest)
		return
	}
	if serverName != "shipyard" && s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}
	forceRefresh := r.URL.Query().Get("force_refresh") == "1" || r.URL.Query().Get("refresh") == "1"

	resp, err := s.toolsResponse(r.Context(), serverName, forceRefresh)
	if err != nil {
		slog.Error("tools/list failed", "server", serverName, "error", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

func (s *Server) toolsResponse(ctx context.Context, serverName string, forceRefresh bool) (toolsAPIResponse, error) {
	if serverName == "shipyard" {
		result, err := s.selfToolsResult()
		if err != nil {
			return toolsAPIResponse{}, err
		}
		tools, err := toolsFromRPCResult(result)
		if err != nil {
			return toolsAPIResponse{}, err
		}
		s.applyGatewayPolicyToTools(serverName, tools)
		return toolsAPIResponse{
			Tools:         tools,
			Source:        "self",
			CacheStatus:   "not_applicable",
			StatusMessage: "Shipyard built-in tools are served directly.",
		}, nil
	}

	if forceRefresh {
		result, err := s.fetchToolsResult(ctx, serverName)
		if err != nil {
			return toolsAPIResponse{}, err
		}
		tools, err := toolsFromRPCResult(result)
		if err != nil {
			return toolsAPIResponse{}, err
		}
		if s.store != nil {
			if _, err := s.store.SaveSnapshot(serverName, toolSchemasFromMaps(tools)); err != nil {
				return toolsAPIResponse{}, err
			}
		}
		s.applyGatewayPolicyToTools(serverName, tools)
		return toolsAPIResponse{
			Tools:         tools,
			Source:        "live",
			CacheStatus:   "refreshed",
			StatusMessage: "Live tools/list refresh completed and the snapshot cache was updated.",
		}, nil
	}

	if s.store == nil {
		return toolsAPIResponse{}, fmt.Errorf("no capture store configured")
	}
	snapTools, snapID, capturedAt, err := s.store.GetLatestSnapshotWithCapturedAt(serverName)
	if err != nil {
		return toolsAPIResponse{}, err
	}
	if snapID == 0 {
		return toolsAPIResponse{
			Tools:         []map[string]interface{}{},
			Source:        "cache",
			CacheStatus:   "missing",
			StatusMessage: "No cached tools snapshot is available yet. Use force_refresh=1 to fetch live tools.",
		}, nil
	}
	tools := toolMapsFromSchemas(snapTools)
	s.applyGatewayPolicyToTools(serverName, tools)
	return toolsAPIResponse{
		Tools:              tools,
		Source:             "cache",
		CacheStatus:        "cached",
		StatusMessage:      "Loaded from the latest cached schema snapshot.",
		SnapshotID:         snapID,
		SnapshotCapturedAt: capturedAt.UTC().Format(time.RFC3339Nano),
	}, nil
}

func toolsFromRPCResult(result json.RawMessage) ([]map[string]interface{}, error) {
	// Parse the JSON-RPC response to extract the result
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		return nil, fmt.Errorf("invalid response from server")
	}
	if rpcResp.Error != nil {
		return nil, fmt.Errorf("server returned tools/list error: %s", string(rpcResp.Error))
	}

	var toolsResult struct {
		Tools []map[string]interface{} `json:"tools"`
	}
	if err := json.Unmarshal(rpcResp.Result, &toolsResult); err != nil {
		return nil, fmt.Errorf("invalid tools/list result: %w", err)
	}
	if toolsResult.Tools == nil {
		toolsResult.Tools = []map[string]interface{}{}
	}
	return toolsResult.Tools, nil
}

func toolMapsFromSchemas(schemas []capture.ToolSchema) []map[string]interface{} {
	tools := make([]map[string]interface{}, 0, len(schemas))
	for _, tool := range schemas {
		entry := map[string]interface{}{
			"name":        tool.Name,
			"description": tool.Description,
		}
		if len(tool.InputSchema) > 0 {
			entry["inputSchema"] = tool.InputSchema
		}
		tools = append(tools, entry)
	}
	return tools
}

func toolSchemasFromMaps(tools []map[string]interface{}) []capture.ToolSchema {
	schemas := make([]capture.ToolSchema, 0, len(tools))
	for _, tool := range tools {
		name, _ := tool["name"].(string)
		description, _ := tool["description"].(string)
		var inputSchema json.RawMessage
		if raw, ok := tool["inputSchema"]; ok && raw != nil {
			if data, err := json.Marshal(raw); err == nil {
				inputSchema = json.RawMessage(data)
			}
		}
		schemas = append(schemas, capture.ToolSchema{
			Name:        name,
			Description: description,
			InputSchema: inputSchema,
		})
	}
	return schemas
}

func (s *Server) applyGatewayPolicyToTools(serverName string, tools []map[string]interface{}) {
	for i, t := range tools {
		if t == nil {
			tools[i] = map[string]interface{}{}
			t = tools[i]
		}
		serverEnabled := true
		toolEnabled := true
		if s.gateway != nil {
			serverEnabled = s.gateway.ServerEnabled(serverName)
			toolName, _ := t["name"].(string)
			toolEnabled = s.gateway.ToolEnabled(serverName, toolName)
		}
		t["enabled"] = serverEnabled && toolEnabled
		t["server_enabled"] = serverEnabled
	}
}

func (s *Server) handleToolCall(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB limit
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Server    string          `json:"server"`
		Tool      string          `json:"tool"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	if req.Server == "" || req.Tool == "" {
		http.Error(w, "server and tool fields required", http.StatusBadRequest)
		return
	}

	// Route Shipyard's built-in tools to the internal dispatcher.
	if req.Server == "shipyard" {
		// Per-tool gateway policy applies to Shipyard tools too.
		if s.gateway != nil && !s.gateway.ToolEnabled("shipyard", req.Tool) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      fmt.Sprintf("tool %q on server %q is disabled by Shipyard gateway policy", req.Tool, req.Server),
				"latency_ms": int64(0),
			})
			return
		}
		start := time.Now()
		result, err := s.dispatchShipyardTool(r.Context(), req.Tool, req.Arguments)
		elapsed := time.Since(start)
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      err.Error(),
				"latency_ms": elapsed.Milliseconds(),
			})
			return
		}
		resultBytes, _ := json.Marshal(result)
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"result":     json.RawMessage(resultBytes),
			"latency_ms": elapsed.Milliseconds(),
		})
		return
	}

	if s.gateway != nil {
		if !s.gateway.ServerEnabled(req.Server) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      fmt.Sprintf("server %q is disabled by Shipyard gateway policy", req.Server),
				"latency_ms": int64(0),
			})
			return
		}
		if !s.gateway.ToolEnabled(req.Server, req.Tool) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			json.NewEncoder(w).Encode(map[string]interface{}{
				"error":      fmt.Sprintf("tool %q on server %q is disabled by Shipyard gateway policy", req.Tool, req.Server),
				"latency_ms": int64(0),
			})
			return
		}
	}

	// Build tools/call params
	params := map[string]interface{}{
		"name": req.Tool,
	}
	if req.Arguments != nil {
		params["arguments"] = json.RawMessage(req.Arguments)
	}
	paramsBytes, _ := json.Marshal(params)

	start := time.Now()
	result, err := s.proxies.SendRequest(r.Context(), req.Server, "tools/call", paramsBytes)
	elapsed := time.Since(start)

	if err != nil {
		slog.Error("tools/call failed", "server", req.Server, "tool", req.Tool, "error", err)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		json.NewEncoder(w).Encode(map[string]interface{}{
			"error":      err.Error(),
			"latency_ms": elapsed.Milliseconds(),
		})
		return
	}

	// Parse the JSON-RPC response
	var rpcResp struct {
		Result json.RawMessage `json:"result"`
		Error  json.RawMessage `json:"error"`
	}
	if err := json.Unmarshal(result, &rpcResp); err != nil {
		http.Error(w, "invalid response from server", http.StatusBadGateway)
		return
	}

	resp := map[string]interface{}{
		"latency_ms": elapsed.Milliseconds(),
	}
	if rpcResp.Error != nil {
		resp["error"] = json.RawMessage(rpcResp.Error)
	} else {
		resp["result"] = json.RawMessage(rpcResp.Result)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// dispatchShipyardTool executes one of Shipyard's built-in management tools
// and returns a JSON-RPC-style result map suitable for returning to callers.
// toolName is the bare name (without the "shipyard__" prefix).
// arguments is the raw JSON arguments object (may be nil).
func (s *Server) dispatchShipyardTool(ctx context.Context, toolName string, arguments json.RawMessage) (map[string]interface{}, error) {
	switch toolName {
	case "status":
		var servers []serverInfoResponse
		if s.proxies != nil {
			for _, srv := range s.proxies.Servers() {
				servers = append(servers, serverInfoResponse{ServerInfo: srv})
			}
		}
		count := len(servers)
		text := fmt.Sprintf("Shipyard running on port %d with %d child server(s).", s.port, count)
		return map[string]interface{}{
			"content": []map[string]string{{"type": "text", "text": text}},
			"structuredContent": map[string]interface{}{
				"status":       "running",
				"port":         s.port,
				"server_count": count,
				"servers":      servers,
			},
		}, nil

	case "list_servers":
		// Build the full server list including the self-entry.
		selfEntry := serverInfoResponse{
			ServerInfo: ServerInfo{
				Name:      "shipyard",
				Status:    "running",
				ToolCount: len(shipyardTools),
				IsSelf:    true,
			},
		}
		var childEntries []serverInfoResponse
		if s.proxies != nil {
			for _, srv := range s.proxies.Servers() {
				entry := serverInfoResponse{ServerInfo: srv}
				if s.gateway != nil && !s.gateway.ServerEnabled(srv.Name) {
					entry.GatewayDisabled = true
				}
				childEntries = append(childEntries, entry)
			}
		}
		all := append([]serverInfoResponse{selfEntry}, childEntries...)
		allBytes, _ := json.Marshal(all)
		text := fmt.Sprintf("%d server(s) managed by Shipyard.", len(all))
		return map[string]interface{}{
			"content":           []map[string]string{{"type": "text", "text": text}},
			"structuredContent": json.RawMessage(allBytes),
		}, nil

	case "restart":
		if s.proxies == nil {
			return nil, fmt.Errorf("no proxy manager configured")
		}
		var args struct {
			Name string `json:"name"`
		}
		if len(arguments) > 0 {
			if err := json.Unmarshal(arguments, &args); err != nil {
				return nil, fmt.Errorf("invalid arguments: %w", err)
			}
		}
		if args.Name == "" {
			return nil, fmt.Errorf("argument 'name' is required")
		}
		if args.Name == "shipyard" {
			return nil, fmt.Errorf("cannot restart shipyard itself")
		}
		if err := s.proxies.RestartServer(args.Name); err != nil {
			return nil, err
		}
		text := fmt.Sprintf("Server %q is restarting.", args.Name)
		return map[string]interface{}{
			"content":           []map[string]string{{"type": "text", "text": text}},
			"structuredContent": map[string]interface{}{"status": "restarting", "server": args.Name},
		}, nil

	case "stop":
		if s.proxies == nil {
			return nil, fmt.Errorf("no proxy manager configured")
		}
		var args struct {
			Name string `json:"name"`
		}
		if len(arguments) > 0 {
			if err := json.Unmarshal(arguments, &args); err != nil {
				return nil, fmt.Errorf("invalid arguments: %w", err)
			}
		}
		if args.Name == "" {
			return nil, fmt.Errorf("argument 'name' is required")
		}
		if args.Name == "shipyard" {
			return nil, fmt.Errorf("cannot stop shipyard itself")
		}
		if err := s.proxies.StopServer(args.Name); err != nil {
			return nil, err
		}
		text := fmt.Sprintf("Server %q has been stopped.", args.Name)
		return map[string]interface{}{
			"content":           []map[string]string{{"type": "text", "text": text}},
			"structuredContent": map[string]interface{}{"status": "stopped", "server": args.Name},
		}, nil

	default:
		return nil, fmt.Errorf("unknown shipyard tool: %q", toolName)
	}
}

// DispatchSelf implements auth.SelfDispatcher for the auth-gated MCP path.
func (s *Server) DispatchSelf(ctx context.Context, toolName string, arguments json.RawMessage) (map[string]interface{}, error) {
	return s.dispatchShipyardTool(ctx, toolName, arguments)
}

// SelfTools implements auth.SelfDispatcher, returning the built-in Shipyard tool list.
func (s *Server) SelfTools() []auth.SelfTool {
	tools := make([]auth.SelfTool, len(shipyardTools))
	for i, t := range shipyardTools {
		tools[i] = auth.SelfTool{
			Name:        t.Name,
			Description: t.Description,
			InputSchema: t.InputSchema,
		}
	}
	return tools
}

func (s *Server) handleGatewayTools(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	includeDisabled := r.URL.Query().Get("include_disabled") == "1"
	tools, err := s.gatewayCatalog(r.Context(), includeDisabled)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"tools": tools})
}

func (s *Server) handleGatewayPolicy(w http.ResponseWriter, r *http.Request) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(s.gateway.Snapshot())
}

func (s *Server) handleGatewayServerEnable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayServerToggle(w, r, true)
}

func (s *Server) handleGatewayServerDisable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayServerToggle(w, r, false)
}

func (s *Server) handleGatewayToolEnable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayToolToggle(w, r, true)
}

func (s *Server) handleGatewayToolDisable(w http.ResponseWriter, r *http.Request) {
	s.handleGatewayToolToggle(w, r, false)
}

func (s *Server) handleGatewayServerToggle(w http.ResponseWriter, r *http.Request, enabled bool) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}
	// Shipyard cannot be disabled at server level — it is the gateway itself.
	if name == "shipyard" {
		http.Error(w, "shipyard cannot be disabled at server level", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetServerEnabled(name, enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"server": name, "enabled": enabled})
}

func (s *Server) handleGatewayToolToggle(w http.ResponseWriter, r *http.Request, enabled bool) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	serverName := r.PathValue("server")
	toolName := r.PathValue("tool")
	if serverName == "" || toolName == "" {
		http.Error(w, "server and tool required", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetToolEnabled(serverName, toolName, enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"server":  serverName,
		"tool":    toolName,
		"enabled": enabled,
	})
}

// handleServerEnabledPUT handles PUT /api/servers/{name}/enabled (SPEC-028).
// Body: {"enabled": bool}. Returns 200 with the new state, broadcasts WS event.
func (s *Server) handleServerEnabledPUT(w http.ResponseWriter, r *http.Request) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	name := r.PathValue("name")
	if name == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}
	if name == "shipyard" {
		http.Error(w, "shipyard cannot be disabled at server level", http.StatusBadRequest)
		return
	}
	var body struct {
		Enabled bool `json:"enabled"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetServerEnabled(name, body.Enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// Broadcast toggle change via WebSocket
	if s.hub != nil {
		evt := map[string]interface{}{
			"type":    "toggle_changed",
			"target":  "server",
			"name":    name,
			"enabled": body.Enabled,
		}
		data, _ := json.Marshal(evt)
		s.hub.Broadcast(data)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{"server": name, "enabled": body.Enabled})
}

// handleToolEnabledPUT handles PUT /api/tools/{server}/{tool}/enabled (SPEC-028).
// Body: {"enabled": bool}. Returns 200 with the new state, broadcasts WS event.
func (s *Server) handleToolEnabledPUT(w http.ResponseWriter, r *http.Request) {
	if s.gateway == nil {
		http.Error(w, "no gateway policy store configured", http.StatusServiceUnavailable)
		return
	}
	serverName := r.PathValue("server")
	toolName := r.PathValue("tool")
	if serverName == "" || toolName == "" {
		http.Error(w, "server and tool required", http.StatusBadRequest)
		return
	}
	var body struct {
		Enabled bool `json:"enabled"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}
	if err := s.gateway.SetToolEnabled(serverName, toolName, body.Enabled); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// Broadcast toggle change via WebSocket
	if s.hub != nil {
		evt := map[string]interface{}{
			"type":    "toggle_changed",
			"target":  "tool",
			"name":    serverName + "__" + toolName,
			"server":  serverName,
			"tool":    toolName,
			"enabled": body.Enabled,
		}
		data, _ := json.Marshal(evt)
		s.hub.Broadcast(data)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"server":  serverName,
		"tool":    toolName,
		"enabled": body.Enabled,
	})
}

func (s *Server) gatewayCatalog(_ context.Context, includeDisabled bool) ([]gatewayToolInfo, error) {
	result := make([]gatewayToolInfo, 0)

	// Prepend Shipyard's built-in management tools first.
	// Shipyard cannot be disabled at server level; only per-tool policy applies.
	for _, tool := range shipyardTools {
		toolEnabled := true
		if s.gateway != nil {
			toolEnabled = s.gateway.ToolEnabled("shipyard", tool.Name)
		}
		if !includeDisabled && !toolEnabled {
			continue
		}
		result = append(result, gatewayToolInfo{
			Name:          "shipyard__" + tool.Name,
			Server:        "shipyard",
			Tool:          tool.Name,
			Description:   tool.Description,
			InputSchema:   tool.InputSchema,
			ServerEnabled: true, // Shipyard server is always enabled
			ToolEnabled:   toolEnabled,
			Enabled:       toolEnabled,
		})
	}

	if s.proxies == nil {
		return result, nil
	}

	servers := s.proxies.Servers()
	for _, srv := range servers {
		if srv.Status != "online" {
			continue
		}
		// Read tools from the schema snapshot cache (populated by StartSchemaWatcher)
		// rather than making live RPC calls. Live RPC calls are avoided because the
		// HTTP request context may be cancelled by short-lived clients (e.g., the
		// bridge's 2-second HTTP timeout), which would silently drop all tools from
		// the catalog. The snapshot is kept fresh by the schema watcher. (SPEC-BUG-042)
		snapTools, _, err := s.store.GetLatestSnapshot(srv.Name)
		if err != nil {
			slog.Warn("gatewayCatalog: snapshot error", "server", srv.Name, "err", err)
			continue
		}
		for _, tool := range snapTools {
			serverEnabled := true
			toolEnabled := true
			effectiveEnabled := true
			if s.gateway != nil {
				serverEnabled = s.gateway.ServerEnabled(srv.Name)
				toolEnabled = s.gateway.ToolEnabled(srv.Name, tool.Name)
				effectiveEnabled = serverEnabled && toolEnabled
			}
			if !includeDisabled && !effectiveEnabled {
				continue
			}
			result = append(result, gatewayToolInfo{
				Name:          srv.Name + "__" + tool.Name,
				Server:        srv.Name,
				Tool:          tool.Name,
				Description:   tool.Description,
				InputSchema:   tool.InputSchema,
				ServerEnabled: serverEnabled,
				ToolEnabled:   toolEnabled,
				Enabled:       effectiveEnabled,
			})
		}
	}
	return result, nil
}

func (s *Server) fetchToolsResult(ctx context.Context, serverName string) (json.RawMessage, error) {
	if serverName == "shipyard" {
		return s.selfToolsResult()
	}
	return s.proxies.SendRequest(ctx, serverName, "tools/list", json.RawMessage("{}"))
}

func (s *Server) selfToolsResult() (json.RawMessage, error) {
	type toolInfo struct {
		Name        string          `json:"name"`
		Description string          `json:"description,omitempty"`
		InputSchema json.RawMessage `json:"inputSchema,omitempty"`
	}
	type toolsResult struct {
		Tools []toolInfo `json:"tools"`
	}

	result := toolsResult{Tools: make([]toolInfo, len(shipyardTools))}
	for i, tool := range shipyardTools {
		result.Tools[i] = toolInfo{
			Name:        tool.Name,
			Description: tool.Description,
			InputSchema: tool.InputSchema,
		}
	}

	return json.Marshal(map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      "shipyard-self-tools",
		"result":  result,
	})
}

// --- Session Recording Handlers (SPEC-007) ---

func (s *Server) handleSessionStart(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Name   string `json:"name"`
		Server string `json:"server"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	id, err := s.store.StartSession(req.Name, req.Server)
	if err != nil {
		slog.Error("start session", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	// Tell the manager to tag traffic for this server
	if s.proxies != nil {
		s.proxies.StartRecording(req.Server, id)
	}

	sess, err := s.store.GetSession(id)
	if err != nil {
		slog.Error("get session after start", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionStop(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	// Get session to find server name before stopping
	sess, err := s.store.GetSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	if err := s.store.StopSession(id); err != nil {
		http.Error(w, err.Error(), http.StatusConflict)
		return
	}

	// Stop recording in manager
	if s.proxies != nil {
		s.proxies.StopRecording(sess.Server)
	}

	sess, _ = s.store.GetSession(id)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionList(w http.ResponseWriter, r *http.Request) {
	server := r.URL.Query().Get("server")
	status := r.URL.Query().Get("status")

	sessions, err := s.store.ListSessions(server, status)
	if err != nil {
		slog.Error("list sessions", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sessions)
}

func (s *Server) handleSessionDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	sess, err := s.store.GetSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sess)
}

func (s *Server) handleSessionExport(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	cassette, err := s.store.ExportSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="session-%d.json"`, id))
	json.NewEncoder(w).Encode(cassette)
}

func (s *Server) handleSessionReplay(w http.ResponseWriter, r *http.Request) {
	if s.proxies == nil {
		http.Error(w, "no proxy manager configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	cassette, err := s.store.ExportSession(id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	var results []map[string]interface{}
	for _, entry := range cassette.Requests {
		if entry.Params == nil {
			continue // skip responses
		}
		params := entry.Params
		start := time.Now()
		result, sendErr := s.proxies.SendRequest(r.Context(), cassette.Server, entry.Method, params)
		elapsed := time.Since(start)

		res := map[string]interface{}{
			"method":     entry.Method,
			"latency_ms": elapsed.Milliseconds(),
		}
		if sendErr != nil {
			res["error"] = sendErr.Error()
		} else {
			res["result"] = json.RawMessage(result)
		}
		results = append(results, res)
	}

	if results == nil {
		results = []map[string]interface{}{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"session_id": id,
		"results":    results,
	})
}

func (s *Server) handleSessionDelete(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.store.DeleteSession(id); err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "deleted"})
}

func (s *Server) handleWebSocket(w http.ResponseWriter, r *http.Request) {
	conn, err := acceptWebSocket(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		slog.Error("websocket accept", "error", err)
		return
	}

	client := &Client{
		conn: conn,
		send: make(chan []byte, 256),
	}

	s.hub.Register(client)
	defer s.hub.Unregister(client)

	ctx := r.Context()

	// Writer goroutine
	go func() {
		defer conn.CloseNow()
		for {
			select {
			case msg, ok := <-client.send:
				if !ok {
					return
				}
				err := conn.Write(ctx, websocket.MessageText, msg)
				if err != nil {
					return
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	// Reader goroutine (just drain to detect close)
	for {
		_, _, err := conn.Read(ctx)
		if err != nil {
			break
		}
	}
}

// --- Latency Profiling Handlers ---

func (s *Server) handleProfilingSummary(w http.ResponseWriter, r *http.Request) {
	rangeStr := r.URL.Query().Get("range")
	if rangeStr == "" {
		rangeStr = "24h"
	}
	server := r.URL.Query().Get("server")

	result, err := s.store.ProfilingSummary(rangeStr, server)
	if err != nil {
		slog.Error("profiling summary", "error", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

func (s *Server) handleProfilingTools(w http.ResponseWriter, r *http.Request) {
	rangeStr := r.URL.Query().Get("range")
	if rangeStr == "" {
		rangeStr = "24h"
	}
	server := r.URL.Query().Get("server")
	sortBy := r.URL.Query().Get("sort")
	if sortBy == "" {
		sortBy = "p95"
	}
	order := r.URL.Query().Get("order")
	if order == "" {
		order = "desc"
	}

	result, err := s.store.ProfilingByTool(rangeStr, server, sortBy, order)
	if err != nil {
		slog.Error("profiling tools", "error", err)
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	if result == nil {
		result = []capture.ToolProfile{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

// --- Schema Change Detection Handlers ---

func (s *Server) handleSchemaChanges(w http.ResponseWriter, r *http.Request) {
	server := r.URL.Query().Get("server")
	changes, err := s.store.ListSchemaChanges(server)
	if err != nil {
		slog.Error("list schema changes", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(changes)
}

func (s *Server) handleSchemaChangeDetail(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	detail, err := s.store.GetSchemaChange(id)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(detail)
}

func (s *Server) handleSchemaAcknowledge(w http.ResponseWriter, r *http.Request) {
	idStr := r.PathValue("id")
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.store.AcknowledgeSchemaChange(id); err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "acknowledged"})
}

func (s *Server) handleSchemaCurrentTools(w http.ResponseWriter, r *http.Request) {
	server := r.PathValue("server")
	if server == "" {
		http.Error(w, "server name required", http.StatusBadRequest)
		return
	}

	tools, _, err := s.store.GetLatestSnapshot(server)
	if err != nil {
		slog.Error("get latest snapshot", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if tools == nil {
		tools = []capture.ToolSchema{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tools)
}

func (s *Server) handleSchemaUnackCount(w http.ResponseWriter, r *http.Request) {
	count, err := s.store.UnacknowledgedCount()
	if err != nil {
		slog.Error("unacknowledged count", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]int{"count": count})
}

// --- Token Admin API ---

// requireAdminAuth checks that the request carries a valid bootstrap token or admin token.
// Returns false and writes an error response if auth fails.
func (s *Server) requireAdminAuth(w http.ResponseWriter, r *http.Request) bool {
	if s.authStore == nil {
		// Auth not configured — allow
		return true
	}
	v := r.Header.Get("Authorization")
	if !strings.HasPrefix(v, "Bearer ") {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return false
	}
	tok := strings.TrimPrefix(v, "Bearer ")

	// Check bootstrap token first
	if s.authStore.AuthenticateBootstrap(tok) {
		return true
	}
	// Then check admin token. Token administration requires unrestricted scope.
	rec, err := s.authStore.Authenticate(tok)
	if err != nil || !auth.MatchScope(rec.Scopes, "*", "*") {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return false
	}
	return true
}

func (s *Server) handleTokenCreate(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<16))
	if err != nil {
		http.Error(w, "read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Name            string   `json:"name"`
		Scopes          []string `json:"scopes"`
		RateLimitPerMin int      `json:"rate_limit_per_minute"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Name == "" {
		http.Error(w, "name required", http.StatusBadRequest)
		return
	}
	if req.Scopes == nil {
		req.Scopes = []string{}
	}

	plaintext, id, err := s.authStore.GenerateToken(req.Name, req.RateLimitPerMin, req.Scopes)
	if err != nil {
		slog.Error("generate token", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]interface{}{
		"id":    id,
		"token": plaintext, // shown exactly once
		"name":  req.Name,
	})
}

func (s *Server) handleTokenList(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	tokens, err := s.authStore.ListTokens()
	if err != nil {
		slog.Error("list tokens", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	if tokens == nil {
		tokens = []auth.TokenRecord{}
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(tokens)
}

func (s *Server) handleTokenDelete(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	if err := s.authStore.DeleteToken(id); err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("delete token", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) handleTokenUpdateScopes(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<16))
	if err != nil {
		http.Error(w, "read body", http.StatusBadRequest)
		return
	}

	var req struct {
		Scopes []string `json:"scopes"`
	}
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Scopes == nil {
		req.Scopes = []string{}
	}

	if err := s.authStore.UpdateScopes(id, req.Scopes); err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("update scopes", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "updated"})
}

func (s *Server) handleTokenStats(w http.ResponseWriter, r *http.Request) {
	if !s.requireAdminAuth(w, r) {
		return
	}
	if s.authStore == nil {
		http.Error(w, "auth not configured", http.StatusServiceUnavailable)
		return
	}

	idStr := r.PathValue("id")
	var id int64
	if _, err := fmt.Sscanf(idStr, "%d", &id); err != nil {
		http.Error(w, "invalid id", http.StatusBadRequest)
		return
	}

	stats, err := s.authStore.GetStats(id)
	if err != nil {
		if strings.Contains(err.Error(), "not found") {
			http.Error(w, "token not found", http.StatusNotFound)
			return
		}
		slog.Error("get token stats", "error", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

// handleMCPPassthrough forwards MCP JSON-RPC to the appropriate child server without auth.
// Used when auth.enabled is false. Expects tool names in "server__tool" format for tools/call.
func (s *Server) handleMCPPassthrough(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		writeJSONRPCError(w, nil, -32700, "failed to read request body")
		return
	}

	var rpcReq struct {
		ID     json.RawMessage `json:"id"`
		Method string          `json:"method"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.Unmarshal(body, &rpcReq); err != nil {
		writeJSONRPCError(w, nil, -32700, "parse error")
		return
	}

	switch rpcReq.Method {
	case "initialize":
		// SPEC-029 R7: declare listChanged: true in the gateway-level initialize response.
		// Handled before the proxies nil check — initialize does not require child servers.
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"jsonrpc": "2.0",
			"id":      json.RawMessage(rpcReq.ID),
			"result": map[string]interface{}{
				"protocolVersion": "2025-11-25",
				"serverInfo": map[string]string{
					"name":    "shipyard-relay",
					"version": "0.1.0",
				},
				"capabilities": map[string]interface{}{
					"tools": map[string]bool{"listChanged": true},
				},
			},
		})
		return

	case "tools/list":
		// Build a merged tools/list: Shipyard tools first, then child server tools.
		var allTools []map[string]interface{}
		// Prepend Shipyard built-in tools.
		for _, tool := range shipyardTools {
			toolEnabled := true
			if s.gateway != nil {
				toolEnabled = s.gateway.ToolEnabled("shipyard", tool.Name)
			}
			if !toolEnabled {
				continue
			}
			var schema map[string]interface{}
			_ = json.Unmarshal(tool.InputSchema, &schema)
			allTools = append(allTools, map[string]interface{}{
				"name":        "shipyard__" + tool.Name,
				"description": tool.Description,
				"inputSchema": schema,
			})
		}
		// Append tools from all child servers, filtering by gateway policy (SPEC-028).
		var childServerNames []string
		if s.proxies != nil {
			childServerNames = s.proxies.ServersForAuth()
		}
		for _, name := range childServerNames {
			// Skip entire server if gateway-disabled
			if s.gateway != nil && !s.gateway.ServerEnabled(name) {
				continue
			}
			raw, err := s.proxies.SendRequest(r.Context(), name, "tools/list", json.RawMessage("{}"))
			if err != nil {
				continue
			}
			var resp struct {
				Result struct {
					Tools []json.RawMessage `json:"tools"`
				} `json:"result"`
			}
			if err := json.Unmarshal(raw, &resp); err != nil {
				continue
			}
			for _, rawTool := range resp.Result.Tools {
				var toolObj map[string]interface{}
				if err := json.Unmarshal(rawTool, &toolObj); err != nil {
					continue
				}
				toolName, _ := toolObj["name"].(string)
				if toolName == "" {
					continue
				}
				// Skip tool if tool-level disabled
				if s.gateway != nil && !s.gateway.ToolEnabled(name, toolName) {
					continue
				}
				toolObj["name"] = name + "__" + toolName
				allTools = append(allTools, toolObj)
			}
		}
		if allTools == nil {
			allTools = []map[string]interface{}{}
		}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"jsonrpc": "2.0",
			"id":      json.RawMessage(rpcReq.ID),
			"result":  map[string]interface{}{"tools": allTools},
		})
		return

	case "tools/call":
		// Check if the tool name has the shipyard__ prefix and route internally.
		var callParams struct {
			Name      string          `json:"name"`
			Arguments json.RawMessage `json:"arguments"`
		}
		if err := json.Unmarshal(rpcReq.Params, &callParams); err == nil {
			if strings.HasPrefix(callParams.Name, "shipyard__") {
				toolName := strings.TrimPrefix(callParams.Name, "shipyard__")
				// Check shipyard tool-level gateway policy (SPEC-029: -32602 Unknown tool)
				if s.gateway != nil && !s.gateway.ToolEnabled("shipyard", toolName) {
					writeJSONRPCError(w, rpcReq.ID, -32602, fmt.Sprintf("Unknown tool: %s", callParams.Name))
					return
				}
				result, err := s.dispatchShipyardTool(r.Context(), toolName, callParams.Arguments)
				if err != nil {
					writeJSONRPCError(w, rpcReq.ID, -32603, err.Error())
					return
				}
				resultBytes, _ := json.Marshal(result)
				w.Header().Set("Content-Type", "application/json")
				resp := map[string]interface{}{
					"jsonrpc": "2.0",
					"id":      json.RawMessage(rpcReq.ID),
					"result":  json.RawMessage(resultBytes),
				}
				json.NewEncoder(w).Encode(resp)
				return
			}
			// For non-shipyard tools in server__tool format: enforce gateway policy,
			// then route directly to the correct child server (stripping the prefix).
			if strings.Contains(callParams.Name, "__") {
				parts := strings.SplitN(callParams.Name, "__", 2)
				srvName, toolName := parts[0], parts[1]
				if s.gateway != nil {
					if !s.gateway.ServerEnabled(srvName) {
						// SPEC-029: -32602 Unknown tool (disabled server = tools don't exist)
						writeJSONRPCError(w, rpcReq.ID, -32602, fmt.Sprintf("Unknown tool: %s", callParams.Name))
						return
					}
					if !s.gateway.ToolEnabled(srvName, toolName) {
						// SPEC-029: -32602 Unknown tool (disabled tool = doesn't exist)
						writeJSONRPCError(w, rpcReq.ID, -32602, fmt.Sprintf("Unknown tool: %s", callParams.Name))
						return
					}
				}
				if s.proxies == nil {
					writeJSONRPCError(w, rpcReq.ID, -32603, "no proxy manager configured")
					return
				}
				// Route to the correct child server with the bare tool name (no prefix).
				childParams, err := json.Marshal(map[string]interface{}{
					"name":      toolName,
					"arguments": callParams.Arguments,
				})
				if err != nil {
					writeJSONRPCError(w, rpcReq.ID, -32603, "failed to build child request")
					return
				}
				result, err := s.proxies.SendRequest(r.Context(), srvName, "tools/call", childParams)
				if err != nil {
					writeJSONRPCError(w, rpcReq.ID, -32603, fmt.Sprintf("upstream error: %v", err))
					return
				}
				w.Header().Set("Content-Type", "application/json")
				w.Write(result)
				return
			}
		}
	}

	// Methods below this point require a proxy manager.
	if s.proxies == nil {
		writeJSONRPCError(w, rpcReq.ID, -32603, "no proxy manager configured")
		return
	}

	// For passthrough we forward to the server named in params, or "default".
	serverName := extractPassthroughServer(rpcReq.Params)
	if serverName == "" {
		// Try to find any online server
		names := s.proxies.ServersForAuth()
		if len(names) == 0 {
			writeJSONRPCError(w, rpcReq.ID, -32603, "no servers available")
			return
		}
		serverName = names[0]
	}

	result, err := s.proxies.SendRequest(r.Context(), serverName, rpcReq.Method, rpcReq.Params)
	if err != nil {
		writeJSONRPCError(w, rpcReq.ID, -32603, fmt.Sprintf("upstream error: %v", err))
		return
	}

	w.Header().Set("Content-Type", "application/json")
	w.Write(result)
}

func extractPassthroughServer(params json.RawMessage) string {
	if len(params) == 0 {
		return ""
	}
	var p struct {
		Server string `json:"server"`
	}
	_ = json.Unmarshal(params, &p)
	return p.Server
}

func writeJSONRPCError(w http.ResponseWriter, id json.RawMessage, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	resp := map[string]interface{}{
		"jsonrpc": "2.0",
		"error": map[string]interface{}{
			"code":    code,
			"message": message,
		},
	}
	if id != nil {
		resp["id"] = json.RawMessage(id)
	} else {
		resp["id"] = nil
	}
	json.NewEncoder(w).Encode(resp)
}

// handleAccessLog handles GET /api/access-log with optional filters and pagination.
func (s *Server) handleAccessLog(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}

	q := r.URL.Query()
	filter := capture.AccessLogFilter{
		TokenName:  q.Get("token_name"),
		ServerName: q.Get("server_name"),
		ToolName:   q.Get("tool_name"),
		Status:     q.Get("status"),
	}

	if fromStr := q.Get("from"); fromStr != "" {
		if t, err := time.Parse(time.RFC3339, fromStr); err == nil {
			filter.From = t
		}
	}
	if toStr := q.Get("to"); toStr != "" {
		if t, err := time.Parse(time.RFC3339, toStr); err == nil {
			filter.To = t
		}
	}

	if offsetStr := q.Get("offset"); offsetStr != "" {
		if v, err := strconv.Atoi(offsetStr); err == nil && v >= 0 {
			filter.Offset = v
		}
	}
	if limitStr := q.Get("limit"); limitStr != "" {
		if v, err := strconv.Atoi(limitStr); err == nil && v > 0 {
			filter.Limit = v
		}
	}

	page, err := s.store.GetAccessLog(filter)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(page)
}

// handleAccessLogStats handles GET /api/access-log/stats.
func (s *Server) handleAccessLogStats(w http.ResponseWriter, r *http.Request) {
	if s.store == nil {
		http.Error(w, "no store configured", http.StatusServiceUnavailable)
		return
	}

	stats, err := s.store.GetAccessLogStats()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

// settingsSecretsRequest is the shape of the secrets sub-object in settings API calls.
type settingsSecretsRequest struct {
	Backend string `json:"backend"`
}

// settingsResponse is the shape returned by GET /api/settings.
type settingsResponse struct {
	Secrets settingsSecretsRequest `json:"secrets"`
}

// handleSettingsGet handles GET /api/settings.
// Returns current application settings (currently: secrets.backend).
func (s *Server) handleSettingsGet(w http.ResponseWriter, r *http.Request) {
	backend := ""
	if s.settingsStore != nil {
		backend = s.settingsStore.SecretsBackend()
	}
	resp := settingsResponse{
		Secrets: settingsSecretsRequest{Backend: backend},
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(resp)
}

// handleSettingsPost handles POST /api/settings.
// Accepts {"secrets":{"backend":"..."}} and updates the in-memory settings.
// Valid backend values: "keychain", "1password", "env", "".
func (s *Server) handleSettingsPost(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Secrets *settingsSecretsRequest `json:"secrets"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	if req.Secrets == nil {
		http.Error(w, "missing secrets field", http.StatusBadRequest)
		return
	}

	allowed := map[string]bool{"keychain": true, "1password": true, "env": true, "": true}
	if !allowed[req.Secrets.Backend] {
		http.Error(w, "invalid backend value", http.StatusBadRequest)
		return
	}

	if s.settingsStore != nil {
		s.settingsStore.SetSecretsBackend(req.Secrets.Backend)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}
