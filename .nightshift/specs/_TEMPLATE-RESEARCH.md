# Research Spec Template

Copy this template to create a research-domain spec. Save as `specs/SPEC-XXX-short-title.md`.

> **When to use:** For source gathering, synthesis, distillation, fact-checking, or any work where the output is a document (not code). Set `config.yaml → runner.domain: research`.

---

```markdown
---
id: SPEC-XXX
template_version: 2
priority: 1          # Within-layer priority (1 = highest, 10 = lowest)
layer: 0             # 0=foundation, 1=gathering, 2=synthesis, 3=polish
type: research       # research | distillation | fact-check | review
status: draft        # draft | ready | in_progress | done | blocked
domain: research     # research (must match config.yaml → runner.domain)
after: []            # Soft dependencies
prior_attempts: []   # Previous attempts at this problem
created: YYYY-MM-DD
---

# [Title of the Research Task]

## Problem

What question are you trying to answer? What gap does this fill? Why now?

Example:
> We need an updated analysis of KRU's FY2025 financials to re-evaluate
> the Quality Investing thesis. The v1 baseline used estimated data that
> turned out to be materially wrong on margins.

## Source Requirements

Where should the agent look? Be specific about required vs. optional sources.

- **Required sources:**
  - [ ] Source 1 (e.g., specific PDF, API endpoint, web article)
  - [ ] Source 2
  - [ ] Source 3
- **Optional/supplementary:**
  - [ ] Additional context source
- **Minimum distinct sources:** 3 (matches config.yaml → domain.min_sources)
- **Recency requirement:** [e.g., "data from 2025 or later", "articles from past 6 months"]

## Output Requirements

What should the deliverable look like?

- **Format:** [markdown | json | yaml | csv]
- **Output location:** [e.g., `output/SPEC-XXX/report.md`]
- **Template to follow:** [path to output template, if any]
- **Length guidance:** [e.g., "150-300 lines", "executive summary + detailed sections"]
- **Citation format:** [e.g., "[^1] footnotes", "inline (Author, Year)", "numbered references"]

## Requirements

Specific, verifiable things the output must contain or accomplish.

- [ ] Requirement 1: [e.g., "Extract revenue, net income, EBITDA from FY2025 report"]
- [ ] Requirement 2: [e.g., "Compare actual vs v1 estimates with % delta"]
- [ ] Requirement 3: [e.g., "Re-score Quality Investing framework with actual data"]

## Acceptance Criteria

Concrete, verifiable conditions. These become validation checks.

- [ ] AC 1: All required sources are cited with specific page/section references
- [ ] AC 2: No placeholder text remains (TODO, FILL IN, TBD, etc.)
- [ ] AC 3: Every factual claim has at least one supporting source
- [ ] AC 4: Output follows the specified template structure
- [ ] AC 5: Numbers are internally consistent (totals match component sums)

**Avoid vague AC like:**
- ❌ "Analysis is thorough"
- ❌ "Good quality writing"
- ✅ "All 8 Quality Investing dimensions are scored with supporting evidence"
- ✅ "Revenue figure matches source document within 1% tolerance"

## Synthesis Method

How should the agent organize and combine information from sources?

- **Approach:** [e.g., "thematic synthesis", "chronological narrative", "comparison matrix", "framework scoring"]
- **Key dimensions:** [what to organize around — themes, time periods, companies, criteria]
- **Conflict resolution:** [what to do when sources disagree — flag, prefer recency, average, etc.]

## Validation Criteria

What makes the output "correct"? These become the agent's self-check steps (LOOP step 4/5).

### Machine-checkable:
- Source count ≥ [N] distinct sources
- No placeholder text (regex: `TODO|FILL IN|PLACEHOLDER|TBD|XXX`)
- Output format valid (proper markdown headers, valid JSON, etc.)
- Citation completeness (every [^N] has a matching reference)

### Human-judgment (agent approximates, morning reviewer confirms):
- Terminology consistency
- Factual plausibility (do numbers make sense in context?)
- Balanced treatment (no cherry-picking sources)
- Appropriate confidence language for uncertain claims

## Context

Background for the agent. Not implementation instructions — reference material.

- [Link to prior work, baseline documents, related specs]
- [Domain knowledge files the agent should read]
- [Known constraints or limitations]

## Alternatives Considered

(Optional but recommended for non-trivial research)

- **Approach A (this spec):** [Why this synthesis method was chosen]
- **Approach B (rejected):** [Why not, what would change the decision]

## Out of Scope

What this spec explicitly does NOT cover.

- [Explicitly excluded topics, time periods, sources]
- [Follow-up work for future specs]

## Research Hints

Pointers for the research agent. Optional but improves first-pass success rate.

- Files to study: [paths to prior analyses, baseline documents, domain knowledge files]
- Patterns to look for: [data formats, citation styles used in prior work]
- Cortex tags: [relevant tags for querying project history]
- DevKB: [which DevKB files are relevant]

## Gap Protocol

Optional — defaults to standard gap protocol (see Nightshift-Coordinator-And-Observability.md Section 3.3).

- Research-acceptable gaps: [e.g., "source quality unclear", "conflicting data between sources"]
- Stop-immediately gaps: [e.g., "required source inaccessible", "question scope ambiguous"]
- Max research subagents before stopping: 3 (default)

---

## Notes for the Agent

(Optional — clarifications, known source quality issues, etc.)

- [e.g., "Source X may have paywalled data — use the cached PDF in do-przeanalizowania/"]
- [e.g., "The v1 baseline is at path/to/baseline.md — read it for context but don't trust its numbers"]
```

---

## Research Layer Conventions

| Layer | Purpose | Examples |
|-------|---------|----------|
| 0 | Source gathering | Collect raw data, download documents, extract tables |
| 1 | Fact-checking | Verify claims, cross-reference sources, flag inconsistencies |
| 2 | Synthesis | Combine sources into structured analysis, score frameworks |
| 3 | Polish | Improve clarity, add executive summary, format for presentation |

---

## Checklist Before Marking as "ready"

- [ ] Problem and question are specific (not "research X" but "answer Y about X")
- [ ] Required sources are listed and accessible
- [ ] Output format and location are specified
- [ ] Acceptance criteria are specific and verifiable
- [ ] Validation criteria include both machine-checkable and human-judgment items
- [ ] Synthesis method is described (not just "analyze it")
- [ ] Out of scope is clear
- [ ] Prior attempts referenced if this topic was researched before

---

> A good research spec tells the agent what question to answer, where to look, and how to know when the answer is good enough.
