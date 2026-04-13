#!/usr/bin/env bash
# verify-bug-031.sh — Verifies the SPEC-BUG-031 response-section scroll fix before merge.
#
# Checks that the correct flex basis is set on #tool-response-section in index.html
# and that the full test suite passes. Run this from the repo root or from .shipyard-dev/.
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
echo "SPEC-BUG-031 Verification"
echo "========================="
echo ""
echo "HTML: $HTML"
echo ""

echo "── Flex contract checks ──────────────────────────────────────────────────"
echo ""

# AC 4: response section must use flex:0 0 300px
assert_contains \
  "#tool-response-section has flex:0 0 300px" \
  "$HTML" \
  'id="tool-response-section" style="display:flex; flex:0 0 300px;'

# AC 5a: old flex:0 0 auto must be gone
assert_not_contains \
  "#tool-response-section does NOT have flex:0 0 auto (old value)" \
  "$HTML" \
  'id="tool-response-section" style="display:flex; flex:0 0 auto;'

# AC 5b: old min-height:200px must be gone from the response section tag
if grep -oF 'id="tool-response-section"[^>]*>' "$HTML" | grep -qF 'min-height:200px'; then
  check "#tool-response-section does NOT have min-height:200px (superseded by 300px basis)" "fail" \
    "Found min-height:200px on #tool-response-section — should be removed"
else
  check "#tool-response-section does NOT have min-height:200px (superseded by 300px basis)" "pass"
fi

# #tool-response-json must still have overflow:auto (no change required, but validate)
# Extract the line containing the element and check it has overflow:auto
if grep -F 'id="tool-response-json"' "$HTML" | grep -qF 'overflow:auto'; then
  check "#tool-response-json has overflow:auto (JSON body still scrolls)" "pass"
else
  check "#tool-response-json has overflow:auto (JSON body still scrolls)" "fail" \
    "Expected overflow:auto on #tool-response-json inner viewer"
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
