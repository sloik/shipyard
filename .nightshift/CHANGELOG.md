# Nightshift Kit — Changelog & Migration Guide

> **Versioning:** SemVer (`kit_version` in config.yaml).
> - **Major** — breaking changes to protocol, config schema, or metrics schema
> - **Minor** — new features, new config sections, new protocol steps (backward-compatible)
> - **Patch** — bug fixes, wording clarifications, no config/protocol changes
>
> **Rule:** Every change to canonical files MUST bump `kit_version` and add an entry here.
> The `runtime.loop_version` field (date-based) tracks when the LOOP.md was last touched
> and is used for metrics comparison — it is NOT the authoritative version.

---

## 2.60.1 (2026-08-01)

### Board lifecycle authority and contract-review metrics

- A terminal lifecycle decision on main (`blocked`, `done`, `superseded`, or
  `retired`) now remains in its canonical board column even when a retained
  worktree still reports `in_progress`.
- Lifecycle classification events can record bounded, prose-free R/AC contract
  friction telemetry and calibration metrics.

## 2.60.0 (2026-07-29)

### Completed release, lifecycle, and board reliability work

- Fleet release policy declarations now reconcile with compatible repository
  commit hooks before a guarded local rollout (SPEC-156-002).
- The board's copy actions work from both the standalone board and the
  Nightshift Control modal, with a supported browser fallback (SPEC-171,
  SPEC-171-001).
- Spec maturity, priority, and run-admission state are represented separately
  in lifecycle and board views (SPEC-162-001).
- `board.sh` backgrounds the board, reports its exact stop command, and can
  safely stop only its own recorded board process (SPEC-167).

---

## 2.59.0 (2026-07-29)

### Atomic versioned fleet release (SPEC-156)

Canonical kits now have deterministic, content-addressed release manifests.
Release apply copies the complete managed set, verifies it, and writes an exact
installed release marker last. Generated project registries are a separate
operation and are excluded from release diffs.

The `/nightshift release` coordinator now owns canonical preflight, bounded
per-install migration workers, repository-wide dirty-path isolation, exact
allowlisted local commits, declared smoke verification, stop-on-unexpected
semantics and structured fleet evidence. Nightshift Control can run a release
preflight and copy the coordinator prompt, but cannot apply directly.

## 2.58.0 (2026-07-28)

### Canonical sync safety batch (SPEC-151–154)

Canonical sync now excludes documentation templates from live-spec validation,
avoids treating documented structured run IDs as payment-card PII, registers the
canonical Nightshift project for cross-project `SPEC` dependencies, and blocks
propagation when the canonical kit version and changelog release metadata differ.

## 2.57.0 (2026-07-28)

### Compatible commit grammar and lifecycle metrics (SPEC-150)

Nightshift now accepts ordinary `[SPEC-ID] type: description` commits alongside
the parent lifecycle subjects that emit metrics: `chore: mark SPEC-ID done` and
`blocked`. The shared grammar supports hierarchical IDs with numeric final
components, and canonical sync deploys the hook, metrics parser, and supporting
protocol guidance together.

---

## 2.56.0 (2026-07-27)

### Control work summary and metric help (SPEC-144)

Nightshift Control now shows Draft, Blocked, Ready, and Active work counts for
every discovered project, plus an explicit `OPEN` or `CLEAR` state. The counts
are read-only, work when a project board is stopped, and use a short cache so
routine Control polling remains lightweight. The per-project board's RUNS,
MTTD, MTTR, CFR, FORMAT, and EASY-FIX indicators now include concise native
hover help.

---

## 2.55.0 (2026-07-25)

### Pending draft and ready work tiles (SPEC-142)

The Nightshift control board now shows compact Draft and Ready tiles in its
header. They derive from the same canonical spec-frontmatter payload as the
board, refresh with normal board refresh and polling, and explicitly render
zero when no work is waiting in either lifecycle state.

---

## 2.54.0 (2026-07-25)

### Static active-NFR reconciliation gate (SPEC-140)

Active NFR scope matching now has one canonical implementation shared by the
impact audit and validation gate. `ready`, `in_progress`, and `blocked` specs
must bind every mechanically matched active NFR (directly or through its parent)
or record an auditable `nfr_waivers: [{id, reason}]` decision; drafts warn while
done specs are not re-gated. `audit_nfr.py --check-all` provides the CI and
pre-promotion batch gate. The canonical authoring and orchestration guidance now
makes reconciliation agent-owned housekeeping rather than optional human review.

---

## 2.53.0 (2026-07-25)

### Parent-authoritative kickoff resolution metrics (SPEC-139-004-001)

Mark-commit metrics now link blocked and later-recovered transitions with the
canonical `in_progress` commit as a stable run ID. Parent lifecycle commits
capture all four evidence-gate results, blocker class and scope, unblock
attempts/limit, automatic-unblock success, deferred recovery, and measured
resolution latency through controlled Git trailers. Validation remains
backward-compatible for historical rows, while cross-run analysis reports
evidence-gate failure rate, automatic-unblock success rate, deferred-recovery
rate, blocker-class counts, and median final resolution latency.

## 2.52.0 (2026-07-25)

### Bounded parallel orchestration proof and operator guidance (SPEC-139-004)

Canonical Nightshift now includes a hermetic real-Git-repository proof covering
live frontier fan-out, descendant-only blocking, serialized green merges,
conflict holding, post-merge reversion, and retained unmerged work. The
orchestrator and Git guides add the operator checklist: worktrees isolate edits
but do not make specs compatible, and one coordinator exclusively owns lifecycle
and merge transitions. `config-reference.yaml` documents the bounded
`parallel_integration.max_repair_attempts` setting.

## 2.51.0 (2026-07-02)

### Emission-time vocabulary normalization (SPEC-130)

`record_metrics.py` now normalizes status and model vocabulary where rows are
born: status synonyms (`done`, `implemented`, `passed`, …) map to the
VOCABULARY.md canonical enum with the original preserved in `status_raw`;
out-of-vocab statuses pass through with a loud warning. Model spellings are
case-folded through an alias table (`GPT-5 Codex`/`codex-gpt-5`/`codex` →
`gpt-5-codex`) with `model_raw` preserved, and `?`/`unknown`/blank model values
fall through the trailer → config → `unknown` chain instead of winning it.
Historical rows are not rewritten. Driven by the 2026-07-02 cross-project
aggregation (14 status variants, ~39% unusable model attribution across 381
rows).

## 2.50.0 (2026-07-02)

### Canonical audit batch (SPEC-124..128)

- **SPEC-124 (bugfix):** kit test suite no longer reads fixtures from live
  install paths — Dashboard/hear-me-say metrics fixtures vendored into
  `tests/fixtures/`. Suite is green on any checkout.
- **SPEC-125 (bugfix):** `validate_metrics.py` type-guards all numeric
  comparisons (13 sites): null/list-typed fields yield validation errors
  instead of a TypeError that killed `analyze_metrics.py` on real corpora.
- **SPEC-126 (bugfix):** `worktree_janitor.py` resolves project-prefixed spec
  IDs (`FART-SCR-132-002`, `SPEC-CTX-MCP-008`) from branch names; previously
  only bare `SPEC-\d+` matched, making the janitor a no-op on real installs.
- **SPEC-127:** `nightshift-sync.py canonical` now writes `kit_version`
  through to each install's config.yaml (only that value; rest of the file
  untouched). Ends the perennial version-mismatch warning noise.
- **SPEC-128:** janitor gains `sweep_wip_heartbeats()` — removes
  `reports/_wip/orchestrator-progress-*.md` for done specs immediately and
  other resolved per-run `_wip` files past 30 days; wired into
  `run_startup_janitor`.

## 2.49.1 (2026-06-28)

### Board status write-through regression fix

Board-originated status changes now update both the durable status checkpoint
store and the spec file's `status:` frontmatter. This keeps board drag/API
changes aligned with `/nightshift kickoff`, which gates on the markdown file.

The board also reconciles newer spec-file frontmatter for non-terminal statuses,
not only terminal states, while preserving worktree-origin durable checkpoints
whose `spec_path` points at a different checkout.

## 2.49.0 (2026-06-26)

### Multi-axis code-generation rubric (SPEC-108)

`eval/codegen_rubric.py` scores generated code artifacts across test pass-rate,
execution time, SPEC-093 secret/PII scanner findings, and coupling/complexity.
It aggregates vectors per model, selects Pareto-best models without collapsing
the axes into one scalar, flags trivial or under-covered test sets using the
SPEC-097 coverage-targeted posture, and emits `routing_signal` /
`sft_target_signal` fields for SPEC-099 and SPEC-100 consumers.

## 2.48.0 (2026-06-26)

### Trajectory and path evaluation (SPEC-107)

`eval/trajectory.py` evaluates agent runs at final-response, single-step, and
trajectory granularity. Trajectory assertions are opt-in per eval spec and
support any-order, in-order, and exact-order tool-call matching, plus repeated
run averaging for noisy path variance.

## 2.47.0 (2026-06-25)

### Failure taxonomy and tool-call validity metrics (SPEC-106)

`eval/failure_taxonomy.py` classifies failed or low-quality regression traces
into named failure modes, builds row-normalized confusion matrices with the
diagonal zeroed, surfaces dominant asymmetric error pairs, computes tool-call
validity rates, and emits an evolve-friendly prioritized-fix payload.

### SFT decision procedure reference (SPEC-109)

`knowledge/tool-call-schema-validation-rubric.md` now includes the quantitative
SFT pre-run decision procedure: a token-budget gate, learning-curve read-out
rule, optional full-precision-only `weightwatcher` triage, and the
data-before-hyperparameters posture.

## 2.46.0 (2026-06-25)

### Loop observability metrics (SPEC-111)

`loop_observability.py` computes MTTD, MTTR, change failure rate, and
format-failure/easy-fix rates from the existing Nightshift execution history
database. The board exposes the metrics through `/api/loop-observability` and a
compact header strip, while `Skills/evolve/scripts/evolve-metrics.py` includes
the same block in summary JSON and as the named `loop_observability` metric.

---

## 2.45.0 (2026-06-25)

### Confidence calibration reliability diagram (SPEC-112)

`confidence_gate.py` now records labeled confidence/outcome pairs to an
append-only JSONL store, computes reliability-diagram bins and Expected
Calibration Error, renders the diagram as Markdown, and recommends a data-tuned
confidence floor when ECE shows miscalibration.

---

## 2.44.1 (2026-06-25)

### Board durable-status reconciliation (SPEC-120)

The board now reconciles stale durable status checkpoints when canonical spec
frontmatter has a newer terminal status. Active worktree transitions still use
the durable store, but a spec completed through frontmatter/metrics no longer
stays silently stuck in `in_progress`; the board appends a
`frontmatter-reconcile` checkpoint and displays the terminal status.

Canonical sync now also includes `trace_export.py`, which is imported by
`failure_persistence.py`.

---

## 2.44.0 (2026-06-25)

### Loop-level caching (SPEC-105)

`prompt_engine.py` now exposes stable-prefix prompt composition so loop calls
can keep system/primer/spec/DevKB context as a fixed literal prefix while
appending volatile per-step state. `llm_client.py` accepts structured prompts:
Anthropic requests put `cache_control` on the stable prefix block, while
OpenAI-compatible local calls send one literal prompt string for KV-prefix reuse.
`nightshift_coordinator.py` adds an exact full-input-hash cache for
deterministic sub-steps and explicitly bypasses gating tests and volatile state.

## 2.43.0 (2026-06-24)

### Offline replay-eval gate for `/evolve` protocol changes (SPEC-110)

`Skills/evolve/scripts/offline-replay-eval.py` replays candidate protocol
changes against SPEC-095 regression trace cases, scores baseline and candidate
outputs with SPEC-097 graded eval metrics, applies a bootstrap confidence
interval over per-trace deltas, checks declared neutral trace classes for
decision invariance, and logs promote/reject rationales before live protocol
promotion.

## 2.42.0 (2026-06-24)

### Graded eval metrics and calibrated judge pinning (SPEC-097)

`canonical/eval/` adds graded eval primitives over the SPEC-095 regression trace
corpus: pinned judge tuples with stable hashes, explicit local rubrics,
per-slice metric aggregation for production-distribution / known-failure /
out-of-scope cases, north-star correlation anti-overfit flags, bootstrap-CI
improvement gating with the 3x-to-10x sample-size rule, and coverage-targeted
edge-case synthesis for named weak slices.

## 2.41.0 (2026-06-24)

### Confidence-scored escalation gate (SPEC-098)

`confidence_gate.py` adds a pure decision-level escalation gate for agent
outputs. Callers can score discrete decisions from 3-5 diverse reruns using
majority-vote agreement, or use a native 0-1 logprob confidence without extra
rerun cost. The gate escalates material-consequence decisions when confidence is
below the configured floor or rerun variance exceeds the configured bound, while
low-stakes uncertain decisions auto-proceed.

## Documentation (2026-06-24)

### Argo stack threat model (SPEC-102)

`knowledge/argo-stack-threat-model-RAISE.md` captures a Nightshift-local threat
model over Argo's Cortex / Nightshift / Hippo / MCP / parallel-agent surfaces.
It uses Wilson's trust boundaries, RAISE, and excessive-agency taxonomy, and
states explicitly that MAESTRO is only the Albada alternative frame.

## 2.40.0 (2026-06-24)

### Tool-call schema validation + SFT decision rubric (SPEC-100)

`tool_call_validation.py` adds a local runtime guard that parses model-emitted
tool calls, validates arguments with Pydantic schemas before handler execution,
and rejects malformed calls such as `add(jeden, dwa)` or over-arity calls before
any tool side effect can run.

The new rubric in `knowledge/tool-call-schema-validation-rubric.md` documents
schema validation as the near-term deliverable, prompt/grammar tool exposure as
the default over per-tool SFT, and QLoRA adapter retraining as research-tier
work reserved for hot-path, stable tasks with collected weak cases.

## 2.39.0 (2026-06-24)

### Model routing by complexity (SPEC-099)

`model_selection.py` now exposes semantic model-tier routing primitives:
`RouteQuery` for structured classifier output, off-schema tier normalization,
nearest-centroid semantic routing over exemplar tasks, routed tool trimming,
and measured latency/throughput trust gates before a tier can be used.

## 2.38.0 (2026-06-24)

### Regression trace export to eval corpus (SPEC-095)

Failed runs can now export a replayable regression trace case into
`eval-specs/regression-traces/` when the failure event carries structured trace
context. The exported JSON case records the AIE log-everything field contract,
the failing-step label (`retrieval`, `processing`, or `generation`), the expected
output, and a minimal replay check so a captured failure can become a green
regression after the fix.

## 2.37.0 (2026-06-24)

### Actor-critic in-place revision loop (SPEC-096)

`critic.py` now defines structured critic inputs that preserve raw failing
test/lint/type/build output verbatim, including explicit role inversion when the
actor and critic are the same local model. `loop.py` adds a bounded
generate/reflect revision primitive that keeps the same actor in the same
worktree and escalates after the configured cap instead of re-dispatching or
looping indefinitely.

ORCHESTRATOR.md now states that failed post-merge validation output must be sent
back as raw critic input to the same worktree actor before revert/escalation.

## 2.36.0 (2026-06-24)

### Commit secret/PII + escalation gate (SPEC-093)

`scanner.py` is now an importable staged-diff scanner that returns structured
secret/PII findings and threshold-triggered escalation decisions. The
pre-commit hook calls it before spec validation, lint, and type checks, rejecting
staged secrets, valid PII, and over-bound diff/token cost unless explicit
Lukasz sign-off is supplied through the configured environment variable.

New git config fields: `diff_risk_threshold`, `token_cost_threshold`, and
`escalation_signoff_env`.

## 2.35.1 (2026-06-24)

### Board copy-run prompt avoids duplicated spec IDs

`COPY RUN PROMPT` now detects titles that already begin with the selected spec
ID, such as `SPEC-CTX-TOOLS-048 — Eliminate Reverse-Drift False Positives`, and
uses that title as the kickoff label instead of prefixing the ID again. Titles
without the ID keep the existing `/nightshift kickoff <SPEC-ID> <Title>` shape.

## 2.35.0 (2026-06-24)

### Durable spec-status checkpoint layer (SPEC-094)

Spec status can now be stored as append-only SQLite checkpoints keyed by stable
spec id. `status_store.py` exposes `get_state`, `update_state`, and
`get_state_history`; board reads overlay the latest durable checkpoint on top of
spec frontmatter while retaining frontmatter as fallback metadata. The live board
initializes the store from the repository's git common directory, so worktrees of
the same checkout share one status DB and a worktree-side status update becomes
visible to the main board before merge.

The board API adds `/api/spec/{spec_id}/status/history` for the audit ledger.
Existing file-backed `SpecCache` behavior remains available when no store is
configured, which keeps static/export and legacy tests compatible.

## 2.35.0 (2026-06-24)

### Board copy-run prompt includes the spec title

The board's `COPY RUN PROMPT` now includes the selected spec's title in the
kickoff command line (`/nightshift kickoff <SPEC-ID> <Title>`). This keeps
cross-project pasted prompts distinguishable when multiple projects reuse
the same spec ID. No config or protocol-step changes.

---

## 2.34.0 (2026-06-14)

### `run_validation.py`: mechanize Step 9 validation capture (SPEC-092 / R4 conversion)

The first conversion from SPEC-089's mechanization inventory (after metrics in SPEC-086).
`run_validation.py` runs the configured `commands.{build,test,lint,type_check}` (respecting
`test_timeout_s`, Null Command Policy) and writes `metrics/<spec-id>.validation.json`
(build_pass, tests_total/passed/failed, lint/type errors, per-command exit). The mark-done
metrics hook now **prefers** that file for authoritative test/lint/type/build numbers,
falling back to report-parsing when absent — additive, no behaviour change when missing.
LOOP.md Step 9 documents it as optional convenience (not hard-mandatory). +5 run_validation
tests, +1 mark-commit test (prefers validation.json).

**DOGFOODED:** ran `run_validation.py` on the canonical kit's own pytest → a real
`validation.json` (build_pass true, **17/17 tests**); the SPEC-092 mark-done row reads those
counts. This closes the last loose thread in the metrics arc — test counts are now
authoritative, not parsed from prose.

---

## 2.33.0 (2026-06-14)

### Unify telemetry: ingest eval `results/` into the `metrics/` corpus (SPEC-091)

R5 surfaced that small-model data lived only in the eval harness's `results/` corpus,
invisible to `analyze_metrics`/the audit (which read `metrics/`) — two telemetry systems
that don't talk. `ingest_eval_results.py` converts each `results/<model>/EVAL-N/result.json`
into a schema-valid `metrics/*.yaml` row by **reusing `record_metrics.build_metrics`** (no
schema drift): `pass`→completed/done, `fail`→failed/partial, `timeout`→blocked (+ derived
`error_type`/`kill_reason`); `started_at` derived from `timestamp − total_duration_s`; git
fields synthetic. Idempotent (`--dry-run`, `--include-archived`). +4 tests.

**DOGFOODED:** ran on the real corpus → **21 eval rows** ingested, all validate-clean,
idempotent. The `metrics/` corpus now holds 5 small/local models (gemma-4-31b, qwen-72b,
mistral-small, deepseek-32b, qwen3.5-9b-mlx) with outcome distributions — cross-model
comparison (the stated reason metrics exist) is queryable for the first time.

---

## 2.32.0 (2026-06-14)

### Inline duplicate-spec body-text gate (SPEC-088 / audit R6)

`check_followup_spec.py check()` (the per-suggestion gate) compared only titles, so a
verbatim-duplicate follow-up that shared few title tokens slipped through at creation
(the SPEC-055==048 leak); only the whole-corpus `scan_all` compared bodies. `check()`
now accepts `--suggestion-body` (the proposed requirement/AC prose) and flags
`body_similarity` against existing specs' Requirements+AC sections, reusing scan_all's
tokeniser/threshold so inline and corpus agree. Backward compatible (title-only when
omitted). +3 tests (30 green). The `nightshift` skill Step 7 should pass
`--suggestion-body` to activate it; until then `scan_all` remains the disk-level backstop.

---

## 2.31.0 (2026-06-14)

### Hook-driven metrics: rollout mechanism, model attribution (F3), LOOP rewire (SPEC-087)

Builds on SPEC-086 (the dogfooded mechanical emission) to make it the *primary* path
everywhere and to close the audit's F3 (cross-model attribution).

- **LOOP.md Step 13 rewritten:** metric/ledger emission is hook-driven at the mark-done
  commit; the in-loop `record_metrics.py` call is now explicitly **optional enrichment**,
  not a mandatory terminal step (the droppable instruction the audit showed fails).
- **ORCHESTRATOR.md standardized:** mark-done/blocked/in_progress commits use the
  canonical `chore: mark <id> <state>` subject (the hook + `started_at` derivation key on
  it; the old `[<id>] chore: mark done` would not trigger the hook). Metrics no longer
  hand-authored.
- **Model attribution (closes F3):** the mark-done commit MAY carry a `Nightshift-Model: <id>`
  trailer; `record_metrics.py --mark-commit` reads it (precedence trailer > `--model` >
  config > `unknown`). Best-effort — a dropped trailer degrades to `unknown`, no hard
  dependency — but when present the rows finally answer "which model". The mark-commit
  regex also broadened to accept `chore(scope): mark ...`.
- **`nightshift-sync.py --install-git-hooks`** (opt-in): idempotently activates the
  post-commit hook in each install's git hooks dir — merges the marked block into an
  existing hook (e.g. graphify) rather than overwriting, and dedups monorepo installs
  that share one `.git`. Off by default (it touches `.git/hooks`); pair with `--dry-run`.
- **Tests:** +3 mark-commit (trailer / no-trailer→unknown / `chore(scope):`), +5 sync
  hook-install (fresh / merge / idempotent / dry-run / non-git). 39 metrics+sync tests green.
- **DOGFOODED (AC5):** SPEC-087's own `chore: mark SPEC-087 done` commit (`9ab12481`)
  with a `Nightshift-Model: claude-opus-4-8` trailer auto-emitted
  `metrics/2026-06-14_002_SPEC-087.yaml` — validate-clean, `model` populated from the
  trailer, zero hand-authoring.

**Reach:** monorepo installs (Cortex/*, Inbox, Tools/*, Skills/focus) are live (shared
hooks path). **Deferred:** executing the standalone-repo rollout (Fartownik/CoJezdzi/
shipyard/agent-chat-mcp) — the mechanism is built + dry-run-verified, but installing into
active external repos is left as a deliberate `nightshift-sync.py canonical --install-git-hooks`
run rather than mutating them mid-session.

---

## 2.30.0 (2026-06-14)

### Mechanical metrics + failure-ledger emission at the mark-commit (SPEC-086)

The 2026-06-14 audit (`AUDIT-followup-2026-06-14.md`) measured that SPEC-067's
`record_metrics.py` changed nothing on real runs — metric capture stayed at 1.6%
because the script still had to be *invoked by the agent* at the end of a run (a
droppable terminal step), and 0 failure-ledgers existed across 11 installs. Root
cause: fixes that depend on the agent following an instruction don't survive real
runs. The remedy is mechanical.

- **`record_metrics.py` gains `--mark-commit <sha>` mode.** Given a
  `chore: mark <id> done|blocked` commit it derives EVERYTHING with zero
  agent-supplied args: spec-id/outcome from the subject, `started_at` from the
  matching `mark <id> in_progress` commit, `completed_at` from the mark commit,
  files/lines from the `in_progress..mark` span (scoped to the install), tests from
  the spec's newest report, model/harness from config. Routes to the correct
  install via the spec file path changed in the commit. Idempotent (won't duplicate
  or clobber an agent-authored row). No-ops on every non-mark commit.
- **`hooks/post-commit`** (new) calls it, so emission is agent-independent. If the
  repo already has a post-commit hook (e.g. graphify), install the marked block at
  the top (graphify's early `exit 0` would skip a trailing block).
- **`tests/test_mark_commit_metrics.py`** (5 tests, AC1–AC5). Existing 12
  `record_metrics` tests unchanged/green.
- **DOGFOODED (AC6):** SPEC-086's own `chore: mark SPEC-086 done` commit
  (`b59d7a38`) auto-emitted a `validate_metrics`-valid row with zero hand-authoring.
  Emitted row committed as evidence (`metrics/2026-06-14_001_SPEC-086.yaml`).

**Reach:** the monorepo installs (Cortex/*, Inbox, Tools/*, Skills/focus) are LIVE
immediately — they share Argo Home's `core.hooksPath`, so the one installed
`post-commit` serves all of them and falls through to canonical's new
`record_metrics.py`. The next real internal `mark done` auto-emits. **Deferred to
SPEC-087 (rollout, draft):** LOOP.md/ORCHESTRATOR wording (in-loop call → optional
enrichment), and installing the hook + syncing the new `record_metrics.py` into the
STANDALONE repos (Fartownik/CoJezdzi/shipyard — their copies lack `--mark-commit`,
so a hook-only install there no-ops). Verify-then-sync for the standalone fan-out.

**Known limitation (not fixed here):** hook-emitted rows carry `model: unknown` — the
hook can't know which model ran. This fixes R1 (rows exist: 1.6% → guaranteed) and R3
(ledger), but NOT the audit's F3 cross-model-comparison purpose; `model` attribution
still needs the optional in-loop enrichment call, or capturing the running model at
commit time (e.g. a commit trailer the hook reads) — tracked separately.

**Changes:** `record_metrics.py` (+`--mark-commit` mode), `hooks/post-commit` (new),
`tests/test_mark_commit_metrics.py` (new), `specs/SPEC-086-*` (done), `specs/SPEC-087-*`
(draft), version artifacts → 2.30.0.

---

## 2.29.5 (2026-06-14)

### Version-artifact reconciliation + audit follow-up (SPEC-086 drafted)

**Version drift fix (bookkeeping bug).** Releases 2.22.0→2.29.4 bumped this CHANGELOG
but left the version-carrying artifacts behind: `config.yaml` was stuck at `2.23.0`,
`config-reference.yaml` and `LOOP.md` at `2.21.0`. Because `nightshift-sync.py` reads
the canonical version from `config.yaml`, every install was being compared against a
stale baseline. All three artifacts are reconciled to `2.29.5` here. (This is the
recurring drift the journal flagged on 2026-04-17 — "bump + sync in the same commit
as every canonical merge … needs a hook to enforce." Enforcement candidate noted.)

**Audit follow-up (no behavior change in this entry).** `AUDIT-followup-2026-06-14.md`
measured whether the 2026-05-28 audit's R1–R6 (landed v2.19.0) changed real-run
behavior. Finding: they did not — metric capture is still 1.6% (R1), 0 failure-ledgers
exist across 11 installs (R3), 0 small-model runs (R5). The fixes that depended on the
agent following an instruction failed; only the pure-code fixes (R4, R6) moved.

**SPEC-086 drafted** (`specs/SPEC-086-...`): make metrics + failure-ledger emission
mechanical by triggering it at the parent's main-side `chore: mark <id> done|blocked`
commit (a post-commit hook), instead of asking the agent to remember a terminal call.
Status `draft` — must be dogfooded (AC6) before it is marked done, explicitly because
SPEC-067 was marked done without a real-run check and the audit proved it non-working.

**Changes:**

- `config.yaml`, `config-reference.yaml`, `LOOP.md`: `kit_version` → `2.29.5`.
- `specs/SPEC-086-mechanical-metrics-emission-at-mark-commit.md`: new (draft).
- `AUDIT-followup-2026-06-14.md` (in the Nightshift project root): new.

---

## 2.29.4 (2026-06-05)

### Apply git-worktree detection in _load_registries (SPEC-085)

`_load_registries()` now skips any `projects-registry.json` found inside a git-worktree
checkout, closing the same class of gap that SPEC-072 closed for project discovery.
A shared `_is_git_worktree(path)` helper is extracted at module level and used by both
`_discover_projects()` and `_load_registries()` — eliminating duplicated inline detection logic.

SPEC-084's `logger.debug("skipped git-worktree checkout: %s", project_root)` line and
the surrounding comment block in `_discover_projects()` are preserved exactly (behavior
identical; only the predicate expression was replaced with the helper call).

**Changes:**

- `nightshift-master.py`: added `_is_git_worktree(path: Path) -> bool` helper at module
  level (after `_port_for_name`); updated `_load_registries()` to call the helper on each
  registry file's parent dir and skip if it's a worktree; updated `_discover_projects()`
  to call the helper instead of the inline `(project_root / ".git").is_file()` expression.
- `tests/test_ns_control.py`: added `TestLoadRegistries` class with five tests covering
  AC3 (shared helper) and AC4 (worktree registry skipped, real registry loaded).

---

## 2.29.3 (2026-06-05)

### Log skipped git-worktree checkouts during Control discovery (SPEC-084)

`_discover_projects()` now emits a `DEBUG` log line (`skipped git-worktree checkout: <path>`)
whenever it skips a discovered root because it's a linked git worktree (the SPEC-072
`.git is a file` guard). Normal startup output and the returned project list are unchanged.

**Changes:**

- `nightshift-master.py`: added `import logging` and a module-level
  `logger = logging.getLogger(__name__)`; added `logger.debug(...)` call immediately
  before the `continue` in the worktree-skip guard (line ~119).
- `tests/test_ns_control.py`: added `TestDiscovery.test_skipped_worktree_emits_debug_log`
  — asserts the DEBUG line appears (naming the path) for a synthetic worktree (.git FILE)
  and is absent for a normal project (.git directory); also asserts the returned project
  list is unchanged (AC2).

---

## 2.29.2 (2026-06-05)

### Gate static-irrelevant live-only board UI in export (SPEC-083)

The static snapshot export now hides three categories of UI that are meaningless
in an offline, single-file context: the Refresh button (`#btn-refresh`), worktree
status badges (`.wt-badge`), and external-project chips (`.chip[data-external="1"]`).

**Changes:**

- `board.py` (`_build_static_shim`): added a `<style>` block (SPEC-083 section)
  with three `html.static-export { display: none !important; }` rules, and added
  `document.documentElement.classList.add('static-export')` immediately after the
  `window.__STATIC__ = true` assignment. The CSS class is set by JS in the shim so
  it applies only when the shim runs (i.e. in static exports). The live board is
  completely unchanged — no modification to `HTML_TEMPLATE` or live code paths.

- `tests/test_board_export.py`: new `TestStaticUIGating` class (7 tests, AC3).
  Asserts CSS hide rules are present in the export HTML, the `static-export` class
  setter is present, and the gating CSS does NOT appear in the live `HTML_TEMPLATE`.

**No config changes required.**

---

## 2.29.1 (2026-06-05)

### Anchor-scoped display-path strip in master board (SPEC-082)

`nightshift-master.py` frontend JavaScript previously stripped only the macOS
`/Users/<name>` prefix for display, leaking full paths from Cowork VM
(`/sessions/.../mnt/...`), Linux (`/home/<name>`), and macOS temp
(`/var/folders/...`) environments.

**Changes:**

- `nightshift-master.py`: replaced the inline
  `p.path.replace(/^\/Users\/[^\/]+/, '~')` with a call to a new
  `displayPath(p)` helper that collapses four prefix patterns to `~`:
  `/Users/<n>`, `/home/<n>`, `/sessions/<id>`, and `/var/folders/<x>/<y>`.
  The helper is display-only — `p.path` (real absolute path) is still used
  verbatim in `card.dataset.path`, `path.title`, and all action API calls.
  `start`/`stop`/`open` behavior is unchanged (R2 / AC2).

- `tests/test_ns_control.py`: new `TestDisplayPathNormalization` class with 8
  tests covering AC3 (node-executed normalization for `/Users/`, `/home/`,
  `/sessions/` inputs), R3 (unrecognized path preserved), and AC2 (execution
  paths use raw `p.path`).

**No config changes required.** `nightshift-master.py` is outside `canonical/`
so no `kit_version` bump is warranted.

---

## 2.29.0 (2026-06-05)

### kit_version-gated prose path-leak severity (SPEC-081)

`validate_specs.py` now reads the project's live `kit_version` from its
`config.yaml` to decide whether a prose absolute-path leak is a **WARNING**
(transition period) or a hard **ERROR** (post-migration).

**Changes:**

- `validate_specs.py`: two new internal helpers —
  `_read_kit_version(config_path)` (yaml.safe_load, returns None on any
  failure) and `_kit_version_gte(version_str, threshold)` (tuple-split
  comparison, returns False on any parse error for safe degradation).
- `validate_file` now accepts an optional `config_path: Path | None = None`
  parameter. When omitted, it auto-resolves from `spec_file.parent.parent /
  "config.yaml"` (standard `.nightshift/specs/<SPEC>.md` layout), so
  both directory-mode and file-mode invocations (e.g. pre-commit hook) pick up
  the project config automatically.
- Prose leak finding is **ERROR** when `kit_version >= 2.24.0` (value of
  `PROSE_ERROR_KIT_VERSION`); **WARNING** otherwise — including when config is
  absent, unreadable, missing the `kit_version` key, or has a non-parseable
  value.
- Registry leaks remain **ERROR** unconditionally (unchanged from SPEC-071).

**Operator note:** Before bumping a project's `kit_version` to `2.24.0` or
above, run the SPEC-071 prose migration tool (`migrate_paths.py`) to convert
any remaining absolute host paths to `{{ANCHOR}}`-relative tokens.  Bumping
the version without migrating first will cause pre-commit spec validation to
fail for every file that still contains an absolute path.

**No config changes required.**

---

## 2.28.0 (2026-06-04)

### Pre-flight validation of per-project column override config (SPEC-080)

`validate_specs.py` now checks a project's `board_column_defaults` override
(when present in the sibling `config.yaml`) during the normal validation pass.
Malformed overrides are surfaced as `WARNING`-level findings — matching SPEC-078's
runtime severity (warn + fallback, never a hard error).

**Changes:**

- `spec_frontmatter.py`: new `VALID_COLUMN_STATES` frozenset and
  `check_column_override(override) -> list[str]` — shared pure checker for
  unknown status ids, invalid `default_state` values, and non-permutation
  `order`. Single source of truth (R4).
- `board.py`: `_apply_column_override` refactored to call `_check_column_override`
  (imported from `spec_frontmatter`) rather than duplicating the validation
  logic inline. Fallback block retains equivalent logic when `spec_frontmatter`
  is unavailable. Runtime behavior (warn to stderr + fall back to canonical) is
  identical; the SPEC-078 test suite confirms this.
- `validate_specs.py`: new `validate_config_file(config_path) -> list` function
  (mirrors `validate_registry_file` pattern). `validate_directory` calls it when
  a sibling `config.yaml` is present, emitting results under the `"config.yaml"`
  key. Absent or valid overrides produce no findings (R3).
- `tests/test_validate_specs.py`: 9 new tests under `# SPEC-080` covering AC1
  (unknown status id), AC2 (invalid default_state), AC3 (non-permutation order),
  AC4 (valid + absent override → no findings), and `validate_directory` wiring.

**Migration:** None required. `validate_config_file` is additive; projects without
`board_column_defaults` in `config.yaml` see no change in output.

**Note:** `kit_version` bump in `config.yaml` deferred — config.yaml is out of
scope for this worktree agent per task hygiene rules.

---

## 2.27.0 (2026-06-04)

### Startup note when a per-project column override is active (SPEC-079)

`_apply_column_override` now returns a one-line note summarising what
changed vs the canonical defaults when a valid override is applied.
`__main__` prints the note immediately after the primary `▸ NIGHTSHIFT
BOARD — …` line.

**Changes:**

- `board.py`: `_apply_column_override` return type changed from `None` to
  `str | None`.  Returns a `▸ Column override loaded: …` string listing
  only the state-changed columns (in canonical order) and/or "order
  customized", or `None` when no override is active, the section is absent,
  or the override is invalid.  Identity overrides (present but identical to
  canonical) also return `None`.
- `board.py` `__main__`: captures the return value of `_apply_column_override`
  and prints `  <note>` when non-None.
- `tests/test_board_api.py`: eight new tests under "SPEC-079" covering AC1–AC4
  (note present for valid override, absent without one, names only changed
  columns, column order determinism, no-delta edge case, invalid-override guard).

**Migration:** None required.  Callers that discarded the return value of
`_apply_column_override` continue to work unchanged.

---

## 2.26.0 (2026-06-04)

### Board toolbar "Reset column layout" button (SPEC-077)

Adds a one-click "↺ RESET COLS" button to the board header toolbar that restores
the canonical default column layout (collapsed: active, planning, blocked;
hidden: superseded, retired; order: canonical) by calling the existing
`_seedColumnsFromDefaults()` helper and persisting the result via `saveSettings()`.

**Changes:**

- `board.py` HTML: added `<button id="btn-reset-cols" onclick="resetColumnLayout()">↺ RESET COLS</button>` to the header toolbar, between ⇔ FIT and ⊞ COLS.
- `board.py` JS: added `resetColumnLayout()` — calls `_seedColumnsFromDefaults()`, `renderBoard()`, `saveSettings()`. Column-level state only; `cardOrder`, `columnWidths`, graph settings, and all other preferences are untouched.
- `tests/test_board_browser.py`: four new tests covering button presence (AC1), canonical state after click (AC2), preservation of non-column prefs (AC3/AC4), and post-reload persistence (R3).

**Migration:** None required. `resetColumnLayout` is purely additive.

---

## 2.25.0 (2026-06-04)

### Board startup stdout/stderr captured to per-project log file (SPEC-076)

`nightshift-master.py` `start_project()` previously discarded each board's
stdout/stderr via `subprocess.DEVNULL`. Board crashes on startup (such as the
malformed-spec traceback in SPEC-073) left no trace — the only signal was "Board
did not start within 10s" with no cause.

**Changes:**

- `start_project()` opens `board.restart.log` (append-truncated on each start,
  write mode) in the same directory as `board.py`, and passes the file handle
  as both `stdout` and `stderr` to `subprocess.Popen`. The parent closes its
  handle after `Popen` returns; the child keeps writing — the call remains
  non-blocking (AC3).
- Log path resolves relative to `board.py`'s parent directory, covering both
  layouts transparently:
  - Standard `.nightshift/` layout → `<project>/.nightshift/board.restart.log`
  - Flat canonical-kit layout (SPEC-075) → `<project>/board.restart.log`
- The API response now includes `"log": "<absolute path>"` so the caller always
  knows where to look. The Control UI's start-timeout alert (`onStart` JS)
  appends the log path to the message: `"Board did not start within 10s\nLog: <path>"`.
- Tests (+3, `tests/test_ns_control.py`): Popen receives a real file handle (not
  DEVNULL) for stdout and stderr; log path resolves correctly for the standard
  layout; log path resolves correctly for the flat canonical-kit layout.

**Migration:** None — additive change. `board.restart.log` appears next to
`board.py` for each project on next board start. No config changes required.

---

## 2.24.0 (2026-06-04)

### Static board snapshot exporter (SPEC-070)

`board.py` and `nightshift-master.py` now support exporting a self-contained,
offline-capable HTML snapshot of any project's Nightshift board.

**Usage — single project:**

```bash
python .nightshift/board.py --specs .nightshift/specs --export my-board.html
```

**Usage — batch export via master:**

```bash
python nightshift-master.py export-snapshot --projects API,CORE --out ./snapshots/
```

The exported file is a single `.html` file that works without a running server or
network connection. All API routes are intercepted by an inline `fetch()` shim
that resolves from a `window.STATIC` blob embedded in the page. `marked.js` and
`vis-network.js` are downloaded at export time and inlined. Google Fonts and
SortableJS CDN references are removed. `window.Sortable` is stubbed as a no-op
constructor. Worktree `path` values are tokenized via `path_vars.tokenize()`.
AC7 fail-closed gate: any residual absolute path outside a code fence/span
raises `ExportLeakError` and blocks the write.

**New public API in `board.py`:**
- `export_board_html(specs_dir, project, *, lib_fetcher, reports_dir, worktree_status) -> str`
- `ExportLeakError`

**New subcommand in `nightshift-master.py`:**
- `export-snapshot --projects NAME[,NAME,...] [--out DIR]`

---

## 2.23.0 (2026-06-04)

### Per-project column default-state override (SPEC-078)

Projects can now override the canonical SPEC-074 board column defaults (per-column
`default_state` and/or column order) for their board only, without modifying `board.py`.

**How to use:** add an optional `board_column_defaults:` section to the project's
`.nightshift/config.yaml`:

```yaml
board_column_defaults:
  default_state:
    blocked: expanded   # change only the columns you want
  order:                # optional full-permutation reorder
    - in_progress
    - ready
    - draft
    - blocked
    - active
    - planning
    - done
    - superseded
    - retired
```

**Changes:**
- `board.py` gains `_build_status_columns()` (extracted builder, no behavior change),
  `_VALID_DEFAULT_STATES` constant, and `_apply_column_override(config_path)` function.
- `_apply_column_override` is called from `__main__` after `specs_dir` is resolved;
  it reads `config.yaml` (from `specs_dir.parent/`), merges any valid
  `board_column_defaults` override over the canonical defaults, and reassigns the
  `STATUS_COLUMNS` and `status_columns_json` module globals.
- Absent section / missing file / invalid override → canonical defaults unchanged
  (SPEC-074 behavior, `global` reassignment never executed). Invalid overrides emit a
  `WARNING` to stderr and fall through without breaking board startup.
- The `STATUS_COLUMNS_ORDER` drift guard is unaffected: order overrides are validated
  as full permutations of all 9 statuses before being applied.
- `config.yaml` is already excluded from `nightshift-sync.py` (line 51 comment) so
  the override survives canonical syncs.
- `config-reference.yaml` updated with `board_column_defaults` section.
- **Tests:** +10 `canonical/tests/test_board_api.py` covering AC1–AC5. Total: 113 passed.

**Migration:** none — additive config section, no behavior change for projects without
the override. `nightshift-sync.py canonical` propagates the updated `board.py`.

---

## 2.22.0 (2026-06-04)

### Board default column layout (SPEC-074)

Fresh boards now open with an opinionated column layout instead of nine expanded,
equally-weighted columns. The new default (left → right):

| Column | Default state |
|--------|---------------|
| ACTIVE | collapsed |
| PLANNING | collapsed |
| DRAFT | expanded |
| BLOCKED | collapsed |
| READY | expanded |
| IN_PROGRESS | expanded |
| DONE | expanded |
| SUPERSEDED | hidden |
| RETIRED | hidden |

**Changes:**
- `STATUS_COLUMNS_ORDER` reordered to `active, planning, draft, blocked, ready, in_progress, done, superseded, retired`.
- Each `STATUS_COLUMNS` entry now carries `default_state: "expanded"|"collapsed"|"hidden"` — serialized into the `COLUMNS` payload via `__STATUS_COLUMNS_JSON__` / `/api/statuses`.
- Client JS seeds `collapsedColumns` and `hiddenColumns` from `col.default_state` on fresh state (no saved version) or version mismatch.
- `COL_STATE_VERSION = 1` in localStorage. Existing boards pick up the new defaults once (one-time adoption); subsequent loads restore user customization normally. `cardOrder` and all other preferences are not affected by the version bump.
- Drift guard unchanged — `STATUS_COLUMNS_ORDER` set still equals all nine canonical statuses.

**Migration note:** On first load after this update, each project's board will re-seed
`collapsedColumns` / `hiddenColumns` from the new defaults. Any explicit collapse/expand/hide
choices the user made previously will need to be re-applied once. `cardOrder`,
`columnOrder`, `columnWidths`, and all other settings are preserved.

---

## 2.21.0 (2026-06-01)

### Board graph view — grouping-node shape + dashed parent edges (SPEC-070)

The graph view previously drew only `after:` dependency edges and gave every spec
an identical dot, so there was no way to tell a runnable spec from a `type: main`
grouping/umbrella spec — leading to a failed attempt to "run" a grouping spec
(which `ORCHESTRATOR.md` §2.1b and `nightshift-dag.py` treat as non-executable).

- **Grouping-node shape.** Nodes whose `type ∈ {main, nfr}` (the nightshift-dag
  executable predicate) render as a **diamond**; runnable specs keep the **dot**.
- **Dashed parent edges.** Faint, no-arrowhead **dashed** edges show `parent:`
  grouping membership, visually distinct from solid `after:` arrows. Drawn only
  when both endpoints are visible and the parent resolves to a real node.
- **GROUPING legend toggle.** Mirrors the status-hide legend; default on; hides
  the dashed edges on high-fan-out parents (persisted in settings).
- **API (additive).** `/api/graph` nodes now carry `type`; the response gains a
  separate `parent_edges` list (resolvable parents only). Existing `edges`
  (after-deps) and node placement (`X = status`) are unchanged.
- **Tests.** +5 `canonical/tests/test_board_api.py` (node `type`, `parent_edges`
  for resolvable + dangling parents, after-edge isolation). JS syntax green.

**Migration:** none — additive API + client-only render change. `nightshift-sync.py canonical`
propagates the updated `board.py` to installs.

## 2.20.1 (2026-05-31)

### Bugfix — board column fit overflow

`fitColumns()` now subtracts board-view padding and inter-column gaps before
dividing width, so columns fill the viewport without overflowing past the right
edge. *(Catch-up entry — shipped in commit `fceae332`; config.yaml was bumped at
the time but this CHANGELOG entry was missed.)*

## 2.20.0 (2026-05-30)

### Board UX — auto-fit columns + panel below header

⇔ FIT button distributes visible expanded columns to fill board width; the detail
panel starts below the header toolbar (`var(--header-h)`) instead of covering it;
`syncHeaderHeight()` keeps the offset live on init + resize. 4 new unit tests.
*(Catch-up entry — shipped in commits `33b710d3` / `54095cd6`; CHANGELOG entry was
missed at the time.)*

## 2.19.2 (2026-05-29)

### Test-only — correct stale `check_followup_spec` unknown-domain test

`test_proposed_id_fallback_for_unknown_domain` asserted that an unrecognized
domain maps to `FART-MISC-`. That was pre-2.17.0 behavior. Since 2.17.0,
`_proposed_id`'s documented priority is: `--parent-id` → domain in
`_DOMAIN_PREFIX_MAP` → **infer the project's dominant prefix** (generic `SPEC-`
when nothing exists to infer). Only the explicit `misc` domain maps to
`FART-MISC-`. The hardcoded-FART expectation also contradicts the kit's
language-agnostic principle.

Replaced the single stale assertion with three accurate cases: unknown domain
**infers** the existing prefix (`FART-DS-`), unknown domain in an empty project
falls back to `SPEC-`, and explicit `misc` maps to `FART-MISC-`. **Full canonical
suite is now green (904 passed, 0 failed).**

**Migration:** None — test-only, no protocol/runtime/synced-file change.

---

## 2.19.1 (2026-05-29)

### Bugfix — board `/api/projects-registry` crash under import-based launch (SPEC-069)

`board.py`'s `projects_registry()` resolved its file via `specs_dir`, a name bound
only inside the `if __name__ == "__main__":` block. Under the documented
`python board.py` launch that name is a module global and the endpoint works; under
**import-based launch** (`uvicorn board:app`, the test harness, any embedding host)
it is undefined → `NameError` → HTTP 500. Because a board page load calls the
endpoint on startup, the run-prompt browser test could not reach its assertions.

- **Fix:** resolve the registry path via `cache._specs_dir.parent` — the same
  injected-cache source the worktree endpoint already uses. One line; no other
  endpoint was affected (`project_name`, `reports_dir`, `reads_file` all carry
  module-level defaults; only `specs_dir` lacked one).
- **Tests:** +26 in `tests/test_board_api.py` covering the previously-untested
  registry endpoint (incl. the regression: 200 under import launch, populated, and
  malformed-JSON paths), the external-spec proxy (port range, spec_id validation,
  unreachable shape), reports listing/reading (incl. a direct `_resolve_report_path`
  traversal-guard test), and report read-tracking persistence.
- **Stale test fix:** `test_run_prompt_button_copies_skill_based_prompt` asserted
  run-prompt text removed by the 2.18.1 thin-pointer slimming; updated to the
  current phrasing (`before marking the spec blocked`, `Suggested Follow-up Specs`).
  Board test failures went 2 → 0.

**Migration:** None — patch, no config/protocol/metrics change. Projects pick up the
fixed `board.py` via `nightshift-sync.py canonical`.

**Still pre-existing (unrelated, untouched):**
`test_check_followup_spec.py::test_proposed_id_fallback_for_unknown_domain`.

---

## 2.19.0 (2026-05-29)

### Single-call metrics + duplicate-spec scan (SPEC-067, SPEC-068)

Acts on the 2026-05-28 canonical audit, which found that per-spec metric capture had
collapsed in practice (the busiest project, Cortex/api, logged 102 reports but 2
metric files) because Step 13 asked the *model* to hand-author a ~60-field YAML —
the first thing a loaded or less-capable model drops. The fix moves authoring from
the model to deterministic code, shrinking the loop rather than adding to it.

**`record_metrics.py`** (new) — emits one schema-valid per-spec metrics YAML from a
single call. The model supplies only what it knows (status, outcome, test counts,
review cycles, failure info); everything else is **derived** (files/lines/commit from
git; harness/loop_version/review_mode from `config.yaml`) or **computed**
(satisfaction block). Key points:
- Additive **`outcome`** field — controlled vocabulary `done | partial | blocked | noop`
  — alongside the unchanged `status` enum, so reports/metrics become minable without
  breaking any consumer. `noop` (with `status: completed`) marks runs that needed no
  code change, so duplicate/no-op runs stop masquerading as feature work.
- **`--model`** override beats the template's blank `runtime.model`, so the model
  field — the basis for cross-model comparison — is never empty.
- Non-`completed` runs require `--error-type`/`--error-desc` and append a one-line
  `failure-ledger.json` entry, so the failure path is recorded, not invisible.
- Emitted files pass `validate_metrics.py` unchanged (verified by tests).
- Multi-document `config.yaml` is parsed via `safe_load_all` + merge.

**`LOOP.md`** — Step 13 hand-authoring block and the dead "Post-Run Metrics Emission"
triple-JSON section (which produced 0 files in practice) are removed and replaced by
the `record_metrics.py` call. **LOOP.md: 2281 → 2090 lines (−191).** Step 14 report
template gains a controlled `**Outcome:**` line.

**`check_followup_spec.py`** — new **`--scan-all`** mode compares every spec pair
across the whole specs dir by title AND requirement/AC body similarity, catching
duplicates regardless of how they were created. Root cause from the audit: the
per-suggestion gate only runs in the kickoff flow, so hand-authored/bulk-promoted
duplicates (e.g. SPEC-CTX-API-055, a verbatim copy of SPEC-048) bypass it entirely.

**Tests** — `tests/test_record_metrics.py` (12) and 6 added to
`tests/test_check_followup_spec.py`; all green.

**Incidental:** fixed `config-reference.yaml` `kit_version` drift (was stuck at
2.17.0 → 2.19.0); bumped `loop_version` to 2026-05-29.

**Migration:** None required — schema is backward-compatible (additive `outcome`
field; `status` enum unchanged). Projects pick up `record_metrics.py`,
`check_followup_spec.py`, and the slimmer `LOOP.md` via `nightshift-sync.py canonical`.
The next LOOP run per project emits metrics via the script instead of by hand.

**Known pre-existing failures (not introduced here):**
`test_check_followup_spec.py::test_proposed_id_fallback_for_unknown_domain` and
`test_board_browser.py::test_run_prompt_button_copies_skill_based_prompt` fail on the
parent commit too; left for a separate fix to keep this change surgical.

---

## 2.18.1 (2026-05-28)

### Relocate follow-up spec policy into the kickoff skill

The post-report **Suggested Follow-up Specs** handling policy (the
`check_followup_spec.py` conflict-check loop) previously lived inline in
`board.py`'s `buildRunPrompt()`, duplicating behavior that belongs to the
`/nightshift kickoff` flow. It now lives solely in the kickoff skill.

**`board.py`:**
- `buildRunPrompt()` is now a thin pointer — it tells the kickoff agent to follow
  the `/nightshift kickoff` skill and not implement the spec itself, instead of
  embedding the full unblock + follow-up policy inline. The board run prompt and
  the skill can no longer drift.

**Kickoff skill (`SKILL.md`, not part of kit sync):**
- New "Step 7: Process suggested follow-up specs" carries the full policy
  (clean/conflict/NFR/missing-script branches).

**Migration:** None. No config schema, protocol step, or metrics change. Projects
pick up the slimmer `board.py` via `nightshift-sync.py canonical`.

---

## 2.18.0 (2026-05-28)

### NFR alignment gate + impact audit (SPEC-065, SPEC-066)

Two new mechanisms ensuring specs are reviewed against active NFRs before
execution, and that existing specs are surfaced when a new NFR is added.

**`validate_specs.py`:**
- Error on `status: ready` + `type: feature/bugfix/refactor` specs missing
  the `nfrs:` field. `nfrs: []` is valid — it means "reviewed, none apply."
- Warning (non-fatal) on `status: draft` + same types missing `nfrs:`.
- `status: done`, `in_progress`, and `blocked` specs are exempt (backward
  compatibility).
- New: `scope_tags:` on NFR-family specs must be a list of strings when present.

**`check_followup_spec.py`:**
- `nfr_texts` now returns ALL active NFRs unconditionally. Previous keyword
  filtering (domain/artifact match in NFR body) silently excluded NFRs that
  didn't happen to contain the domain string. Retired NFRs are excluded.

**`audit_nfr.py`** (new script):
- Scope-filtered impact report for non-done specs when a new NFR is added.
- Match strategy: spec's `domain:` / `layer-N` / `touches:` token intersection
  with NFR's `scope_tags`. No `scope_tags` = conservative, all non-done specs.
- Retired NFRs produce a message and exit 0 (no report).
- `--format text` (default) or `--format json`. Always exits 0 — report tool,
  not a pass/fail gate.

**`specs/_TEMPLATE-NFR.md`:**
- New `scope_tags: []` field on both top-level and sub-NFR frontmatter.
- Vocabulary: domain names (`ui`, `be`, `ds`), layer indicators (`layer-0`…
  `layer-3`), tech keywords (`swiftui`, `auth`, `database`).

**`SPEC-GUIDE.md`:**
- Phase 0: new step 3 — read all active NFRs before the spec interview begins.
- Phase 9 checklist: `nfrs:` item added (populate before saving).
- New "Creating an NFR Spec" section with `audit_nfr.py` post-save workflow.

**`SKILL.md`** (nightshift skill):
- Step 1: NFR scan added to context check.
- Step 4: `nfrs:` validation item added.
- Step 6 (new): post-save `audit_nfr.py` run for `type: nfr` specs.

**Migration:** No breaking changes. Existing `done`/`in_progress`/`blocked`
specs are exempt from the `nfrs:` requirement. Projects with `ready` specs
that lack `nfrs:` will now see validation errors — add `nfrs: []` to clear
them (or list applicable NFR IDs).

---

## 2.17.0 (2026-05-26)

### Follow-up spec ID collision prevention

Fixed a class of spec ID collision where follow-up specs from multiple parent
specs share a global sequential counter and land on the same ID (e.g., two
parents both generate a third child and both claim `-044`).

**`check_followup_spec.py`:**
- Added `--parent-id PARENT` argument. When provided, the proposed ID uses
  `PARENT-NNN` format scoped to that parent, making cross-stream collisions
  structurally impossible.
- Added existence check: the returned `proposed_id` is now guaranteed unique
  against all existing spec IDs in the directory — even without `--parent-id`.
- Fixed project-prefix inference: when the domain doesn't match the built-in
  `_DOMAIN_PREFIX_MAP` (Fartownik-specific), the script now infers the dominant
  ID prefix from existing specs instead of falling back to `FART-MISC-`. This
  makes the script useful in non-Fartownik projects without configuration.

**`LOOP.md`** — report template `## Suggested Follow-up Specs` block gains a
`parent:` field. Set it to the originating spec's parent ID so the kickoff
agent can pass `--parent-id` to `check_followup_spec.py`.

**`SPEC-GUIDE.md`** — new `## ID Assignment Rules` section documents the
mandatory use of `check_followup_spec.py` for all ID generation, the collision
risk of manual increment, and when to use `--parent-id`.

**Migration:** No changes to existing specs or config.yaml. The `--parent-id`
argument is additive and backward-compatible. Projects should update their local
`check_followup_spec.py` via `nightshift-sync.py canonical`.

---

## 2.16.0 (2026-05-23)

### Board responsiveness — diff render, tab-activate sync, dep-aware panel refresh (SPEC-063)

The SPEC-050 board now updates incrementally:

- **Card-level diff render.** When the 10s poll detects only an mtime change
  on existing specs (no column moves, no adds/removes), only the changed
  cards' DOM is swapped via `renderCard(spec, blocksMap).replaceWith()`. Full
  `renderBoard()` still fires for column-move / topology changes (preserves
  SortableJS state and column ordering) and for the REFRESH button.
- **Graph node-level diff.** `updateGraphFromSpecs(fresh)` uses
  `graphNodesDataset.update([{id, color}])` to recolor changed nodes without
  destroying the network or re-running layout. Topology changes still hit
  `showGraph()` on next tab activate.
- **Tab-activate sync.** `showBoard()` (made async) and `showGraph()` now
  fetch `/api/specs` on activate so the newly-visible tab reflects current
  disk state, not the cached `specs[]` from the last poll. Eliminates the
  "manual refresh after switching tabs" workaround.
- **Dependency-aware panel refresh.** When the panel is open and a spec
  referenced by it (`after:`, `requires:`, `parent:`, `violates:`, `nfrs:`,
  `children:`, or reverse `blocks`) changes status, `refreshPanelDependencies()`
  re-renders just the chips section — no full panel rebuild, no scroll-jump.

### Cross-project dependency navigation (SPEC-064)

The board now resolves dependencies that live in other projects:

- **`projects-registry.json` in every `.nightshift/`.** Generated by
  `nightshift-sync.py canonical` at the end of the sync pass. Lists each
  project's name, absolute path, hash-derived board port, and most common
  spec-ID prefixes (≥3 occurrences, sorted by count then length).
- **`/api/projects-registry`** — board exposes the file as JSON for the UI.
- **`/api/external-spec/{port}/{spec_id}`** — server-side proxy to a peer
  board's `/api/spec/{id}`. Port whitelisted to 7800-7999 (SSRF protection),
  500ms timeout, returns `{_unreachable: true}` gracefully when the target
  board isn't running. CORS-free by design — no `CORSMiddleware` needed.
- **External chip rendering.** Dependency chips for specs that resolve to
  other projects render as anchors with `↗` icon, dashed border, and
  `target="_blank"`. Status pill fills in asynchronously via the proxy.
- **`?spec=<id>` URL handler.** Auto-opens the panel for the requested
  spec after load. Powers cross-board navigation (the external link from
  project A's board lands on project B's board at the right spec).
- **Longest-prefix-match resolver.** `SPEC-CTX-API-007` correctly resolves
  to `api` (prefix `SPEC-CTX-API`), not `core` (prefix `SPEC-CTX`).
- **"Spike" reminder.** VOCABULARY.md gained a Cross-Project Dependencies
  section linking the registry mechanism to the spec-type vocabulary.

### Compatibility

Fully backward-compatible:
- No frontmatter schema changes.
- Boards without a `projects-registry.json` (older projects, never re-synced)
  degrade gracefully — `/api/projects-registry` returns
  `{generated_at: null, projects: []}` and external dep resolution returns
  null, falling through to the existing internal-chip path.
- REFRESH button still triggers the full `renderBoard()` / `showGraph()`
  path; the diff render is additive.

### Migration

Run canonical sync once to write `projects-registry.json` into every project:

```bash
python3 ManagedProjects/Nightshift/nightshift-sync.py canonical
```

The new file appears alongside the propagated protocol files in each
`.nightshift/`. Restart any running `nightshift-board` processes so they
pick up the new endpoints.

### Out of scope (deferred)

- WebSocket/SSE push for sub-second freshness — 10s poll + diff render is
  sufficient at current scale.
- Multi-host federation (boards on different machines).
- Auto-starting the target project's board when clicking an external link.
- Reverse navigation ("who references me across projects").

---

## 2.15.1 (2026-05-23)

### Spec-type vocabulary for sub-agent discoverability (SPEC-062)

Added `canonical/VOCABULARY.md` — a concise (114-line) reference card summarizing
how sub-agents should treat each spec type. Focuses on the cases agents most often
mishandle: NFR lifecycle (`active | retired` only, never `blocked`/`done`),
research/analysis "done" criteria (`output_artifact` presence, not build/test
gates), and the "spike maps to research" clarification.

The full per-type rules still live in `_TEMPLATE-NFR.md`, `_TEMPLATE-RESEARCH.md`,
and `_TEMPLATE-ANALYSIS.md`. VOCABULARY.md is the entry-point summary so a
sub-agent handed a brief with `nfrs: [NFR-NNN]` injections doesn't have to
read four templates to learn the lifecycle rules.

**New file: `canonical/VOCABULARY.md`**
- Summary table (lifecycle / loop pickup / blockable / "done" per type)
- NFR contract (lifecycle, loop exclusion, blocker semantics, cross-refs, hierarchy, common sub-agent mistakes)
- Research/Analysis contract (lifecycle, output_artifact requirement, what "done" means, what NOT to do)
- Spike note (Agile-sense spike = `research` or `analysis`; no new type)
- Cross-reference quick card (`nfrs:`, `violates:`, `parent:`, `children:`, `domain:`, `output_artifact:`)

**Propagation:** added to `nightshift-sync.py → CANONICAL_PROTOCOL_FILES`. Synced
to every project's `.nightshift/VOCABULARY.md` on next `nightshift-sync.py canonical`.

**ORCHESTRATOR.md integration:** when a sub-agent brief includes injected NFR
constraints (§3.x), it now also receives a required-read line pointing to
`.nightshift/VOCABULARY.md`. Same for briefs whose spec resolves to
`domain: research` or `domain: analysis`.

**SPEC-GUIDE.md integration:** Phase 2 (Scope & Type) now cross-links to
VOCABULARY.md so spec authors discover the non-code lifecycle rules during
spec creation.

### Drift cleanup (incidental)

This release also bumps `kit_version` in `canonical/LOOP.md` and
`canonical/config-reference.yaml` to match `canonical/config.yaml` (previously
they were stuck at 2.14.3 while config.yaml was already 2.15.0). The drift was
pre-existing — `python3 scripts/check_nightshift_drift.py` is now green again.

### Out of scope (deferred)

- No new `type:` enum values. "Spike" is documented as a synonym for
  `research`/`analysis`, not a new type. Adding new types would require
  changes across `spec_frontmatter.py`, `validate_specs.py`, runners, and the
  board — explicitly deferred.
- No changes to NFR enforcement code (SPEC-058 already enforces lifecycle at the
  validator/board layer).

### Compatibility

Fully backward-compatible. No frontmatter schema changes, no protocol semantics
changes. New file is doc-only; existing projects keep working without re-sync
(but should re-sync at next opportunity to receive the new vocabulary file).

### Migration

```bash
cd <project>/.nightshift
python3 ../ManagedProjects/Nightshift/nightshift-sync.py canonical --dry-run
python3 ../ManagedProjects/Nightshift/nightshift-sync.py canonical
```

Or run `python3 nightshift-sync.py canonical` from the Nightshift root to
propagate to all projects at once.

---

## 2.15.0 (2026-05-21)

### Follow-up spec autocreation with conflict check (SPEC-060)

When the kickoff agent finishes or unblocks a spec, it now checks for a
`## Suggested Follow-up Specs` section in the run report and auto-creates
follow-up specs — no manual step required.

**New file: `canonical/check_followup_spec.py`**
Mechanical conflict check script. Given a suggestion title + optional artifact,
domain, and layer, it runs four checks:
- Title Jaccard similarity against all existing spec titles (threshold 0.4)
- `output_artifact` exact clash with any ready/in_progress spec
- Domain+layer cluster membership (informational)
- NFR file extraction — returns full NFR text for semantic judgment by the agent

Exit 0 = clean (with `proposed_id`). Exit 1 = conflict (with `conflicts` list).
NFR texts are always returned in both cases so the agent can judge semantically.

**`buildRunPrompt` updated** — the copied prompt now includes a follow-up spec
creation policy block: for each suggestion entry, run the script, auto-create if
clean, record conflict reason if not. NFR violations are judged semantically by
the kickoff agent after reading the surfaced NFR texts.

**`LOOP.md` Step 14 updated** — the run report template now includes a
`## Suggested Follow-up Specs` structured section (one YAML-like entry per
suggestion). Orchestrator fills it during report generation.

**`nightshift-sync.py` updated** — `check_followup_spec.py` added to
`CANONICAL_FILES` so it deploys to all `.nightshift/` projects on sync.

**Migration:** run `nightshift-sync.py canonical` to deploy. No config changes.
After deployment, `.nightshift/check_followup_spec.py` exists in each synced
project and the board's run prompt includes the creation policy.

---

## 2.14.3 (2026-05-20)

### Kickoff unblock before block

The board-copied `COPY RUN PROMPT` now tells the parent kickoff agent to try one
focused unblock pass before marking a spec blocked. If the orchestrator reports
blocked/stuck or the evidence gate fails, the parent gathers the exact blocker,
redirects or relaunches the run/implementation agent with a narrow unblock task,
and reruns the evidence gate.

The spec is marked blocked only when the unblock pass fails, cannot run without
human/external input, or continuing would be unsafe. Final Block Reasons and
escalations must include what unblock attempt was made, or why it was skipped.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board
prompt and protocol docs.

## 2.14.2 (2026-05-20)

### Enforce NFR active lifecycle

NFR-family specs are now guarded by both validation and runtime tooling. Any
spec whose `id` starts with `NFR-`, or whose `type` is `nfr`, may use only
`status: active` or `status: retired`.

`validate_specs.py` rejects blocked/ready/done NFR-family specs with an explicit
NFR lifecycle error. `failure_persistence.mark_spec_blocked()` no longer writes
`status: blocked` to NFR-family specs; it records pending/failure state in the
body under `## Active Run State` instead. The board API rejects invalid
NFR-family status edits, and the detail-panel status dropdown limits NFR-family
specs to `active` and `retired`.

**Migration:** run `nightshift-sync.py canonical` to deploy the validator,
failure-persistence helper, board update, templates, and protocol docs. Existing
NFR-family specs with invalid statuses should be changed to `status: active`
unless intentionally retired.

## 2.14.1 (2026-05-17)

### Canonical sync ships validator helper modules

`nightshift-sync.py canonical` now deploys the first-party Python helper
modules imported by synced validators and DAG tooling. This prevents deployed
project copies from receiving `nightshift-dag.py` or `validate_metrics.py`
without local dependencies such as `model_stylesheet.py`,
`parallel_executor.py`, `dispatch.py`, and `metrics_fidelity.py`.

The canonical drift checker now parses synced Python files and fails if a
first-party import is missing from `CANONICAL_PROTOCOL_FILES`, so future helper
imports cannot silently break deployed `.nightshift/` folders.

**Migration:** run `nightshift-sync.py canonical` to deploy the helper modules
into project `.nightshift/` folders.

---

## 2.14.0 (2026-05-12)

### Autonomous kickoff resolution

The parent kickoff agent no longer offers merge/discard choices to the user.
Instead it resolves the run autonomously after the orchestrator completes:

- **Evidence gate (all four must pass to merge):** report exists, tests passed,
  code changed outside `reports/`, AC checklist has no `❌`.
- **Pass:** merge worktree branch, clean up, mark spec `done`, report to user.
- **Fail:** mark spec `blocked` via `failure_persistence.mark_spec_blocked`,
  write a Cortex breadcrumb, leave the worktree for inspection, send an
  escalation message explaining which check(s) failed and what's missing.

The board-copied "COPY RUN PROMPT" text was updated to reflect this contract.
The user is only involved when evidence is genuinely insufficient and the spec
is blocked.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated
`board.py` to project `.nightshift/` folders. The SKILL.md (`kickoff` and
`run` commands, Step 6) is updated in the global skills directory and does not
need a per-project deploy.

---

## 2.13.1 (2026-05-05)

### Blocked spec title preservation

Spec validation now rejects specs whose first body H1 is `# Block Reason`,
because the board derives card titles from the first H1 and would display the
blocker label instead of the real spec title.

Blocked specs must keep the real spec title as the first body H1 and use
`## Block Reason` as the first content section after that title. The canonical
template, loop/orchestrator guidance, and failure persistence helper now emit
that shape.

**Migration:** run `nightshift-sync.py canonical` to deploy the validator,
template, protocol docs, and helper update into project `.nightshift/` folders.
Existing blocked specs should be adjusted to keep a real title H1 first.

---

## 2.13.0 (2026-05-05)

### Board spec-link status previews

Spec links in the board detail panel now show linked-spec status without
requiring navigation. The `after:` and `blocks:` chips include compact status
labels and status-colored borders, with blocked and done specs emphasized.

Rendered `spec://SPEC-ID` links inside spec markdown get the same status
decoration. Hovering either a dependency chip or a decorated markdown link shows
the linked spec preview with ID, title, status, and problem/context snippet when
available.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board,
docs, and config metadata into project `.nightshift/` folders.

---

## 2.12.1 (2026-05-03)

### Explicit kickoff command contract

Replaces the board prompt's implicit `/nightshift run <SPEC-ID>` parent-mode
instruction with an explicit `/nightshift kickoff <SPEC-ID>` command.

The Nightshift skill now treats `/nightshift kickoff` as a parent kickoff wrapper
around `/nightshift run` with `kickoff_parent: true`. In that mode, the generated
run/orchestrator brief must include a `## Kickoff Parent Context` section, so the
launched agent knows it is being monitored and must write live progress to
`reports/_wip/orchestrator-progress-<SPEC-ID>.md`.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board and
orchestrator protocol. Update installed Nightshift skills separately where
applicable.

---

## 2.12.0 (2026-05-03)

### Board kickoff prompt and orchestrator progress contract

Adds a board action for copying a skill-based Nightshift run prompt from the
spec detail panel. The prompt delegates to `/nightshift run <SPEC-ID>` and
frames the receiving agent as a parent kickoff monitor rather than the
implementer.

The Nightshift skill now documents parent kickoff agent mode for `/nightshift
run`, including the split between the kickoff agent and the run/orchestrator
agent. `ORCHESTRATOR.md` adds a kickoff-parent progress contract: orchestrators
choose a cadence and keep live progress inspectable in
`reports/_wip/orchestrator-progress-<SPEC-ID>.md`.

The board copy-spec-ID icon is also restyled for clearer contrast in light and
dark mode.

**Migration:** run `nightshift-sync.py canonical` to deploy the updated board,
orchestrator protocol, and config metadata into project `.nightshift/` folders.
Update installed Nightshift skills separately where applicable.

---

## 2.11.1 (2026-05-02)

### Git policy source of truth

Adds `GIT.md` as the canonical Nightshift git workflow policy. It now owns the
semantics for dirty-tree handling, spec status commits, commit format, hooks,
worktrees, merge/post-merge validation, and human-review expectations.

`LOOP.md`, `ORCHESTRATOR.md`, `BOOTSTRAP.md`, `HUMAN-REVIEW.md`, config comments,
and hooks now reference `GIT.md` instead of independently owning those rules.
The drift checker now verifies that the policy document is present, synced, and
referenced by the key protocol surfaces.

**Migration:** run `nightshift-sync.py canonical` to deploy `GIT.md` and
the updated references into project `.nightshift/` folders. No config field
changes are required.

---

## 2.11.0 (2026-05-01)

### OpenSpec-transfer workflow controls

Adds five canonical workflow/audit primitives derived from the OpenSpec analysis:

- `nightshift-instructions.py` emits agent-readable instruction packets with state, blockers, context files, validation commands, progress, and recommended next action.
- `verification_report.py` defines durable `verification.json` + `verification.md` artifacts with completeness/correctness/coherence dimensions and CRITICAL/WARNING/SUGGESTION severity gates.
- `source_fingerprints.py` records base SHA-256 fingerprints and blocks stale source-of-truth writes unless a human override reason is recorded.
- `nightshift-dag.py graph|next` now surfaces optional stacking metadata (`provides`, `requires`, `touches`, `parent`) and ready-spec guidance.
- `replay.py` writes and inspects failed-run replay bundles with command evidence, context hashes, diff summary, inventories, and blocker explanation.

Protocol docs now require instruction packets during context loading and verification reports before `status: done`. `nightshift-sync.py` deploys the new canonical helpers.

**Migration:** run `nightshift-sync.py canonical --apply` to copy the new helper scripts into deployed `.nightshift/` folders. Existing specs remain valid; stacking fields are optional.

---

## 2.10.3 (2026-04-26)

### New tool: `validate_specs.py` — static spec frontmatter validator

Adds a static validator that checks every spec `.md` file in a `specs/` directory
for well-formed frontmatter and a canonical lifecycle status value.

**What it validates:**
- Opening and closing `---` frontmatter delimiters present
- YAML inside the block is valid
- Required fields `id` and `status` are present
- `status` is one of: `planning`, `draft`, `ready`, `in_progress`, `blocked`, `done`, `superseded`, `active`, `retired`

**Source of truth:** `VALID_SPEC_STATUSES` constant added to `spec_frontmatter.py`.
Both `validate_specs.py` and (going forward) `board.py` should import from there
rather than maintaining a duplicate list.

**Pre-commit hook:** `hooks/pre-commit` now detects staged `specs/*.md` files and
runs `validate_specs.py` against them. A commit that stages a spec with an invalid
`status` is rejected before it lands.

**CLI usage:**
```
python3 .nightshift/validate_specs.py .nightshift/specs/            # full scan
python3 .nightshift/validate_specs.py .nightshift/specs/SPEC-001.md  # single file
python3 .nightshift/validate_specs.py .nightshift/specs/ --format json
```

**Tests:** `tests/test_validate_specs.py` — 24 tests covering all validation paths.

**Migration:** Copy `validate_specs.py` from canonical to your project's
`.nightshift/` directory and install (or reinstall) the pre-commit hook.

---

## 2.10.2 (2026-04-26)

### board.py — REPORTS button: spec-specific count

The spec-detail panel's `📋 REPORTS` button label was showing **global** unread count, but clicking it opens the panel **filtered by spec ID**. So a spec with zero matching reports still showed "(6 unread)" and the user opened to "no reports found" — confusing mismatch.

Now:

- No unread anywhere → `📋 REPORTS`
- No spec context, or all unread reports happen to match this spec → `📋 REPORTS (N unread)` (single number)
- Spec context, mixed counts → `📋 REPORTS (N/M unread)` where N = unread for this spec, M = unread total

Tooltip explains the format. The number you see is the number you'll see in the pre-filtered panel.

---

## 2.10.1 (2026-04-26)

### board.py — Fix: detail panel no longer auto-restores on page load

`openPanelId` was both **persisted** in localStorage and **restored on `loadSpecs()`**, which meant: open a spec → click outside the panel (which hides but doesn't clear the state) → reload → panel pops back open with the previous spec, even when you didn't have one open.

Two fixes:

1. `loadSpecs()` no longer auto-calls `openPanel(openPanelId)`; it explicitly resets `openPanelId = null` on every load. Recent-bar chips remain for one-click re-entry.
2. `openPanelId` is no longer written to `localStorage` (commented out in `saveSettings` / `loadSettings`). Stale state from previous sessions can't drift back.

The card-highlight feature (`card--active` for the spec whose panel is open) still works in-session — it just doesn't survive across reloads. That's the fix the user asked for.

---

## 2.10.0 (2026-04-26)

### board.py — Archive view for done specs

Done specs older than **14 days** (by file mtime) are now treated as **archived** for display purposes only — there's no new status, no protocol change, no spec edits. Pure UI behavior.

**Default:** archived specs are **hidden** from both the board and the graph view. The DONE column shows only fresh items (≤ 14 days), keeping it uncluttered as the project ages.

**New header button:** `🗄 ARCHIVED` lives next to `📋 REPORTS`.

- When archived items are hidden (default) and at least one exists, the button reads `🗄 +N` (with the count of hidden archives). Click to reveal.
- When showing, the button reads `🗄 ARCHIVED` and gets the active highlight. Click to hide again.
- When zero archived specs exist, the button is neutral.

**Coverage:** filter applies to (a) board column rendering, (b) board column count badges, (c) graph nodes (and incident edges drop along with them). Toggling the button re-renders both views.

**Threshold:** hardcoded to 14 days. Source of truth: each spec's file mtime, exposed via `_mtime` on `/api/specs`. State persisted in localStorage (`showArchived`).

**Why mtime:** matches the existing DONE-column auto-sort. No protocol changes, no `done_at` field needed. If a done spec gets edited (e.g. notes added) it'll un-archive until 14 days pass again — acceptable trade-off for not requiring a schema migration.

---

## 2.9.2 (2026-04-25)

### board.py — Reports: stronger read/unread distinction + live refresh

**Visual distinction** between read and unread reports:

- **Unread:** 3px left-rail accent in the theme color, subtle theme-tinted background, name in bold full-contrast text. Hover deepens the tint. Designed to draw the eye on a long list.
- **Read:** 55% opacity, no left-rail accent, name in muted color and normal weight. Hover lifts to 85% so they're still readable when you mouse over.

**Live refresh on MARK READ.** Hitting `✓ MARK READ` in the report-content view now re-renders the list view in the background, so when you click `← REPORTS` you immediately see the just-read item faded out — no manual refresh needed. (Previously the toast appeared but the list still rendered the report as unread.)

---

## 2.9.1 (2026-04-25)

### board.py — Reports list filter + header entry point

- **Filter input** in the reports panel. Live, case-insensitive substring match against report filename + basename. Heading shows `N of M · K unread` when filtered, or `M reports · K unread` when not. `✕` button clears the filter.
- **Pre-filled from spec context.** Clicking `📋 REPORTS` on a spec card now opens the reports list pre-filtered with that spec's ID — so you immediately see only reports for that spec. Clear the filter to see everything.
- **Header REPORTS button.** New `📋 REPORTS` in the main header (next to GRAPH / COLS) opens the reports panel without any spec context — useful for browsing across the whole project. Panel header shows "ALL REPORTS"; back button is hidden because there's no spec to return to.
- **Panel header label** now reflects the current view: `<spec-id>` (spec view), `<spec-id> · REPORTS` (reports filtered to a spec), `ALL REPORTS` (header entry), `<spec-id> · REPORT` / `REPORT` (single report view).

---

## 2.9.0 (2026-04-25)

### board.py — Report discovery: recursive

Reports were only being read from `.nightshift/reports/`, but agents tend to drop reports next to the artifact they reviewed (e.g. `App/FartownikDS/reports/...`, `App/Fartownik/reports/...`). The board now walks the project root and surfaces every `*.md` file inside any directory named `reports/`, with sensible excludes (`.git`, `.claude`, `.cortex`, `node_modules`, `DerivedData`, `Pods`, build/dist/target, venvs).

**API changes:**

- `GET /api/reports` items now have `filename` (project-relative path, used as the unique identifier) and `name` (short basename, used for display). Sorted newest-first by mtime.
- `GET /api/report/{filename:path}` accepts paths with slashes; resolves and validates the candidate is inside the project root (no traversal). Frontend uses `encodeURIComponent` on the path.

**UI changes:**

- Reports list shows the basename (without `.md`) as the title and the directory path on the meta line below (e.g. `2026-04-25-FART-DS-002-nightshift-report` · `App/FartownikDS/reports`).
- Selected-report header in the panel shows just the short name; full path is on the `title=` tooltip for hover.
- Read-state in `.nightshift/board-reads.json` is keyed by relative path so reports with the same basename in different sub-packages are tracked independently.

---

## 2.8.3 (2026-04-25)

### board.py — Card border color updates immediately on drag

Dragging a card to a different column now updates its `data-status` attribute on the moved DOM element, not just the JS state. The CSS border-left rule (`.card[data-status="..."] { border-left-color: var(--c-status); }`) repaints right away. Previously the card kept the old column's color until the next poll/render cycle, which made it look like the drop hadn't taken effect. Revert path also restores the old `data-status` if the API write fails.

---

## 2.8.2 (2026-04-25)

### board.py — AUTO is a toggle; drag cancels physics

`⚙ AUTO` is now a real on/off toggle:

- **Click once** → physics starts; button shows `⏸ STOP` (active state).
- **Click again** → physics halts immediately; current positions are snap-aligned (if SNAP is on), saved, and locked. Button returns to `⚙ AUTO`.
- **Drag any node while physics is running** → simulation cancels right away so the user isn't fighting it; positions are saved at that moment.
- **Stabilization completing** also auto-stops physics (the natural settle point).

Internal: `_physicsRunning` flag drives the UI state; `startAutoArrange` / `stopAutoArrange` keep `setOptions({physics: ...})` calls symmetric so vis.js never gets stuck with physics half-on. Physics is also explicitly reset on every `showGraph()` re-render so theme changes / filter toggles don't leak the running state.

---

## 2.8.1 (2026-04-25)

### board.py — Suppress graph hover tooltip during drag

vis.js can fire `hoverNode` mid-drag, which was re-showing the spec popover after `dragStart` had hidden it. Added an `_isNodeDragging` flag set in `dragStart` (when a node is involved) and cleared in `dragEnd`. The `hoverNode` handler now early-returns while the flag is set, so dragging stays uncluttered. Tooltip resumes normally after release.

---

## 2.8.0 (2026-04-25)

### board.py — Cards follow worktree status

Previously a sibling worktree's status only showed up as a 🔧 badge overlay; the card itself stayed in the column matching `main`'s status. Now the board uses the **most progressive** status across `main` + every sibling worktree as the spec's effective state:

- If main says `ready` and worktree says `in_progress` → card is in IN_PROGRESS, badge still labels which worktree.
- If main says `in_progress` and worktree says `done` (pre-merge) → card is in DONE, badge surfaces which branch.

Same logic flows through to the graph view (column placement + node color). Counts in column headers and DONE-column auto-sort all use the effective status. The 🔧 badge continues to show the divergence so you can tell apart "merged" from "pending merge".

Status precedence follows the canonical board lifecycle: `planning < draft < ready < in_progress < blocked < active < done < superseded < retired`. Worktree never *demotes* a card's status — only promotes.

---

## 2.7.5 (2026-04-25)

### board.py — Graph edge direction fix

Edges in `/api/graph` now go **prerequisite → dependent** instead of dependent → prerequisite. If `FART-DS-014` has `after: [FART-DS-019]`, the arrow now points `019 → 014` ("do 019 first, it unblocks 014") — matching how a kanban/project-flow graph is naturally read. Previously arrows pointed the other way ("014 needs 019"), which was technically a build-dependency convention but confused everyone reading it as a workflow graph.

---

## 2.7.4 (2026-04-25)

### board.py — Auto-arrange graph nodes

New `⚙ AUTO` button in the graph toolbar (next to `⟲ RESET` and `⚏ SNAP`). Click to run Barnes-Hut force-directed physics for 250 iterations starting from the **current** node positions, then freeze. Resolves overlaps, lets edges pull connected nodes toward each other, and respects `⚏ SNAP` (snaps the final positions to grid). Saved positions update so the new arrangement persists.

Distinction: `⟲ RESET` discards manual positions and re-applies the column layout. `⚙ AUTO` keeps the rough current arrangement and just settles it.

---

## 2.7.3 (2026-04-25)

### board.py — Graph: click vs drag

vis.js fires a `click` event even after a node drag completes. This made the spec detail panel pop open every time you finished dragging a node. Now we set a one-shot suppression flag in `dragStart` (when `params.nodes.length > 0`) and clear it on the next `click`. Result: drag does drag, click does click, no surprise panel.

---

## 2.7.2 (2026-04-25)

### board.py — Peek-on-hover from RECENT bar

Hovering a chip in the RECENT bar now temporarily highlights the matching card on the board (dashed `--c-theme` outline via `.card--peek`) and/or the matching node in the graph (thicker theme-colored border + soft glow via `graphNodesDataset.update`). Highlight clears on `mouseleave`. Camera, scroll, and zoom are **not** touched — if the card/node is offscreen, that's fine; the existing tooltip already shows you the spec details. Coexists with `.card--active` (open panel) so both can be visible simultaneously.

---

## 2.7.1 (2026-04-25)

### board.py — Independent graph filter; tooltip contrast

- **Graph and board now have independent visibility.** The clickable graph legend (top-right, in graph view) toggles `graphHiddenStatuses` — used only by the graph. The board's COLS dropdown still toggles `hiddenColumns` — used only by the board. Same set of statuses, two independent filters; both persisted separately in localStorage.
- **Tooltip problem text uses `var(--text)` instead of `var(--text-muted)`** for proper contrast against the popover background. Title and problem snippet now share the same color; the visual hierarchy comes from the divider line and font size.

---

## 2.7.0 (2026-04-25)

### board.py — Hover popovers, node click, theme refresh, snap

**Hover popovers everywhere.** Hovering a card on the board, a chip in the RECENT bar, or a node in the graph now shows the same styled tooltip: spec ID (in theme color) → full title → status (in its status color) → snippet of the spec's `## Problem` (or `Issue`/`Why`/`Background`/`Context`/`Description`/`Summary`/`Overview`) section. Backend `_parse_spec_file` extracts the snippet to `_problem` (capped at 280 chars, markdown bullets/quotes stripped); served via `/api/specs` so no per-hover fetch.

**Node click opens the spec detail panel.** Clicking a graph node now opens the same right slide-in detail panel as clicking a board card (full title, meta, deps, REPORTS button, full markdown body). Highlight-and-info-bar still happens too. Closing the panel returns you to the graph as it was.

**Graph re-renders on theme change.** Toggling dark/light (`☀`/`☾`) or cycling the theme color (`◉`) while the graph is open now re-runs `showGraph()` so node colors, edge colors, and label strokes update from the live CSS variables. Saved positions and snap state persist across the re-render.

**Snap-to-grid for graph nodes.** New `⚏ SNAP` toggle in the graph toolbar. When on (default), dragged nodes snap to a 35px grid on drop — visually aligned without exact pixel-pushing. Toggling SNAP on also re-snaps all currently rendered positions. Saved positions are kept on grid coordinates. State persists in localStorage.

---

## 2.6.1 (2026-04-25)

### board.py — DONE auto-sort, theme-aware nav, clickable legend filter

- **DONE column auto-sorts by completion time.** Most-recently-modified done specs appear at the top. Backend exposes file mtime via `_mtime` in the spec API; frontend sorts `done` cards by `_mtime` desc instead of using `cardOrder`. When a card is dragged into DONE, its local `_mtime` is bumped immediately so the card jumps to the top right away (no waiting for the next poll).
- **vis.js navigation buttons themed.** Replaced vis.js's hardcoded PNG sprite icons with Unicode glyphs (`↑↓←→ + − ⊡`). Buttons now use `--surface-hi`, `--border`, `--text` for resting state and `--c-theme` on hover, so they match dark/light mode and the cycled theme color.
- **Legend doubles as filter.** The graph legend (top-right) is now interactive: click a status to toggle its visibility. Hidden statuses fade to 32% opacity. The `hiddenColumns` set is shared with the board's COLS dropdown — toggle in one place, both views update.

---

## 2.6.0 (2026-04-25)

### board.py — Worktree-aware status badges

When a sibling git worktree has a spec at a different `status:` than what `main` shows (e.g. a Codex subagent in worktree branch `feat/foo` has marked `FART-DS-008` as `in_progress` but the main branch still says `ready`), the board card now displays a 🔧 badge in the theme color: `🔧 IN_PROGRESS · feat-foo`.

This surfaces in-flight work that hasn't merged back to main yet — without merging the branch.

**Backend:** new endpoint `GET /api/worktree-status` runs `git worktree list --porcelain`, walks each non-main worktree's `.nightshift/specs/` directory, and reports specs whose worktree status differs from main. Returns `{spec_id: [{branch, status, path}, ...]}`.

**Frontend:** worktree state is fetched alongside `/api/specs` on initial load and on every poll cycle. Re-renders the board on change.

**Protocol note (in `~/.claude/CLAUDE.md`):** worktree-side status changes don't propagate to the board until merge. The parent agent (on `main`) should still mark `status: in_progress` on `main` *before* spawning a worktree subagent. The 🔧 badge is ambient awareness, not a substitute for marking on `main`.

---

## 2.5.1 (2026-04-25)

### board.py — Graph polish

- **Free-axis drag.** Dropped the per-axis `fixed: { x: true, y: false }` lock that prevented horizontal dragging. Physics is now disabled entirely so the column layout is the deterministic *initial placement*; you can drag any node anywhere from there.
- **Empty status columns skipped.** Only statuses that actually have nodes get a column slot — no more huge empty gap between READY and DONE when nothing else has work.
- **Column spacing widened** (260px between columns, 70px between rows) and **vertically centered** around origin.
- **Legend & info panel theme-aware.** Background now uses `var(--surface-hi)` instead of hardcoded `rgba(20,20,20,0.9)`; correct in both dark and light modes.
- **Legend moved to top-right** so it doesn't conflict with vis.js's bottom-left navigation buttons. The selected-node info bar now floats at top-center.
- **Initial fit works without physics.** Switched from `stabilizationIterationsDone` (which doesn't fire when physics is off) to `afterDrawing` for the first-frame fit.

---

## 2.5.0 (2026-04-25)

### board.py — Graph view rework

**Root-cause fix:** vis.js was rendering canvas elements that could escape the `#graph-container` flex bounds, leaving the graph invisible (worst case: dense graphs in light mode). Added explicit CSS constraints (`#graph-container > div`, `#graph-container canvas` forced to `100%/100%`) plus `position: relative; overflow: hidden; min-height: 0` on the container itself.

**Theme-aware colors:** Node, edge, label, and highlight colors are now read live from CSS variables (`--c-draft`, `--c-ready`, ..., `--text`, `--text-muted`, `--c-theme`) at graph render time. Light and dark mode both look correct; cycling the theme color affects the graph too. Labels get a stroke matching `--surface` for readability against any node fill.

**Column layout:** By default, graph nodes are positioned in vertical columns matching the board's status order (DRAFT → READY → IN_PROGRESS → BLOCKED → ONGOING → DONE → SUPERSEDED). X is locked per status; Y is seeded from `cardOrder` (so the visual order in a graph column reflects the order on the board) and adjusted by Barnes-Hut physics.

**Drag-to-persist:** Drag any node and its position is saved to localStorage. On next load, that node stays where you put it (both axes locked). All other nodes still follow the column layout.

**Nav controls:** vis.js's `navigationButtons` are now enabled — zoom, pan, fit. Keyboard arrows pan, +/- zoom (when graph has focus).

**Column visibility filter:** Hiding a column on the board (via the COLS dropdown) now also hides those nodes (and their edges) from the graph view. One control, both views.

**RESET button:** New `⟲ RESET` button in the graph toolbar clears all saved node positions and re-applies the default column layout.

---

## 2.4.6 (2026-04-25)

### board.py — Fix: graph view — switch to force-directed layout

The previous LR hierarchical layout broke on dense graphs (e.g. Fartownik: 20+ specs all depending on DS-001/002/003). vis.js cannot produce a valid hierarchical layout when many nodes share the same parents — it collapses them to overlapping positions or renders nothing visible.

Switched to Barnes-Hut force-directed layout (`improvedLayout: true`), which handles arbitrary dependency density. `stabilization.fit: true` + explicit `network.fit()` after stabilization ensures the graph always fills the view on open.

---

## 2.4.5 (2026-04-25)

### board.py — Fix: graph view empty on open

`network.fit()` is now called after stabilization completes when no specific node is being highlighted. Previously the graph rendered but placed nodes outside the visible viewport (double-click was needed to fit). Now the graph automatically fits to show all nodes on first open.

---

## 2.4.4 (2026-04-25)

### board.py — Recent bar hover tooltip

Hovering a chip in the RECENT bar now shows a styled tooltip with the full spec title, ID, and status (in its status color). The native browser `title` attribute has been removed. Tooltip positions above the chip and flips below if near the top of the screen.

---

## 2.4.3 (2026-04-25)

### board.py — Resizable detail panel

The spec detail panel can now be resized by dragging its left edge. The handle lights up in the theme color on hover. Width is constrained between 280px and 85% of viewport. Setting persists in localStorage and is restored on next visit.

---

## 2.4.2 (2026-04-25)

### board.py — Reports panel + card order persistence

**Reports panel:** Human review reports (`.nightshift/reports/*.md`) are now surfaced directly in the board. Open any spec's detail panel and click `📋 REPORTS (N unread)` to browse reports. Reports open in a slide-in sub-view within the same panel with ●/○ read/unread indicators. Click a report to read it with full markdown rendering; click `✓ MARK READ` to mark it. Read state is stored in `.nightshift/board-reads.json` (atomically written). Back navigation returns you to the report list or spec detail.

**Card order persistence:** Dragging specs within a column (reordering) now persists across restarts. Order is stored in localStorage under the board's port key. New specs that haven't been manually ordered appear at the bottom of their column. Cross-column drops also preserve the target column's order.

---

## 2.4.1 (2026-04-25)

### board.py — auto-poll

Board tab now polls `/api/specs` every 10 seconds automatically. Only fires
when the board tab is active and no search is in progress. Re-renders only
if a spec's status or count actually changed — silent no-op otherwise. Open
detail panels and active card highlights are preserved across polls.

---

## 2.4.0 (2026-04-25)

### Local Web Kanban Board (`board.py`)

New `canonical/board.py` — a single-file FastAPI server that serves a local Kanban
board for Nightshift specs at `http://localhost:7842`.

**Features:**
- Terminal Noir theme (dark, monospace, neon status accents)
- Seven status columns: DRAFT → READY → IN_PROGRESS → BLOCKED → ONGOING → DONE → SUPERSEDED
- Drag-and-drop status updates (SortableJS); changes write to spec files atomically
- mtime-keyed two-tier cache: Tier 1 (frontmatter, always in memory), Tier 2 (body, lazy)
  — cannot serve stale data; automatically picks up external file changes
- Search: debounced, in-memory after body warm, no cache staleness risk
- Detail panel: full markdown render (Marked.js), dependency chips with jump-to
- Dependency graph tab: Vis.js network, click-to-highlight connections
- `[⌥ DEPS]` toggle: dep badges on cards + click-to-graph navigation
- `--port`, `--open`, `--specs` CLI flags

**Sync:** `board.py` added to `CANONICAL_PROTOCOL_FILES` — deploy with
`python nightshift-sync.py canonical --apply`.

**Launch:**
```bash
.nightshift/board.sh                          # auto-opens browser, hash port
.nightshift/board.sh --port 8080              # override port
python .nightshift/board.py --specs ./plans/specs/  # test against any spec dir
```

**Hash-based port:** `board.py` derives a deterministic port from the project name
(`7800 + sum(ord(c) for c in project_name) % 200`). Each project always gets the
same port — safe to run multiple boards in parallel and easy to bookmark.

**Sync:** `board.sh` added to `CANONICAL_PROTOCOL_FILES` alongside `board.py`.

---

## 2.3.0 (2026-04-17)

### Karpathy Coding Principles — agent prompts v2 + spec template v5

Direct adoption of Andrej Karpathy's four LLM-coding principles (Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution), sourced from `forrestchang/andrej-karpathy-skills`. Applied to both Argo's global protocol surface and Nightshift's agent prompt chain.

**Changes to canonical/:**

- `prompts/implementation_v2.md`, `prompts/test_planning_v2.md`, `prompts/review_v2.md`, `prompts/validation_v2.md` — new Karpathy-aware versions of each agent phase prompt. Each extends the v1 body with principle-targeted guidance appropriate to that phase:
  - **implementation_v2** — Simplicity First + Surgical Changes + Think Before Coding; rejects speculative abstractions, "improvements" outside spec scope, silent assumption-picking.
  - **test_planning_v2** — Goal-Driven Execution; every AC becomes a failing-then-passing test; vague ACs get pushed back to the author, not invented around.
  - **review_v2** — Surgical Changes enforcement with a concrete blocklist (quote-style drift, out-of-scope docstrings, whitespace reflows) + Simplicity First senior-engineer test + Goal-Driven verification (every AC maps to a passing test).
  - **validation_v2** — Goal-Driven verification with strict evidence rules; "tests pass" alone is not proof; Live Execution Checklist items require their own evidence.
- `prompts/_registry.yaml` — v2 activated for all four phases; v1 kept as `experimental` for A/B comparison.
- `specs/_TEMPLATE.md` — bumped to v5 with optional `karpathy_checklist: [think|simple|surgical|goal]` frontmatter field. Empty means the global defaults apply; populated signals extra emphasis for agents running v2+ prompts (e.g., `[surgical]` on a bugfix spec where drive-by refactoring is the primary risk).

**Changes to Argo startup surface (outside canonical/, listed for traceability):**

- `~/.claude/CLAUDE.md` — new `## Karpathy Coding Principles` section after Defaults.
- `Argo/session.md` — one-line reference in Defaults.

**Migration:** No action required for existing v4 specs — `karpathy_checklist` is optional. Agents on the next run automatically use the v2 prompts. v1 prompts remain in `prompts/` for comparison; set `_registry.yaml` → `active:` back to `*_v1.md` to revert per-phase.

### Accumulated audit follow-up (prior work, bundled into 2.3.0)

The 2.2.1 → 2.3.0 bump also bundles canonical changes landed since 2026-04-10 that had not yet been versioned:

- **SPEC-040..048** (2026-04-16 audit follow-up): execution history DB wired into LOOP Step 16, handler registry wired into Step 2, outcome router into Step 11 with policies/backoff/ESCALATE action, `nsm.py` multi-root config, `IMPROVEMENTS.md` extractor fix, `config.yaml v3.0.0` + `--migrate-config`, `prior_attempts` enforcement gate, metrics timestamp validation.
- **SPEC-026/027/028** (Multi-stack Phase 3, 2026-04-17): cross-stack integration gate, output artifact verification, research synthesis gate.

These were already merged to canonical; 2.3.0 is the first version that captures them in the changelog.

---

## 2.2.1 (2026-04-10)

### Fix: Human review report now enforced in LOOP.md

Step 14 (Report Generation) was softly worded and skipped by agents.
Step 16 (Loop exit) had no gate on report existence.

**Changes:**
- Step 14: added `MANDATORY` header, self-verification step (confirm file exists before proceeding to Step 15), updated Why to clarify the report is the primary deliverable
- Step 16: added exit gate — loop cannot exit without `reports/YYYY-MM-DD-nightshift-report.md` present and non-empty; if missing, returns to Step 14
- `Skills/nightshift/SKILL.md`: brief boilerplate now includes explicit MANDATORY report instruction; post-run review blocks merge until report is confirmed

### Fix: Attempts write gap — `knowledge/attempts/` now has write triggers

`knowledge/attempts/` existed in every project but was never written to. The read side (Step 3) was wired; the write side was not.

**Changes:**
- LOOP.md implementation debug discipline (~line 712): "If 3+ fix attempts fail" now explicitly instructs writing `knowledge/attempts/<spec-id>-<description>.md` before triggering the circuit breaker
- LOOP.md Step 12 pattern decision Q3 ("Did I iterate through 3+ approaches?"): now explicitly instructs writing attempt records for each failed approach in `knowledge/attempts/`, with cross-reference from the pattern file
- `canonical/knowledge/attempts/_TEMPLATE.md`: reconciled format — YAML frontmatter with `spec_id`, `problem_area`, `date`, `status`, `approach`, `model_used`, `phase`, `error_type`; sections now match LOOP.md stall section (`What Was Tried`, `Why It Failed`, `What We Learned`, `Revisit If`, `Related Patterns`); added filled-in example

**Migration:** No config changes. Runs on 2.2.0 projects automatically on next sync.

---

## 2.2.0 (2026-03-30)

### New: Pre-Commit Hook

`hooks/pre-commit` is now part of the canonical kit and synced to every project
by `nightshift-sync.py`. The hook reads `lint` and `type_check` commands from
`config.yaml` and runs them before every `git commit`, rejecting commits that
fail — regardless of which agent or harness is running.

**Files changed:** `hooks/pre-commit` (new), `nightshift-sync.py`

**What's new:**
- `hooks/pre-commit` — shell script: reads `commands.lint` and `commands.type_check`
  from `config.yaml`, runs them, exits non-zero on failure
- `nightshift-sync.py` — canonical sync now includes `hooks/` directory sync
  (always-overwrite, executable bit preserved). Hooks were previously documented
  in `BOOTSTRAP.md` but never shipped with the kit.

**Migration (2.1.0 → 2.2.0):**

```bash
# Install the hook into your project's git:
cp .nightshift/hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

The hook is inert until `lint` and/or `type_check` are set in `config.yaml`.
No config changes required — just install and go.

---

## 2.1.0 (2026-03-30)

### New: DevKB Injection System

External Development Knowledge Base (DevKB) can now be loaded into every Nightshift
run automatically. DevKB contains cross-project lessons per technology — agents no
longer need to rediscover known fixes.

**Files changed:** `config.yaml`, `BOOTSTRAP.md`, `LOOP.md`

**What's new:**
- `config.yaml` — new `devkb` section: `path`, `writeback`, `mappings`, `always_include`
- `BOOTSTRAP.md` — Phase B8 (interactive DevKB config), Phase E1a (DevKB loading at bootstrap)
- `LOOP.md` — Step 3a (DevKB loading per loop iteration), Step 12.5 (DevKB writeback staging)
- `nightshift-sync.py` — new script: ingests DevKB proposals + syncs canonical protocol files

### New: Spec Status Lifecycle

Specs now have their `status:` frontmatter explicitly updated at each lifecycle stage.
Previously, specs were never marked `in_progress` or `done` — only `blocked` was set.

**Files changed:** `LOOP.md`, `ORCHESTRATOR.md`

**What's new:**
- `LOOP.md` Step 2 — marks selected spec as `status: in_progress` + commit
- `LOOP.md` Step 12.7 — marks completed spec as `status: done` + commit (MANDATORY)
- `ORCHESTRATOR.md` Step b — marks spec `in_progress` on main before launching sub-agent
- `ORCHESTRATOR.md` Post-merge — verifies `status: done`, sets it if sub-agent forgot
- `ORCHESTRATOR.md` Failure handling — records failed/blocked/discarded outcomes in metrics/reports and uses canonical frontmatter lifecycle statuses

### New: nightshift-sync.py

Bidirectional sync tool for all Nightshift projects:
1. **DevKB Ingest** — collects proposals from `.nightshift/knowledge/devkb-updates/`, deduplicates, appends to canonical DevKB, removes processed proposals
2. **Canonical Sync** — pushes protocol files from `canonical/` to all `.nightshift/` directories

**Location:** `ManagedProjects/Nightshift/nightshift-sync.py`

### Migration from 2.0.0

1. **config.yaml** — add the `devkb` section (optional, leave `path: ""` to disable):
   ```yaml
   devkb:
     path: ""
     writeback: true
     mappings: {}
     always_include: []
   ```
   Also bump:
   ```yaml
   kit_version: "2.1.0"
   ```
   And in `runtime:`:
   ```yaml
   loop_version: "2026-03-30"
   ```

2. **LOOP.md / BOOTSTRAP.md / ORCHESTRATOR.md** — run `nightshift-sync.py canonical`
   to push updated protocol files to all projects. Or wait for the scheduled task (daily 7 AM).

3. **Existing specs** — any specs currently `status: ready` that were already completed
   by a previous run should be manually set to `status: done`. Check metrics files to
   confirm which specs were actually completed.

4. **DevKB setup** (optional) — if you want DevKB injection, set `devkb.path` in each
   project's config.yaml and define `devkb.mappings` for the project's languages.

5. **No breaking changes.** All existing config.yaml files work without modification.
   The new `devkb` section is optional and defaults to disabled.

---

## 2.0.0 (2026-03-23)

### Breaking: Hierarchical Specs

Specs can now be organized in parent-child hierarchies with NFR (Non-Functional
Requirement) constraints.

**Files changed:** `config.yaml`, `LOOP.md`, `ORCHESTRATOR.md`, `nightshift-dag.py`

**What's new:**
- Spec frontmatter: `type: main`, `type: nfr`, `parent:`, `children:`, `implementation_order:`, `violates:`
- `nightshift-dag.py` — DAG engine for dependency analysis and execution plan generation
- `ORCHESTRATOR.md` — §2.1a (pre-computed plan check), §2.1b (main spec detection), §3.x (NFR injection)
- `LOOP.md` — Task Selection excludes `type: main` and `type: nfr` specs

### Breaking: Metrics Schema v1.0

Structured YAML metrics with enforced schema. Previous freeform metrics are no longer accepted.

**Files changed:** `metrics/_SCHEMA.md`, `validate_metrics.py`

### Migration from 1.x

1. **Specs** — existing specs keep working. New `type:` values (`main`, `nfr`) are optional.
   Specs without `type:` default to `feature`.
2. **Metrics** — all metrics YAML must now conform to `_SCHEMA.md`. Run `validate_metrics.py`
   to check existing files.
3. **config.yaml** — add `kit_version: "2.0.0"` at the top level.
4. **nightshift-dag.py** — copy to `.nightshift/` if using hierarchical specs.

---

## 1.0.0 (2026-03-16)

Initial release of Nightshift Kit.

- 16-step autonomous execution loop (LOOP.md)
- 5-phase bootstrap (BOOTSTRAP.md)
- Orchestrator for multi-spec delegation (ORCHESTRATOR.md)
- 6-persona review system (REVIEW.md)
- Knowledge patterns (knowledge/patterns/)
- Circuit breaker (stall detection)
- Crash recovery (checkpoints)
- Watcher (parallel review agent)
- Pre-commit hook generation
- Metrics collection (per-spec YAML)
