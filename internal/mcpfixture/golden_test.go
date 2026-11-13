package mcpfixture

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

var update = flag.Bool("update", false, "rewrite golden files under testdata/golden")

var eras = []mcpcore.Era{mcpcore.EraModern, mcpcore.EraLegacy}

type harness struct {
	t   *testing.T
	era mcpcore.Era
	obs *Observer
	rec *Recorder
	cs  *mcp.ClientSession
}

func newHarness(t *testing.T, era mcpcore.Era) *harness {
	t.Helper()
	obs := NewObserver()
	srv := httptest.NewServer(NewHandler(era, obs))
	t.Cleanup(srv.Close)
	t.Cleanup(obs.Release) // runs before srv.Close
	rec := NewRecorder(http.DefaultTransport)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	cs, err := Connect(ctx, era, srv.URL, &http.Client{Transport: rec})
	if err != nil {
		t.Fatalf("Connect(%v): %v", era, err)
	}
	t.Cleanup(func() { _ = cs.Close() })
	return &harness{t: t, era: era, obs: obs, rec: rec, cs: cs}
}

func ctxT(t *testing.T) context.Context {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// requestsByMethod returns the recorded exchanges whose request envelope has
// the given JSON-RPC method.
func requestsByMethod(exs []Exchange, method string) []Exchange {
	var out []Exchange
	for _, ex := range exs {
		if ex.Request != nil && ex.Request.View().Method == method {
			out = append(out, ex)
		}
	}
	return out
}

func onlyResult(t *testing.T, ex Exchange) json.RawMessage {
	t.Helper()
	for _, r := range ex.Responses {
		if v := r.View(); v.Kind == mcpcore.KindResponse {
			return v.Result
		}
	}
	t.Fatalf("exchange for %s has no result response: %d responses", ex.Request.View().Method, len(ex.Responses))
	return nil
}

func TestGolden_Discovery(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			if got := h.cs.InitializeResult().ProtocolVersion; got != VersionFor(era) {
				t.Fatalf("negotiated %q, want %q", got, VersionFor(era))
			}
			exs := h.rec.Exchanges()
			if len(exs) == 0 || exs[0].Request == nil {
				t.Fatal("no handshake recorded")
			}
			first := exs[0].Request.View()
			switch era {
			case mcpcore.EraModern:
				if first.Method != mcpcore.MethodDiscover {
					t.Fatalf("modern handshake method = %q, want %q", first.Method, mcpcore.MethodDiscover)
				}
				if len(requestsByMethod(exs, "initialize")) != 0 {
					t.Fatal("modern era must not fall back to initialize against the modern fixture")
				}
				var res struct {
					SupportedVersions []string `json:"supportedVersions"`
				}
				if err := json.Unmarshal(onlyResult(t, exs[0]), &res); err != nil {
					t.Fatal(err)
				}
				if !slices.Equal(res.SupportedVersions, []string{mcpcore.ModernVersion}) {
					t.Fatalf("supportedVersions = %v, want [%s]", res.SupportedVersions, mcpcore.ModernVersion)
				}
			case mcpcore.EraLegacy:
				if first.Method != "initialize" || first.ProtocolVersion != mcpcore.LegacyVersion {
					t.Fatalf("legacy handshake = %s offering %q, want initialize offering %q", first.Method, first.ProtocolVersion, mcpcore.LegacyVersion)
				}
			}
			checkGolden(t, "discovery-"+era.String(), exs[:1])
		})
	}
}

func TestGolden_MetaPassThrough(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			res, err := h.cs.CallTool(ctxT(t), &mcp.CallToolParams{
				Meta:      mcp.Meta{"x.example/trace": "t-1"},
				Name:      ToolEchoMeta,
				Arguments: map[string]any{},
			})
			if err != nil {
				t.Fatalf("CallTool: %v", err)
			}
			if got := res.Meta["x.example/trace"]; got != "t-1" {
				t.Fatalf("result _meta = %v, want the request's custom key echoed", res.Meta)
			}
			calls := requestsByMethod(h.rec.Exchanges(), "tools/call")
			if len(calls) != 1 {
				t.Fatalf("recorded %d tools/call exchanges, want 1", len(calls))
			}
			meta := calls[0].Request.View().Meta
			if string(meta["x.example/trace"]) != `"t-1"` {
				t.Fatalf("wire _meta = %v, want custom key", meta)
			}
			_, hasVersion := meta[mcp.MetaKeyProtocolVersion]
			if hasVersion != (era == mcpcore.EraModern) {
				t.Fatalf("wire _meta protocolVersion present=%v for era %v", hasVersion, era)
			}
			checkGolden(t, "meta-"+era.String(), calls)
		})
	}
}

func TestGolden_Errors(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			ctx := ctxT(t)
			if _, err := h.cs.CallTool(ctx, &mcp.CallToolParams{Name: "no_such_tool", Arguments: map[string]any{}}); err == nil {
				t.Fatal("unknown tool must return a JSON-RPC error")
			}
			res, err := h.cs.CallTool(ctx, &mcp.CallToolParams{Name: ToolError, Arguments: map[string]any{}})
			if err != nil {
				t.Fatalf("tool error must be a result, got protocol error %v", err)
			}
			if !res.IsError {
				t.Fatal("tool error result must set isError")
			}
			calls := requestsByMethod(h.rec.Exchanges(), "tools/call")
			if len(calls) != 2 {
				t.Fatalf("recorded %d tools/call exchanges, want 2", len(calls))
			}
			var sawError bool
			for _, r := range calls[0].Responses {
				if v := r.View(); v.Kind == mcpcore.KindError && v.ErrorCode != 0 {
					sawError = true
				}
			}
			if !sawError {
				t.Fatal("unknown tool did not produce a JSON-RPC error envelope on the wire")
			}
			for _, ex := range calls {
				for _, r := range ex.Responses {
					if err := mcpcore.Validate(r); err != nil {
						t.Fatalf("SDK response failed the shared validator: %v (%s)", err, r.Raw())
					}
				}
			}
			checkGolden(t, "errors-"+era.String(), calls)
		})
	}
}

func TestGolden_ResultAndCacheFields(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			if _, err := h.cs.ListTools(ctxT(t), nil); err != nil {
				t.Fatalf("ListTools: %v", err)
			}
			lists := requestsByMethod(h.rec.Exchanges(), "tools/list")
			if len(lists) != 1 {
				t.Fatalf("recorded %d tools/list exchanges, want 1", len(lists))
			}
			var fields map[string]json.RawMessage
			if err := json.Unmarshal(onlyResult(t, lists[0]), &fields); err != nil {
				t.Fatal(err)
			}
			// go-sdk v1.8.0 emits the SEP cache hints (ttlMs, cacheScope
			// normalized to "public") on list results in both eras; the
			// golden file pins the exact values.
			var scope string
			_ = json.Unmarshal(fields["cacheScope"], &scope)
			if _, hasTTL := fields["ttlMs"]; !hasTTL || scope != "public" {
				t.Fatalf("era %v: list result cache fields ttlMs=%s cacheScope=%s, want ttlMs present and cacheScope \"public\"", era, fields["ttlMs"], fields["cacheScope"])
			}
			if _, ok := fields["tools"]; !ok {
				t.Fatal("tools/list result has no tools field")
			}
			checkGolden(t, "result-cache-"+era.String(), lists)
		})
	}
}

func TestGolden_RoutingHeaders(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			if _, err := h.cs.CallTool(ctxT(t), &mcp.CallToolParams{Name: ToolEchoMeta, Arguments: map[string]any{}}); err != nil {
				t.Fatalf("CallTool: %v", err)
			}
			calls := requestsByMethod(h.rec.Exchanges(), "tools/call")
			if len(calls) != 1 {
				t.Fatalf("recorded %d tools/call exchanges, want 1", len(calls))
			}
			hdr := calls[0].RequestHeaders
			if got := hdr.Get(mcpcore.HeaderProtocolVersion); got != VersionFor(era) {
				t.Fatalf("%s = %q, want %q", mcpcore.HeaderProtocolVersion, got, VersionFor(era))
			}
			switch era {
			case mcpcore.EraModern:
				if hdr.Get(mcpcore.HeaderMethod) != "tools/call" || hdr.Get(mcpcore.HeaderName) != ToolEchoMeta {
					t.Fatalf("modern routing headers = %s=%q %s=%q", mcpcore.HeaderMethod, hdr.Get(mcpcore.HeaderMethod), mcpcore.HeaderName, hdr.Get(mcpcore.HeaderName))
				}
			case mcpcore.EraLegacy:
				if hdr.Get(mcpcore.HeaderMethod) != "" || hdr.Get(mcpcore.HeaderName) != "" {
					t.Fatalf("legacy era must not send modern routing headers: %v", hdr)
				}
			}
			checkGolden(t, "routing-headers-"+era.String(), calls)
		})
	}
}

func TestGolden_Cancellation(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			ctx, cancel := context.WithCancel(ctxT(t))
			errCh := make(chan error, 1)
			go func() {
				_, err := h.cs.CallTool(ctx, &mcp.CallToolParams{Name: ToolSlow, Arguments: map[string]any{}})
				errCh <- err
			}()
			select {
			case <-h.obs.Started():
			case <-time.After(5 * time.Second):
				t.Fatal("slow tool never started")
			}
			cancel()
			if err := <-errCh; err == nil {
				t.Fatal("cancelled call must return an error")
			}
			// Legacy (stateful) servers route notifications/cancelled to the
			// in-flight call. go-sdk v1.8.0 stateless (modern) servers start a
			// fresh session per request, so the notification cannot reach the
			// original call and the handler is not cancelled; the wire
			// notification below is still asserted for both eras.
			if era == mcpcore.EraLegacy {
				select {
				case <-h.obs.Cancelled():
				case <-time.After(5 * time.Second):
					t.Fatal("legacy server handler never observed cancellation")
				}
			}

			var cancelled []Exchange
			deadline := time.Now().Add(5 * time.Second)
			// The notification is sent asynchronously; wait until its HTTP
			// round trip has completed so the recorded status is final.
			for time.Now().Before(deadline) {
				cancelled = requestsByMethod(h.rec.Exchanges(), mcpcore.MethodCancelled)
				if len(cancelled) > 0 && cancelled[0].Status != 0 {
					break
				}
				time.Sleep(10 * time.Millisecond)
			}
			if len(cancelled) != 1 {
				t.Fatalf("recorded %d %s notifications, want 1", len(cancelled), mcpcore.MethodCancelled)
			}
			call := requestsByMethod(h.rec.Exchanges(), "tools/call")[0].Request.View()
			id, ok := cancelled[0].Request.View().CancelledRequestID()
			if !ok || string(id) != string(call.ID) {
				t.Fatalf("cancellation names request %s, want %s", id, call.ID)
			}
			checkGolden(t, "cancellation-"+era.String(), cancelled)
		})
	}
}

func TestGolden_SessionHeader(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			h := newHarness(t, era)
			if _, err := h.cs.ListTools(ctxT(t), nil); err != nil {
				t.Fatalf("ListTools: %v", err)
			}
			exs := h.rec.Exchanges()
			var issued, echoed int
			for _, ex := range exs {
				if ex.ResponseHeaders.Get(mcpcore.HeaderSessionID) != "" {
					issued++
				}
				if ex.RequestHeaders.Get(mcpcore.HeaderSessionID) != "" {
					echoed++
				}
			}
			switch era {
			case mcpcore.EraModern:
				if issued != 0 || echoed != 0 {
					t.Fatalf("modern era is stateless: %d responses issued and %d requests carried %s", issued, echoed, mcpcore.HeaderSessionID)
				}
			case mcpcore.EraLegacy:
				if issued == 0 || echoed == 0 {
					t.Fatalf("legacy era is stateful: issued=%d echoed=%d %s", issued, echoed, mcpcore.HeaderSessionID)
				}
			}
			checkGolden(t, "session-header-"+era.String(), exs)
		})
	}
}

func TestEra_VersionFor(t *testing.T) {
	if VersionFor(mcpcore.EraModern) != mcpcore.ModernVersion || VersionFor(mcpcore.EraLegacy) != mcpcore.LegacyVersion || VersionFor(mcpcore.EraUnknown) != "" {
		t.Fatal("VersionFor must map eras to their protocol versions")
	}
}

func TestParseEra(t *testing.T) {
	for in, want := range map[string]mcpcore.Era{"modern": mcpcore.EraModern, "legacy": mcpcore.EraLegacy} {
		got, err := ParseEra(in)
		if err != nil || got != want {
			t.Fatalf("ParseEra(%q) = %v, %v", in, got, err)
		}
	}
	if _, err := ParseEra("future"); err == nil {
		t.Fatal("ParseEra must reject unknown eras")
	}
}

// R4: the conformance waiver list must be a verbatim copy of the pinned SDK's
// conformance/baseline.yml — Shipyard adds zero waivers of its own.
func TestConformanceWaivers_AreVerbatimSDKBaseline(t *testing.T) {
	ours, err := os.ReadFile(filepath.Join("..", "..", "test", "mcp-conformance", "expected-failures.yml"))
	if err != nil {
		t.Fatalf("read Shipyard waiver list: %v", err)
	}
	sdkDir, err := sdkModuleDir()
	if err != nil {
		t.Fatalf("locate go-sdk module: %v", err)
	}
	theirs, err := os.ReadFile(filepath.Join(sdkDir, "conformance", "baseline.yml"))
	if err != nil {
		t.Fatalf("read SDK baseline: %v", err)
	}
	if !bytes.Equal(ours, theirs) {
		t.Fatalf("test/mcp-conformance/expected-failures.yml differs from %s/conformance/baseline.yml; waivers must be copied verbatim", sdkDir)
	}
	if !strings.Contains(sdkDir, "go-sdk@"+SDKVersion) {
		t.Fatalf("SDK module dir %s is not the pinned %s", sdkDir, SDKVersion)
	}
}

func checkGolden(t *testing.T, name string, exs []Exchange) {
	t.Helper()
	got := NormalizeExchanges(exs)
	path := filepath.Join("testdata", "golden", name+".json")
	if *update {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, got, 0o644); err != nil {
			t.Fatal(err)
		}
		return
	}
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read golden %s (run `go test ./internal/mcpfixture -update` to create): %v", path, err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("golden %s mismatch\n--- got ---\n%s\n--- want ---\n%s", path, got, want)
	}
}
