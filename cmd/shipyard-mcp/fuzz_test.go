package main

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func FuzzJSONRPCRequestEnvelope(f *testing.F) {
	for _, seed := range []string{
		``, `null`, `{`, `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`,
		`{"jsonrpc":"2.0","id":null,"method":"notifications/initialized","params":null}`,
		`{"jsonrpc":"2.0","id":"żółw","method":"unknown","params":{"x":1,"x":2}}`,
		`{"jsonrpc":"2.0","id":999999999999999999999,"method":"tools/call","params":{"name":"server__tool","arguments":[[[[]]]]}}`,
	} {
		f.Add(seed)
	}

	f.Fuzz(func(t *testing.T, raw string) {
		if len(raw) > 64*1024 || strings.Contains(raw, "\n") {
			t.Skip()
		}
		line := strings.TrimSpace(raw)
		if line == "" {
			return
		}
		var request rpcRequest
		if err := json.Unmarshal([]byte(line), &request); err == nil {
			if len(request.ID) > 0 && !json.Valid(request.ID) {
				t.Fatalf("decoded request retained invalid ID: %q", request.ID)
			}
			if len(request.Params) > 0 && !json.Valid(request.Params) {
				t.Fatalf("decoded request retained invalid params: %q", request.Params)
			}
		}

		// Prefixing an arbitrary mutation with ! guarantees a parse error, so this
		// exercises the production error envelope without routing any fuzz input
		// to a local gateway or other external dependency.
		var out bytes.Buffer
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		if err := run(ctx, strings.NewReader("!"+line+"\n"), &out, &bytes.Buffer{}, nil); err != nil {
			t.Fatalf("serve malformed request: %v", err)
		}
		var response rpcResponse
		if err := json.Unmarshal(out.Bytes(), &response); err != nil {
			t.Fatalf("malformed request did not return JSON-RPC envelope: %q", out.String())
		}
		if response.Error == nil || response.Error.Code != -32700 || response.Result != nil {
			t.Fatalf("malformed request returned partial success: %+v", response)
		}
	})
}
