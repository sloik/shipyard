# Non-Functional Requirement (NFR) Template

Copy this template to define a standing quality constraint. Save as `specs/NFR-NNN-short-title.md`.

NFRs are different from feature/bugfix/refactor specs:
- They are **never picked up by the loop** — they define constraints, not tasks
- They use `status: active` (not the draft → ready → done lifecycle)
- Bug specs reference them via `violates: [NFR-001]` when the constraint is broken
- They stay active indefinitely until explicitly retired

---

```markdown
---
# --- Top-level NFR (quality area grouping) ---
id: NFR-001
template_version: 2
priority: 1          # Relative importance among NFRs (1 = highest)
layer: 0             # 0 = applies to all layers; or specific layer if scoped
type: nfr
status: active       # active | retired (NFRs don't use draft/ready/done)
children: [NFR-001-001, NFR-001-002]  # Sub-NFRs in this quality area (optional)
created: 2026-03-26
---
```

```markdown
---
# --- Sub-NFR (specific testable constraint) ---
id: NFR-001-001
template_version: 2
priority: 1
layer: 0
type: nfr
status: active
parent: NFR-001      # Top-level NFR this constraint belongs to
created: 2026-03-26
---

# [Title: One-Line Description of the Quality Constraint]

## Constraint

What quality attribute must the system maintain? Be specific and measurable.

Example:
> The application must produce zero SwiftUI fault-level logs (`Type: Fault`) during
> normal operation. Any fault indicates incorrect API usage and must be treated as a bug.

## Rationale

Why does this constraint matter? What happens if it's violated?

Example:
> SwiftUI faults indicate undefined behavior — the framework is telling us we're using
> it wrong. While the app may not crash immediately, faults can cause subtle rendering
> bugs, state corruption, and performance degradation. Apple may also change fault
> behavior in future OS releases, turning today's warning into tomorrow's crash.

## Scope

What parts of the system does this NFR apply to?

- All SwiftUI views
- All @Observable state management
- All environment injection

## Verification

How to check if this NFR is being met. These become things to check during code review
and testing.

- [ ] V1: Run the app and exercise all major flows — check Console for fault-level logs
- [ ] V2: Execute tools, navigate tabs, start/stop servers — zero faults in output
- [ ] V3: New PRs should not introduce new fault-level logs

## Known Violations

List any current violations that are known and tracked. Remove entries as bugs are fixed.

- BUG-006: onChange multiple updates per frame (FIXED)

## References

- Apple documentation on SwiftUI diagnostics
- Related specs that commonly trigger violations of this NFR
```

---

## Filing an NFR

### File Naming

- Save as `specs/NFR-NNN-short-title.md`
- Example: `specs/NFR-001-no-swiftui-faults.md`
- Use `NFR-NNN` format (not `SPEC-NNN` or `BUG-NNN`)

### When to Create an NFR

Create an NFR when you notice a recurring quality issue that:

1. Spans multiple features (not specific to one spec)
2. Should be a standing constraint for all future work
3. Violations should be filed as bugs with `violates: [NFR-NNN]`

### Relationship to Bug Specs

When a bug violates an NFR, the bug spec should reference it:

```yaml
violates: [NFR-001]           # NFR reference
violates: [SPEC-011, NFR-001] # Can reference both feature specs and NFRs
```

### Status Lifecycle

NFRs have a simpler lifecycle than other specs:

- `active` — constraint is in effect, violations are bugs
- `retired` — constraint is no longer relevant (document why in the spec)

NFRs are never `draft`, `ready`, `in_progress`, or `done`.

### Loop Exclusion

The task selection algorithm in LOOP.md explicitly filters out `type: nfr` specs.
NFRs exist to be referenced, not to be "worked on" as tasks.

---

## NFR Hierarchy

NFRs support a two-level hierarchy for organizing quality constraints:

**Top-level NFRs** (`NFR-NNN`) group a quality area:
- Have an optional `children:` field listing sub-NFR IDs
- Describe the general quality attribute (e.g., "Performance", "SwiftUI Correctness")
- Can be referenced directly by specs when the entire quality area applies

**Sub-NFRs** (`NFR-NNN-NNN`) are specific, testable constraints:
- Have a `parent:` field back-referencing the top-level NFR
- Define one concrete, measurable constraint (e.g., "App cannot crash on malformed input")
- Are the primary target for spec `nfrs:` references

**ID format:**
- Top-level: `NFR-NNN` (zero-padded, e.g., `NFR-001`, `NFR-042`)
- Sub-level: `NFR-NNN-NNN` (e.g., `NFR-001-001`, `NFR-001-042`)
- **Max depth: 2 levels.** `NFR-001-001-001` is invalid.

Both levels use `type: nfr`, both use `status: active | retired`, neither is picked up by the loop.

---

## NFR Injection (How Specs Reference NFRs)

Regular feature/bugfix/refactor specs can declare quality constraints via the `nfrs:` field in their frontmatter:

```yaml
nfrs: [NFR-001-001, NFR-002]   # Constraints this spec must satisfy
```

**How injection works:**
When a spec lists `nfrs:`, the executing agent MUST:
1. Read each referenced NFR file from `specs/NFR-NNN-*.md`
2. Extract the `## Constraint` section text
3. Treat it as **binding acceptance criteria** — violations are automatic AC failures

**What is binding vs informational:**
- `## Constraint` — **binding.** This is what "done" means. Violations fail the spec.
- `## Rationale` — informational. Helps the agent understand WHY.
- `## Scope` — informational. Shows WHERE the constraint applies.
- `## Verification` — informational. Shows HOW to check compliance.

**Example:** If a spec has `nfrs: [NFR-001-001]` and NFR-001-001's Constraint says "zero SwiftUI fault-level logs during normal operation," then ANY fault log in the implementation means the spec fails — even if all explicit ACs pass.

A spec can reference both top-level and sub-level NFRs. Referencing a top-level NFR means the entire quality area applies.

---

> NFRs are the guardrails. Features say what to build. NFRs say how well it must work.
