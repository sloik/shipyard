---
id: SPEC-026-006
priority: 4
layer: 3
type: feature
status: done
after: [SPEC-026-004]
parent: SPEC-026
nfrs: [NFR-003]
prior_attempts: []
created: 2026-03-31
---

# GitHub Issue to Spec Intake

## Problem

When Shipyard goes public, bug reports and feature requests will come in as GitHub issues. These issues need to be structured enough to convert into Nightshift specs without extensive back-and-forth. GitHub issue templates can enforce this structure at submission time, making the spec-driven workflow accessible to external contributors.

## Requirements

- [ ] Create GitHub issue template for bug reports (maps to BUGFIX spec type)
- [ ] Create GitHub issue template for feature requests (maps to FEATURE spec type)
- [ ] Create GitHub issue template for non-functional concerns (maps to NFR type)
- [ ] Templates include fields that map to spec sections: Problem, Expected Behavior, Steps to Reproduce (bugs), Requirements (features), Acceptance Criteria
- [ ] Add `.github/ISSUE_TEMPLATE/config.yml` to configure template chooser
- [ ] Add brief guide in template comments explaining what each field is for
- [ ] Include labels auto-assignment in templates (bug, enhancement, nfr)

## Acceptance Criteria

- [ ] AC 1: `.github/ISSUE_TEMPLATE/bug_report.yml` exists and renders correctly on GitHub
- [ ] AC 2: `.github/ISSUE_TEMPLATE/feature_request.yml` exists and renders correctly on GitHub
- [ ] AC 3: `.github/ISSUE_TEMPLATE/nfr.yml` exists and renders correctly on GitHub
- [ ] AC 4: Bug template includes: description, steps to reproduce, expected vs actual behavior, environment info, log output
- [ ] AC 5: Feature template includes: problem statement, proposed solution, requirements (checkbox list), alternatives considered
- [ ] AC 6: A well-filled bug report can be converted to a BUGFIX spec by copying fields with minimal editing
- [ ] AC 7: Template chooser (`config.yml`) shows all three templates with descriptions

## Context

- GitHub issue templates use YAML format (`.yml` extension) in `.github/ISSUE_TEMPLATE/`
- Templates can define form fields: input, textarea, dropdown, checkboxes
- The conversion from issue to spec is manual (maintainer creates spec from issue) — this spec just ensures the input is structured
- Nightshift spec sections to map: Problem → issue description, Requirements → proposed requirements, AC → from expected behavior

## Scenarios

1. User finds a bug → clicks "New Issue" → sees template chooser → selects "Bug Report" → fills structured form → submits → maintainer reads it → creates BUGFIX spec with minimal editing
2. User wants a feature → selects "Feature Request" → fills problem, proposed solution, requirements → submits → maintainer evaluates → creates FEATURE spec or closes with explanation
3. User reports a performance concern → selects "Non-Functional Concern" → describes the constraint → maintainer evaluates → creates NFR or links to existing one

## Out of Scope

- Automated issue-to-spec conversion (future automation)
- GitHub Actions that auto-create spec files from issues
- Issue triage automation
- PR templates (could be added but not part of this spec)

## Notes for the Agent

- Use GitHub's YAML-based issue form syntax (not the older Markdown template format)
- Study GitHub's issue template documentation for current best practices
- Keep templates concise — too many required fields discourages reporting
- The bug template should have a "Shipyard version" and "macOS version" field
