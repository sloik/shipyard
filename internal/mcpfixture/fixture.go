// Package mcpfixture provides modern (2026-07-28) and legacy (2025-11-25)
// MCP fixture servers and clients built on the official Go SDK, a recording
// HTTP transport, and the conformance-scenario surface used by
// scripts/mcp-conformance.sh.
//
// The modern fixture supports only 2026-07-28 and serves stateless streamable
// HTTP; the legacy fixture supports every pre-2026 version and serves
// stateful streamable HTTP with Mcp-Session-Id. Nothing here is wired into
// Shipyard's live gateway, bridge, or child handling.
package mcpfixture

import (
	"context"
	"fmt"
	"net/http"
	"os/exec"
	"strings"
	"sync"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// SDKVersion is the pinned go-sdk version the fixtures and waivers track.
const SDKVersion = "v1.8.0"

// Fixture-specific tool names (in addition to the conformance surface).
const (
	// ToolEchoMeta echoes the request's _meta back in the result's _meta.
	ToolEchoMeta = "fixture_echo_meta"
	// ToolError returns a tool-level error result (isError: true).
	ToolError = "fixture_error"
	// ToolSlow blocks until its request is cancelled.
	ToolSlow = "fixture_slow"
)

// fixtureImpl identifies the fixture server and client on the wire.
var fixtureImpl = &mcp.Implementation{Name: "shipyard-mcp-fixture", Version: "1.0.0"}

// VersionFor returns the protocol version a fixture of the given era speaks.
func VersionFor(era mcpcore.Era) string {
	switch era {
	case mcpcore.EraModern:
		return mcpcore.ModernVersion
	case mcpcore.EraLegacy:
		return mcpcore.LegacyVersion
	default:
		return ""
	}
}

// ParseEra parses "modern" or "legacy".
func ParseEra(s string) (mcpcore.Era, error) {
	switch s {
	case "modern":
		return mcpcore.EraModern, nil
	case "legacy":
		return mcpcore.EraLegacy, nil
	default:
		return mcpcore.EraUnknown, fmt.Errorf("unknown era %q (want modern or legacy)", s)
	}
}

// eraVersions lists the protocol versions a fixture server of the era accepts.
func eraVersions(era mcpcore.Era) []string {
	var out []string
	for _, v := range mcpcore.SupportedVersions() {
		if e, _ := mcpcore.EraForVersion(v); e == era {
			out = append(out, v)
		}
	}
	return out
}

// Observer lets tests watch the slow tool's lifecycle on the server side.
type Observer struct {
	startOnce, cancelOnce, releaseOnce sync.Once
	started, cancelled, release        chan struct{}
}

// NewObserver returns an Observer with unsignalled channels.
func NewObserver() *Observer {
	return &Observer{started: make(chan struct{}), cancelled: make(chan struct{}), release: make(chan struct{})}
}

// Release lets any in-flight slow tool call return normally. It is used to
// tear down a server whose transport never delivers cancellation.
func (o *Observer) Release() { o.releaseOnce.Do(func() { close(o.release) }) }

func (o *Observer) releaseCh() <-chan struct{} {
	if o == nil {
		return nil
	}
	return o.release
}

// Started is closed when the slow tool begins executing.
func (o *Observer) Started() <-chan struct{} { return o.started }

// Cancelled is closed when the slow tool observes its request's cancellation.
func (o *Observer) Cancelled() <-chan struct{} { return o.cancelled }

func (o *Observer) markStarted() {
	if o != nil {
		o.startOnce.Do(func() { close(o.started) })
	}
}

func (o *Observer) markCancelled() {
	if o != nil {
		o.cancelOnce.Do(func() { close(o.cancelled) })
	}
}

// NewServer builds a fixture server restricted to the era's protocol
// versions, with the conformance surface and the fixture tools registered.
func NewServer(era mcpcore.Era, obs *Observer) *mcp.Server {
	server := mcp.NewServer(fixtureImpl, &mcp.ServerOptions{
		SupportedProtocolVersions: eraVersions(era),
		CompletionHandler:         completionHandler,
		SubscribeHandler:          func(context.Context, *mcp.SubscribeRequest) error { return nil },
		UnsubscribeHandler:        func(context.Context, *mcp.UnsubscribeRequest) error { return nil },
	})
	registerConformanceSurface(server)
	registerFixtureTools(server, obs)
	return server
}

// NewHandler serves a fixture server over streamable HTTP: stateless for the
// modern era, stateful (session-bearing) for the legacy era.
func NewHandler(era mcpcore.Era, obs *Observer) http.Handler {
	server := NewServer(era, obs)
	return mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server },
		&mcp.StreamableHTTPOptions{Stateless: era == mcpcore.EraModern})
}

// Connect connects a fixture client of the given era to a streamable HTTP
// endpoint. httpClient may be nil.
func Connect(ctx context.Context, era mcpcore.Era, endpoint string, httpClient *http.Client) (*mcp.ClientSession, error) {
	return connect(ctx, era, endpoint, httpClient, connectOptions{disableStandaloneSSE: true})
}

// connectOptions tunes the fixture client. Golden tests disable the
// standalone SSE stream so recorded traffic is deterministic; conformance
// scenarios keep the SDK default.
type connectOptions struct {
	client               *mcp.ClientOptions
	oauth                oauthHandler
	disableStandaloneSSE bool
}

func connect(ctx context.Context, era mcpcore.Era, endpoint string, httpClient *http.Client, o connectOptions) (*mcp.ClientSession, error) {
	if era == mcpcore.EraUnknown {
		return nil, fmt.Errorf("connect: unknown era")
	}
	transport := &mcp.StreamableClientTransport{
		Endpoint:             endpoint,
		HTTPClient:           httpClient,
		DisableStandaloneSSE: o.disableStandaloneSSE,
	}
	if o.oauth != nil {
		transport.OAuthHandler = o.oauth
	}
	cs, err := mcp.NewClient(fixtureImpl, o.client).Connect(ctx, transport, &mcp.ClientSessionOptions{ProtocolVersion: VersionFor(era)})
	if err != nil {
		return nil, fmt.Errorf("connect %s fixture client: %w", era, err)
	}
	return cs, nil
}

// sdkModuleDir locates the pinned go-sdk module in the module cache.
func sdkModuleDir() (string, error) {
	out, err := exec.Command("go", "list", "-m", "-f", "{{.Dir}}", "github.com/modelcontextprotocol/go-sdk").Output()
	if err != nil {
		return "", fmt.Errorf("go list go-sdk: %w", err)
	}
	return strings.TrimSpace(string(out)), nil
}
