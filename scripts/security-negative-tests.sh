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

offline_output=$(mktemp)
trap 'rm -f "$offline_output"' EXIT
if GOPROXY=off GOSUMDB=off GOVCS='*:off' \
  "$make_cmd" -C "$repo_root" --no-print-directory security-govulncheck-offline-fixture \
  GOVULNCHECK="$repo_root/.tools/bin/govulncheck" >"$offline_output" 2>&1; then
  printf '%s\n' 'govulncheck offline advisory probe unexpectedly passed' >&2
  exit 1
fi
if ! grep -Fq 'GO-SHIPYARD-0001' "$offline_output"; then
  printf '%s\n' 'govulncheck offline advisory probe did not report the locked advisory' >&2
  cat "$offline_output" >&2
  exit 1
fi
printf '%s\n' 'govulncheck locked offline advisory probe rejected as expected'

expect_failure gosec \
  "$make_cmd" -C "$repo_root" --no-print-directory security-gosec \
  GOSEC="$fixture_root/gosec"
