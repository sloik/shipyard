# Loop Domain Mapping

**Version:** 2026-03-18

**Purpose:** This document describes how the 16-step autonomous loop adapts to non-code domains. The loop skeleton (spec → plan → execute → validate → knowledge) is universal. Only the activities within each step change.

**When to read this:** If `config.yaml` → `runner.domain` is NOT `code`, read this file before entering the loop. It maps each of the 16 steps to your domain (research or analysis) and explains what "passing" means for non-code work.

---

## Step Mapping Table

| Step | Code Domain | Research Domain | Analysis Domain |
|------|------------|-----------------|-----------------|
| 1. Pre-flight | Build + test + lint baseline | Check tools exist (Python, APIs, access to sources) | Check tools + data sources accessible |
| 2. Task selection | Same across all domains | Same | Same |
| 3. Context loading | Read code + knowledge patterns | Read source materials + prior research + knowledge patterns | Read data files + prior analyses + knowledge patterns |
| 4. Test planning | Write test plan (what to test, edge cases) | Write validation criteria (what makes output correct, fact-checkable claims) | Write validation criteria (calculations to verify, cross-references needed) |
| 5. Test writing | Write failing tests (TDD red phase) | Write acceptance checklist (machine-checkable where possible) | Write validation script or checklist |
| 6. Implementation planning | Plan code approach | Plan research approach (sources, structure, synthesis method) | Plan analysis approach (data pipeline, calculations, output structure) |
| 7. Plan review | Review personas: architect, security, quality | Review personas: methodology, completeness, bias | Review personas: methodology, accuracy, completeness |
| 8. Implementation | Write code, run lint after every change | Gather sources, synthesize, write output | Process data, calculate, generate output |
| 8.5. Status check | Same across all domains | Same | Same |
| 9. Validation | Build + full test suite + lint | Fact-check claims, verify source citations, check format | Verify calculations, cross-reference totals, check format |
| 9.5. Completion verification | Same across all domains | Same | Same |
| 10. Post-impl review | Code review personas | Research review personas (methodology, accuracy, bias) | Analysis review personas (accuracy, completeness, methodology) |
| 11. Capture TODOs | Same across all domains | Same | Same |
| 12. Commit + knowledge | Same across all domains | Same | Same |
| 13-16 | Same across all domains | Same | Same |

---

## Research Domain Details

For `runner.domain: research`:

### Pre-flight Check (Step 1)

**What to do:**
1. Skip build/test/lint commands
2. Instead, verify:
   - Required tools exist: Python (or your scripting language), curl/wget, text processing tools
   - Access to required sources: APIs, databases, file storage, or public web access
   - Output tools work: pandoc (if converting formats), Python formatting libraries, text editors
   - Check for existing outputs that need to be preserved (don't overwrite prior work)
   - Verify git working tree is clean

**Example pre-flight checklist:**
```
✓ Git working tree clean (no uncommitted changes)
✓ Python 3.8+ available (for source verification scripts)
✓ Web access available (for news/article sources)
✓ Required APIs accessible (verified by test call)
✓ Prior outputs exist at: output/SPEC-XXX/ (will preserve)
✓ pandoc installed (for markdown → docx conversion)
```

**If pre-flight fails:**
- Read the error carefully
- Attempt fixes (install missing tool, check network/API access, etc.)
- Re-run pre-flight
- If still fails after 3 attempts → write BLOCKED report, move to next spec

### Validation Criteria (Step 4, replaces test planning)

The agent writes a validation plan that describes what makes output "correct" and fact-checkable.

**Template:**
```markdown
## Validation Plan for SPEC-XXX

### 1. Source Verification
- Minimum N distinct sources cited (from config.yaml → domain.min_sources)
- Each factual claim has at least one source
- Sources are accessible and recent (within timeframe specified in spec)
- Citation format matches spec requirements

### 2. Completeness Check
- [ ] All spec requirements addressed
- [ ] All sections from output template present
- [ ] No placeholder text remaining
- [ ] All data points requested are provided

### 3. Consistency Check
- No contradictory claims within the document
- Terminology used consistently
- Numbers/dates internally consistent
- Cross-references valid

### 4. Format Compliance
- Output matches expected format (markdown/json/yaml/csv, etc.)
- Citations follow specified format
- Headers/structure match template if provided
- File encoding and line endings correct

### 5. Machine-Checkable Validations
- Source count: assert count(citations) >= N
- No placeholder text: regex check for "TODO|FILL IN|PLACEHOLDER"
- Citation completeness: every [^1] link has matching reference
- Format structure: valid JSON/YAML/CSV if applicable
```

**Why:** Without clear validation criteria, "done" is subjective. Writing this plan upfront prevents rework and gives the agent clear acceptance conditions.

### Acceptance Checks (Step 5, replaces test writing)

The agent writes machine-checkable validations where possible, plus a manual checklist.

**What to include:**
- Python script that verifies citation count, checks for placeholder text, validates format structure
- Checklist of manual checks that require human judgment (is terminology consistent? Do facts sound right?)
- Commit message for this phase: `check(SPEC-XXX): add validation criteria`

**Example acceptance check script:**
```python
# validate_SPEC-XXX.py
import re
import json

def validate_sources():
    """Verify minimum source count and citation format."""
    with open('output/SPEC-XXX/report.md') as f:
        text = f.read()
    sources = re.findall(r'\[\^(\d+)\]', text)
    assert len(set(sources)) >= 3, f"Need ≥3 sources, found {len(set(sources))}"

def validate_no_placeholders():
    """Ensure no TODO/PLACEHOLDER text remains."""
    with open('output/SPEC-XXX/report.md') as f:
        text = f.read()
    assert 'TODO' not in text, "Found TODO placeholder text"
    assert 'FILL IN' not in text, "Found FILL IN placeholder text"

def validate_format():
    """Verify markdown structure."""
    with open('output/SPEC-XXX/report.md') as f:
        lines = f.readlines()
    # Check headers exist
    headers = [l for l in lines if l.startswith('#')]
    assert len(headers) >= 3, f"Need ≥3 sections, found {len(headers)}"

if __name__ == '__main__':
    validate_sources()
    validate_no_placeholders()
    validate_format()
    print("✓ All validation checks passed")
```

### Implementation Planning (Step 6)

The agent plans the research approach:

**What to include:**
- Which sources to gather from (web search, APIs, files, databases)
- Synthesis method: how will information be organized and synthesized?
- Output structure: outline or template for the final report
- Any calculations or aggregations needed
- Risk mitigation: where might facts be hard to verify? What are backup sources?

**Example plan:**
```markdown
## Research Approach for SPEC-XXX

### Phase 1: Source Gathering (Est. 30 min)
- Query news API for articles on [topic], filtered by date range and relevance
- Pull financial statements from SEC Edgar API
- Gather expert analysis from [3-5 specific sources]
- Fallback: use broader search if specific APIs unavailable

### Phase 2: Synthesis (Est. 20 min)
- Organize findings by theme: A, B, C from spec requirements
- Cross-reference for contradictions (flag and resolve)
- Weight sources by recency and authority
- Build outline with citations as we go

### Phase 3: Write Output (Est. 25 min)
- Draft each section following the template
- Embed citations inline using [^1] format
- Validate draft against checklist

### Risk Mitigation
- API rate limits: implement exponential backoff
- Missing sources: have 2-3 backup sources per major claim
- Citation format: use markdown footnotes, validate syntax
```

### Plan Review (Step 7)

**Review personas for research:**

| Persona | Owns | Reviews Against |
|---------|------|-----------------|
| **Methodology** | Research standards, source evaluation criteria, synthesis logic | Is the approach sound? Are sources reliable and appropriate? Is the synthesis method suitable for the spec's requirements? |
| **Completeness** | Spec requirements, output template | Are all requirements addressed? Any gaps? Any sections thin or underdeveloped? Will the output answer the original question? |
| **Bias** | Nothing specific — adversarial role | Are conclusions balanced? Any cherry-picking of sources? Any framing bias in language? Are counterarguments presented? |

**What reviewers check:**
- Methodology: Is this the best way to answer the question? Are the sources reliable?
- Completeness: Does the plan address every spec requirement?
- Bias: Would a skeptical reader see this as fair and balanced?

### Implementation (Step 8)

The agent:
1. Gathers sources (web search, API calls, file reading)
2. Synthesizes information into structured output
3. Writes the deliverable following the spec template
4. Embeds citations inline as content is written
5. Runs format check after each major section (equivalent of lint in code)
6. Commits incrementally: `feat(SPEC-XXX): gather sources from [source1, source2]` → `feat(SPEC-XXX): draft section A` → etc.

**Key practice:** Validate as you go. Don't write all the content, then validate at the end. After each section, run the machine-checkable validations to catch format/citation errors early.

### Validation (Step 9)

The agent:
1. Runs the validation script from step 5 (check citation count, no placeholders, format)
2. Manually fact-checks against original sources (spot-check key claims)
3. Runs `domain.validate` command if configured in config.yaml
4. Runs `domain.format_check` command if configured in config.yaml
5. Reviews for consistency (no internal contradictions)
6. Verifies sources are recent and authoritative

**Passing condition:** All machine checks pass AND spot-checked facts are accurate AND no placeholder text remains.

### Post-Implementation Review (Step 10)

Same review personas as step 7:
- **Methodology:** Does the approach make sense? Should anything be done differently?
- **Completeness:** Are all spec requirements addressed?
- **Bias:** Is the output balanced?

Plus any extra reviews from `config.yaml` → `domain.review_personas`.

---

## Analysis Domain Details

For `runner.domain: analysis`:

Similar to research, but with emphasis on data integrity, calculation verification, and cross-referencing.

### Pre-flight Check (Step 1)

**What to do:**
1. Skip build/test/lint commands
2. Instead, verify:
   - Input data files exist and are readable (CSV, JSON, Excel, databases)
   - Data format is valid (parsing doesn't fail)
   - Tools available: Python + required libraries (pandas, numpy, etc.), or database client tools
   - Prior analyses exist (check `output/` for prior work to preserve)
   - Git working tree is clean

**Example pre-flight checklist:**
```
✓ Git working tree clean
✓ Input data accessible: data/transactions.csv (500MB, parseable)
✓ Python 3.8+ with pandas, numpy available
✓ Database credentials configured (if using DB sources)
✓ Prior output preserved: output/SPEC-XXX-v1/ exists
✓ Pandas CSV parser can read input without errors
```

### Validation Criteria (Step 4)

The agent writes a validation plan for data processing and calculations.

**Template:**
```markdown
## Validation Plan for SPEC-XXX

### 1. Data Integrity Check
- Input data fully loaded (no parse errors, missing files, or data corruption)
- Row/column counts match expected ranges
- Data types correct (dates are dates, numbers are numeric)
- No unexpected nulls or anomalies

### 2. Calculation Verification
- [ ] All formulas verified: sum(line_items) == total
- [ ] Rounding consistent across all calculations
- [ ] Intermediate results cross-referenced (same number should appear consistently)
- [ ] Edge cases handled (zero values, negative numbers, etc.)

### 3. Cross-Reference Checks
- Summary totals match detail totals
- Period-by-period numbers reconcile to cumulative
- All referenced line items exist and are accounted for
- No double-counting or missing items

### 4. Output Format Compliance
- Output format matches spec (JSON/CSV/YAML/Excel/Markdown)
- Headers and labels present and clear
- Numbers formatted consistently (decimal places, thousands separator)
- Dates in specified format

### 5. Machine-Checkable Validations
- CSV structure: assert all rows have same column count
- Total reconciliation: assert sum(details) == summary
- Date ordering: assert dates are sequential
- Numeric ranges: assert all percentages 0-100, etc.
```

### Acceptance Checks (Step 5)

The agent writes:
- Python script that verifies calculations, cross-references, and format
- Checklist of manual validations (does the data pass a sanity check? Are anomalies explainable?)
- Commit: `check(SPEC-XXX): add validation criteria`

**Example validation script:**
```python
# validate_SPEC-XXX.py
import pandas as pd

def validate_input():
    """Verify input data loads without errors."""
    df = pd.read_csv('data/transactions.csv')
    assert len(df) > 0, "Input data is empty"
    assert df['amount'].dtype in ['float64', 'int64'], "Amount column not numeric"
    return df

def validate_calculations(df):
    """Verify totals reconcile."""
    summary = df.groupby('category')['amount'].sum()
    detail = df['amount'].sum()
    assert abs(summary.sum() - detail) < 0.01, "Summary doesn't reconcile to detail"

def validate_output():
    """Verify output format and structure."""
    import json
    with open('output/SPEC-XXX/analysis.json') as f:
        out = json.load(f)
    assert 'summary' in out, "Output missing summary"
    assert 'detail' in out, "Output missing detail"
    assert len(out['detail']) > 0, "Detail section is empty"

if __name__ == '__main__':
    df = validate_input()
    validate_calculations(df)
    validate_output()
    print("✓ All validations passed")
```

### Implementation Planning (Step 6)

The agent plans the analysis pipeline:

**What to include:**
- Data source and loading strategy
- Transformations and calculations needed
- Output structure and format
- Any aggregations or pivots
- Risk mitigation (what if data has anomalies? Fallback approaches?)

**Example plan:**
```markdown
## Analysis Approach for SPEC-XXX

### Phase 1: Data Loading (Est. 10 min)
- Load transactions from data/transactions.csv
- Validate row count and schema
- Check for duplicates or data quality issues

### Phase 2: Processing & Calculations (Est. 20 min)
- Group by category and time period
- Calculate totals, averages, and percentages
- Identify outliers or anomalies
- Cross-reference with prior period data

### Phase 3: Output Generation (Est. 15 min)
- Generate summary statistics table
- Build detailed transaction export
- Create CSV and JSON output formats
- Validate totals reconcile

### Risk Mitigation
- Missing data: use forward-fill if time-series, drop if sparse
- Outliers: flag any transactions > 2 std dev from mean
- Duplicates: merge by ID, report any discrepancies
```

### Plan Review (Step 7)

**Review personas for analysis:**

| Persona | Owns | Reviews Against |
|---------|------|-----------------|
| **Methodology** | Analysis techniques, statistical methods, data pipeline design | Is the approach sound? Are calculations correct? Is the pipeline robust? |
| **Accuracy** | Source data, calculation formulas, cross-references | Are calculations correct? Do totals reconcile? Are any assumptions questionable? |
| **Completeness** | Spec requirements, output template | Does the output answer all questions in the spec? Any missing sections or data? |

### Implementation (Step 8)

The agent:
1. Loads data and validates schema/row counts
2. Applies transformations step-by-step
3. Generates calculations and validates intermediate results
4. Writes output in specified format
5. Runs validation checks after each major phase
6. Commits incrementally: `feat(SPEC-XXX): load and validate input data` → `feat(SPEC-XXX): calculate summaries` → etc.

### Validation (Step 9)

The agent:
1. Runs the validation script (totals reconcile, calculations correct, format valid)
2. Spot-checks calculations manually (pick a few rows, verify math by hand)
3. Runs `domain.validate` command if configured
4. Runs `domain.format_check` command if configured
5. Verifies cross-references (summary matches detail)

**Passing condition:** All machine checks pass AND spot-checked calculations are correct AND all totals reconcile.

### Post-Implementation Review (Step 10)

Same review personas as step 7:
- **Methodology:** Is the approach sound? Are there better ways to do this?
- **Accuracy:** Are the numbers correct? Do totals reconcile?
- **Completeness:** Does the output answer all spec requirements?

---

## Universal Steps (Same Across All Domains)

These steps work identically for code, research, and analysis domains:

- **Step 2: Task Selection** — Same algorithm, regardless of domain
- **Step 3: Context Loading** — Load domain-specific context (code, sources, data)
- **Step 8.5: Status Check** — Same checkpoint structure
- **Step 9.5: Completion Verification** — Same final verification
- **Step 11: Capture TODOs** — Same knowledge capture process
- **Step 12: Commit + Knowledge** — Same git and knowledge-file workflow
- **Steps 13-16: Loop Control** — Same end-of-loop logic

---

## Configuration Reference

When using non-code domains, consult `config.yaml` → `domain:` section for:

```yaml
domain:
  validate: ""                    # Validation command (exit 0 on success)
  format_check: ""                # Format check command
  output_dir: "output/"           # Where deliverables go
  output_format: "markdown"       # Expected output format
  require_sources: true           # For research: require citations
  min_sources: 3                  # Minimum distinct sources (research)
  review_personas:                # Override review personas for this domain
    - methodology
    - accuracy
    - completeness
    - bias
```

If any of these fields are blank or not configured, the loop uses sensible defaults.

---

## Summary

The 16-step loop is a universal skeleton:
1. **Pre-flight** → Verify you're ready to work (no green baseline = failure)
2. **Task Selection** → Pick a spec
3. **Context Loading** → Gather everything you'll need
4. **Test/Validation Planning** → Define what "done" means
5. **Test/Acceptance Writing** → Write checkable criteria
6. **Implementation Planning** → Plan your approach
7. **Plan Review** → Review the plan with domain-specific personas
8. **Implementation** → Do the work
9. **Validation** → Verify against the criteria from step 4-5
10. **Post-Impl Review** → Review the result with domain-specific personas
11-16. **Wrap-up** → Capture knowledge, commit, loop

The domain mapping tells you what each step means in context. Read it once at the start, refer back as needed during loop execution.
