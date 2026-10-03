# Dependency record: github.com/modelcontextprotocol/go-sdk

Recorded by SPEC-BUG-181 (R6 / AC5) on 2026-10-03.

## Version

| Field | Value |
| --- | --- |
| Module | `github.com/modelcontextprotocol/go-sdk` |
| Version | `v1.8.0` (tag `refs/tags/v1.8.0`, published 2026-09-04) |
| Upstream commit | `3f3b699b2b67e1ed033a63d6651671dab53c2d32` |
| `go.sum` | `h1:KIvahhYqwtbeniWVPs3TcXEA7b8jEtwfBpOTAI+Urx4=` |
| Protocol versions | `2026-07-28`, `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` (`mcp/shared.go`) |

Packages imported by Shipyard: `mcp`, `jsonrpc`, `auth` and `oauthex`. The
last two are imported only by the conformance fixture client.

## Where it is used

Only these new packages import the SDK:

- `internal/mcpcore`: the shared core. It provides era classification, raw-preserving envelopes and the shared validator.
- `internal/mcpfixture` and `internal/mcpfixture/cmd/mcpfixture`: the fixture servers and clients, the golden wire tests, and the conformance runner binary.
- `*_mcpgap_test.go` files (build tag `mcpgap`): the gap suite.

The shipped binaries (`cmd/shipyard`, `cmd/shipyard-mcp`) do not link the
SDK. Their `go version -m` module lists are unchanged from the rollback
revision (see the SPEC-BUG-181 run report). Gateway, bridge and child
behaviour is unchanged.

## License

The SDK repository `LICENSE` covers a licensing transition:

- New code is **Apache-2.0**.
- Contributions whose authors have not consented to relicensing remain **MIT**.
- Documentation is CC-BY-4.0.

The adapted conformance files carry `Copyright 2025 The Go MCP SDK Authors` and
an MIT-style header:

- `conformance/everything-server/main.go`, adapted in `internal/mcpfixture/surface.go`.
- `conformance/everything-client/main.go`, adapted in `internal/mcpfixture/client.go`.

The Shipyard adaptations keep that attribution in their file headers. Apache-2.0
and MIT are both permissive and compatible with Shipyard's distribution.

Transitive modules this adds to the module graph, with license as stated in
each module's `LICENSE` file:

| Module | Version | License |
| --- | --- | --- |
| `github.com/google/jsonschema-go` | v0.4.3 | MIT |
| `github.com/segmentio/encoding` | v0.5.4 | MIT |
| `github.com/segmentio/asm` | v1.1.3 | MIT |
| `github.com/yosida95/uritemplate/v3` | v3.0.2 | BSD-3-Clause |
| `github.com/golang-jwt/jwt/v5` | v5.3.1 | MIT |
| `golang.org/x/oauth2` | v0.35.0 | BSD-3-Clause |
| `golang.org/x/time` | v0.15.0 | BSD-3-Clause |
| `golang.org/x/sync` | v0.23.0 | BSD-3-Clause |

## Security notes

- The pinned `govulncheck` (v1.4.0, `make security-tools`) ran over the whole
  module on 2026-10-03 and reported `No vulnerabilities found.`
- Upstream reports vulnerabilities through GitHub Security Advisories
  (`SECURITY.md`). Watch the repository's advisories when bumping.
- The SDK's streamable HTTP handler has DNS-rebinding protection on by
  default. The conformance `dns-rebinding-protection` scenario passes against
  the fixture server.
- The fixture client's OAuth flow (`auth.NewAuthorizationCodeHandler`) is
  used only by conformance scenarios against the CLI's local mock
  authorization server. No Shipyard runtime path uses it.
- The SDK deprecates sampling, roots and logging for `2026-07-28` (SEP-2577).
  The legacy conformance surface still exercises them. That is the only
  `SA1019` exception, scoped to `internal/mcpfixture/surface.go` and
  `internal/mcpfixture/scenario_test.go`, each with its rationale in the file
  header.
- Before any upgrade, re-run `go test ./internal/mcpfixture`. Its golden files
  pin the wire format, and `TestConformanceWaivers_AreVerbatimSDKBaseline`
  pins the waiver list to the SDK's `conformance/baseline.yml`. After
  bumping the SDK, re-copy that file.

## Rollback

Roll back to Shipyard revision **`1d0a07206f6893dc95651cfe737f3aff6591653e`**
(`1d0a072`). That is the baseline the SPEC-BUG-181 run started from. It
contains no SDK dependency, no `internal/mcpcore` and no
`internal/mcpfixture`. The spec's measurement revision `95bc5a1` is an
equally valid pre-SDK point.

Because no shipped binary imports the SDK, rolling back has no runtime
effect. To roll back, do either of the following:

- Revert the SPEC-BUG-181 commits.
- Delete the three new package trees, the `mcpgap` test files,
  `scripts/mcp-*.sh` and `test/mcp-conformance/`, then run `go mod tidy`.
