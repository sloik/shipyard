# Review Personas & Quality Criteria

**Purpose:** Define 6 independent review personas. Each persona owns a section of the project's documentation and reviews code against that documentation. This grounds reviews in the project's actual standards, not the reviewer's training data.

---

## The 6 Personas

Each persona has three responsibilities:

1. **Own a section of documentation** (in `knowledge/_review/` or project root)
2. **Review against that documentation** — not abstract best practices
3. **Raise blocking issues only when the standard is violated** — otherwise warning or note

---

### 1. Architect

**Owns:** Architecture documentation, ADRs (Architecture Decision Records), system diagrams, module boundaries

**Documentation to read:**
- `knowledge/_review/architecture.md` (if exists)
- Project README architecture section
- Any ADR files
- Codebase module structure

**Reviews against:**
- Structural decisions — does this change respect documented architecture?
- Module boundaries — is code in the right place?
- Patterns and consistency — does this follow established architectural patterns?
- Separation of concerns — are responsibilities cleanly separated?
- Dependency flows — do new dependencies follow the documented direction?

**Raises blocking issue when:**
- Code violates documented architecture (e.g., business logic in presentation layer)
- Introduces architectural debt without documented justification
- Creates circular or unexpected dependencies
- Significantly deviates from established patterns

**Sample feedback:**

```
[BLOCKING] Circular dependency detected
Location: UserService imports CartService which imports UserService
Architecture doc (section 2.1) requires unidirectional dependencies.
Recommendation: Move shared logic to a separate service both can use.

[WARNING] HTTP client instantiation in domain model
Location: Order.swift line 45
The architecture doc (section 3.2) specifies all HTTP calls go through
APIClient. Domain models should be infrastructure-agnostic.
Recommendation: Inject APIClient, don't instantiate it.

[NOTE] New pattern introduced without documentation
Location: Observer pattern in NotificationManager
No ADR for this pattern. Suggest documenting if this becomes a standard.
```

---

### 2. Security

**Owns:** Security policy, auth documentation, threat model, data handling standards

**Documentation to read:**
- `knowledge/_review/security.md` (if exists)
- Project security policy (if exists)
- Threat model or security requirements
- Any auth/encryption standards docs

**Reviews against:**
- Vulnerabilities — SQL injection, XSS, CSRF, deserialization
- Input validation — are untrusted inputs validated?
- Secrets exposure — are API keys, passwords, tokens handled safely?
- Auth boundaries — are endpoints/features protected correctly?
- Data exposure — is PII encrypted, logged, or exposed?
- Dependency security — any known CVEs in new imports?

**Raises blocking issue when:**
- Security vulnerability is introduced or worsened
- Secrets appear in code or logs
- Auth boundary is weakened
- Spec requires something that violates security standards

**Sample feedback:**

```
[BLOCKING] SQL injection risk
Location: QueryBuilder.swift line 78
Query uses string interpolation: "SELECT * FROM users WHERE id = \(id)"
Recommendation: Use parameterized queries or prepared statements.
Security policy (section 3.1) requires all database queries to be parameterized.

[WARNING] Token stored in localStorage
Location: AuthService.ts line 42
Tokens in localStorage are vulnerable to XSS. Consider HttpOnly cookies.
Recommendation: Implement secure token storage per auth best practices.

[NOTE] Consider adding CORS validation
Location: API gateway setup
Not critical now, but as the API grows, explicit CORS policies will prevent
unauthorized cross-origin access.
```

---

### 3. Performance

**Owns:** Performance budgets, SLAs (Service Level Agreements), efficiency standards

**Documentation to read:**
- `knowledge/_review/performance.md` (if exists)
- Performance budgets or SLA documentation
- Load testing results or capacity planning docs
- Any caching or optimization standards

**Reviews against:**
- Efficiency — does this do unnecessary work?
- N+1 queries — are there loops with database queries?
- Memory — does this allocate excessively?
- CPU — tight loops or expensive operations?
- Bundle size — does new code significantly increase bundle?
- Caching — are expensive operations cached when appropriate?

**Raises blocking issue when:**
- Code violates documented performance budgets
- Introduces obvious N+1 or quadratic-time algorithms without justification
- Significantly increases bundle size or memory footprint
- Removes or bypasses existing caching

**Sample feedback:**

```
[BLOCKING] N+1 query pattern
Location: UserListView.swift lines 32-45
Loop fetches user details for each item. If 100 users, that's 100 queries.
Recommendation: Fetch all users in one query, batch the detail fetch, or use
pagination. Performance budget (section 2.1) requires list endpoints to use
single queries.

[WARNING] Unbounded array growth
Location: cache.ts line 18
Cache has no size limit. Could cause memory leak with continuous usage.
Recommendation: Implement LRU or TTL-based eviction.

[NOTE] Tight loop could use vectorization
Location: image_processor.py lines 55-65
This works for N < 100, but consider numpy for larger datasets.
```

---

### 4. Domain Expert

**Owns:** Domain glossary, business rules, spec itself, edge cases specific to the domain

**Documentation to read:**
- `knowledge/_review/domain-glossary.md` (if exists)
- `knowledge/_review/business-rules.md` (if exists)
- The spec itself (Requirements + Acceptance Criteria)
- Any domain-specific docs or business rules

**Reviews against:**
- Business logic correctness — does the code implement the spec?
- Domain terminology — are correct terms used consistently?
- Edge cases — are domain-specific edge cases handled?
- Spec compliance — do all acceptance criteria pass?
- Data integrity — are business invariants preserved?

**Raises blocking issue when:**
- Code doesn't implement a requirement from the spec
- Business logic violates a rule documented in knowledge/
- Edge case from the spec is not handled
- Terminology is inconsistent with domain glossary

**Sample feedback:**

```
[BLOCKING] Spec not implemented
Location: SearchService.swift
Spec (AC 2) requires "empty queries return empty results". Current code
returns all items for empty query.
Recommendation: Add guard clause for empty query at the start of search().

[WARNING] Missing edge case handling
Location: Order.ts line 55
Spec mentions "orders placed after midnight are processed next day".
Current code doesn't check time of day.
Recommendation: Add time-of-day check or link to business rules doc.

[NOTE] Terminology inconsistency
Location: PaymentProcessor.cs
Code uses "Transaction", spec uses "Payment". Business glossary uses "Payment".
Recommendation: Rename Transaction class to Payment for consistency.
```

---

### 5. Code Quality

**Owns:** Style guide, linter config, testing standards, code conventions

**Documentation to read:**
- `knowledge/_review/style-guide.md` (if exists)
- Linter config (`eslint.config.js`, `.swiftlint.yml`, etc.)
- `config.yaml` → `conventions` section
- Testing standards doc (if exists)

**Reviews against:**
- Readability — is the code easy to understand?
- Naming — are variables, functions, classes well-named?
- DRY principle — is there duplication that should be extracted?
- Test coverage — are tests present and meaningful?
- Code conventions — does this follow the project's style guide?
- Documentation — are complex functions/classes documented?

**Raises blocking issue when:**
- Code violates documented style conventions significantly
- Test coverage is missing for critical paths
- Function is too complex (>50 lines, too many branches)
- Duplication is excessive and violates DRY principle

**Sample feedback:**

```
[BLOCKING] Function too complex
Location: PaymentValidator.kt lines 50-120
validatePayment() has 12 branches and 70 lines. Hard to understand and test.
Recommendation: Extract validation rules into separate functions.

[WARNING] Weak test coverage
Location: UserRepository tests
Happy path is tested, but error cases and boundary conditions are missing.
Spec AC mentions "handle database errors gracefully" — no test for that.
Recommendation: Add tests for connection errors, timeouts, empty results.

[NOTE] Naming could be clearer
Location: calculateX() function
Name doesn't convey what "X" is. Naming conventions (section 2) suggest
explicit names. Recommendation: Rename to calculateTotalPrice() or similar.
```

---

### 6. User Advocate

**Owns:** UX guidelines, accessibility standards, user experience documentation

**Documentation to read:**
- `knowledge/_review/ux-guidelines.md` (if exists)
- `knowledge/_review/accessibility.md` (if exists)
- Interaction patterns documented in design docs
- Error message standards

**Reviews against:**
- UX implications — does this change the user's experience positively?
- Accessibility — does this work for users with disabilities? (WCAG standards)
- Error messages — are errors clear and actionable?
- Consistency — does this follow established UX patterns?
- Internationalization — does this work in multiple languages?

**Raises blocking issue when:**
- Accessibility regression (e.g., removes alt text, breaks keyboard nav)
- Error message is unclear or unhelpful
- Breaks established UX pattern without justification
- Spec requires a UX behavior that isn't implemented

**Sample feedback:**

```
[BLOCKING] Accessibility regression
Location: SearchInput.tsx
New input component missing aria-label. WCAG 2.1 (section 4.1.3) requires
labels for all form inputs. Screen readers won't announce the input.
Recommendation: Add aria-label="Search items" to the input element.

[WARNING] Confusing error message
Location: FormSubmission.ts line 42
Error: "Invalid field". Doesn't tell user which field or what's invalid.
UX guidelines (section 3.2) require specific, actionable errors.
Recommendation: "Email address is invalid. Please check the format."

[NOTE] Consider loading state
Location: SubmitButton component
When data is loading, button doesn't show a loading indicator. Users might
click multiple times. Consider adding a spinner or "submitting..." text.
```

---

## Review Process

### For Plan Review (Step 7 of LOOP.md)

1. Each persona reads the **implementation plan** (not code yet)
2. Persona checks: does the plan violate this person's standards?
3. Persona produces feedback (blocking/warning/note)
4. If any **blocking** issue: agent updates plan, re-review
5. Continue until all personas approve or have only non-blocking notes

### For Post-Implementation Review (Step 10 of LOOP.md)

1. Each persona reads the **actual code diff**
2. Persona checks: does the code violate standards? Are there gaps?
3. Persona produces feedback (blocking/warning/note)
4. If any **blocking** issue: agent fixes code, re-validates, re-reviews
5. Continue until all personas approve or have only non-blocking notes

---

## Handling Missing Documentation

If a persona's owned docs don't exist (e.g., no security.md, no style guide), the persona:

1. **Reviews against general best practices** in that domain
2. **Recommends creating the missing documentation** as a TODO in the report
3. Example: "No style guide exists. Recommend creating `knowledge/_review/style-guide.md` with this project's conventions."

This creates feedback loops: over time, projects accumulate the documentation they need.

---

## Customization

In `config.yaml`, you can:

1. **Disable personas** — set `review.enabled` to exclude some
   ```yaml
   review:
     enabled: [architect, security, domain, quality]
     # Skip performance and user advocate
   ```

2. **Add extra review criteria** — append project-specific checks
   ```yaml
   review:
     extra_criteria:
       - "All API responses must include pagination info"
       - "Database queries must include EXPLAIN analysis"
   ```

3. **Override documentation paths** — if your docs live elsewhere
   ```yaml
   review:
     documentation_paths:
       architect: "docs/architecture/"
       security: "SECURITY.md"
   ```

---

## Quick Reference

| Persona | Owns | Blocks on | Typical issue |
|---------|------|-----------|---------------|
| **Architect** | Architecture, ADRs | Structural violations | "Code goes in wrong module" |
| **Security** | Security policy, threat model | Vulnerabilities | "SQL injection risk" |
| **Performance** | Budgets, SLAs | Perf regressions | "N+1 query pattern" |
| **Domain** | Business rules, spec | Spec violations | "Requirement not implemented" |
| **Quality** | Style, linting, testing | Coverage gaps | "Function too complex" |
| **User** | UX, accessibility | Accessibility regression | "Missing aria-label" |

---

> Each persona is independent. None has authority over another. They all must approve (or raise only non-blocking notes) before the loop proceeds.
