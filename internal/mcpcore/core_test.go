package mcpcore

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"github.com/sloik/shipyard/internal/capture"
)

func TestSupportedVersions_ComeFromSDK(t *testing.T) {
	got := SupportedVersions()
	want := mcp.SupportedProtocolVersions()
	if !slices.Equal(got, want) {
		t.Fatalf("SupportedVersions() = %v, want SDK list %v", got, want)
	}
	if got[0] != ModernVersion {
		t.Fatalf("newest supported version = %q, want ModernVersion %q", got[0], ModernVersion)
	}
	if !slices.Contains(got, LegacyVersion) {
		t.Fatalf("SupportedVersions() = %v, missing LegacyVersion %q", got, LegacyVersion)
	}
	got[0] = "mutated"
	if SupportedVersions()[0] != ModernVersion {
		t.Fatal("SupportedVersions() must return a copy")
	}
}

func TestEraForVersion(t *testing.T) {
	cases := []struct {
		version string
		want    Era
		ok      bool
	}{
		{"2026-07-28", EraModern, true},
		{"2025-11-25", EraLegacy, true},
		{"2025-06-18", EraLegacy, true},
		{"2025-03-26", EraLegacy, true},
		{"2024-11-05", EraLegacy, true},
		{"1999-01-01", EraUnknown, false},
		{"2099-01-01", EraUnknown, false},
		{"", EraUnknown, false},
	}
	for _, tc := range cases {
		got, ok := EraForVersion(tc.version)
		if got != tc.want || ok != tc.ok {
			t.Errorf("EraForVersion(%q) = (%v, %v), want (%v, %v)", tc.version, got, ok, tc.want, tc.ok)
		}
	}
	if EraModern.String() != "modern" || EraLegacy.String() != "legacy" || EraUnknown.String() != "unknown" {
		t.Fatalf("unexpected Era strings: %q %q %q", EraModern, EraLegacy, EraUnknown)
	}
}

// rawModernRequest deliberately uses spacing, key order, a unicode escape, and
// an integer ID above 2^53 — every one of which a decode/re-encode would alter.
const rawModernRequest = "{ \"params\":{\"name\":\"caf\\u00e9\",\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\"," +
	"\"io.modelcontextprotocol/clientCapabilities\":{},\"x.example/trace\":\"t-1\"}},\n  \"method\":\"tools/call\",\"id\":9007199254740993,\"jsonrpc\":\"2.0\" }"

const rawModernResponse = "{\"jsonrpc\":\"2.0\",  \"id\":9007199254740993,\"result\":{\"content\":[],\"_meta\":{\"x.example/trace\":\"t-1\"}}}"

func modernHeaders() http.Header {
	h := http.Header{}
	h.Set("Content-Type", "application/json")
	h.Set(HeaderProtocolVersion, ModernVersion)
	h.Add("Accept", "application/json")
	h.Add("Accept", "text/event-stream")
	return h
}

func TestIngest_KeepsRawBytesAndHeadersWithoutAliasing(t *testing.T) {
	raw := []byte(rawModernRequest)
	headers := modernHeaders()
	env := Ingest(raw, headers)

	// Mutate every input after ingest: the envelope must not alias them.
	raw[0] = 'X'
	headers.Set(HeaderProtocolVersion, "mutated")
	headers["Accept"][0] = "mutated"

	if got := env.Raw(); !bytes.Equal(got, []byte(rawModernRequest)) {
		t.Fatalf("Raw() = %q, want original bytes %q", got, rawModernRequest)
	}
	if got := env.Headers(); !equalHeaders(got, modernHeaders()) {
		t.Fatalf("Headers() = %v, want %v", got, modernHeaders())
	}

	// Mutating what the accessors return must not change the envelope either.
	env.Raw()[0] = 'Y'
	env.Headers().Set("Accept", "mutated")
	if !bytes.Equal(env.Raw(), []byte(rawModernRequest)) {
		t.Fatal("Raw() must return a copy")
	}
	if got := env.Headers().Values("Accept"); !slices.Equal(got, []string{"application/json", "text/event-stream"}) {
		t.Fatalf("Headers() must return a clone, got Accept=%v", got)
	}
}

func TestIngest_NilHeadersAreEmpty(t *testing.T) {
	env := Ingest([]byte(`{"jsonrpc":"2.0","method":"ping","id":1}`), nil)
	if env.Headers() == nil || len(env.Headers()) != 0 {
		t.Fatalf("Headers() = %v, want empty non-nil header map", env.Headers())
	}
}

func TestIngest_NormalizedViewIsDerivedFromRaw(t *testing.T) {
	env := Ingest([]byte(rawModernRequest), modernHeaders())
	v := env.View()
	if v.Kind != KindRequest {
		t.Fatalf("Kind = %v, want request", v.Kind)
	}
	if v.Method != "tools/call" {
		t.Fatalf("Method = %q", v.Method)
	}
	if string(v.ID) != "9007199254740993" {
		t.Fatalf("ID = %s, want exact large integer bytes", v.ID)
	}
	if v.ProtocolVersion != ModernVersion || v.Era != EraModern {
		t.Fatalf("ProtocolVersion/Era = %q/%v, want %q/modern", v.ProtocolVersion, v.Era, ModernVersion)
	}
	if string(v.Meta["x.example/trace"]) != `"t-1"` {
		t.Fatalf("Meta pass-through lost custom key: %v", v.Meta)
	}
	if !bytes.Contains(v.Params, []byte("caf\\u00e9")) {
		t.Fatalf("Params must be the raw params bytes, got %s", v.Params)
	}
}

func TestIngest_EraFallsBackToHeaderThenInitialize(t *testing.T) {
	h := http.Header{}
	h.Set(HeaderProtocolVersion, "2025-11-25")
	v := Ingest([]byte(`{"jsonrpc":"2.0","id":"a","method":"tools/list","params":{}}`), h).View()
	if v.Era != EraLegacy || v.ProtocolVersion != "2025-11-25" {
		t.Fatalf("header era = %v/%q, want legacy/2025-11-25", v.Era, v.ProtocolVersion)
	}

	v = Ingest([]byte(`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}`), nil).View()
	if v.Era != EraLegacy || v.ProtocolVersion != "2025-06-18" {
		t.Fatalf("initialize era = %v/%q, want legacy/2025-06-18", v.Era, v.ProtocolVersion)
	}

	v = Ingest([]byte(`{"jsonrpc":"2.0","id":1,"method":"tools/list"}`), nil).View()
	if v.Era != EraUnknown || v.ProtocolVersion != "" {
		t.Fatalf("no version signal: era = %v/%q, want unknown/empty", v.Era, v.ProtocolVersion)
	}
}

func TestIngest_ResponseErrorAndNotificationKinds(t *testing.T) {
	cases := []struct {
		raw  string
		kind Kind
	}{
		{rawModernResponse, KindResponse},
		{`{"jsonrpc":"2.0","id":"x","error":{"code":-32601,"message":"nope"}}`, KindError},
		{`{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":7,"reason":"user"}}`, KindNotification},
		{`{not json`, KindInvalid},
	}
	for _, tc := range cases {
		if got := Ingest([]byte(tc.raw), nil).View().Kind; got != tc.kind {
			t.Errorf("Kind(%s) = %v, want %v", tc.raw, got, tc.kind)
		}
	}
	if s := KindError.String(); s != "error" {
		t.Fatalf("KindError.String() = %q", s)
	}
}

func TestView_ErrorCodeAndResult(t *testing.T) {
	v := Ingest([]byte(`{"jsonrpc":"2.0","id":"x","error":{"code":-32601,"message":"nope"}}`), nil).View()
	if v.ErrorCode != -32601 || v.ErrorMessage != "nope" {
		t.Fatalf("error view = %d/%q", v.ErrorCode, v.ErrorMessage)
	}
	v = Ingest([]byte(rawModernResponse), nil).View()
	if !bytes.Equal(v.Result, []byte(`{"content":[],"_meta":{"x.example/trace":"t-1"}}`)) {
		t.Fatalf("Result = %s", v.Result)
	}
	if string(v.Meta["x.example/trace"]) != `"t-1"` {
		t.Fatalf("result _meta not exposed: %v", v.Meta)
	}
}

func TestCancelledRequestID(t *testing.T) {
	v := Ingest([]byte(`{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":"shipyard-7","reason":"user"}}`), nil).View()
	id, ok := v.CancelledRequestID()
	if !ok || string(id) != `"shipyard-7"` {
		t.Fatalf("CancelledRequestID() = (%s, %v), want (\"shipyard-7\", true)", id, ok)
	}
	if _, ok := Ingest([]byte(`{"jsonrpc":"2.0","method":"ping","id":1}`), nil).View().CancelledRequestID(); ok {
		t.Fatal("non-cancellation must not report a cancelled request ID")
	}
}

func TestValidate(t *testing.T) {
	legacyHeader := http.Header{}
	legacyHeader.Set(HeaderProtocolVersion, LegacyVersion)
	badHeader := http.Header{}
	badHeader.Set(HeaderProtocolVersion, "1999-01-01")
	mismatch := http.Header{}
	mismatch.Set(HeaderProtocolVersion, LegacyVersion)

	cases := []struct {
		name       string
		raw        string
		headers    http.Header
		wantCode   int
		wantStatus int
	}{
		{"legacy request", `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`, legacyHeader, 0, 0},
		{"modern request", rawModernRequest, modernHeaders(), 0, 0},
		{"modern request missing capabilities", `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}`, nil, -32602, http.StatusBadRequest},
		{"header and _meta disagree", rawModernRequest, mismatch, -32600, http.StatusBadRequest},
		{"unsupported header version", `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`, badHeader, mcp.CodeUnsupportedProtocolVersion, http.StatusBadRequest},
		{"wrong jsonrpc version", `{"jsonrpc":"1.0","id":1,"method":"tools/list"}`, nil, -32600, http.StatusBadRequest},
		{"missing jsonrpc", `{"id":1,"method":"tools/list"}`, nil, -32600, http.StatusBadRequest},
		{"object id", `{"jsonrpc":"2.0","id":{"a":1},"method":"tools/list"}`, nil, -32600, http.StatusBadRequest},
		{"empty method", `{"jsonrpc":"2.0","id":1,"method":""}`, nil, -32600, http.StatusBadRequest},
		{"result and error", `{"jsonrpc":"2.0","id":1,"result":{},"error":{"code":1,"message":"x"}}`, nil, -32600, http.StatusBadRequest},
		{"neither result nor error", `{"jsonrpc":"2.0","id":1}`, nil, -32600, http.StatusBadRequest},
		{"error without message", `{"jsonrpc":"2.0","id":1,"error":{"code":1}}`, nil, -32600, http.StatusBadRequest},
		{"parse error", `{not json`, nil, -32700, http.StatusBadRequest},
		{"valid response", rawModernResponse, nil, 0, 0},
		{"valid error", `{"jsonrpc":"2.0","id":"x","error":{"code":-32601,"message":"nope"}}`, nil, 0, 0},
		{"valid notification", `{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":1}}`, nil, 0, 0},
		{"error with null id", `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}`, nil, 0, 0},
		{"result with null id", `{"jsonrpc":"2.0","id":null,"result":{}}`, nil, -32600, http.StatusBadRequest},
		{"modern meta with unsupported version", `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2099-01-01","io.modelcontextprotocol/clientCapabilities":{}}}}`, nil, mcp.CodeUnsupportedProtocolVersion, http.StatusBadRequest},
		{"notification with incomplete modern meta", `{"jsonrpc":"2.0","method":"notifications/progress","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}`, nil, 0, 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := Validate(Ingest([]byte(tc.raw), tc.headers))
			if tc.wantCode == 0 {
				if err != nil {
					t.Fatalf("Validate() = %v, want nil", err)
				}
				return
			}
			var verr *ValidationError
			if !errors.As(err, &verr) {
				t.Fatalf("Validate() = %v, want *ValidationError", err)
			}
			if verr.Code != tc.wantCode || verr.HTTPStatus != tc.wantStatus {
				t.Fatalf("Validate() = code %d status %d (%s), want code %d status %d", verr.Code, verr.HTTPStatus, verr.Reason, tc.wantCode, tc.wantStatus)
			}
			if verr.Error() == "" {
				t.Fatal("ValidationError.Error() must describe the failure")
			}
		})
	}
}

// AC4: a captured request/response pair keeps its raw bytes and headers after
// passing through the shared core, and the capture store persists the core's
// raw payload byte-for-byte.
func TestPair_CaptureRoundTripKeepsRawBytesAndHeaders(t *testing.T) {
	reqHeaders := modernHeaders()
	respHeaders := http.Header{}
	respHeaders.Set("Content-Type", "application/json")
	respHeaders.Add("Vary", "Origin")
	respHeaders.Add("Vary", "Accept")

	pair := NewPair(Ingest([]byte(rawModernRequest), reqHeaders), Ingest([]byte(rawModernResponse), respHeaders))
	if err := pair.Validate(); err != nil {
		t.Fatalf("pair.Validate() = %v", err)
	}
	if !pair.Correlated() {
		t.Fatal("request and response with the same raw ID must correlate")
	}

	dir := t.TempDir()
	store, err := capture.NewStore(filepath.Join(dir, "t.db"), filepath.Join(dir, "t.jsonl"))
	if err != nil {
		t.Fatalf("NewStore: %v", err)
	}
	t.Cleanup(func() { store.Close() })

	now := time.Now()
	reqView := pair.Request.View()
	store.Insert(&capture.TrafficEntry{
		Timestamp: now, Direction: capture.DirectionClientToServer, ServerName: "fixture",
		Method: reqView.Method, MessageID: string(reqView.ID), Payload: string(pair.Request.Raw()), Status: "pending",
	})
	store.Insert(&capture.TrafficEntry{
		Timestamp: now.Add(time.Millisecond), Direction: capture.DirectionServerToClient, ServerName: "fixture",
		Method: reqView.Method, MessageID: string(pair.Response.View().ID), Payload: string(pair.Response.Raw()), Status: "ok", IsResponse: true,
	})

	page, err := store.Query(1, 10, "", "")
	if err != nil {
		t.Fatalf("Query: %v", err)
	}
	if page.TotalCount != 2 {
		t.Fatalf("captured %d rows, want 2", page.TotalCount)
	}
	payloads := map[string]bool{}
	for _, item := range page.Items {
		payloads[item.Payload] = true
	}
	if !payloads[rawModernRequest] || !payloads[rawModernResponse] {
		t.Fatalf("stored payloads are not byte-identical to the received envelopes: %#v", payloads)
	}

	if !bytes.Equal(pair.Request.Raw(), []byte(rawModernRequest)) || !bytes.Equal(pair.Response.Raw(), []byte(rawModernResponse)) {
		t.Fatal("pair lost raw bytes after validation")
	}
	if !equalHeaders(pair.Request.Headers(), modernHeaders()) || !equalHeaders(pair.Response.Headers(), respHeaders) {
		t.Fatal("pair lost headers after validation")
	}
	// The normalized view must never be re-encoded into the raw slot.
	var reencoded bytes.Buffer
	if err := json.Compact(&reencoded, []byte(rawModernRequest)); err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(pair.Request.Raw(), reencoded.Bytes()) {
		t.Fatal("fixture is not sensitive to re-encoding; test would be vacuous")
	}
}

func TestPair_UncorrelatedAndInvalid(t *testing.T) {
	p := NewPair(Ingest([]byte(`{"jsonrpc":"2.0","id":1,"method":"ping"}`), nil), Ingest([]byte(`{"jsonrpc":"2.0","id":2,"result":{}}`), nil))
	if p.Correlated() {
		t.Fatal("different IDs must not correlate")
	}
	p = NewPair(Ingest([]byte(`{"jsonrpc":"2.0","id":1,"method":"ping"}`), nil), Ingest([]byte(`{bad`), nil))
	if err := p.Validate(); err == nil {
		t.Fatal("pair with invalid response must fail validation")
	}
	p = NewPair(Ingest([]byte(`{"jsonrpc":"1.0","id":1,"method":"ping"}`), nil), Ingest([]byte(`{"jsonrpc":"2.0","id":1,"result":{}}`), nil))
	if err := p.Validate(); err == nil {
		t.Fatal("pair with invalid request must fail validation")
	}
}

func equalHeaders(a, b http.Header) bool {
	if len(a) != len(b) {
		return false
	}
	for k, av := range a {
		if !slices.Equal(av, b[k]) {
			return false
		}
	}
	return true
}
