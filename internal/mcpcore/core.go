// Package mcpcore is Shipyard's shared MCP compatibility core: protocol-era
// classification, wire constants, raw-preserving envelopes, and a shared
// modern/legacy validator built on the official Go SDK
// (github.com/modelcontextprotocol/go-sdk).
//
// The SDK owns protocol types, the supported-version list, and JSON-RPC
// envelope decoding. This package keeps one custom type at the capture
// boundary, Envelope, because capture must stay byte-identical to what was
// received: the SDK's decoded jsonrpc.Message normalizes IDs (an integer ID
// above 2^53 loses precision) and is re-encoded on output, and it carries no
// HTTP headers. See docs/adr/0005-mcp-go-sdk-adoption.md.
package mcpcore

import (
	"slices"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Protocol versions that anchor the two eras Shipyard bridges.
const (
	// ModernVersion is the stateless 2026-07-28 protocol (SEP-2575).
	ModernVersion = "2026-07-28"
	// LegacyVersion is the newest initialize-handshake protocol version.
	LegacyVersion = "2025-11-25"
)

// HTTP header and method names on the wire. The SDK keeps its header names
// unexported, so they are mirrored here; the fixture golden tests observe the
// SDK's actual wire traffic and fail if these ever disagree.
const (
	HeaderProtocolVersion = "Mcp-Protocol-Version"
	HeaderSessionID       = "Mcp-Session-Id"
	HeaderMethod          = "Mcp-Method"
	HeaderName            = "Mcp-Name"
	MethodDiscover        = "server/discover"
	MethodInitialize      = "initialize"
	MethodCancelled       = "notifications/cancelled"
)

// Era is an MCP protocol era.
type Era int

// The protocol eras.
const (
	EraUnknown Era = iota
	EraLegacy
	EraModern
)

func (e Era) String() string {
	switch e {
	case EraLegacy:
		return "legacy"
	case EraModern:
		return "modern"
	default:
		return "unknown"
	}
}

// SupportedVersions returns the protocol versions supported by the pinned SDK,
// newest first. The returned slice is a copy.
func SupportedVersions() []string { return mcp.SupportedProtocolVersions() }

// EraForVersion classifies a protocol version. It reports false for versions
// the pinned SDK does not support.
func EraForVersion(version string) (Era, bool) {
	if !slices.Contains(SupportedVersions(), version) {
		return EraUnknown, false
	}
	if version >= ModernVersion {
		return EraModern, true
	}
	return EraLegacy, true
}
