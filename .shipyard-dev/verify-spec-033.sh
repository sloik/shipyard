#!/usr/bin/env bash
# verify-spec-033.sh — Verifies the SPEC-BUG-033 resize handle drag fix before merge.
#
# Checks that getBoundingClientRect is used instead of offsetHeight in both the
# mousemove and window resize handlers, that the IIFE does not clamp against
# offsetHeight, and that the full test suite passes.
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

echo ""
echo "SPEC-BUG-033 Verification"
echo "========================="
echo ""
echo "HTML: $HTML"
echo ""

echo "── JS correctness checks ─────────────────────────────────────────────────"
echo ""

# AC 3: getBoundingClientRect appears at least twice (mousemove + window resize)
count=$(grep -cF 'getBoundingClientRect' "$HTML" || true)
if [[ "$count" -ge 2 ]]; then
  check "getBoundingClientRect appears at least 2 times (mousemove + window resize)" "pass"
else
  check "getBoundingClientRect appears at least 2 times (mousemove + window resize)" "fail" \
    "Found $count occurrence(s) — expected at least 2"
fi

# AC 4: IIFE does NOT call toolDetail.offsetHeight
# Extract the IIFE block between the localStorage.getItem call and the closing })()
# and assert toolDetail.offsetHeight is absent from it
iife_block=$(awk "/localStorage.getItem\('shipyard_tool_response_height'\)/{found=1} found{print} /\}\)\(\);/{if(found) exit}" "$HTML")
if echo "$iife_block" | grep -qF 'toolDetail.offsetHeight'; then
  check "IIFE does NOT use toolDetail.offsetHeight (no clamping at init)" "fail" \
    "Found toolDetail.offsetHeight in the IIFE block — will produce corrupt height when element is hidden"
else
  check "IIFE does NOT use toolDetail.offsetHeight (no clamping at init)" "pass"
fi

# AC 3 (sanity): mousemove handler still uses toolResizeDragging
if grep -qF 'toolResizeDragging' "$HTML"; then
  check "mousemove handler still uses toolResizeDragging" "pass"
else
  check "mousemove handler still uses toolResizeDragging" "fail" \
    "toolResizeDragging not found — handler may have been removed"
fi

# AC: window resize listener still exists
if grep -qF "window.addEventListener('resize'" "$HTML"; then
  check "window.addEventListener('resize' still exists" "pass"
else
  check "window.addEventListener('resize' still exists" "fail" \
    "window resize listener not found"
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
