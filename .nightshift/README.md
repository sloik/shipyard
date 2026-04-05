# Nightshift Kit — Canonical Copy

This is the clean, project-agnostic version of the Nightshift Kit autonomous dev loop.
Copy this entire folder into any project as `.nightshift/` to bootstrap autonomous development.

## Quick Start

```bash
# 1. Copy into your project
cp -r canonical/ /path/to/your-project/.nightshift/

# 2. Point your agent at BOOTSTRAP.md
claude --dangerously-skip-permissions ".nightshift/BOOTSTRAP.md"

# 3. The agent will:
#    - Scan your project for stack indicators
#    - Ask you to confirm/correct its findings
#    - Fill in config.yaml interactively
#    - Audit tooling, write initial specs
#    - Enter the loop
```

## What's Included

| File | Purpose |
|------|---------|
| `BOOTSTRAP.md` | Entry point — auto-discovery, interactive config, tooling audit |
| `LOOP.md` | The 16-step autonomous dev loop (the core protocol) |
| `ORCHESTRATOR.md` | Multi-spec orchestration via sub-agents |
| `REVIEW.md` | 6-persona review protocol (architect, security, performance, domain, quality, user) |
| `HUMAN-REVIEW.md` | Guide for human review of overnight runs |
| `WATCHER.md` | Parallel review agent (optional) |
| `LOOP-DOMAIN-MAP.md` | Adaptations for research and analysis domains |
| `SPEC-GUIDE.md` | How to write good specs |
| `config.yaml` | Template — filled in during bootstrap |
| `.gitignore` | Excludes ephemeral files, keeps protocol + specs + knowledge |
| `specs/_TEMPLATE.md` | Spec template (code) |
| `specs/_TEMPLATE-ANALYSIS.md` | Spec template (analysis domain) |
| `specs/_TEMPLATE-RESEARCH.md` | Spec template (research domain) |

## What's NOT Included

This canonical copy contains only the protocol files and templates. Project-specific
content that gets created during use (and should NOT be in canonical):

- `knowledge/` entries — learned patterns, accumulated per project
- `specs/SPEC-*.md` — actual specs (you write these)
- `metrics/*.yaml` — per-run telemetry
- `reports/*.md` — nightshift run reports
- Python tooling (`analyze_metrics.py`, `graph_engine.py`, etc.) — optional, lives in mature installations

## Updating

When the protocol evolves (new LOOP.md version, new config options), update this
canonical copy. Existing project installations can pull changes from here.

Source of truth: `Argo/ManagedProjects/Nightshift/canonical/`
