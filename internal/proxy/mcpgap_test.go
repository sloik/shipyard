//go:build mcpgap

// SPEC-BUG-181 gap suite (proxy/manager surface). These cases describe the
// target MCP 2026-07-28 behaviour and are EXPECTED TO FAIL until the owning
// child spec closes the gap. They are compiled only with `-tags mcpgap` and
// are never part of `go test ./...` or CI. Run: scripts/mcp-gap-suite.sh.
package proxy

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// G1: managed children are always initialized with a fixed protocol version
// and no negotiation. Target: the first handshake message offers the newest
// version for its handshake style — server/discover with the modern version
// in _meta, or initialize with the newest legacy version.
func TestMCPGap_G1_ManagedChildVersionNegotiation(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)
	cw := newChildInputWriter()
	sink := newLineObserverWriteCloser()
	cw.attach(sink)
	mp.SetInputWriter(cw)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _ = m.SendRequest(ctx, "alpha", "tools/list", json.RawMessage(`{}`))
	}()
	t.Cleanup(func() { cancel(); <-done })

	var first string
	select {
	case first = <-sink.lines:
	case <-time.After(2 * time.Second):
		t.Fatal("G1: manager wrote no handshake message to the child")
	}

	method, offered := handshakeOffer(t, first)
	switch {
	case method == mcpcore.MethodDiscover && offered == mcpcore.ModernVersion:
	case method == "initialize" && offered == mcpcore.LegacyVersion:
	default:
		t.Errorf("G1: managed child handshake %s offered protocol version %q; want %s with %q or initialize with %q (negotiation)",
			method, offered, mcpcore.MethodDiscover, mcpcore.ModernVersion, mcpcore.LegacyVersion)
	}
}

// G7: notifications/cancelled is never forwarded deliberately. Target: when the
// caller abandons an in-flight child request, the child receives
// notifications/cancelled naming that request's ID.
func TestMCPGap_G7_CancellationForwardedToChild(t *testing.T) {
	m := NewManager()
	p, _ := newTestProxy(t)
	mp := m.Register("alpha", p)
	cw := newChildInputWriter()
	sink := newLineObserverWriteCloser()
	cw.attach(sink)
	mp.SetInputWriter(cw)
	mp.initReady = true

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _ = m.SendRequest(ctx, "alpha", "tools/call", json.RawMessage(`{"name":"slow","arguments":{}}`))
	}()

	var reqLine string
	select {
	case reqLine = <-sink.lines:
	case <-time.After(2 * time.Second):
		cancel()
		<-done
		t.Fatal("G7: manager wrote no tools/call request to the child")
	}
	var req struct {
		ID json.RawMessage `json:"id"`
	}
	if err := json.Unmarshal([]byte(reqLine), &req); err != nil {
		t.Fatalf("G7: unmarshal child request: %v", err)
	}

	cancel()
	<-done

	deadline := time.After(time.Second)
	for {
		select {
		case line := <-sink.lines:
			v := mcpcore.Ingest([]byte(line), nil).View()
			if id, ok := v.CancelledRequestID(); ok && string(id) == string(req.ID) {
				return
			}
		case <-deadline:
			t.Errorf("G7: child never received %s for abandoned request %s", mcpcore.MethodCancelled, req.ID)
			return
		}
	}
}

func handshakeOffer(t *testing.T, line string) (method, version string) {
	t.Helper()
	var msg struct {
		Method string `json:"method"`
		Params struct {
			ProtocolVersion string         `json:"protocolVersion"`
			Meta            map[string]any `json:"_meta"`
		} `json:"params"`
	}
	if err := json.Unmarshal([]byte(line), &msg); err != nil {
		t.Fatalf("unmarshal handshake %q: %v", line, err)
	}
	if v, ok := msg.Params.Meta[mcp.MetaKeyProtocolVersion].(string); ok {
		return msg.Method, v
	}
	return msg.Method, msg.Params.ProtocolVersion
}
