package performance

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestRecorder_BoundedRetention(t *testing.T) {
	rec := NewRecorder(2)
	rec.RecordHTTP(HTTPSample{Route: "/first"})
	rec.RecordHTTP(HTTPSample{Route: "/second"})
	rec.RecordHTTP(HTTPSample{Route: "/third"})

	got := rec.HTTP()
	if len(got) != 2 {
		t.Fatalf("got %d samples, want 2", len(got))
	}
	if got[0].Route != "/second" || got[1].Route != "/third" {
		t.Fatalf("oldest samples were not evicted: %+v", got)
	}
}

func TestResponseRecorder_CapturesStatusAndSizeWithoutPayload(t *testing.T) {
	w := httptest.NewRecorder()
	rw := NewResponseRecorder(w)

	rw.WriteHeader(http.StatusTeapot)
	if _, err := rw.Write([]byte("secret-token-value")); err != nil {
		t.Fatalf("Write: %v", err)
	}

	if rw.StatusCode != http.StatusTeapot {
		t.Fatalf("status = %d, want %d", rw.StatusCode, http.StatusTeapot)
	}
	if rw.Size != int64(len("secret-token-value")) {
		t.Fatalf("size = %d, want %d", rw.Size, len("secret-token-value"))
	}
	sample := HTTPSample{
		Timestamp:    time.Now(),
		Route:        "/api/test",
		Method:       http.MethodGet,
		StatusCode:   rw.StatusCode,
		ResponseSize: rw.Size,
	}
	if strings.Contains(sample.Route, "secret") {
		t.Fatalf("sample leaked payload-like value: %+v", sample)
	}
}

func TestRPCResultFromResponse_DetectsJSONRPCErrorWithoutPayload(t *testing.T) {
	if got := RPCResultFromResponse([]byte(`{"jsonrpc":"2.0","id":1,"result":{"token":"secret"}}`)); got != "ok" {
		t.Fatalf("result = %q, want ok", got)
	}
	if got := RPCResultFromResponse([]byte(`{"jsonrpc":"2.0","id":1,"error":{"message":"boom","token":"secret"}}`)); got != "error" {
		t.Fatalf("result = %q, want error", got)
	}
}
