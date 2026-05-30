package performance

import (
	"encoding/json"
	"net/http"
	"sync"
	"time"
)

const DefaultMaxSamples = 256

// HTTPSample is a redacted timing sample for one HTTP request.
type HTTPSample struct {
	Timestamp    time.Time `json:"timestamp"`
	Method       string    `json:"method"`
	Route        string    `json:"route"`
	StatusCode   int       `json:"status_code"`
	DurationMs   int64     `json:"duration_ms"`
	ResponseSize int64     `json:"response_size"`
}

// RPCSample is a redacted timing sample for one child JSON-RPC request.
type RPCSample struct {
	Timestamp  time.Time `json:"timestamp"`
	Server     string    `json:"server"`
	Method     string    `json:"method"`
	Result     string    `json:"result"`
	Reason     string    `json:"reason,omitempty"`
	DurationMs int64     `json:"duration_ms"`
}

// Recorder keeps bounded, redacted runtime performance samples.
type Recorder struct {
	mu         sync.RWMutex
	maxSamples int
	http       []HTTPSample
	rpc        []RPCSample
}

func NewRecorder(maxSamples int) *Recorder {
	if maxSamples <= 0 {
		maxSamples = DefaultMaxSamples
	}
	return &Recorder{maxSamples: maxSamples}
}

func (r *Recorder) RecordHTTP(sample HTTPSample) {
	if r == nil {
		return
	}
	if sample.Timestamp.IsZero() {
		sample.Timestamp = time.Now().UTC()
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.http = appendBounded(r.http, sample, r.maxSamples)
}

func (r *Recorder) RecordRPC(sample RPCSample) {
	if r == nil {
		return
	}
	if sample.Timestamp.IsZero() {
		sample.Timestamp = time.Now().UTC()
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.rpc = appendBounded(r.rpc, sample, r.maxSamples)
}

func (r *Recorder) HTTP() []HTTPSample {
	if r == nil {
		return nil
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return append([]HTTPSample(nil), r.http...)
}

func (r *Recorder) RPC() []RPCSample {
	if r == nil {
		return nil
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return append([]RPCSample(nil), r.rpc...)
}

func appendBounded[T any](items []T, item T, limit int) []T {
	items = append(items, item)
	if len(items) <= limit {
		return items
	}
	out := make([]T, limit)
	copy(out, items[len(items)-limit:])
	return out
}

// ResponseRecorder captures status and byte count without observing payloads.
type ResponseRecorder struct {
	http.ResponseWriter
	StatusCode int
	Size       int64
}

func NewResponseRecorder(w http.ResponseWriter) *ResponseRecorder {
	return &ResponseRecorder{ResponseWriter: w, StatusCode: http.StatusOK}
}

func (rw *ResponseRecorder) WriteHeader(statusCode int) {
	rw.StatusCode = statusCode
	rw.ResponseWriter.WriteHeader(statusCode)
}

func (rw *ResponseRecorder) Write(b []byte) (int, error) {
	n, err := rw.ResponseWriter.Write(b)
	rw.Size += int64(n)
	return n, err
}

func (rw *ResponseRecorder) Unwrap() http.ResponseWriter {
	return rw.ResponseWriter
}

func RPCResultFromResponse(raw json.RawMessage) string {
	var envelope struct {
		Error json.RawMessage `json:"error"`
	}
	if len(raw) == 0 || json.Unmarshal(raw, &envelope) != nil {
		return "ok"
	}
	if len(envelope.Error) > 0 && string(envelope.Error) != "null" {
		return "error"
	}
	return "ok"
}
