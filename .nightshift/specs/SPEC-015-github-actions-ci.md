---
id: SPEC-015
priority: 15
type: nfr
status: done
after: [SPEC-014]
created: 2026-04-06
---

# GitHub Actions CI — Test & Release Pipeline

## Problem

No CI pipeline exists. Tests only run locally. Releases must be done manually. There is no automated gate preventing broken code from reaching v2/main.

## Goal

Set up GitHub Actions for continuous integration (test on push/PR) and continuous delivery (release on tag via GoReleaser).

## Key Changes

### 1. `.github/workflows/ci.yml` — Test Pipeline

Triggers: push to `v2/main`, all PRs targeting `v2/main`

```yaml
name: CI

on:
  push:
    branches: [v2/main]
  pull_request:
    branches: [v2/main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
      - run: go vet ./...
      - run: go test -race -count=1 ./...
      - run: go build ./cmd/shipyard/
```

### 2. `.github/workflows/release.yml` — Release Pipeline

Triggers: push of version tags (`v*`)

```yaml
name: Release

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
      - uses: goreleaser/goreleaser-action@v6
        with:
          version: "~> v2"
          args: release --clean
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 3. Badge in README

Add CI status badge to README.md hero section:
```markdown
[![CI](https://github.com/sloik/shipyard/actions/workflows/ci.yml/badge.svg)](https://github.com/sloik/shipyard/actions/workflows/ci.yml)
```

## Acceptance Criteria

- [ ] AC-1: `.github/workflows/ci.yml` exists and runs on push/PR to v2/main
- [ ] AC-2: CI runs `go vet`, `go test -race`, and `go build`
- [ ] AC-3: `.github/workflows/release.yml` exists and triggers on version tags
- [ ] AC-4: Release workflow uses goreleaser-action to produce cross-platform binaries
- [ ] AC-5: README includes CI status badge

## Out of Scope

- Code coverage reporting
- Dependency scanning (Dependabot)
- Container image builds in CI
- Branch protection rules (manual GitHub config)

## Notes for Implementation

- Use `go test -race` in CI to catch data races (we use goroutines extensively)
- `fetch-depth: 0` is required for goreleaser changelog generation
- `GITHUB_TOKEN` is automatically available in GitHub Actions — no manual secret needed
- Test locally with `act` if available, otherwise just push and iterate

## Target Files

- `.github/workflows/ci.yml` (new)
- `.github/workflows/release.yml` (new)
- `README.md` (badge addition — depends on SPEC-013)
