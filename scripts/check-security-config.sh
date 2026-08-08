#!/usr/bin/env bash
# Validates repository-owned workflow hardening without contacting GitHub.
set -euo pipefail

root=${1:-.}
cd "$root"

fail() {
  printf 'security configuration error: %s\n' "$*" >&2
  exit 1
}

command -v rg >/dev/null 2>&1 || fail "ripgrep (rg) is required"

# A readable release comment makes a pinned commit auditable; Renovate maintains
# future digest updates through helpers:pinGitHubActionDigests.
if rg --hidden -n '^\s*-\s*uses:\s*[^@[:space:]]+@(?![0-9a-f]{40}\s+#\s+v)' --pcre2 .github/workflows; then
  fail "every workflow uses: reference must be a full SHA with a version comment"
fi

if rg -n 'go install .+@latest' .github/workflows Makefile; then
  fail "go install @latest is forbidden"
fi

if rg -n --glob '*.go' '#nosec' .; then
  fail "no gosec suppressions are currently approved"
fi

rg -q 'helpers:pinGitHubActionDigests' renovate.json || fail "Renovate digest updates are not enabled"
rg -q 'github.com/wailsapp/wails/v3/cmd/wails3@v3.0.0-alpha2.117' .github/workflows/desktop.yml || fail "desktop Wails CLI must match go.mod"

for workflow in .github/workflows/*.yml; do
  rg -q '^permissions:$|^    permissions:$' "$workflow" || fail "$workflow has no explicit permissions"
done

rg -U -q '^permissions:\n  contents: read' .github/workflows/ci.yml || fail "CI default permissions must be contents: read"
rg -U -q '^permissions:\n  contents: read' .github/workflows/desktop.yml || fail "desktop default permissions must be contents: read"
rg -U -q '^permissions:\n  contents: read' .github/workflows/release.yml || fail "release default permissions must be contents: read"
rg -U -q '^    permissions:\n      contents: write' .github/workflows/release.yml || fail "release job must explicitly hold contents: write"

printf 'security configuration check passed\n'
