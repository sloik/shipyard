# ADR 0005: Adopt the official MCP Go SDK behind a raw-preserving core

**Status:** accepted (SPEC-BUG-181, 2026-10-03)

## Context

Shipyard hand-codes its JSON-RPC envelopes and MCP version strings in
`internal/proxy`, `internal/auth`, `internal/web` and `cmd/shipyard-mcp`.
Supporting MCP `2026-07-28` alongside the legacy `2025-11-25` era requires
three things:

- Version negotiation for both eras.
- A shared validator.
- A way to prove that later transport changes are correct.

That proof needs fixtures and the official conformance suite. SPEC-BUG-181 is
the foundation child of SPEC-BUG-180. It must not change live behaviour.

## Decision

1. **The SDK owns protocol types and versions.**
   `github.com/modelcontextprotocol/go-sdk` v1.8.0 provides:
   - the supported-version list (`mcp.SupportedProtocolVersions`);
   - the `_meta` keys (`mcp.MetaKey*`);
   - the error codes (`mcp.CodeUnsupportedProtocolVersion`, `jsonrpc.Code*`);
   - JSON-RPC envelope decoding (`jsonrpc.DecodeMessage`);
   - the fixture servers and clients.

   Shipyard defines no protocol types of its own.
2. **One custom type stays at the capture boundary: `mcpcore.Envelope`.**
   Capture must stay byte-identical to what was received (R5). The SDK's
   decoded `jsonrpc.Message` cannot do that, for three reasons:
   - It normalizes request IDs. A JSON number ID is decoded through `float64`, so an integer above 2^53 changes value.
   - It is re-encoded on output, which changes whitespace, key order and escapes.
   - It carries no HTTP headers.

   `Envelope` therefore keeps:
   - a private copy of the raw bytes;
   - a clone of the headers;
   - a `View` derived from those bytes. The `View` is never re-encoded into the raw slot.

   Validation delegates to `jsonrpc.DecodeMessage` and then adds the era rules.
3. **The SDK's wire header names are mirrored as constants.** The SDK keeps
   `Mcp-Protocol-Version`, `Mcp-Session-Id`, `Mcp-Method` and `Mcp-Name`
   unexported. The golden wire tests record real SDK traffic and fail if
   these constants ever drift.
4. **Era model.**
   - Modern means `2026-07-28`: stateless streamable HTTP, discovery through `server/discover`, the version carried in `_meta`, and routing headers.
   - Legacy means every supported version below that, using the `initialize` handshake and `Mcp-Session-Id`.

   The modern fixture accepts only `2026-07-28`. The legacy fixture accepts
   only pre-2026 versions.
5. **Gaps stay red and out of CI.**
   - The G1–G7 gap suite uses build tag `mcpgap`. It runs through `scripts/mcp-gap-suite.sh` or `make mcp-gap`.
   - Conformance runs through `scripts/mcp-conformance.sh` or `make mcp-conformance`, against the CLI pinned at `0.1.16`.

   Neither is part of `make quality` or CI.

## Consequences

- Nothing in the shipped binaries imports the new packages yet. Later specs
  wire the core into the gateway, bridge and child paths. Those are
  SPEC-BUG-182 through 185, and each one turns its own gap case green.
- Observed SDK v1.8.0 behaviour is pinned by the goldens:
  - List results carry `ttlMs` and `cacheScope` in both eras.
  - In stateless (modern) mode, `notifications/cancelled` is sent but does not
    cancel the original in-flight call, because each request gets a fresh
    session. Shipyard's own cancellation forwarding (G7) must not rely on it.
- The stable conformance CLI (`0.1.16`) has no `2026-07-28` scenarios. The
  modern era is covered by the golden wire tests until a stable CLI release
  adds them.
- Capture persistence (`internal/capture.Store`) stores payload bytes but
  not headers. The core keeps headers. Persisting them is out of scope here.
- See `docs/dependencies/go-sdk.md` for license, security and rollback.
