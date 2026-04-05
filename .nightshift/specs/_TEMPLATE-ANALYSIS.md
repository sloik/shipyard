# Analysis Spec Template

Copy this template to create an analysis-domain spec. Save as `specs/SPEC-XXX-short-title.md`.

> **When to use:** For data processing, financial statements, calculations, reconciliations, or any work where the output requires verified numbers and computations. Set `config.yaml → runner.domain: analysis`.

---

```markdown
---
id: SPEC-XXX
template_version: 2
priority: 1          # Within-layer priority (1 = highest, 10 = lowest)
layer: 0             # 0=data-prep, 1=calculations, 2=analysis, 3=presentation
type: analysis       # analysis | reconciliation | valuation | scoring | report
status: draft        # draft | ready | in_progress | done | blocked
domain: analysis     # analysis (must match config.yaml → runner.domain)
after: []            # Soft dependencies
prior_attempts: []   # Previous attempts at this problem
created: YYYY-MM-DD
---

# [Title of the Analysis Task]

## Problem

What decision does this analysis support? What question does it answer?

Example:
> We need to extract KRU's actual FY2025 financial data from the annual
> report PDF and re-score the Quality Investing framework using real
> numbers instead of estimates. The investment thesis depends on margins
> that the v1 analysis overestimated.

## Input Data

Specify ALL data sources with exact locations. The agent must be able to find every input.

- **Primary data:**
  - [ ] File: `path/to/data-file.pdf` — [what it contains, which sections matter]
  - [ ] File: `path/to/spreadsheet.xlsx` — [sheet name, row/column ranges]
- **Reference data (for cross-checking):**
  - [ ] File: `path/to/baseline.md` — [prior analysis to compare against]
  - [ ] API: [endpoint, what data it provides]
- **Data quality notes:**
  - [Known issues: e.g., "PDF tables may not parse cleanly", "numbers in thousands"]
  - [Currency, units, fiscal year conventions]

## Calculations Required

List every calculation the agent must perform. Be explicit about formulas.

- [ ] **Metric 1:** [e.g., "Net margin = Net income / Revenue × 100%"]
- [ ] **Metric 2:** [e.g., "EBITDA margin = EBITDA / Revenue × 100%"]
- [ ] **Metric 3:** [e.g., "ROE = Net income / Shareholders equity × 100%"]
- [ ] **Derived:** [e.g., "Quality score = weighted average of 8 dimensions per framework"]

**Calculation conventions:**
- Rounding: [e.g., "2 decimal places for percentages, integers for currency amounts"]
- Currency: [e.g., "PLN thousands", "USD millions"]
- Period: [e.g., "FY2025 = Jan-Dec 2025", "Q4 = Oct-Dec"]

## Output Requirements

What should the deliverable look like?

- **Format:** [markdown | json | yaml | csv | xlsx]
- **Output location:** [e.g., `output/SPEC-XXX/analysis.md`]
- **Template to follow:** [path to output template, if any]
- **Required sections:**
  - [ ] Section 1: [e.g., "Financial summary table"]
  - [ ] Section 2: [e.g., "Period-over-period comparison"]
  - [ ] Section 3: [e.g., "Framework scoring with evidence"]
  - [ ] Section 4: [e.g., "Conclusions and confidence assessment"]

## Acceptance Criteria

Concrete, verifiable conditions. Focus on numerical accuracy.

- [ ] AC 1: All figures extracted from source match source document (agent states page/table reference)
- [ ] AC 2: Calculated metrics are arithmetically correct (verifiable by re-computation)
- [ ] AC 3: Totals reconcile (e.g., revenue = sum of segment revenues)
- [ ] AC 4: Comparison with baseline shows explicit deltas (actual vs. estimated, with %)
- [ ] AC 5: Output follows the specified template structure
- [ ] AC 6: Confidence tags on uncertain figures (e.g., "[estimated]", "[calculated]", "[reported]")

**Avoid vague AC like:**
- ❌ "Analysis is accurate"
- ❌ "Numbers look right"
- ✅ "Net margin calculated from extracted net income and revenue matches within 0.1pp"
- ✅ "All 8 framework dimensions scored with 1+ supporting data point each"

## Reconciliation Checks

Cross-checks the agent must perform to validate internal consistency.

- [ ] **Check 1:** [e.g., "Revenue breakdown by segment sums to total revenue"]
- [ ] **Check 2:** [e.g., "Balance sheet: Assets = Liabilities + Equity"]
- [ ] **Check 3:** [e.g., "YoY growth rates are consistent with absolute figures"]
- [ ] **Check 4:** [e.g., "Extracted figures match across multiple source documents"]

## Validation Criteria

What makes the output "correct"? These become the agent's self-check steps.

### Machine-checkable:
- All reconciliation checks pass (sums match, no arithmetic errors)
- No placeholder text (regex: `TODO|FILL IN|PLACEHOLDER|TBD|XXX`)
- Output format valid (proper structure, tables render correctly)
- Confidence tags present on all non-reported figures

### Human-judgment (agent approximates, morning reviewer confirms):
- Extracted figures match source (requires visual comparison with PDF)
- Analysis narrative is consistent with the numbers
- Conclusions follow logically from the data
- Comparison with baseline is fair (apples-to-apples)

## Context

Background for the agent. Reference material, not instructions.

- [Link to prior analyses, framework docs, methodology descriptions]
- [Domain knowledge the agent should read]
- [Known limitations of the data or methodology]

## Alternatives Considered

(Optional)

- **Approach A (this spec):** [Why this analysis method was chosen]
- **Approach B (rejected):** [Why not]

## Out of Scope

What this spec explicitly does NOT cover.

- [Excluded metrics, time periods, comparisons]
- [Follow-up analyses for future specs]

## Research Hints

Pointers for the analysis agent. Optional but improves first-pass success rate.

- Files to study: [paths to data files, prior analyses, methodology docs]
- Patterns to look for: [data formats, calculation conventions, fiscal year conventions]
- Cortex tags: [relevant tags for querying project history]
- DevKB: [which DevKB files are relevant]

## Gap Protocol

Optional — defaults to standard gap protocol (see Nightshift-Coordinator-And-Observability.md Section 3.3).

- Research-acceptable gaps: [e.g., "data extraction ambiguity", "missing reference data"]
- Stop-immediately gaps: [e.g., "source PDF unreadable", "calculation methodology undefined"]
- Max research subagents before stopping: 3 (default)

---

## Notes for the Agent

(Optional — gotchas, data extraction tips, etc.)

- [e.g., "PDF extraction may produce OCR errors — cross-check key figures"]
- [e.g., "Fiscal year ends March 31, not December 31"]
- [e.g., "Use independent extraction (don't copy from baseline) to catch baseline errors"]
```

---

## Analysis Layer Conventions

| Layer | Purpose | Examples |
|-------|---------|----------|
| 0 | Data preparation | Extract from PDFs, clean spreadsheets, normalize formats |
| 1 | Calculations | Compute metrics, ratios, aggregates |
| 2 | Analysis | Compare, score frameworks, identify trends, draw conclusions |
| 3 | Presentation | Format for stakeholders, add executive summary, create visuals |

---

## Checklist Before Marking as "ready"

- [ ] Problem states the decision this analysis supports
- [ ] All input data files are listed with exact paths
- [ ] Every required calculation has an explicit formula
- [ ] Reconciliation checks are defined (how to verify internal consistency)
- [ ] Output format, location, and required sections are specified
- [ ] Acceptance criteria focus on numerical accuracy (not vague quality)
- [ ] Confidence tagging convention is specified
- [ ] Prior attempts referenced if this data was analyzed before

---

> A good analysis spec tells the agent what numbers to extract, how to calculate derived metrics, and how to verify the results are correct.
