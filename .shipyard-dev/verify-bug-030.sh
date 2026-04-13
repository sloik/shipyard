#!/usr/bin/env bash
# verify-bug-030.sh — Verifies the SPEC-BUG-030 flex layout fix before merge.
#
# Checks that the correct flex roles are in place in index.html and that
# the full test suite passes. Run this from the repo root or from .shipyard-dev/.
#
# Exit codes: 0 = all checks pass, 1 = one or more checks failed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HTML="$ROOT/internal/web/ui/index.html"

PASS=0
FAIL=0

check() {
  local label="$1"
  local result="$2"   # "pass" or "fail"
  local detail="${3:-}"
  if [[ "$result" == "pass" ]]; then
    echo "  ✅  $label"
    PASS=$((PASS + 1))
  else
    echo "  ❌  $label"
    [[ -n "$detail" ]] && echo "       $detail"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1"
  local file="$2"
  local needle="$3"
  if grep -qF "$needle" "$file"; then
    check "$label" "pass"
  else
    check "$label" "fail" "Expected to find: $needle"
  fi
}

assert_not_contains() {
  local label="$1"
  local file="$2"
  local needle="$3"
  if grep -qF "$needle" "$file"; then
    check "$label" "fail" "Must NOT contain: $needle"
  else
    check "$label" "pass"
  fi
}

echo ""
echo "SPEC-BUG-030 Verification"
echo "========================="
echo ""
echo "HTML: $HTML"
echo ""

echo "── Flex contract checks ──────────────────────────────────────────────────"
echo ""

# AC 5: scroll section must use flex:1 1 0
assert_contains \
  "#tool-detail-scroll has flex:1 1 0" \
  "$HTML" \
  'id="tool-detail-scroll" style="display:flex; flex:1 1 0;'

# Inverse: old broken value must be gone
assert_not_contains \
  "#tool-detail-scroll does NOT have flex:0 1 auto (old broken value)" \
  "$HTML" \
  'id="tool-detail-scroll" style="display:flex; flex:0 1 auto;'

# AC 6: response section must use flex:0 0 auto
assert_contains \
  "#tool-response-section has flex:0 0 auto" \
  "$HTML" \
  'id="tool-response-section" style="display:flex; flex:0 0 auto;'

# AC 6: response section must have min-height:200px
assert_contains \
  "#tool-response-section has min-height:200px" \
  "$HTML" \
  'min-height:200px'

# Inverse: old broken flex:1 must be gone from response section
# Use a pattern that matches the exact broken tag (not "flex:10px" etc.)
if grep -oF 'id="tool-response-section"[^>]*>' "$HTML" | grep -qF 'flex:1;'; then
  check "#tool-response-section does NOT have flex:1 (old broken value)" "fail" \
    "Found flex:1 on #tool-response-section — this collapses response to 0px on long forms"
else
  check "#tool-response-section does NOT have flex:1 (old broken value)" "pass"
fi

# Outer container must NOT have padding directly (padding was moved inward by SPEC-BUG-029)
if grep -oF 'id="tool-detail"[^>]*>' "$HTML" | grep -qF 'padding:'; then
  check "#tool-detail outer container has no direct padding" "fail" \
    "Found padding on #tool-detail — padding should be on inner regions only"
else
  check "#tool-detail outer container has no direct padding" "pass"
fi

echo ""
echo "── Test suite ────────────────────────────────────────────────────────────"
echo ""

cd "$ROOT"
if go test ./... 2>&1 | tail -20; then
  check "go test ./... passes" "pass"
else
  check "go test ./... passes" "fail" "See test output above"
fi

echo ""
echo "── Summary ───────────────────────────────────────────────────────────────"
echo ""
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [[ $FAIL -gt 0 ]]; then
  echo "  RESULT: ❌ FAIL — do not merge"
  exit 1
else
  echo "  RESULT: ✅ PASS — safe to merge"
  exit 0
fi
