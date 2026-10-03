//go:build mcpgap

// SPEC-BUG-181 gap suite (stdio bridge surface). EXPECTED TO FAIL until the
// owning child spec closes the gap. Compiled only with `-tags mcpgap`; never
// part of `go test ./...` or CI.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// G2: the bridge's initialize/discovery surface never offers 2026-07-28.
func TestMCPGap_G2_BridgeDiscoverOffersModern(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	t.Cleanup(api.Close)

	in := strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{` +
		`"io.modelcontextprotocol/protocolVersion":"2026-07-28",` +
		`"io.modelcontextprotocol/clientCapabilities":{}}}}` + "\n")
	var out bytes.Buffer
	if err := run(context.Background(), in, &out, &bytes.Buffer{}, []string{"--api-base", api.URL}); err != nil {
		t.Fatalf("run: %v", err)
	}

	var resp struct {
		Result struct {
			SupportedVersions []string `json:"supportedVersions"`
		} `json:"result"`
	}
	line, _, _ := strings.Cut(out.String(), "\n")
	_ = json.Unmarshal([]byte(line), &resp)
	if !slices.Contains(resp.Result.SupportedVersions, mcpcore.ModernVersion) {
		t.Errorf("G2: bridge %s did not offer %q; output %q", mcpcore.MethodDiscover, mcpcore.ModernVersion, out.String())
	}
}
