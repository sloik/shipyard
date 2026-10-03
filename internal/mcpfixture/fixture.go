// Package mcpfixture provides modern (2026-07-28) and legacy (2025-11-25)
// MCP fixture servers and clients built on the official Go SDK, a recording
// HTTP transport, and the conformance-scenario surface used by
// scripts/mcp-conformance.sh. Stub: implementation pending.
package mcpfixture

import (
	"context"
	"errors"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// SDKVersion is the pinned go-sdk version.
const SDKVersion = "v1.8.0"

// Fixture tool names.
const (
	ToolEchoMeta = "fixture_echo_meta"
	ToolError    = "fixture_error"
	ToolSlow     = "fixture_slow"
)

// Observer (stub).
type Observer struct{}

// NewObserver (stub).
func NewObserver() *Observer { return &Observer{} }

// Started (stub).
func (o *Observer) Started() <-chan struct{} { return nil }

// Cancelled (stub).
func (o *Observer) Cancelled() <-chan struct{} { return nil }

// NewHandler (stub).
func NewHandler(mcpcore.Era, *Observer) http.Handler { return http.NotFoundHandler() }

// Connect (stub).
func Connect(context.Context, mcpcore.Era, string, *http.Client) (*mcp.ClientSession, error) {
	return nil, errors.New("not implemented")
}

// VersionFor (stub).
func VersionFor(mcpcore.Era) string { return "" }

// ParseEra (stub).
func ParseEra(string) (mcpcore.Era, error) { return mcpcore.EraUnknown, nil }

// ClientScenarios (stub).
func ClientScenarios() []string { return nil }

// RunClientScenario (stub).
func RunClientScenario(context.Context, mcpcore.Era, string, string, map[string]any) error {
	return nil
}

func sdkModuleDir() (string, error) { return "", errors.New("not implemented") }

// Exchange (stub).
type Exchange struct {
	HTTPMethod      string
	Status          int
	RequestHeaders  http.Header
	ResponseHeaders http.Header
	Request         *mcpcore.Envelope
	Responses       []*mcpcore.Envelope
}

// Recorder (stub).
type Recorder struct{}

// NewRecorder (stub).
func NewRecorder(http.RoundTripper) *Recorder { return &Recorder{} }

// RoundTrip (stub).
func (r *Recorder) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, errors.New("not implemented")
}

// Exchanges (stub).
func (r *Recorder) Exchanges() []Exchange { return nil }

// NormalizeExchanges (stub).
func NormalizeExchanges([]Exchange) []byte { return nil }
