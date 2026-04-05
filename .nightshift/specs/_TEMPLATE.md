# Spec Template

Copy this template to create a new spec. Fill in all sections. Save as `specs/SPEC-XXX-short-title.md`.

---

```markdown
# Spec Template v2
# Changelog:
#   v1 (2026-03-16): Initial template
#   v2 (2026-04-01): Added template_version, research_hints, gap_protocol sections.
#                     Migration: add empty research_hints and gap_protocol sections;
#                     convert prior_attempts from flat list to structured format.
---
id: SPEC-001
template_version: 2
priority: 1          # Within-layer priority (1 = highest, 10 = lowest)
layer: 0             # 0=foundation, 1=infra, 2=feature, 3=polish
type: feature        # feature | bugfix | refactor | eval | nfr | main
                     # main: parent spec with children — never executed directly (see Main Specs below)
                     # For bugfix: use _TEMPLATE-BUGFIX.md and include `violates:` field (required)
                     # For nfr: use _TEMPLATE-NFR.md — standing quality constraints, never picked by the loop
status: draft        # draft | ready | in_progress | done | blocked
                     # If blocked: first section MUST be "# Block Reason" (see rules below)
after: []            # Soft dependencies: list of spec IDs (e.g., [SPEC-001, SPEC-005])
prior_attempts: []   # Previous attempts at this problem (e.g., [SPEC-005-sqlite-search])
                     # Files in knowledge/attempts/ the agent MUST read before starting.
                     # Auto-discovery also searches by problem area, but explicit refs are preferred.
# --- Sub-spec additions (optional, only for child specs of a main spec) ---
parent:              # Parent main-spec ID (e.g., SPEC-004). Back-reference to the feature this belongs to.
nfrs: []             # NFR constraint IDs this spec must satisfy (e.g., [NFR-001-001, NFR-002])
                     # Agent MUST read referenced NFR files and treat their ## Constraint sections as binding AC.
created: 2026-03-17
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

When a spec has `status: blocked`, the **first section** after the frontmatter MUST be:

```markdown
# Block Reason

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
# Block Reason

Blocked by SPEC-012 (Add Authentication Layer).
This spec needs SPEC-012's JWT token validation middleware (Requirements R1, R3)
to protect the API endpoints defined here.
SPEC-012 is blocked because the auth provider contract hasn't been finalized.
Unblock path: finalize auth provider → unblock SPEC-012 → unblock this spec.
```

**When a blocked spec is unblocked:** Remove the Block Reason section, set
`status: ready`, and verify all cascading blocks are also updated.

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

- [ ] `template_version` is set to latest (2)
- [ ] Problem and context are clear
- [ ] Requirements map to acceptance criteria
- [ ] Acceptance criteria are specific and testable
- [ ] Layer and priority are reasonable
- [ ] Out of scope is clear (prevent scope creep)
- [ ] You've noted any soft dependencies (after: ...)
- [ ] You've listed prior attempts if this problem was tackled before (prior_attempts: ...)
- [ ] Alternatives considered section is filled for non-trivial problems
- [ ] Scenarios describe end-to-end user journeys (not just unit-level conditions)
- [ ] Exemplar is linked if a similar solution exists elsewhere (optional but high-value)
- [ ] Research Hints section filled if implementation involves unfamiliar code areas
- [ ] Gap Protocol section filled if non-standard gap handling is needed
- [ ] If status is `blocked`: first section is "# Block Reason" with specific details
- [ ] If any `after:` dependency is blocked: this spec is also blocked with cascading explanation
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
