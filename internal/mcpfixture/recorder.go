package mcpfixture

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"

	"github.com/sloik/shipyard/internal/mcpcore"
)

// Exchange is one recorded HTTP round trip. Request is nil when the request
// had no body (GET, DELETE). Responses holds the JSON body, or one envelope
// per SSE data event, each byte-exact.
type Exchange struct {
	HTTPMethod      string
	Status          int
	RequestHeaders  http.Header
	ResponseHeaders http.Header
	Request         *mcpcore.Envelope
	Responses       []*mcpcore.Envelope
}

// Recorder is an http.RoundTripper that records every exchange through the
// shared core without altering the bytes the client and server see. Response
// bodies are teed as they stream, so long-lived SSE responses keep working.
type Recorder struct {
	base http.RoundTripper

	mu        sync.Mutex
	exchanges []*recorded
}

type recorded struct {
	ex   Exchange
	body *bytes.Buffer
	sse  bool
}

// NewRecorder wraps base (http.DefaultTransport when nil).
func NewRecorder(base http.RoundTripper) *Recorder {
	if base == nil {
		base = http.DefaultTransport
	}
	return &Recorder{base: base}
}

// RoundTrip implements http.RoundTripper.
func (r *Recorder) RoundTrip(req *http.Request) (*http.Response, error) {
	rec := &recorded{ex: Exchange{HTTPMethod: req.Method, RequestHeaders: req.Header.Clone(), ResponseHeaders: http.Header{}}, body: &bytes.Buffer{}}
	if req.Body != nil && req.Body != http.NoBody {
		raw, err := io.ReadAll(req.Body)
		_ = req.Body.Close()
		if err != nil {
			return nil, err
		}
		if len(raw) > 0 {
			rec.ex.Request = mcpcore.Ingest(raw, req.Header)
		}
		req = req.Clone(req.Context())
		req.Body = io.NopCloser(bytes.NewReader(raw))
		req.GetBody = func() (io.ReadCloser, error) { return io.NopCloser(bytes.NewReader(raw)), nil }
	}
	// Record the request before the round trip so a request whose response
	// never arrives (cancelled, or a transport error) is still captured.
	r.mu.Lock()
	r.exchanges = append(r.exchanges, rec)
	r.mu.Unlock()
	resp, err := r.base.RoundTrip(req)
	if err != nil {
		return nil, err
	}
	r.mu.Lock()
	rec.ex.Status = resp.StatusCode
	rec.ex.ResponseHeaders = resp.Header.Clone()
	rec.sse = strings.HasPrefix(resp.Header.Get("Content-Type"), "text/event-stream")
	r.mu.Unlock()
	resp.Body = &teeBody{rc: resp.Body, rec: rec, mu: &r.mu}
	return resp, nil
}

type teeBody struct {
	rc  io.ReadCloser
	rec *recorded
	mu  *sync.Mutex
}

func (t *teeBody) Read(p []byte) (int, error) {
	n, err := t.rc.Read(p)
	t.mu.Lock()
	t.rec.body.Write(p[:n])
	t.mu.Unlock()
	return n, err
}

func (t *teeBody) Close() error { return t.rc.Close() }

// Exchanges returns a snapshot of every exchange recorded so far, with the
// response bytes received up to now parsed into envelopes.
func (r *Recorder) Exchanges() []Exchange {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Exchange, 0, len(r.exchanges))
	for _, rec := range r.exchanges {
		ex := rec.ex
		ex.Responses = parseBody(rec.body.Bytes(), rec.sse, ex.ResponseHeaders)
		out = append(out, ex)
	}
	return out
}

func parseBody(body []byte, sse bool, headers http.Header) []*mcpcore.Envelope {
	if !sse {
		if len(bytes.TrimSpace(body)) == 0 {
			return nil
		}
		return []*mcpcore.Envelope{mcpcore.Ingest(bytes.TrimRight(body, "\n"), headers)}
	}
	var out []*mcpcore.Envelope
	var data [][]byte
	flush := func() {
		if len(data) > 0 {
			out = append(out, mcpcore.Ingest(bytes.Join(data, []byte("\n")), headers))
			data = nil
		}
	}
	sc := bufio.NewScanner(bytes.NewReader(body))
	sc.Buffer(make([]byte, 0, 64*1024), 4<<20)
	for sc.Scan() {
		line := sc.Bytes()
		switch {
		case len(line) == 0:
			flush()
		case bytes.HasPrefix(line, []byte("data:")):
			data = append(data, bytes.TrimPrefix(bytes.TrimPrefix(line, []byte("data:")), []byte(" ")))
		}
	}
	flush()
	return out
}

// goldenHeaders are the wire headers the golden cases pin.
var goldenHeaders = []string{
	"Content-Type",
	mcpcore.HeaderProtocolVersion,
	mcpcore.HeaderSessionID,
	mcpcore.HeaderMethod,
	mcpcore.HeaderName,
}

// NormalizeExchanges renders exchanges as indented JSON for golden files:
// selected headers only, session IDs redacted, bodies re-indented (the raw
// bytes stay untouched in the envelopes themselves).
func NormalizeExchanges(exs []Exchange) []byte {
	type message struct {
		Kind string          `json:"kind"`
		Body json.RawMessage `json:"body"`
	}
	type normalized struct {
		HTTP            string            `json:"http"`
		Status          int               `json:"status"`
		RequestHeaders  map[string]string `json:"request_headers"`
		Request         *message          `json:"request,omitempty"`
		ResponseHeaders map[string]string `json:"response_headers"`
		Responses       []message         `json:"responses"`
	}
	toMessage := func(e *mcpcore.Envelope) message {
		raw := e.Raw()
		if !json.Valid(raw) {
			b, _ := json.Marshal(string(raw))
			raw = b
		}
		return message{Kind: e.View().Kind.String(), Body: raw}
	}
	out := make([]normalized, 0, len(exs))
	for _, ex := range exs {
		n := normalized{HTTP: ex.HTTPMethod, Status: ex.Status,
			RequestHeaders: selectHeaders(ex.RequestHeaders), ResponseHeaders: selectHeaders(ex.ResponseHeaders),
			Responses: []message{}}
		if ex.Request != nil {
			m := toMessage(ex.Request)
			n.Request = &m
		}
		for _, r := range ex.Responses {
			n.Responses = append(n.Responses, toMessage(r))
		}
		out = append(out, n)
	}
	b, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		return []byte(err.Error())
	}
	return append(b, '\n')
}

func selectHeaders(h http.Header) map[string]string {
	out := map[string]string{}
	for _, name := range goldenHeaders {
		if v := h.Get(name); v != "" {
			if name == mcpcore.HeaderSessionID {
				v = "redacted"
			}
			out[name] = v
		}
	}
	return out
}
