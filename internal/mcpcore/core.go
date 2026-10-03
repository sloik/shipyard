// Package mcpcore is Shipyard's shared MCP compatibility core: protocol-era
// classification, wire constants, raw-preserving envelopes, and a shared
// modern/legacy validator built on the official Go SDK.
package mcpcore

import (
	"encoding/json"
	"net/http"
)

// Protocol versions and wire names (stub).
const (
	ModernVersion         = ""
	LegacyVersion         = ""
	HeaderProtocolVersion = ""
	HeaderSessionID       = ""
	HeaderMethod          = ""
	HeaderName            = ""
	MethodDiscover        = ""
	MethodCancelled       = ""
)

// Era is an MCP protocol era.
type Era int

// Eras.
const (
	EraUnknown Era = iota
	EraLegacy
	EraModern
)

func (e Era) String() string { return "" }

// SupportedVersions returns supported versions (stub).
func SupportedVersions() []string { return nil }

// EraForVersion classifies a version (stub).
func EraForVersion(string) (Era, bool) { return EraUnknown, false }

// Kind is a JSON-RPC message kind.
type Kind int

// Kinds.
const (
	KindInvalid Kind = iota
	KindRequest
	KindNotification
	KindResponse
	KindError
)

func (k Kind) String() string { return "" }

// View is the normalized view of an envelope.
type View struct {
	Kind            Kind
	Method          string
	ID              json.RawMessage
	Params          json.RawMessage
	Result          json.RawMessage
	ErrorCode       int
	ErrorMessage    string
	Meta            map[string]json.RawMessage
	ProtocolVersion string
	Era             Era
}

// CancelledRequestID (stub).
func (v View) CancelledRequestID() (json.RawMessage, bool) { return nil, false }

// Envelope is a raw-preserving message (stub).
type Envelope struct{}

// Ingest (stub).
func Ingest([]byte, http.Header) *Envelope { return &Envelope{} }

// Raw (stub).
func (e *Envelope) Raw() []byte { return nil }

// Headers (stub).
func (e *Envelope) Headers() http.Header { return nil }

// View (stub).
func (e *Envelope) View() View { return View{} }

// ValidationError (stub).
type ValidationError struct {
	Code       int
	HTTPStatus int
	Reason     string
}

func (e *ValidationError) Error() string { return "" }

// Validate (stub).
func Validate(*Envelope) error { return nil }

// Pair (stub).
type Pair struct {
	Request  *Envelope
	Response *Envelope
}

// NewPair (stub).
func NewPair(req, resp *Envelope) Pair { return Pair{Request: req, Response: resp} }

// Validate (stub).
func (p Pair) Validate() error { return nil }

// Correlated (stub).
func (p Pair) Correlated() bool { return false }
