# Nightshift Report — 2026-10-03

**Outcome:** blocked
<!-- Follow-up 2026-10-03: the coordinator relayed a human-approved scope
     amendment (main 441438b). R1 is resolved. The coverage floors could not be
     committed: the write-scope hook reads scope.write from the spec frontmatter
     on main, and 441438b added only the amendment row, not the frontmatter entry.
     See Scope Blockers. -->

Run: `kickoff-20261003-bug181`. Spec: SPEC-BUG-181, MCP 2026-07-28 conformance fixtures and compatibility core.
Baseline: `1d0a07206f6893dc95651cfe737f3aff6591653e`. The worktree started at `8609a53`; it was fast-forwarded to the baseline before any work began.
Branch: `worktree-agent-a7d39841455a362cf`.

## Summary
- Specs completed: 0 of 1. Only the coverage-floor commit is outstanding (see Scope Blockers).
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
- Coverage gate (`make coverage-check`, the configured `commands.test`). The total is 80.3%, above the 75.1% floor. I added the three floors in the working tree and the gate was re-run. With those floors in place, its only failure was `internal/secrets/op: 21.1% is below baseline 28.6%`, which is environment-only:
  - The package is identical to main (`git diff 441438b -- internal/secrets` is empty).
  - Its coverage depends on whether the 1Password `op` CLI is on PATH, and it is absent on this host.
  - So main fails the same way here.
  - The floor was not lowered.

  The floors themselves are not committed: the write-scope hook rejected `.nightshift/coverage-baseline.json` (see Scope Blockers). The committed branch therefore still lacks the floors.
- Review cycles: 2 advisor reviews, one before implementation and one before completion. No separate LOOP Step 7/10 persona pass was performed. The second advisor review led to the `--suite all` comparison, the floor-stability check and the G3/G2 note below.

## Completed Specs
- None yet. Everything except the coverage-floor commit is done; see Scope Blockers.

## Changes (SPEC-BUG-181)
Commits on the branch:
- `4ef9d73` `[SPEC-BUG-181] test: add red core, fixture, golden and G1-G7 gap tests`: the red tests, with compile-only stubs.
- `24a034c` `[SPEC-BUG-181] feat: MCP conformance fixtures and compatibility core`
- `518c691` `[SPEC-BUG-181] docs: generate nightshift report`
- A follow-up commit, `[SPEC-BUG-181] fix: register full SDK auth scenario set and document conformance suite choice`. It registers the remaining SDK auth scenarios in the fixture client, records the `core`-versus-`all` rationale, adds the suite-all evidence and applies these report corrections.
- `cc85741` `[SPEC-BUG-181] chore: merge main scope amendment (441438b)`: a `--no-ff` merge of main. It brings in the human-approved `## Scope Amendments` row, plus main's unrelated `a87838a` (SPEC-BUG-164 tracking files).
- A final follow-up commit, `[SPEC-BUG-181] docs: add R1 resolution and record coverage-floor blocker`. It adds the spec `## Resolution — 2026-10-03` section, ticks R1 and updates this report. The coverage floors were rejected by the write-scope hook and are not committed.

Compared with the baseline, only `Makefile`, `go.mod` and `go.sum` are modified, ignoring the spec and report files and main's merged SPEC-BUG-164 files. Every other file is new. No live gateway, bridge or child source file is touched.

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
| `make coverage-check` (run with the three floors added in the working tree, then reverted) | environment-only failure. The ratchet's single finding was `internal/secrets/op: 21.1% is below baseline 28.6%`. That package is untouched and identical to main, and the `op` CLI is not installed. New packages: mcpcore 95.2, mcpfixture 87.4, cmd/mcpfixture 84.3; total 80.3%. As committed, without the floors, the gate also reports the three missing floors. |

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
- **`.nightshift/coverage-baseline.json` is still not writable.** The repo owner's amendment row is on main at `441438b` and is merged here as `cc85741`. But the commit with the floors was rejected:
  ```
  [nightshift write-scope] BLOCKED — spec SPEC-BUG-181 declares write scope: internal/**, cmd/**, test/**, scripts/**, docs/**, go.mod, go.sum, Makefile
  [nightshift write-scope]   DENY outside_root .nightshift/coverage-baseline.json
  ```
  - Cause: `.nightshift/scope_guard.py` resolves the write scope from the spec's frontmatter `scope.write` **on main** (`git show main:<spec>`).
  - A `## Scope Amendments` row only authorizes a *widening of that frontmatter list*. Widenings without a covering row are rolled back, so the row on its own grants nothing.
  - `441438b` added the row but did not add `.nightshift/coverage-baseline.json` to `scope.write`.
  - The hook has no environment-variable bypass.
  - I cannot fix this from the branch: the guard reads main, and I must not change the frontmatter.
- **Smallest recovery.** Choose one.
  - **(a)** On main, add `- .nightshift/coverage-baseline.json` to the spec frontmatter `scope.write`. The existing 2026-10-03 amendment row covers that widening. Then re-run this follow-up; I add the floors and commit.
  - **(b)** The parent commits the floors itself, adding these entries to the `packages` map of `.nightshift/coverage-baseline.json`, alphabetically after `internal/gateway`:
    ```json
    "github.com/sloik/shipyard/internal/mcpcore": 95.2,
    "github.com/sloik/shipyard/internal/mcpfixture": 87.4,
    "github.com/sloik/shipyard/internal/mcpfixture/cmd/mcpfixture": 84.3,
    ```
  - These follow the file's convention: a floor equals the measured value at one decimal, and the values were stable across three runs. `total` and `measured_at` stay unchanged.
- **Environment-only residual, not a blocker.** `internal/secrets/op` measures 21.1% against a 28.6% floor.
  - The package is untouched and identical to main.
  - Its tests branch on `exec.LookPath("op")`, and the 1Password CLI is not installed on this host.
  - It fails here on main too. It was not lowered.

## Blocked Specs
- SPEC-BUG-181: MCP 2026-07-28 conformance fixtures and compatibility core. ⏸ worker-blocked. The only remaining step is the coverage-floor commit, which needs recovery (a) or (b) under Scope Blockers.

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
| (this report) | Yes | deferred: coverage floors need the scope.write frontmatter entry on main, or a parent commit |

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
