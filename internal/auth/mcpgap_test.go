//go:build mcpgap

// SPEC-BUG-181 gap suite (HTTP gateway surface). These cases describe the
// target MCP 2026-07-28 behaviour and are EXPECTED TO FAIL until the owning
// child spec closes the gap. They are compiled only with `-tags mcpgap` and
// are never part of `go test ./...` or CI. Run: scripts/mcp-gap-suite.sh.
package auth

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

func gapHandler(t *testing.T) (*MCPHandler, *mockProxy, string) {
	t.Helper()
	h, store := newTestMCPHandler(t, "bootstrap")
	token, _, err := store.GenerateToken("gap", 0, []string{"*:*"})
	if err != nil {
		t.Fatalf("GenerateToken: %v", err)
	}
	return h, h.proxies.(*mockProxy), token
}

func gapPOST(t *testing.T, h http.Handler, body, token string, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json, text/event-stream")
	req.Header.Set("Authorization", "Bearer "+token)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	return w
}

func modernDiscoverBody() string {
	return `{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{` +
		`"io.modelcontextprotocol/protocolVersion":"2026-07-28",` +
		`"io.modelcontextprotocol/clientCapabilities":{},` +
		`"io.modelcontextprotocol/clientInfo":{"name":"gap","version":"1"}}}}`
}

// G2: Shipyard's own initialize/discovery surfaces never offer 2026-07-28.
func TestMCPGap_G2_GatewayDiscoverOffersModern(t *testing.T) {
	h, _, token := gapHandler(t)
	w := gapPOST(t, h, modernDiscoverBody(), token, map[string]string{mcpcore.HeaderProtocolVersion: mcpcore.ModernVersion})

	var resp struct {
		Result struct {
			SupportedVersions []string `json:"supportedVersions"`
		} `json:"result"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if !slices.Contains(resp.Result.SupportedVersions, mcpcore.ModernVersion) {
		t.Errorf("G2: gateway %s did not offer %q; status %d body %s", mcpcore.MethodDiscover, mcpcore.ModernVersion, w.Code, w.Body.String())
	}
}

// G3: the HTTP gateway issues Mcp-Session-Id unconditionally. Target: a client
// that negotiates the stateless modern era never receives a session header.
// The only assertion is on the header; how the client connects (discover or
// its legacy fallback) is whatever the gateway's current surface forces.
func TestMCPGap_G3_ModernClientReceivesNoSessionHeader(t *testing.T) {
	h, _, token := gapHandler(t)
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)

	rec := &sessionHeaderRecorder{base: http.DefaultTransport, token: token}
	client := mcp.NewClient(&mcp.Implementation{Name: "gap-g3", Version: "1"}, nil)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cs, err := client.Connect(ctx, &mcp.StreamableClientTransport{
		Endpoint:             srv.URL,
		HTTPClient:           &http.Client{Transport: rec},
		DisableStandaloneSSE: true,
	}, &mcp.ClientSessionOptions{ProtocolVersion: mcpcore.ModernVersion})
	if err == nil {
		_, _ = cs.ListTools(ctx, nil)
		_ = cs.Close()
	}

	requests, sessionIDs := rec.snapshot()
	if requests == 0 {
		t.Fatal("G3: harness sent no requests to the gateway")
	}
	if len(sessionIDs) > 0 {
		t.Errorf("G3: gateway issued %s %q to a client negotiating the modern era (%s); modern-era requests are stateless",
			mcpcore.HeaderSessionID, sessionIDs[0], mcpcore.ModernVersion)
	}
}

// G4: no code reads or sets MCP-Protocol-Version. Target: a request carrying an
// unsupported protocol-version header is rejected with HTTP 400.
func TestMCPGap_G4_UnsupportedProtocolVersionHeaderRejected(t *testing.T) {
	h, _, token := gapHandler(t)
	w := gapPOST(t, h, `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, token,
		map[string]string{mcpcore.HeaderProtocolVersion: "1999-01-01"})
	if w.Code != http.StatusBadRequest {
		t.Errorf("G4: request with %s: 1999-01-01 got HTTP %d, want %d; body %s", mcpcore.HeaderProtocolVersion, w.Code, http.StatusBadRequest, w.Body.String())
	}
}

// G5: the JSON-RPC envelope is hand-coded with no shared validator. Target: an
// envelope that is not JSON-RPC 2.0 is rejected with -32600 Invalid Request.
func TestMCPGap_G5_InvalidEnvelopeRejected(t *testing.T) {
	h, _, token := gapHandler(t)
	w := gapPOST(t, h, `{"jsonrpc":"1.0","id":1,"method":"tools/list","params":{}}`, token, nil)
	var resp struct {
		Error *struct {
			Code int `json:"code"`
		} `json:"error"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if resp.Error == nil || resp.Error.Code != -32600 {
		t.Errorf("G5: non-2.0 envelope was not rejected with -32600; body %s", w.Body.String())
	}
}

// G6: _meta has no explicit pass-through. Target: request _meta reaches the
// child unchanged on tools/call.
func TestMCPGap_G6_MetaPassedThroughToChild(t *testing.T) {
	h, proxy, token := gapHandler(t)
	var (
		mu         sync.Mutex
		downstream json.RawMessage
	)
	proxy.sendFunc = func(_ context.Context, _, method string, params json.RawMessage) (json.RawMessage, error) {
		if method == "tools/call" {
			mu.Lock()
			downstream = append(json.RawMessage(nil), params...)
			mu.Unlock()
		}
		return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{"content":[]}}`), nil
	}
	const meta = `{"progressToken":"p-1","x.example/trace":"t-1"}`
	gapPOST(t, h, `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"fs__read","arguments":{},"_meta":`+meta+`}}`, token, nil)

	mu.Lock()
	defer mu.Unlock()
	var got struct {
		Meta json.RawMessage `json:"_meta"`
	}
	_ = json.Unmarshal(downstream, &got)
	if !jsonEqual(got.Meta, json.RawMessage(meta)) {
		t.Errorf("G6: child received params %s; want _meta %s passed through", downstream, meta)
	}
}

func jsonEqual(a, b json.RawMessage) bool {
	var av, bv any
	if json.Unmarshal(a, &av) != nil || json.Unmarshal(b, &bv) != nil {
		return false
	}
	ab, _ := json.Marshal(av)
	bb, _ := json.Marshal(bv)
	return bytes.Equal(ab, bb)
}

type sessionHeaderRecorder struct {
	base  http.RoundTripper
	token string

	mu         sync.Mutex
	requests   int
	sessionIDs []string
}

func (r *sessionHeaderRecorder) RoundTrip(req *http.Request) (*http.Response, error) {
	req = req.Clone(req.Context())
	req.Header.Set("Authorization", "Bearer "+r.token)
	resp, err := r.base.RoundTrip(req)
	r.mu.Lock()
	defer r.mu.Unlock()
	r.requests++
	if err == nil {
		if id := resp.Header.Get(mcpcore.HeaderSessionID); id != "" {
			r.sessionIDs = append(r.sessionIDs, id)
		}
	}
	return resp, err
}

func (r *sessionHeaderRecorder) snapshot() (int, []string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.requests, slices.Clone(r.sessionIDs)
}
