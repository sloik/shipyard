#!/usr/bin/env bash
# verify-spec-033.sh — Verifies the SPEC-BUG-033 resize handle drag fix (Attempt 2).
#
# Checks that style.flexBasis is used (not style.height) for toolResponseSection,
# that getBoundingClientRect and toolResizeDragging are still present, and that
# the full test suite passes.
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
echo "SPEC-BUG-033 Verification (Attempt 2 — flexBasis fix)"
echo "======================================================"
echo ""
echo "HTML: $HTML"
echo ""

echo "── JS correctness checks ─────────────────────────────────────────────────"
echo ""

# AC 1 + AC 3: toolResponseSection.style.flexBasis appears at least 3 times
count=$(grep -cF 'toolResponseSection.style.flexBasis' "$HTML" || true)
if [[ "$count" -ge 3 ]]; then
  check "toolResponseSection.style.flexBasis appears at least 3 times" "pass"
else
  check "toolResponseSection.style.flexBasis appears at least 3 times" "fail" \
    "Found $count occurrence(s) — expected at least 3 (IIFE, mousemove, window resize)"
fi

# AC 2: No toolResponseSection.style.height assignments remain
height_count=$(grep -cE 'toolResponseSection\.style\.height[[:space:]]*=' "$HTML" || true)
if [[ "$height_count" -eq 0 ]]; then
  check "No toolResponseSection.style.height assignments remain" "pass"
else
  check "No toolResponseSection.style.height assignments remain" "fail" \
    "Found $height_count assignment(s) — all must be replaced with style.flexBasis"
fi

# AC 4: getBoundingClientRect still appears at least 2 times
brc_count=$(grep -cF 'getBoundingClientRect' "$HTML" || true)
if [[ "$brc_count" -ge 2 ]]; then
  check "getBoundingClientRect appears at least 2 times (mousemove + window resize)" "pass"
else
  check "getBoundingClientRect appears at least 2 times (mousemove + window resize)" "fail" \
    "Found $brc_count occurrence(s) — expected at least 2"
fi

# AC 4: toolResizeDragging still present in mousemove handler
if grep -qF 'toolResizeDragging' "$HTML"; then
  check "toolResizeDragging still present" "pass"
else
  check "toolResizeDragging still present" "fail" \
    "toolResizeDragging not found — handler may have been removed"
fi

# AC 5: window resize listener still exists
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
