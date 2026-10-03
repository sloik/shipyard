package mcpcore

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/modelcontextprotocol/go-sdk/jsonrpc"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// ValidationError describes why an envelope is not a valid MCP message for
// its era. Code is the JSON-RPC error code to answer with; HTTPStatus is the
// status an HTTP transport should use.
type ValidationError struct {
	Code       int
	HTTPStatus int
	Reason     string
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("invalid MCP message (code %d): %s", e.Code, e.Reason)
}

func invalid(code int, format string, args ...any) *ValidationError {
	return &ValidationError{Code: code, HTTPStatus: http.StatusBadRequest, Reason: fmt.Sprintf(format, args...)}
}

// Validate checks an envelope against JSON-RPC 2.0 (decoded by the SDK's
// jsonrpc package) and the era rules shared by both protocol eras:
//
//   - an Mcp-Protocol-Version header must name a supported version;
//   - a request whose _meta declares the modern era must name a supported
//     version, carry clientCapabilities, and agree with any version header;
//   - a response carries exactly one of result or error, and an error has an
//     integer code and a string message.
//
// Notifications never select the modern era (SEP-2575), so their _meta is
// passed through unvalidated.
func Validate(e *Envelope) error {
	if !e.wire.object {
		return invalid(jsonrpc.CodeParseError, "message is not a JSON object")
	}
	v := e.view
	nullIDError := v.Kind == KindError && e.wire.hasID && len(v.ID) == 0
	if !nullIDError {
		if _, err := jsonrpc.DecodeMessage(e.raw); err != nil {
			return invalid(jsonrpc.CodeInvalidRequest, "%v", err)
		}
	} else if !bytes.Equal(bytes.TrimSpace(e.wire.version), []byte(`"2.0"`)) {
		return invalid(jsonrpc.CodeInvalidRequest, "jsonrpc member must be \"2.0\"")
	}

	switch v.Kind {
	case KindRequest, KindNotification:
		if v.Method == "" {
			return invalid(jsonrpc.CodeInvalidRequest, "method must be a non-empty string")
		}
	case KindResponse, KindError:
		if e.wire.hasResult == e.wire.hasError {
			return invalid(jsonrpc.CodeInvalidRequest, "response must carry exactly one of result or error")
		}
		if v.Kind == KindResponse && len(v.ID) == 0 {
			return invalid(jsonrpc.CodeInvalidRequest, "result response must carry a non-null id")
		}
		if v.Kind == KindError {
			var shape struct {
				Code    *int    `json:"code"`
				Message *string `json:"message"`
			}
			if json.Unmarshal(e.wire.errorShape, &shape) != nil || shape.Code == nil || shape.Message == nil {
				return invalid(jsonrpc.CodeInvalidRequest, "error must carry an integer code and a string message")
			}
		}
	}

	header := e.headers.Get(HeaderProtocolVersion)
	if header != "" {
		if _, ok := EraForVersion(header); !ok {
			return invalid(mcp.CodeUnsupportedProtocolVersion, "unsupported %s %q", HeaderProtocolVersion, header)
		}
	}

	if v.Kind == KindRequest {
		var metaVersion string
		if raw, ok := v.Meta[mcp.MetaKeyProtocolVersion]; ok && json.Unmarshal(raw, &metaVersion) == nil && metaVersion >= ModernVersion {
			if _, ok := EraForVersion(metaVersion); !ok {
				return invalid(mcp.CodeUnsupportedProtocolVersion, "unsupported _meta protocol version %q", metaVersion)
			}
			var caps map[string]json.RawMessage
			if json.Unmarshal(v.Meta[mcp.MetaKeyClientCapabilities], &caps) != nil || caps == nil {
				return invalid(jsonrpc.CodeInvalidParams, "missing or invalid _meta field %q", mcp.MetaKeyClientCapabilities)
			}
			if header != "" && header != metaVersion {
				return invalid(jsonrpc.CodeInvalidRequest, "%s %q disagrees with _meta protocol version %q", HeaderProtocolVersion, header, metaVersion)
			}
		}
	}
	return nil
}

// Pair is a captured request with its response, each kept byte-exact.
type Pair struct {
	Request  *Envelope
	Response *Envelope
}

// NewPair pairs a request envelope with its response envelope.
func NewPair(req, resp *Envelope) Pair { return Pair{Request: req, Response: resp} }

// Validate validates both halves of the pair.
func (p Pair) Validate() error {
	if err := Validate(p.Request); err != nil {
		return fmt.Errorf("request: %w", err)
	}
	if err := Validate(p.Response); err != nil {
		return fmt.Errorf("response: %w", err)
	}
	return nil
}

// Correlated reports whether the response answers the request, comparing the
// exact ID bytes.
func (p Pair) Correlated() bool {
	req, resp := p.Request.view.ID, p.Response.view.ID
	return len(req) > 0 && bytes.Equal(bytes.TrimSpace(req), bytes.TrimSpace(resp))
}
