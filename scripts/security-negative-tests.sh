#!/usr/bin/env bash
# Runs controlled scanner-result probes without network or advisory access.
set -euo pipefail

make_cmd=${1:?make command required}
repo_root=${2:?repository root required}
fixture_root="$repo_root/test/security-fixtures/scanner-probes"

expect_failure() {
  local name=$1
  shift
  if "$@"; then
    printf '%s probe unexpectedly passed\n' "$name" >&2
    exit 1
  fi
  printf '%s controlled known-bad probe rejected as expected\n' "$name"
}

expect_failure govulncheck \
  "$make_cmd" -C "$repo_root" --no-print-directory security-govulncheck \
  GOVULNCHECK="$fixture_root/govulncheck"
expect_failure gosec \
  "$make_cmd" -C "$repo_root" --no-print-directory security-gosec \
  GOSEC="$fixture_root/gosec"
