//go:build mcpgap

// SPEC-BUG-181 gap suite (unauthenticated /mcp passthrough surface). EXPECTED
// TO FAIL until the owning child spec closes the gap. Compiled only with
// `-tags mcpgap`; never part of `go test ./...` or CI.
package web

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// G2: the passthrough initialize/discovery surface never offers 2026-07-28.
func TestMCPGap_G2_PassthroughDiscoverOffersModern(t *testing.T) {
	srv := newTestServer(t)
	srv.SetProxyManager(&mockProxyManager{
		servers: []ServerInfo{},
		sendFunc: func(context.Context, string, string, json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`{"jsonrpc":"2.0","id":1,"result":{}}`), nil
		},
	})

	body := `{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{` +
		`"io.modelcontextprotocol/protocolVersion":"2026-07-28",` +
		`"io.modelcontextprotocol/clientCapabilities":{}}}}`
	req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set(mcpcore.HeaderProtocolVersion, mcpcore.ModernVersion)
	w := httptest.NewRecorder()
	srv.handleMCPPassthrough(w, req)

	var resp struct {
		Result struct {
			SupportedVersions []string `json:"supportedVersions"`
		} `json:"result"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if !slices.Contains(resp.Result.SupportedVersions, mcpcore.ModernVersion) {
		t.Errorf("G2: passthrough %s did not offer %q; status %d body %s", mcpcore.MethodDiscover, mcpcore.ModernVersion, w.Code, w.Body.String())
	}
}
