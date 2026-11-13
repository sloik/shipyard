# Nightshift Report — 2026-10-03

**Outcome:** done
<!-- Follow-ups 2026-10-03: human-approved scope amendment (main 441438b) and the
     matching scope.write frontmatter entry (main e763474) were merged; coverage
     floors committed and R1 resolved. The one remaining coverage-check failure
     (internal/secrets/op) is environment-only and also fails on main here. -->

Run: `kickoff-20261003-bug181`. Spec: SPEC-BUG-181, MCP 2026-07-28 conformance fixtures and compatibility core.
Baseline: `1d0a07206f6893dc95651cfe737f3aff6591653e`. The worktree started at `8609a53`; it was fast-forwarded to the baseline before any work began.
Branch: `worktree-agent-a7d39841455a362cf`.

## Summary
- Specs completed: 1 of 1. Lifecycle status is left to the parent.
- Tests passed: `go test -race -count=1 ./...` passed in all 17 packages, 0 failures.
- Build: ✅ pass (`go build ./...`)
- Vet: ✅ pass (`go vet ./...` and `go vet -tags mcpgap ./...`)
- Lint: ✅ pass (`make lint`, plus staticcheck `-tags mcpgap ./...`)
- Format: ✅ pass (`make format-check`, `gofmt -l` clean)
- Script check: ✅ pass (`make script-check`, `make security-config-check`)
- Smoke: ✅ pass (`make smoke-full`: Tool Browser, Servers and Traffic views)
- Conformance: ✅ CLI `@modelcontextprotocol/conformance@0.1.16`:
  - server leg: 40 checks across 30 scenarios
  - client-legacy leg: 217 checks across 18 scenarios
  - client-modern leg: 239 checks across 18 scenarios
  - 0 failures, 0 Shipyard waivers
- Gap suite: exactly G1–G7 open (`scripts/mcp-gap-suite.sh --expect-open G1,G2,G3,G4,G5,G6,G7` reports `expectation met`)
- Coverage gate (`make coverage-check`, the configured `commands.test`): the only failure is environment-only. The total is 80.3%, above the 75.1% floor, and the three new packages meet their committed floors (95.2 / 87.4 / 84.3). The single remaining finding is `internal/secrets/op: 21.1% is below baseline 28.6%`:
  - The package is identical to main (`git diff 441438b -- internal/secrets` is empty).
  - Its coverage depends on whether the 1Password `op` CLI is on PATH, and it is absent on this host.
  - So main fails the same way here.
  - The floor was not lowered.
- Review cycles: 2 advisor reviews, one before implementation and one before completion. No separate LOOP Step 7/10 persona pass was performed. The second advisor review led to the `--suite all` comparison, the floor-stability check and the G3/G2 note below.

## Completed Specs
- SPEC-BUG-181: MCP 2026-07-28 conformance fixtures and compatibility core. ✅ done (worker outcome). The parent owns the `status:` transition and the merge.

## Changes (SPEC-BUG-181)
Commits on the branch:
- `4ef9d73` `[SPEC-BUG-181] test: add red core, fixture, golden and G1-G7 gap tests`: the red tests, with compile-only stubs.
- `24a034c` `[SPEC-BUG-181] feat: MCP conformance fixtures and compatibility core`
- `518c691` `[SPEC-BUG-181] docs: generate nightshift report`
- A follow-up commit, `[SPEC-BUG-181] fix: register full SDK auth scenario set and document conformance suite choice`. It registers the remaining SDK auth scenarios in the fixture client, records the `core`-versus-`all` rationale, adds the suite-all evidence and applies these report corrections.
- `cc85741` `[SPEC-BUG-181] chore: merge main scope amendment (441438b)`: a `--no-ff` merge of main. It brings in the human-approved `## Scope Amendments` row, plus main's unrelated `a87838a` (SPEC-BUG-164 tracking files).
- `ffb1e02` `[SPEC-BUG-181] docs: add R1 resolution and record coverage-floor blocker`: adds the spec `## Resolution — 2026-10-03` section and ticks R1.
- `e6ad913` `[SPEC-BUG-181] chore: merge main scope.write widening (e763474)`: a `--no-ff` merge of main's frontmatter entry that grants `.nightshift/coverage-baseline.json`.
- A final commit, `[SPEC-BUG-181] chore: add coverage floors for new MCP packages`. It adds the three floors and updates this report.

Compared with the baseline, only `Makefile`, `go.mod`, `go.sum` and the approved `.nightshift/coverage-baseline.json` are modified, ignoring the spec and report files and main's merged SPEC-BUG-164 files. Every other file is new. No live gateway, bridge or child source file is touched.

- **R1, SDK adoption.** `github.com/modelcontextprotocol/go-sdk v1.8.0` is added to `go.mod`.
  - `internal/mcpcore` takes the supported versions, `_meta` keys, error codes and envelope decoding (`jsonrpc.DecodeMessage`) from the SDK.
  - One custom type, `mcpcore.Envelope`, is kept at the capture boundary. The rationale is in `docs/adr/0005-mcp-go-sdk-adoption.md` and the package doc. Without it, the SDK message re-encodes the payload, loses the precision of integer IDs above 2^53, and has no headers.
- **R2, fixtures.**
  - `internal/mcpfixture` provides two fixture servers and clients:
    - a modern one: `2026-07-28` only, stateless streamable HTTP;
    - a legacy one: pre-2026 versions, stateful, with `Mcp-Session-Id`.
  - A recording transport captures traffic through the core.
  - Golden files cover 7 cases × 2 eras in `testdata/golden/`. The cases are discovery, `_meta`, errors, result/cache fields, routing headers, cancellation, and session-header presence or absence.
- **R3, gap suite.** Tests named `TestMCPGap_G<n>_*` are build-tagged `mcpgap`:
  - `internal/proxy`: G1, G7
  - `internal/auth`: G2, G3, G4, G5, G6
  - `internal/web`: G2
  - `cmd/shipyard-mcp`: G2

  The runner is `scripts/mcp-gap-suite.sh` / `make mcp-gap`. It is not part of `go test ./...`, `make quality` or CI.
- **R4, conformance.** `scripts/mcp-conformance.sh` / `make mcp-conformance` pins the CLI at `0.1.16`, which is the latest stable release; there is no `@latest`. It runs against the `mcpfixture` binary at `internal/mcpfixture/cmd/mcpfixture`.
  - The waivers in `test/mcp-conformance/expected-failures.yml` are a byte copy of go-sdk v1.8.0 `conformance/baseline.yml`. `TestConformanceWaivers_AreVerbatimSDKBaseline` enforces this.
  - The script fails any leg that runs zero scenarios.
  - The client legs use suite `core`, not `all`. Under CLI 0.1.16 the go-sdk v1.8.0 reference `everything-client` itself fails two `all`-suite scenarios that the pinned baseline does not list: `auth/2025-03-26-oauth-metadata-backcompat` and `auth/cross-app-access-complete-flow`. The baseline tracks CLI 0.2.0-alpha.11. With the SDK's full auth scenario set registered, the fixture client fails exactly the same 7 scenarios (5 waived, those 2 not). Under the zero-Shipyard-waiver rule, `core` is the largest suite that can honestly pass, and all 18 of its scenarios pass. Evidence: `evidence/suite-all-*.log`. The rationale is also in the script header.
- **R5, raw preservation.** `Ingest` copies the bytes and clones the headers. Every accessor returns a copy, and the derived view is never re-encoded into the raw slot.
- **R6, dependency record.** `docs/dependencies/go-sdk.md` covers:
  - the version, the upstream commit `3f3b699b2b67e1ed033a63d6651671dab53c2d32`, and the `go.sum` hash;
  - the license;
  - the license of each transitive module;
  - security notes (govulncheck: `No vulnerabilities found.`);
  - rollback to `1d0a072`, or `95bc5a1`.

## Test Results
| Command | Result |
| --- | --- |
| `go build ./...` | pass |
| `go vet ./...` / `go vet -tags mcpgap ./...` | pass / pass |
| `go test -race -count=1 ./...` | pass (17 packages ok, `teststubchild` has no tests) |
| `make lint` / staticcheck `-tags mcpgap` | pass / pass |
| `make format-check`, `make script-check`, `make security-config-check` | pass |
| `make smoke-full` | pass (`SMOKE PASSED` for all three harnesses) |
| `.tools/bin/govulncheck ./...` (v1.4.0) | `No vulnerabilities found.` |
| `make security-gosec` | environment failure, not caused by this change: gosec v2.22.10 hits `internal error: package ... without types` under the local go1.27.1 toolchain. It fails identically on the untouched `internal/capture` package. |
| `scripts/mcp-conformance.sh` | pass (all three legs; the logs are in `.nightshift/reports/SPEC-BUG-181/evidence/`) |
| `scripts/mcp-gap-suite.sh` | exit 1, with exactly G1–G7 open (the intended red state; `evidence/gap-suite.txt`) |
| `make coverage-check` (with the committed floors) | environment-only failure. The ratchet's single finding is `internal/secrets/op: 21.1% is below baseline 28.6%`. That package is untouched and identical to main, and the `op` CLI is not installed, so main fails the same way here. New packages: mcpcore 95.2, mcpfixture 87.4, cmd/mcpfixture 84.3; total 80.3%. |

Coverage of the new packages:
- `internal/mcpcore`: 95.2%
- `internal/mcpfixture`: 87.4%
- `internal/mcpfixture/cmd/mcpfixture`: 84.3%

The total is 80.3%, against a baseline of 75.1%.

## Acceptance Criteria
- [x] **AC1 (R2, R3).** Both eras are exercised by every golden case, through `TestGolden_*` with `/modern` and `/legacy` subtests. The gap suite reports exactly G1–G7 failing, and every test name carries its gap ID. Each gap fails on its own assertion:
  - G1: the child handshake offered `2025-03-26`.
  - G2: `server/discover` returns -32602, -32603 or -32601 on the gateway, passthrough and bridge.
  - G3: `Mcp-Session-Id` is issued to a modern-era SDK client. The header is the only assertion.
  - G4: `Mcp-Protocol-Version: 1999-01-01` gets HTTP 200.
  - G5: a `"jsonrpc":"1.0"` envelope is served.
  - G6: `_meta` is dropped from the downstream `tools/call` params.
  - G7: no `notifications/cancelled` reaches the child.

  Evidence: `evidence/gap-suite.txt`.
- [x] **AC2 (R1, R5).** `go test -race -count=1 ./...` and `go vet ./...` pass. No existing test file was modified (`git diff --name-status 1d0a072` lists only additions, plus `Makefile`, `go.mod` and `go.sum`), so the capture and parser tests pass unchanged.
- [x] **AC3 (R4).** One documented command, `scripts/mcp-conformance.sh` (or `make mcp-conformance`), runs the pinned CLI `0.1.16` against the fixture server and both fixture clients. There are zero failures, and the waiver list is the verbatim SDK baseline, with no Shipyard entry.
  - Server: `--spec-version 2025-11-25`, the full active suite, 30 scenarios.
  - Clients: suite `core`, 18 scenarios per era.
  - Suite `all` was also run. Its only non-baseline failures are the two scenarios that the SDK reference client also fails (see R4 above). No Shipyard waiver was added to hide them.
- [x] **AC4 (R5).** `TestPair_CaptureRoundTripKeepsRawBytesAndHeaders` and `TestIngest_KeepsRawBytesAndHeadersWithoutAliasing` in `internal/mcpcore/core_test.go` cover this.
  - The input defeats any re-encoding: odd whitespace and key order, a `\u00e9` escape, an integer ID of 2^53+1, and multi-value headers.
  - The pair keeps its bytes and headers after validation.
  - The capture store persists both payloads byte-identically.
  - Mutating the inputs or the returned copies does not alter the envelope.
- [x] **AC5 (R6).** `docs/dependencies/go-sdk.md` records the SDK version, the license, the security notes and the rollback revision `1d0a072`, noting `95bc5a1`.
- [x] **AC6.** No gateway, bridge or child source changed.
  - `make smoke-full` passes, and the existing integration tests pass with no assertion edits.
  - `go version -m` on freshly built `cmd/shipyard` and `cmd/shipyard-mcp` shows identical dependency module lists before and after. Only the main-module VCS pseudo-version differs. Evidence: `evidence/ac6-*.mods`.
  - The SDK is not linked into any shipped binary.

R1 is now ticked. The spec has a `## Resolution — 2026-10-03` section that points to `docs/adr/0005-mcp-go-sdk-adoption.md` and states where the custom capture-boundary type is kept (`mcpcore.Envelope`, `internal/mcpcore/envelope.go`) and why. No R or AC text and no `status:` was changed.

## Scope Blockers
- Resolved.
  - The repo owner approved widening scope to `.nightshift/coverage-baseline.json` only. The `## Scope Amendments` row is on main at `441438b`, merged here as `cc85741`.
  - Main commit `e763474` mirrors it into the frontmatter `scope.write`, merged here as `e6ad913`. The guard (`scope_guard.py`) reads the write scope from that frontmatter list, and an amendment row on its own does not grant a path.
  - Floors were added following the file's convention: a floor equals the measured value at one decimal, keys are in alphabetical order, and the values were stable across three runs.
    - `internal/mcpcore`: 95.2
    - `internal/mcpfixture`: 87.4
    - `internal/mcpfixture/cmd/mcpfixture`: 84.3
  - `total` and `measured_at` are unchanged.
  - `.nightshift/coverage-exclusions.json` and `.staticcheck.conf` were not touched.
- Environment-only residual, not a blocker: `internal/secrets/op` measures 21.1% against a 28.6% floor.
  - The package is untouched and identical to main.
  - Its tests branch on `exec.LookPath("op")`, and the 1Password CLI is not installed on this host.
  - It fails here on main too. It was not lowered.

## Blocked Specs
None

## Open Questions
- SPEC-BUG-181 § R1: resolved. The spec now has a `## Resolution — 2026-10-03` section, and R1 is ticked.
- SPEC-BUG-181 § Context, staticcheck policy (advisory): `.staticcheck.conf` asks that every exception be named in that file. That file is outside my scope. The only exception added is `SA1019`, scoped to `internal/mcpfixture/surface.go` and `internal/mcpfixture/scenario_test.go`, with a rationale in each file header: the legacy conformance surface exercises sampling and logging, which SEP-2577 deprecates. The parent may want to list it in `.staticcheck.conf`.
- SPEC-BUG-181 § R4 (advisory): conformance CLI `0.1.16` is the latest stable release and has no `2026-07-28` scenarios. The go-sdk's own CI uses `0.2.0-alpha.11` for that leg. The modern era is covered by the golden wire tests. The script prints a NOTICE and runs no fake-green modern server leg.
- SPEC-BUG-182…185 (advisory, these are findings pinned by the goldens):
  1. go-sdk v1.8.0 emits `ttlMs` and `cacheScope` on list results in both eras.
  2. In stateless (modern) mode the SDK client sends `notifications/cancelled`, but it cannot cancel the original in-flight call, because each request gets a fresh session. G7's fix must not rely on SDK stateless cancellation.
  3. `capture.Store` persists payload bytes but not headers.
- SPEC-BUG-182…185, G3 owner (advisory): the G3 case is not independent of G2. It goes red only because the modern SDK client falls back to `initialize`, and it does that only because `server/discover` is missing on the gateway, which is the G2 gap. Whichever spec closes G2 will probably turn G3 green as a side effect, even if `initialize` still issues `Mcp-Session-Id` unconditionally for legacy-era sessions. The G3 owner should keep or extend a direct check of the `initialize` path if that behaviour is in scope.

## Report Action Log
| Report | `## Open Questions` / `## Blocked Specs` present? | Action taken |
| --- | --- | --- |
| (this report) | Yes | resolved_in_report |

## Discovered TODOs
- `make security-gosec` cannot run under the local go1.27.1 toolchain (gosec v2.22.10 internal error). This is unrelated to this spec.

## Suggested Follow-up Specs
- title: "Bump MCP conformance CLI pin when a stable release covers 2026-07-28"
  rationale: "The pinned stable @modelcontextprotocol/conformance 0.1.16 has no 2026-07-28 scenarios (go-sdk CI uses 0.2.0-alpha.11). Once a stable 0.2.x ships, add a stateless modern server leg to scripts/mcp-conformance.sh against the modern fixture and re-copy the go-sdk baseline if it changes. Out of scope here: R4 requires a stable pin."
  artifact: "scripts/mcp-conformance.sh"
  domain: "test"
  layer: 0
  parent: "SPEC-BUG-180"
- title: "Persist captured MCP headers alongside payload bytes"
  rationale: "mcpcore.Envelope keeps the headers, but capture.Store's schema stores only the payload. The modern era routes on Mcp-Method, Mcp-Name and Mcp-Protocol-Version, so header capture is needed for faithful traffic inspection. Changing the capture schema was out of scope (AC2/AC6)."
  artifact: "internal/capture/store.go"
  domain: "be"
  layer: 1
  parent: "SPEC-BUG-180"

## Metrics Fidelity
Not run. Metrics are emitted by the post-commit hook when the parent makes the lifecycle commit (LOOP Step 13). This worker made no lifecycle commit.

## Changelog
- Added `internal/mcpcore`: an SDK-backed MCP era classifier, raw-preserving envelope and shared validator.
- Added `internal/mcpfixture` and the `mcpfixture` command: modern and legacy fixture servers and clients, the recording transport and the golden wire cases.
- Added `scripts/mcp-conformance.sh` (`make mcp-conformance`), with the CLI pinned at 0.1.16 and verbatim SDK waivers.
- Added `scripts/mcp-gap-suite.sh` (`make mcp-gap`), covering G1–G7 with build tag `mcpgap`.
- Added ADR 0005 and `docs/dependencies/go-sdk.md`.
- Dependency: `github.com/modelcontextprotocol/go-sdk v1.8.0`, not linked into the shipped binaries.

## Process Notes
- The worktree branch started at `8609a53`, behind the baseline. I fast-forwarded it to `1d0a072` before any edits.
- `internal/mcpcore/core.go`, a red-phase stub created in this run, was replaced with Write rather than Edit (a deviation from the brief's Edit-only rule for existing files). All other stub replacements used Edit.
- The Write tool converted a literal `\u00e9` escape inside a Go raw string into the character itself. I caught this through a failing test and fixed it with an escaped string literal.
