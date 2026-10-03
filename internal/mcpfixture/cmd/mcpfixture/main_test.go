package main

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/sloik/shipyard/internal/mcpcore"
	"github.com/sloik/shipyard/internal/mcpfixture"
)

func TestRun_RejectsUsageErrors(t *testing.T) {
	cases := [][]string{
		nil,
		{"bogus"},
		{"server", "-era", "future"},
		{"server"},
		{"client"},
		{"client", "-era", "future", "http://x"},
	}
	for _, args := range cases {
		if err := run(context.Background(), args, func(string) string { return "initialize" }, &bytes.Buffer{}); err == nil {
			t.Errorf("run(%q) must fail", args)
		}
	}
}

func TestRun_ClientRequiresScenario(t *testing.T) {
	err := run(context.Background(), []string{"client", "http://127.0.0.1:1"}, func(string) string { return "" }, &bytes.Buffer{})
	if err == nil || !strings.Contains(err.Error(), "MCP_CONFORMANCE_SCENARIO") {
		t.Fatalf("missing scenario must be reported, got %v", err)
	}
}

func TestRun_ClientRunsScenarioWithContext(t *testing.T) {
	srv := httptest.NewServer(mcpfixture.NewHandler(mcpcore.EraLegacy, nil))
	t.Cleanup(srv.Close)
	env := map[string]string{
		"MCP_CONFORMANCE_SCENARIO": "initialize",
		"MCP_CONFORMANCE_CONTEXT":  `{"client_id":"c"}`,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := run(ctx, []string{"client", "-era", "legacy", srv.URL}, func(k string) string { return env[k] }, &bytes.Buffer{}); err != nil {
		t.Fatalf("client initialize scenario: %v", err)
	}
	env["MCP_CONFORMANCE_CONTEXT"] = "{bad json"
	if err := run(ctx, []string{"client", srv.URL}, func(k string) string { return env[k] }, &bytes.Buffer{}); err == nil {
		t.Fatal("malformed conformance context must be rejected")
	}
}

func TestRun_ServerServesUntilCancelled(t *testing.T) {
	for _, era := range []string{"modern", "legacy"} {
		t.Run(era, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			var out lockedBuffer
			done := make(chan error, 1)
			go func() {
				done <- run(ctx, []string{"server", "-era", era, "-http", "127.0.0.1:0"}, func(string) string { return "" }, &out)
			}()

			deadline := time.Now().Add(5 * time.Second)
			var addr string
			for addr == "" && time.Now().Before(deadline) {
				if s := out.String(); strings.Contains(s, "listening on ") {
					addr = strings.TrimSpace(strings.SplitN(s, "listening on ", 2)[1])
				} else {
					time.Sleep(10 * time.Millisecond)
				}
			}
			if addr == "" {
				cancel()
				t.Fatalf("server never reported its address: %q", out.String())
			}
			resp, err := http.Get("http://" + addr + "/")
			if err != nil {
				cancel()
				t.Fatalf("GET fixture server: %v", err)
			}
			_ = resp.Body.Close()
			cancel()
			select {
			case err := <-done:
				if err != nil {
					t.Fatalf("run returned %v after cancellation", err)
				}
			case <-time.After(5 * time.Second):
				t.Fatal("server did not stop after cancellation")
			}
		})
	}
}
