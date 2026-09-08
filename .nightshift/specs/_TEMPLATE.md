# Spec Template

Copy this template to create a new spec. Fill in all sections. Save as `specs/SPEC-XXX-short-title.md`.

---

```markdown
# Spec Template v11
# Changelog:
#   v11 (2026-09-06): Live Execution Checklist items now require an inline
#                     `(evidence: <path>)` reference on each checked LEn line
#                     when real_use_evidence.policy is required_before_done
#                     (BUG-023). The path must resolve to a real file relative
#                     to the spec's directory or its parent. Existence only —
#                     no hash required. Grandfathered: specs below v11 are
#                     exempt; do not bump an already-done spec to v11 without
#                     also backfilling real evidence references.
#   v10 (2026-09-04): Added optional `scope:` frontmatter block (write/deny/read)
#                     and the `## Scope Amendments` body section (SPEC-300-001).
#                     Migration: add nothing; absent `scope:` means project root.
#   v9 (2026-08-29): Added required-on-amendment AC Amendments table (SPEC-260).
#   v1 (2026-03-16): Initial template
#   v2 (2026-04-01): Added template_version, research_hints, gap_protocol sections.
#                     Migration: add empty research_hints and gap_protocol sections;
#                     convert prior_attempts from flat list to structured format.
#   v3 (2026-04-12): Added multi-stack & domain fields (SPEC-023): stack, domain,
#                     output_artifact, output_type, output_schema, context.required_inputs.
#                     All new fields optional — v2 specs work unchanged.
#   v4 (2026-04-16): Added spec-quality fields via EVOLVE-007/008/009:
#                     - devkb_required (required for code/bugfix specs)
#                     - cortex_cites (optional, encouraged)
#                     - Live Execution Checklist section (required for feature specs
#                       except trivial single-file fixes).
#                     Migration: v3 specs work unchanged; new specs SHOULD populate
#                     devkb_required when stack is code. Live Execution section omits
#                     only for CSS/text single-file fixes.
#   v5 (2026-04-17): Added karpathy_checklist field (Karpathy Coding Principles opt-in).
#                     OPTIONAL field accepting [think, simple, surgical, goal].
#                     Empty/absent = global defaults apply (see global CLAUDE.md
#                     § "Karpathy Coding Principles"). Agents running v2+ prompts read
#                     this field for per-spec emphasis (e.g., [surgical] on a bugfix spec
#                     signals the risk is drive-by refactoring, not complexity).
#                     Migration: v4 specs work unchanged.
#   v6 (2026-04-28): Added ## Documentation Impact section (from FART-TEST-006 pattern).
#                     OPTIONAL body section listing doc files created or changed by this spec.
#                     "None" is a valid entry — the section header must be present in new specs.
#                     Encourages doc-sync discipline; no tooling required.
#                     Migration: v5 specs work unchanged; add section to new specs only.
#   v7 (2026-05-01): Added optional attachments frontmatter convention for visual
#                     references, screenshots, logs, and other evidence artifacts.
#                     Each attachment has path + description; kind/role are optional.
#                     Migration: v6 specs work unchanged; add attachments only when useful.
#   v8 (2026-08-26): Added explicit real_use_evidence closure policy (SPEC-238).
#                     Existing specs remain readable; new feature specs must choose
#                     required_before_done, delegated_experiment, or not_applicable.
---
id: SPEC-001
template_version: 11
priority: 1          # Within-layer priority (1 = highest, 10 = lowest)
layer: 0             # 0=foundation, 1=infra, 2=feature, 3=polish
type: feature        # See SPEC-GUIDE.md § Spec Types for all valid values
                     # main: parent spec with children — never executed directly (see Main Specs below)
                     # For bugfix: use _TEMPLATE-BUGFIX.md and include `violates:` field (required)
                     # For nfr or any NFR-* ID: use _TEMPLATE-NFR.md — standing quality constraints, never picked by the loop
status: draft        # draft | planned | ready | in_progress | done | blocked | superseded
                     # planned and ready have the same intrinsic quality gate; planned is intentionally future work.
                     # Dependencies and external/time/resource waits are derived run states, never reasons to mark blocked.
                     # NFR-family specs (id starts NFR- or type: nfr) use active | retired only.
                     # If blocked: require blocker_class, block_reason, blocked_since, unblock_condition,
                     # blocker_scope and blocker_evidence; ordinary waits remain ready/planned.
after: []            # Hard execution dependencies: list of spec IDs (e.g., [SPEC-001, SPEC-005])
requires_specs: []   # Explicit cross-project admission prerequisites only, e.g. [{project: BENCHMARKS, spec: SPEC-001}].
                     # `after:` is same-project only; malformed entries refuse this spec locally.
provides: []         # Optional capability markers this spec creates (SPEC-054).
requires: []         # Optional capability markers this spec needs; advisory unless paired with `after:`.
touches: []          # Optional files/capabilities likely affected; used for overlap warnings.
scope:               # Optional (v10, SPEC-300-001). Declares WHERE this spec may write/read.
                      # Absent entirely (or `write: []`) means the whole project root — never
                      # "anywhere" outside it. See SPEC-GUIDE.md § Write scope for the full
                      # semantics (implicit-allow rules, deny-wins, reason codes).
  # write: []         # Globs relative to the project root (git toplevel), gitignore-style.
                      # Absent or [] means the project-root default (equivalent to ["**"]).
  # deny: []          # Globs never writable even when matched by write; deny always wins
                      # except over the spec's own file.
  # read: unrestricted # unrestricted | [globs]. Absent means unrestricted.
                      # NOTE (v10, SPEC-300-001-001): if `write` already names a file that is
                      # itself part of the release manifest's managed set (nightshift-sync.py's
                      # CANONICAL_PROTOCOL_FILES) -- e.g. this spec edits scope_guard.py or
                      # SKILL.md -- you do NOT need to also add `<kit_dir>/release-manifest.json`
                      # or `<kit_dir>/CHANGELOG.md` to `write` by hand. scope_guard.py implicit-
                      # allows exactly those two files (reason implicit_kit_path) once that
                      # relationship holds. A spec with no managed-payload file in `write` gets
                      # no such exception -- release-manifest.json/CHANGELOG.md still DENY.
production_resources: [] # Optional absolute paths to production resources this run must stat, never open.
attachments: []      # Optional evidence/reference artifacts. List of mappings:
                     # - path: reports/ui/expected.png
                     #   kind: image        # image | log | video | data | doc | other
                     #   role: expected     # expected | actual | annotated | reference | evidence
                     #   description: Correct visual state or issue shown in this artifact.
                     # `attachments:` is evidence the AUTHOR cites at authoring time; the process's
                     # own record of what it decided and why (every status transition's reason,
                     # promotion knowledge) lives in reports/<SPEC-ID>/artifacts/ instead (SPEC-291)
                     # -- discoverable from the spec ID, never added here.
prior_attempts: []   # Previous attempts at this problem (e.g., [SPEC-005-sqlite-search])
                     # Files in knowledge/attempts/ the agent MUST read before starting.
                     # Auto-discovery also searches by problem area, but explicit refs are preferred.
# --- Sub-spec additions (optional, only for child specs of a main spec) ---
parent:              # Parent main-spec ID (e.g., SPEC-004). Back-reference to the feature this belongs to.
nfrs: []             # REQUIRED for type: feature/bugfix/refactor. List applicable NFR IDs (e.g., [NFR-001])
nfr_waivers: []      # Matched-but-inapplicable NFRs only: [{id: NFR-001, reason: "why"}]
                     # or [] to declare "reviewed all active NFRs, none apply to this spec."
                     # validate_specs.py errors on status: ready specs missing this field.
                     # Agent MUST read referenced NFR files and treat their ## Constraint sections as binding AC.
created: 2026-03-17
# --- Multi-stack & domain fields (optional, v3) ---
stack:                # Stack name from config.yaml stacks: section (e.g., "python-api")
                      # When set, loop uses this stack's commands instead of flat commands: block
domain:               # Override runner.domain for this spec (code | research | analysis)
output_artifact:      # Path (relative to project root) where this spec's output lives
output_type:          # What this spec produces: code | report | data | config | mixed
output_schema:        # Path to JSON/YAML schema the output_artifact must conform to
context:
  required_inputs: [] # Paths to artifacts from upstream specs that must exist before this spec runs
# --- Spec-quality fields (v4, added 2026-04-16 via EVOLVE-007/009) ---
devkb_required: []    # REQUIRED for type: feature/bugfix/refactor when stack is code.
                      # List of DevKB filenames the agent MUST read (e.g., [python.md, architecture.md]).
                      # Paste verbatim code snippets from those files into Research Hints for max leverage.
                      # Evidence: 2026-04-16 audit — specs with devkb_required populated complete in 0-1 fix cycles.
cortex_cites: []      # OPTIONAL but encouraged. List of Cortex entry IDs the spec author used as proof-of-research.
                      # Example: [#230, #240] — tells the agent which prior lessons shaped this spec.
# --- Karpathy Coding Principles opt-in (v5, added 2026-04-17) ---
karpathy_checklist: [] # OPTIONAL. Values: think | simple | surgical | goal
                       # Signals extra emphasis on a specific Karpathy principle for this spec:
                       #   think    — requirements still ambiguous; agent MUST surface assumptions before coding
                       #   simple   — resist overengineering; senior-engineer test applies at review
                       #   surgical — drive-by refactoring is the main risk (typical for bugfix specs)
                       #   goal     — AC must become failing tests first, then made to pass
                       # Empty = defaults apply (all four principles, no extra emphasis).
                       # Full text: global CLAUDE.md § "Karpathy Coding Principles".
# --- Real-use evidence policy (v8) ---
real_use_evidence:
  policy: required_before_done # required_before_done | delegated_experiment | not_applicable
  # reason:              # Required only for narrowly applicable not_applicable cases.
  # deferred:            # Required only for delegated_experiment; unchecked LE IDs exactly once.
  # - live_execution_id: LE1
  #   experiment_id: EXP-SPEC-001-01
  #   descriptor: experiments/EXP-SPEC-001-01.yaml
  #   hypothesis_ids: [H1]
  #   instrumentation_spec_id: SPEC-001-001
  #   lineage_record: metrics/followups/<operation-key>.json
  #   lineage_hash: <sha256-of-immutable-lineage-record>
# --- Execution model override (optional, SPEC-307) ---
# execution:
#   worker_model: sonnet            # Free-form model identifier; absent means "parent default"
#   verifier_model: sonnet          # Only worker_model/verifier_model are recognized keys
---

# [Title of the Feature]

## Problem

What problem does this solve? Why does it matter? Why now?

Example:
> Users can't search the document library. Currently, finding a specific document requires scrolling through hundreds of entries. This is slowing down daily workflows.

## Requirements

Specific, testable requirements. Each one should map to one or more acceptance criteria below.

- [ ] Requirement 1
- [ ] Requirement 2
- [ ] Requirement 3

Example:
- [ ] Add a search box on the document list page
- [ ] Support searching by document title
- [ ] Support searching by document content (full-text search)
- [ ] Display search results ranked by relevance

## Acceptance Criteria

Concrete, verifiable conditions. These become test cases.

- [ ] AC 1: When user types in the search box, results filter in real-time
- [ ] AC 2: Empty search returns all documents (or no results, per business rule)
- [ ] AC 3: Search is case-insensitive
- [ ] AC 4: Results are ranked by relevance (title matches rank higher than content matches)
- [ ] AC 5: Search handles special characters gracefully (no crashes, clear errors)

## AC Amendments

Leave this table empty unless an acceptance criterion changes after `status: ready`.
Every amendment preserves the original criterion and records independent approval.

| Date | AC | Change (old → new) | Kind | Justification | Approved by |
| --- | --- | --- | --- | --- | --- |

## Scope Amendments

Leave this table empty unless the declared `scope:` widens after `status: ready`.
Scope only widens through a human-approved commit on the main branch — see
SPEC-GUIDE.md § Write scope. `Approved by` must be `human` or `human:<name>`.

| Date | Path or glob | Change (old → new) | Reason | Approved by |
| --- | --- | --- | --- | --- |

## Live Execution Checklist

REQUIRED for `type: feature` unless the change is a single-file CSS/text fix.
Added 2026-04-16 via EVOLVE-008 — evidence: SPEC-029 (Shipyard) passed build + unit tests
but had 3 integration bugs that only surfaced in live execution. Green build + unit tests
is a necessary but insufficient gate for feature work.

After implementation + unit tests pass, the agent must trace the live path end-to-end.
Use stable bold IDs (`**LE1:**`) so closure validation can bind evidence:

- [ ] **LE1:** Trigger the feature in the live environment (click the button, call the API, run the CLI)
- [ ] **LE2:** Verify the integration wiring (route registered, store initialized, API response shape)
- [ ] **LE3:** Observe downstream effects (DB row written, event emitted, UI updated)
- [ ] **LE4:** Confirm the failure mode surfaces correctly when a precondition is violated
- [ ] **LE5:** Document the live execution trace in the run report (not just "tests passed")

Omit this section only for trivial changes that don't interact with routes, stores, or APIs.

**Evidence references (v11, BUG-023):** a checked box is text, not proof. When
`real_use_evidence.policy: required_before_done` (the default for this
template), checking a box before `status: done` requires an inline
`(evidence: <path>)` reference on the same line, pointing to a real file
(report, log, screenshot, or run artifact) relative to this spec's directory
or its parent. `validate_specs.py` verifies the file exists — no hash is
required. Example:

```markdown
- [x] **LE1:** Triggered via `curl -X POST /api/search?q=test` (evidence: reports/SPEC-001/live-run.md)
```

A checked box with no reference, an empty reference, or a reference to a file
that does not exist is a validation ERROR at `status: done`. This requirement
only binds specs with `template_version >= 11`; it is not retroactive.

**Avoid vague AC like:**
- ❌ "Search works well"
- ❌ "Performance is good"
- ✅ "Search returns results within 500ms"
- ✅ "Search handles 100K documents"

## Context

Relevant background, pointers to code/docs, and constraints. Do NOT include implementation details.

- See `src/repositories/DocumentRepository.ts` for existing document fetching
- Search algorithm preference: full-text search (see knowledge/search-patterns.md)
- API contract: GET `/api/documents/search?q=<query>` (documented in API guide)
- Database: PostgreSQL with full-text search already enabled
- Performance expectation: search results in <500ms for up to 100K documents

## Attachments

Optional. Use this section when screenshots, logs, videos, or data files clarify
the expected behavior or the current issue. Every item listed here must also
appear in frontmatter `attachments:` so tools can parse it.

```yaml
attachments:
  - path: reports/ui/expected.png
    kind: image
    role: expected
    description: Correct state from the handoff; tab bar is visible.
  - path: reports/ui/actual.png
    kind: image
    role: actual
    description: Current implementation; tab bar is missing.
  - path: reports/ui/annotated.png
    kind: image
    role: annotated
    description: One screenshot with numbered callouts for spacing and overlap issues.
```

Use relative paths from the project root. Put long explanations in this section,
not in the YAML description. Common UI roles:
- `expected` — correct state or reference design.
- `actual` — current buggy state.
- `annotated` — one artifact with multiple issues called out.
- `reference` — external or prior-art visual reference.
- `evidence` — supporting log/data/output from reproduction.

## Alternatives Considered

(Optional but recommended for non-trivial problems.)

What other approaches were considered? Why was this one chosen?
If prior attempts exist in `knowledge/attempts/`, reference them here.

- **Approach A (this spec):** [Why chosen — trade-offs, evidence]
- **Approach B (rejected/deferred):** [Why not chosen — what would change the decision]
- **Prior attempt:** [If applicable — link to knowledge/attempts/SPEC-XXX-description.md]

This section helps future specs avoid re-exploring rejected paths and gives the
agent context on why this particular approach was selected.

## Scenarios

End-to-end user journeys that describe complete workflows. Unlike Acceptance Criteria
(which test specific conditions), scenarios test *behavior* — full paths through the
feature as a real user would experience them.

Think of these as holdout tests: they validate the feature works in context, not just in isolation.

1. [Actor] does [action] → sees [result] → does [next action] → sees [final state]
2. [Actor] encounters [edge case] → system responds with [behavior]
3. [Actor] is in [unusual state] → feature behaves [gracefully]

Example:
1. User opens document list → types "budget" in search → sees 3 matching docs → clicks first → opens correctly
2. User searches while offline → sees cached results with "last updated 2h ago" banner → reconnects → results refresh automatically
3. User pastes 500-character string into search → input is truncated to 100 chars → no crash, results shown for truncated query

## Exemplar (Optional)

A working implementation of something similar the agent should study before planning.
Not for copying — for understanding patterns, trade-offs, and edge cases someone already solved.

- **Source:** [URL, file path, or project name]
- **What to learn:** [Patterns, architecture decisions, edge case handling]
- **What NOT to copy:** [Things specific to the exemplar that don't apply here]

## Out of Scope

What this spec explicitly does NOT cover.

- Advanced filters (by date, author, tag) — future spec
- Autocomplete/suggestions — future spec
- Search history/saved searches — not in MVP
- Highlighting matched terms in results — nice-to-have, post-MVP

## Documentation Impact

List every doc file this spec creates or changes, with a one-line note on what changes.

- `path/to/doc.md` — what changes (one line)
- `path/to/other.md` — what changes (one line)

(Or: "None — this spec does not touch user-facing documentation.")

## Research Hints

Pointers for the implementation agent: which files to read, which patterns to look for,
which Cortex tags are relevant. Optional but improves first-pass success rate.

- Files to study: [paths to key source files, test files, similar implementations]
- Patterns to look for: [naming conventions, architectural patterns in use]
- Cortex tags: [relevant tags for querying project history]
- DevKB: [which DevKB files are relevant — e.g., DevKB/swift.md]

## Gap Protocol

What should the implementation agent do if it gets stuck? Which gaps are acceptable
to research vs which should cause a stop? Optional — defaults to standard gap protocol
(see Nightshift-Coordinator-And-Observability.md Section 3.3).

- Research-acceptable gaps: [e.g., "project conventions", "existing patterns"]
- Stop-immediately gaps: [e.g., "ambiguous requirements", "missing API contracts"]
- Max research subagents before stopping: 3 (default)

---

## Notes for the Agent

(Optional section for clarifications, known gotchas, etc.)

- The existing DocumentRepository has a `search()` method stub — implement this first
- Watch out for N+1 queries when fetching document metadata in results
- Tests: see `src/__tests__/fixtures/documents.json` for test data

```

---

## Creating a New Spec

### File Naming
- Save as `specs/SPEC-XXX-short-title.md`
- Example: `specs/SPEC-001-add-search.md`
- Use the spec ID in the filename for easy lookup

### Setting Status

- `draft` — still being written, not ready for the loop
- `ready` — agent can pick this up
- `in_progress` — agent is working on it
- `done` — completed and merged
- `blocked` — **NEVER implement.** See Block Reason rules below.

### Blocked Specs — Rules

Every spec body must start with the display title used by the board:

```markdown
# SPEC-XXX - Short Title
```

When a spec has `status: blocked`, the **first content section after the title**
MUST be:

```markdown
## Block Reason

[Why this spec cannot be implemented. Be specific:]
- What is missing, unclear, or impossible?
- What would need to change to unblock this?
- If blocked by another spec: which spec, and which PART of that spec is needed?
```

**Blocked specs are NEVER picked up by the loop.** The task selection algorithm
filters them out. No agent should attempt to implement a blocked spec.

**Cascading blocks:** If Spec B depends on Spec A (via `after: [SPEC-A]`) and
Spec A is blocked, then Spec B MUST also be marked `blocked` with a Block Reason
that explains:
1. Which dependency is blocked (`SPEC-A`)
2. Which specific part of SPEC-A this spec needs (not just "depends on SPEC-A")
3. What would unblock the chain

Example cascading block reason:
```markdown
# SPEC-013 - Protected Endpoint UI

## Block Reason

Blocked by SPEC-012 (Add Authentication Layer).
This spec needs SPEC-012's JWT token validation middleware (Requirements R1, R3)
to protect the API endpoints defined here.
SPEC-012 is blocked because the auth provider contract hasn't been finalized.
Unblock path: finalize auth provider → unblock SPEC-012 → unblock this spec.
```

**When a blocked spec is unblocked:** Remove the Block Reason section, set
`status: ready`, and verify all cascading blocks are also updated.

**NFR-family exception:** Specs whose `id` starts with `NFR-` or whose
`type` is `nfr` are standing constraints / verification trackers. They use
`status: active | retired` only and are never marked `blocked`. If an NFR run
cannot execute because inputs, credentials, screenshots, APIs, or choices are
missing, record the pending state in the NFR body under `## Active Run State`,
`## Pending Inputs`, or `## Run Log`. If an NFR check fails, block the
triggering spec or create/link a concrete violation bug with
`violates: [NFR-001]`; do not block the NFR spec.

### Main Specs (type: main)

Main specs group related sub-specs into one feature. They are NEVER executed directly — the orchestrator reads them, builds the execution plan, and runs their children.

**Frontmatter for a main spec:**

```yaml
---
id: SPEC-004
priority: 1
layer: 1
type: main           # Never executed directly — orchestrator fans out to children
status: planning     # planning | ready | in_progress | done (NOT draft or blocked)
children:            # List of sub-spec IDs belonging to this feature
  - SPEC-004-001
  - SPEC-004-002
  - SPEC-004-003
implementation_order: # Authoritative execution sequence (may differ from children order)
  - SPEC-004-001
  - SPEC-004-003     # Discovery found this should run before 002
  - SPEC-004-002
after: []
prior_attempts: []
created: 2026-03-30
---
```

**Main spec body:** Same sections as regular specs (Problem, Requirements, AC, Context, Out of Scope, Notes) but describes WHAT the whole feature achieves — no implementation details for any single sub-spec.

**Main spec status lifecycle:**
- `planning` — spec is being designed, children may not exist yet
- `ready` — all children exist and are ready; run `nightshift-dag plan SPEC-ID` before execution
- `in_progress` — orchestrator is executing children
- `done` — all children completed successfully

Main specs do NOT use `draft` or `blocked`. If a main spec can't proceed, block its children instead.

**Notes for the agent reading a main spec:**
Do not implement this spec directly. Run `nightshift-dag plan <SPEC-ID>` to generate `execution-plan.json`, then execute children in the plan's `execution_order`.

### Sub-Spec Conventions

Sub-specs are regular executable specs that belong to a main spec. They gain two optional frontmatter fields:

- `parent: SPEC-NNN` — back-reference to the parent main spec
- `nfrs: [NFR-NNN, ...]` — list of NFR constraint IDs this spec must satisfy

**ID format rules:**
- Main/standalone specs: `SPEC-NNN` (e.g., `SPEC-004`)
- Sub-specs: `SPEC-NNN-NNN` (e.g., `SPEC-004-001`)
- **Max depth: 2 levels.** `SPEC-NNN-NNN-NNN` is invalid.
- Sub-spec IDs use zero-padded 3-digit suffixes

Sub-specs use the normal status lifecycle (`draft | ready | in_progress | done | blocked`) — they are regular executable specs in every way except they have a parent relationship.
This normal sub-spec lifecycle does not apply to `NFR-*` IDs; dated NFR run
specs still use `active | retired`.

### When to Use Main Specs

| Situation | Use |
|---|---|
| Single atomic deliverable | Plain feature spec |
| 2 loosely related tasks | Two separate specs with `after:` |
| 3+ interdependent sub-tasks for one feature | **Main spec + sub-specs** |
| Feature too large for one spec (>200 lines, >5 requirements) | **Main spec + sub-specs** |

**Rule of thumb:** If you need to explain how multiple specs relate to each other, they should be children of a main spec.

### Quality Constraints (NFRs)

Specs can declare quality constraints they must satisfy using the `nfrs:` field:

```yaml
nfrs: [NFR-001-001, NFR-002]   # Optional: NFR constraints (binding AC)
```

When present, the agent executing this spec MUST:
1. Read each NFR file listed (e.g., `specs/NFR-001-001-no-fault-logs.md`)
2. Extract the `## Constraint` section
3. Treat it as a binding acceptance criterion — violations fail the spec

The `nfrs:` field is optional. Specs without it have no injected constraints. See `_TEMPLATE-NFR.md` for NFR format and hierarchy.

Failed NFR verification is a failure of the triggering work, not of the NFR
lifecycle. Keep NFR-family specs `active`, record the verdict in the NFR body,
and block the triggering spec or file a violation bug.

### Setting Priority

Within a layer, priority 1 is highest. Use 1-10 scale.

- 1-3: High priority, should do soon
- 4-6: Medium priority
- 7-10: Low priority, can wait

### Setting Layer

Layers enforce natural build order. All Layer 0 must be done before Layer 1, etc.

| Layer | Purpose | Examples |
|-------|---------|----------|
| 0 | Foundation | Project scaffolding, CI setup, core data models, static tools |
| 1 | Infrastructure | Logging, auth, API client, database layer, caching |
| 2 | Features | User-facing features, search, profiles, notifications |
| 3 | Polish | Performance optimization, accessibility, analytics |

### Setting Soft Dependencies

If this spec needs another spec to be done first, list it in `after:`.

```yaml
after: [SPEC-001, SPEC-003]
```

This means: "If SPEC-001 and SPEC-003 are in the queue, wait for them. If they're not in the queue, proceed anyway."

Soft dependencies are hints, not blockers. Use them when one spec builds on another within the same layer.

### Writing Problem & Requirements

- Be specific. A reviewer should understand what you're trying to achieve.
- Include the "why" — not just "what."
- Link to existing code or documentation where relevant.

### Writing Acceptance Criteria

These become the test cases. They should be:

- **Specific:** "returns results within 500ms" not "fast"
- **Testable:** automated test can verify it
- **Independent:** each AC can be tested separately
- **Clear edge cases:** "empty input," "special characters," "boundary values"
- **No unnamed dependencies:** If an AC names a specific component or module, that component must appear in `after:`. If you don't want the blocking dependency, describe the slot/role generically (e.g. "a toggle" not "`BrandToggle`"). An AC that names something not in `after:` is a hidden dependency.

### Size Check

If your spec is >200 lines or has >5 related requirements, use a **main spec with sub-specs**:

1. Create a main spec (`type: main`) describing the full feature
2. Break into atomic sub-specs (`SPEC-NNN-NNN`), each with ≤3-5 requirements
3. Set `implementation_order:` in the main spec to define execution sequence
4. Run `nightshift-dag plan <SPEC-ID>` to validate the dependency graph

Example: SPEC-004 (Hierarchical Specs) → SPEC-004-001 (template changes), SPEC-004-002 (NFR hierarchy), SPEC-004-003 (DAG tool), SPEC-004-004 (orchestrator).

If the requirements are truly **unrelated** (not parts of one feature), use separate standalone specs with `after:` dependencies instead.

---

## Example: Complete Spec

```markdown
---
id: SPEC-005
template_version: 2
priority: 2
layer: 2
type: feature
status: ready
after: [SPEC-002]
prior_attempts: []
created: 2026-03-17
---

# Add Fuzzy Search with Typo Tolerance

## Problem

Users report that search is too strict. A typo ("recieve" instead of "receive") returns no results, frustrating users. We need fuzzy search to handle common misspellings.

## Requirements

- [ ] Implement fuzzy matching algorithm (Levenshtein distance)
- [ ] Allow 1-2 character mismatches per term
- [ ] Maintain sub-500ms response time for 100K document corpus

## Acceptance Criteria

- [ ] AC 1: "recieve" matches "receive" documents
- [ ] AC 2: "sarch" matches "search" documents
- [ ] AC 3: Single-character typos are caught
- [ ] AC 4: Response time stays <500ms (P95) for 100K docs
- [ ] AC 5: Empty queries return no results (per business rule)
- [ ] AC 6: Tests cover happy path, edge cases, and boundary values

## Context

- SPEC-002 (basic search) must be done first
- Levenshtein distance is already a dependency in package.json (js-levenshtein)
- Database: PostgreSQL, no built-in fuzzy matching
- See knowledge/search-patterns.md for project's search approach
- Existing test fixtures in src/__tests__/fixtures/documents.json

## Scenarios

1. User types "recieve memo" → sees results containing "receive memo" → opens correct document
2. User types "buget report 2025" → sees "budget report 2025" in results despite two typos → clicks it → correct doc opens
3. User types "x" (single char) → no fuzzy results shown (too short) → types "xy" → still no fuzzy (minimum 3 chars) → types "xyz" → fuzzy matches appear

## Exemplar

- **Source:** `js-levenshtein` README examples + Algolia typo-tolerance docs (https://www.algolia.com/doc/guides/managing-results/optimize-search-results/typo-tolerance/)
- **What to learn:** How production search engines handle typo distance thresholds per word length
- **What NOT to copy:** Algolia's ranking formula is overkill for our corpus size

## Out of Scope

- Soundex or phonetic matching (future)
- Weighting by document popularity (future)
- Fuzzy matching on metadata fields (future; scope creep risk)

## Research Hints

- Files to study: `src/repositories/DocumentRepository.ts`, `src/search/SearchEngine.ts`, `src/__tests__/search.test.ts`
- Patterns to look for: existing fuzzy matching in `js-levenshtein` usage, search result ranking
- Cortex tags: search, fuzzy-matching, performance
- DevKB: DevKB/typescript.md, DevKB/architecture.md

## Gap Protocol

- Research-acceptable gaps: project's search patterns, existing test fixtures format
- Stop-immediately gaps: performance requirements unclear, search API contract changes
- Max research subagents before stopping: 2

## Notes

- SPEC-002 tests basic search. Don't duplicate those tests — focus on fuzzy behavior.
- Watch out: fuzzy matching on very short queries (1-2 chars) may return too many results. Consider minimum threshold.
```

---

## Checklist Before Marking as "ready"

- [ ] `template_version` is set to latest (11)
- [ ] Documentation Impact section is present (list docs changed, or write "None — …")
- [ ] Attachments are listed in `attachments:` when visual/log/data evidence is needed; each has `path` and `description`
- [ ] Problem and context are clear
- [ ] Requirements map to acceptance criteria
- [ ] Acceptance criteria are specific and testable
- [ ] No AC names a component/module that isn't in `after:` (if named → add to `after:`; if not a dep → describe the role generically)
- [ ] Layer and priority are reasonable
- [ ] Out of scope is clear (prevent scope creep)
- [ ] You've noted any soft dependencies (after: ...)
- [ ] You've listed prior attempts if this problem was tackled before (prior_attempts: ...)
- [ ] Alternatives considered section is filled for non-trivial problems
- [ ] Scenarios describe end-to-end user journeys (not just unit-level conditions)
- [ ] Exemplar is linked if a similar solution exists elsewhere (optional but high-value)
- [ ] Research Hints section filled if implementation involves unfamiliar code areas
- [ ] Gap Protocol section filled if non-standard gap handling is needed
- [ ] Body starts with the real spec title H1 (`# SPEC-XXX - Short Title`)
- [ ] If status is `blocked`: first content section after the title is "## Block Reason" with specific details
- [ ] If any `after:` dependency is blocked: this spec is also blocked with cascading explanation
- [ ] If this is an NFR-family spec (`id: NFR-*` or `type: nfr`): status is `active` or `retired`, never `blocked`
- [ ] If this is a main spec: all children listed in `children:` and `implementation_order:`
- [ ] If this is a sub-spec: `parent:` field references the correct main spec
- [ ] If NFR constraints apply: `nfrs:` lists the relevant NFR IDs
- [ ] Someone reviewed the spec for clarity (optional but recommended)

---

> A well-written spec is the difference between smooth execution and frustrating back-and-forth.

---

## Migration from v1 → v2

1. Add to frontmatter: `template_version: 2`
2. Add new section after "Out of Scope":
   ### Research Hints
   [Pointers for the implementation agent: which files to read, which patterns to look for,
    which Cortex tags are relevant. Optional but improves first-pass success rate.]
3. Add new section after Research Hints:
   ### Gap Protocol
   [What should the implementation agent do if it gets stuck? Which gaps are acceptable
    to research vs which should cause a stop? Optional — defaults to standard gap protocol.]
4. Convert `prior_attempts` from flat list to structured:
   Old: `prior_attempts: ["Session 45 — failed on auth"]`
   New: `prior_attempts: [{session: "S-260325", phase: 8, gap_type: "context_gap", summary: "failed on auth — couldn't find auth pattern"}]`

## Migration from v2 → v3

1. Update frontmatter: `template_version: 3` (optional — v2 specs work unchanged)
2. Add multi-stack fields (all optional):
   - `stack:` — references a key in config.yaml → stacks: section
   - `domain:` — overrides project-level runner.domain for this spec
   - `output_artifact:` — path to this spec's primary output
   - `output_type:` — what kind of output (code | report | data | config | mixed)
   - `output_schema:` — path to a schema file for output validation
   - `context.required_inputs:` — paths to artifacts from upstream specs
3. All v2 fields remain unchanged. No v2 field was removed or renamed.

## Migration from v4 → v5

1. Update frontmatter: `template_version: 5` (optional — v4 specs work unchanged)
2. Add the opt-in Karpathy field (optional):
   - `karpathy_checklist: []` — accepts `[think, simple, surgical, goal]`
     - `think` — requirements ambiguous; surface assumptions before coding
     - `simple` — resist overengineering; senior-engineer test at review
     - `surgical` — drive-by refactoring is the risk (common for bugfix specs)
     - `goal` — AC become failing tests first, then made to pass
3. Empty `karpathy_checklist` means defaults apply — all four Karpathy principles are
   in force globally (see global CLAUDE.md § "Karpathy Coding Principles"). The field
   only adds *emphasis* for agents running v2+ prompts; it does not disable anything.
4. No v4 field was removed or renamed.

## Migration from v5 → v6

1. Update frontmatter: `template_version: 6` (optional — v5 specs work unchanged)
2. Add `## Documentation Impact` section to the spec body (after `## Out of Scope`,
   before `## Research Hints`):
   ```markdown
   ## Documentation Impact

   - `path/to/doc.md` — what changes (one line)

   (Or: "None — this spec does not touch user-facing documentation.")
   ```
3. No v5 field was removed or renamed.
4. **Backfill policy:** Only new and in-progress specs need the section. Done specs
   are left as-is until they need an update, at which point add the section then.
5. **No migration script.** Spec template changes are always manual and
   backwards-compatible — the loop accepts specs at any template_version.
   (config.yaml has `--migrate-config` in nightshift-sync.py; specs do not.)

## Migration from v6 → v7

1. Update frontmatter: `template_version: 7` (optional — v6 specs work unchanged)
2. Add optional `attachments:` frontmatter only when evidence artifacts are useful:
   ```yaml
   attachments:
     - path: reports/ui/actual.png
       kind: image
       role: actual
       description: Current buggy state with duplicated title.
   ```
3. Add `## Attachments` body section when attachments need explanation. Keep paths
   relative to the project root. Use `description` for the short tool-readable
   summary, and the body section for human detail.

## Migration from v9 → v10

Add nothing; absent `scope:` means project root.

1. Update frontmatter: `template_version: 10` (optional — v9 specs work unchanged).
2. Add optional `scope:` frontmatter (`write`, `deny`, `read`) only when the spec's
   write boundary is narrower than the whole project root. See SPEC-GUIDE.md
   § Write scope for the full semantics, defaults, and controlled reason codes.
3. Add the `## Scope Amendments` body section (same shape as `## AC Amendments`)
   so a future human-approved scope widening has somewhere to be recorded. An
   empty table is valid and is the common case.
4. No v9 field was removed or renamed. A spec with no `scope:` behaves exactly
   as it did under v9: writable anywhere inside the project root.

## Migration from v10 → v11

1. Update frontmatter: `template_version: 11` (optional — v10 and earlier specs
   are intentionally grandfathered and are NOT retroactively required to add
   evidence references; see BUG-023 R4).
2. Only bump an existing spec to v11 if you are also backfilling real
   `(evidence: <path>)` references on every checked LE item — bumping the
   version without the backfill turns an already-passing spec into a failing
   one at the next validation run.
3. For new specs (which default to v11 via this template), when
   `real_use_evidence.policy: required_before_done`, every checked
   `- [x] **LEn:**` line must carry `(evidence: <path>)` pointing to a real
   file, resolved relative to the spec's directory or its parent. No other
   frontmatter or section changes.
4. `delegated_experiment`'s existing `lineage_record`/`lineage_hash` evidence
   is unaffected by this migration.
