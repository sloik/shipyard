// SA1019 exception (SPEC-BUG-181, this file only): the 2025-11-25 conformance
// surface exercises sampling and logging, which SEP-2577 deprecates for
// 2026-07-28 but which remain in their deprecation window. Review when the
// legacy era is retired.
//
//lint:file-ignore SA1019 legacy-era conformance surface exercises SEP-2577-deprecated sampling/logging.
package mcpfixture

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/mcpcore"
)

func TestClientScenarios_RegisteredForConformanceCoreSuite(t *testing.T) {
	want := []string{
		"initialize", "tools_call", "elicitation-sep1034-client-defaults", "sse-retry",
		"auth/metadata-default", "auth/metadata-var1", "auth/metadata-var2", "auth/metadata-var3",
		"auth/basic-cimd", "auth/scope-from-www-authenticate", "auth/scope-from-scopes-supported",
		"auth/scope-omitted-when-undefined", "auth/scope-step-up", "auth/scope-retry-limit",
		"auth/token-endpoint-auth-basic", "auth/token-endpoint-auth-post", "auth/token-endpoint-auth-none",
		"auth/pre-registration",
	}
	got := ClientScenarios()
	for _, name := range want {
		if !slices.Contains(got, name) {
			t.Errorf("client scenario %q is not registered (have %v)", name, got)
		}
	}
	if !slices.IsSorted(got) {
		t.Fatalf("ClientScenarios() must be sorted: %v", got)
	}
}

func TestRunClientScenario_AgainstFixtureServer(t *testing.T) {
	for _, era := range eras {
		t.Run(era.String(), func(t *testing.T) {
			srv := httptest.NewServer(NewHandler(mcpcore.EraLegacy, nil))
			t.Cleanup(srv.Close)
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()

			if err := RunClientScenario(ctx, era, "initialize", srv.URL, nil); err != nil {
				t.Fatalf("initialize scenario: %v", err)
			}
			if err := RunClientScenario(ctx, era, "tools_call", srv.URL, nil); err == nil || !strings.Contains(err.Error(), "add_numbers") {
				t.Fatalf("tools_call against a server without add_numbers must fail naming it, got %v", err)
			}
			if err := RunClientScenario(ctx, era, "sse-retry", srv.URL, nil); err != nil {
				t.Fatalf("sse-retry scenario: %v", err)
			}
			// The CLI's own test server provides this tool; the fixture server
			// does not, so the scenario must fail naming it.
			if err := RunClientScenario(ctx, era, "elicitation-sep1034-client-defaults", srv.URL, nil); err == nil || !strings.Contains(err.Error(), "test_client_elicitation_defaults") {
				t.Fatalf("elicitation defaults scenario must fail naming its tool, got %v", err)
			}
		})
	}
}

func TestRunClientScenario_Unknown(t *testing.T) {
	err := RunClientScenario(context.Background(), mcpcore.EraModern, "no-such-scenario", "http://127.0.0.1:1", nil)
	if err == nil || !strings.Contains(err.Error(), "no-such-scenario") {
		t.Fatalf("unknown scenario must be rejected by name, got %v", err)
	}
}

func TestRunClientScenario_AuthUsesPreregisteredClientFromContext(t *testing.T) {
	// The OAuth flow itself is exercised by the conformance CLI. Here we only
	// prove the scenario wires the conformance context and fails cleanly when
	// the server is unreachable.
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	err := RunClientScenario(ctx, mcpcore.EraLegacy, "auth/pre-registration", "http://127.0.0.1:1/mcp",
		map[string]any{"client_id": "c", "client_secret": "s"})
	if err == nil {
		t.Fatal("auth scenario against an unreachable server must fail")
	}
}

func TestConformanceServerSurface(t *testing.T) {
	srv := httptest.NewServer(NewHandler(mcpcore.EraLegacy, nil))
	t.Cleanup(srv.Close)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	var elicited, sampled bool
	client := mcp.NewClient(&mcp.Implementation{Name: "surface", Version: "1"}, &mcp.ClientOptions{
		ElicitationHandler: func(context.Context, *mcp.ElicitRequest) (*mcp.ElicitResult, error) {
			elicited = true
			return &mcp.ElicitResult{Action: "accept", Content: map[string]any{"username": "u"}}, nil
		},
		CreateMessageHandler: func(context.Context, *mcp.CreateMessageRequest) (*mcp.CreateMessageResult, error) {
			sampled = true
			return &mcp.CreateMessageResult{Model: "m", Role: "assistant", Content: &mcp.TextContent{Text: "hi"}}, nil
		},
	})
	cs, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: srv.URL}, &mcp.ClientSessionOptions{ProtocolVersion: mcpcore.LegacyVersion})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	defer cs.Close()

	tools, err := cs.ListTools(ctx, nil)
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	for _, tool := range tools.Tools {
		args := map[string]any{}
		switch tool.Name {
		case ToolSlow:
			continue
		case "test_sampling":
			args["prompt"] = "p"
		case "test_elicitation":
			args["message"] = "m"
		}
		if _, err := cs.CallTool(ctx, &mcp.CallToolParams{Name: tool.Name, Arguments: args}); err != nil {
			t.Errorf("CallTool(%s): %v", tool.Name, err)
		}
	}
	if !elicited || !sampled {
		t.Fatalf("server-initiated requests not exercised: elicited=%v sampled=%v", elicited, sampled)
	}

	resources, err := cs.ListResources(ctx, nil)
	if err != nil {
		t.Fatalf("ListResources: %v", err)
	}
	for _, r := range resources.Resources {
		if _, err := cs.ReadResource(ctx, &mcp.ReadResourceParams{URI: r.URI}); err != nil {
			t.Errorf("ReadResource(%s): %v", r.URI, err)
		}
	}
	read, err := cs.ReadResource(ctx, &mcp.ReadResourceParams{URI: "test://template/42/data"})
	if err != nil || !strings.Contains(read.Contents[0].Text, `"id": "42"`) {
		t.Fatalf("template resource: %v %+v", err, read)
	}
	if err := cs.Subscribe(ctx, &mcp.SubscribeParams{URI: "test://watched-resource"}); err != nil {
		t.Fatalf("Subscribe: %v", err)
	}
	if err := cs.Unsubscribe(ctx, &mcp.UnsubscribeParams{URI: "test://watched-resource"}); err != nil {
		t.Fatalf("Unsubscribe: %v", err)
	}

	prompts, err := cs.ListPrompts(ctx, nil)
	if err != nil {
		t.Fatalf("ListPrompts: %v", err)
	}
	for _, p := range prompts.Prompts {
		args := map[string]string{}
		for _, a := range p.Arguments {
			args[a.Name] = "v"
		}
		if _, err := cs.GetPrompt(ctx, &mcp.GetPromptParams{Name: p.Name, Arguments: args}); err != nil {
			t.Errorf("GetPrompt(%s): %v", p.Name, err)
		}
	}
	if _, err := cs.Complete(ctx, &mcp.CompleteParams{
		Ref:      &mcp.CompleteReference{Type: "ref/prompt", Name: "test_prompt_with_arguments"},
		Argument: mcp.CompleteParamsArgument{Name: "arg1", Value: "a"},
	}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if err := cs.SetLoggingLevel(ctx, &mcp.SetLoggingLevelParams{Level: "info"}); err != nil {
		t.Fatalf("SetLoggingLevel: %v", err)
	}
	if err := cs.Ping(ctx, nil); err != nil {
		t.Fatalf("Ping: %v", err)
	}
}

func TestRecorder_PassesThroughGETAndErrors(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.Header().Set("Content-Type", "text/event-stream")
			_, _ = w.Write([]byte("event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/ping\"}\n\n"))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":1,"result":{}}`))
	}))
	t.Cleanup(srv.Close)
	rec := NewRecorder(nil)
	client := &http.Client{Transport: rec}

	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	drain(t, resp)
	resp, err = client.Post(srv.URL, "application/json", strings.NewReader(`{"jsonrpc":"2.0","id":1,"method":"ping"}`))
	if err != nil {
		t.Fatal(err)
	}
	drain(t, resp)

	exs := rec.Exchanges()
	if len(exs) != 2 {
		t.Fatalf("recorded %d exchanges, want 2", len(exs))
	}
	if exs[0].Request != nil || len(exs[0].Responses) != 1 || exs[0].Responses[0].View().Method != "notifications/ping" {
		t.Fatalf("GET exchange = %+v", exs[0])
	}
	if exs[1].Request.View().Method != "ping" || len(exs[1].Responses) != 1 {
		t.Fatalf("POST exchange = %+v", exs[1])
	}

	if _, err := client.Get("http://127.0.0.1:1"); err == nil {
		t.Fatal("unreachable endpoint must error")
	}
	var normalized []map[string]any
	if err := json.Unmarshal(NormalizeExchanges(exs), &normalized); err != nil || len(normalized) != 2 {
		t.Fatalf("NormalizeExchanges output invalid: %v", err)
	}
}

func drain(t *testing.T, resp *http.Response) {
	t.Helper()
	buf := make([]byte, 512)
	for {
		if _, err := resp.Body.Read(buf); err != nil {
			break
		}
	}
	_ = resp.Body.Close()
}
