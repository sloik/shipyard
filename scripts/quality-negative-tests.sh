#!/bin/zsh
# Negative fixtures keep static gates honest without weakening production checks.
set -euo pipefail

staticcheck_bin="${1:?staticcheck path required}"
actionlint_bin="${2:?actionlint path required}"
repo_root="${0:A:h:h}"
fixture_root="$repo_root/test/quality-fixtures"

expect_failure() {
	local label="$1"
	shift
	if "$@" >/dev/null 2>&1; then
		print -u2 "expected $label to fail, but it passed"
		exit 1
	fi
	print "$label rejects its controlled invalid fixture"
}

expect_failure "staticcheck" zsh -c "cd '$fixture_root/staticcheck' && '$staticcheck_bin' ./..."
expect_failure "actionlint" "$actionlint_bin" "$fixture_root/invalid-workflow.yml"
expect_failure "JavaScript syntax check" node "$repo_root/scripts/check-js-syntax.mjs" "$fixture_root/invalid.js"
expect_failure "zsh parser" zsh -n "$fixture_root/invalid.zsh"
