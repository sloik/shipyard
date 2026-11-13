package mcpcore

import (
	"bytes"
	"encoding/json"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Kind is the JSON-RPC message kind of an envelope.
type Kind int

// The message kinds. KindInvalid covers bytes that are not a JSON object.
const (
	KindInvalid Kind = iota
	KindRequest
	KindNotification
	KindResponse
	KindError
)

func (k Kind) String() string {
	switch k {
	case KindRequest:
		return "request"
	case KindNotification:
		return "notification"
	case KindResponse:
		return "response"
	case KindError:
		return "error"
	default:
		return "invalid"
	}
}

// View is the normalized view of an envelope. Every field is derived from the
// envelope's raw bytes and headers; json.RawMessage fields alias nothing the
// caller can mutate and are never re-encoded into the raw slot.
type View struct {
	Kind   Kind
	Method string
	// ID is the exact ID bytes as received (an integer above 2^53 survives).
	ID     json.RawMessage
	Params json.RawMessage
	Result json.RawMessage
	// ErrorCode and ErrorMessage are set for KindError.
	ErrorCode    int
	ErrorMessage string
	// Meta is the params `_meta` object (requests and notifications) or the
	// result `_meta` object (responses), key by key and byte-exact.
	Meta map[string]json.RawMessage
	// ProtocolVersion is the version this message declares: the modern
	// `_meta` protocol version, else the Mcp-Protocol-Version header, else an
	// initialize request's or result's protocolVersion.
	ProtocolVersion string
	Era             Era
}

// CancelledRequestID returns the requestId named by a notifications/cancelled
// message, byte-exact.
func (v View) CancelledRequestID() (json.RawMessage, bool) {
	if v.Kind != KindNotification || v.Method != MethodCancelled {
		return nil, false
	}
	var p struct {
		RequestID json.RawMessage `json:"requestId"`
	}
	if json.Unmarshal(v.Params, &p) != nil || len(p.RequestID) == 0 {
		return nil, false
	}
	return p.RequestID, true
}

// Envelope is one JSON-RPC message exactly as received, with the HTTP headers
// that carried it (empty for stdio) and its normalized view.
type Envelope struct {
	raw     []byte
	headers http.Header
	view    View
	wire    wireFields
}

// wireFields records which top-level members were present, for validation.
type wireFields struct {
	object     bool
	version    json.RawMessage
	hasID      bool
	hasMethod  bool
	hasResult  bool
	hasError   bool
	errorShape json.RawMessage
}

// Ingest copies raw and headers into a new Envelope. It never fails: bytes
// that do not decode are kept verbatim with KindInvalid so capture can still
// record them; Validate reports why they are invalid.
func Ingest(raw []byte, headers http.Header) *Envelope {
	e := &Envelope{raw: bytes.Clone(raw), headers: headers.Clone()}
	if e.headers == nil {
		e.headers = http.Header{}
	}
	e.view, e.wire = derive(e.raw, e.headers)
	return e
}

// Raw returns a copy of the envelope's bytes as received.
func (e *Envelope) Raw() []byte { return bytes.Clone(e.raw) }

// Headers returns a copy of the headers that carried the envelope.
func (e *Envelope) Headers() http.Header { return e.headers.Clone() }

// View returns the normalized view.
func (e *Envelope) View() View {
	v := e.view
	if v.Meta != nil {
		meta := make(map[string]json.RawMessage, len(v.Meta))
		for k, val := range v.Meta {
			meta[k] = bytes.Clone(val)
		}
		v.Meta = meta
	}
	v.ID, v.Params, v.Result = bytes.Clone(v.ID), bytes.Clone(v.Params), bytes.Clone(v.Result)
	return v
}

func derive(raw []byte, headers http.Header) (View, wireFields) {
	var members map[string]json.RawMessage
	if err := json.Unmarshal(raw, &members); err != nil || members == nil {
		return View{Kind: KindInvalid}, wireFields{}
	}
	w := wireFields{object: true, version: members["jsonrpc"]}
	var v View

	_, w.hasID = members["id"]
	_, w.hasMethod = members["method"]
	_, w.hasResult = members["result"]
	_, w.hasError = members["error"]
	w.errorShape = members["error"]
	if w.hasID && !bytes.Equal(bytes.TrimSpace(members["id"]), []byte("null")) {
		v.ID = members["id"]
	}

	switch {
	case w.hasMethod:
		_ = json.Unmarshal(members["method"], &v.Method)
		v.Params = members["params"]
		v.Kind = KindNotification
		if w.hasID {
			v.Kind = KindRequest
		}
		v.Meta = metaOf(v.Params)
	case w.hasError:
		v.Kind = KindError
		var e struct {
			Code    int    `json:"code"`
			Message string `json:"message"`
		}
		_ = json.Unmarshal(members["error"], &e)
		v.ErrorCode, v.ErrorMessage = e.Code, e.Message
	default:
		v.Kind = KindResponse
		v.Result = members["result"]
		v.Meta = metaOf(v.Result)
	}

	v.ProtocolVersion = declaredVersion(v, headers)
	v.Era, _ = EraForVersion(v.ProtocolVersion)
	return v, w
}

func metaOf(obj json.RawMessage) map[string]json.RawMessage {
	var holder struct {
		Meta map[string]json.RawMessage `json:"_meta"`
	}
	if json.Unmarshal(obj, &holder) != nil {
		return nil
	}
	return holder.Meta
}

func declaredVersion(v View, headers http.Header) string {
	var s string
	if raw, ok := v.Meta[mcp.MetaKeyProtocolVersion]; ok && json.Unmarshal(raw, &s) == nil && s != "" {
		return s
	}
	if h := headers.Get(HeaderProtocolVersion); h != "" {
		return h
	}
	var body struct {
		ProtocolVersion string `json:"protocolVersion"`
	}
	switch {
	case v.Kind == KindRequest && v.Method == MethodInitialize:
		_ = json.Unmarshal(v.Params, &body)
	case v.Kind == KindResponse:
		_ = json.Unmarshal(v.Result, &body)
	}
	return body.ProtocolVersion
}
