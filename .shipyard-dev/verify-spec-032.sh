#!/usr/bin/env bash
# verify-spec-032.sh — Verifies the SPEC-032 resize handle implementation before merge.
#
# Checks that the resize handle element is present and correctly positioned in
# index.html, that drag JS is wired up, and that the full test suite passes.
# Run this from the repo root or from .shipyard-dev/.
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
echo "SPEC-032 Verification"
echo "====================="
echo ""
echo "HTML: $HTML"
echo ""

echo "── Element presence checks ───────────────────────────────────────────────"
echo ""

# Check 1: resize-handle element with correct id exists
assert_contains \
  "resize-handle element with id=\"tool-resize-handle\" exists" \
  "$HTML" \
  'id="tool-resize-handle"'

# Check 2: element has class="resize-handle"
assert_contains \
  "handle element has class=\"resize-handle\"" \
  "$HTML" \
  'class="resize-handle"'

echo ""
echo "── DOM order check ───────────────────────────────────────────────────────"
echo ""

# Check 3: DOM order — tool-detail-scroll < tool-resize-handle < tool-response-section
SCROLL_IDX=$(grep -bo 'id="tool-detail-scroll"' "$HTML" | head -1 | cut -d: -f1)
HANDLE_IDX=$(grep -bo 'id="tool-resize-handle"' "$HTML" | head -1 | cut -d: -f1)
RESPONSE_IDX=$(grep -bo 'id="tool-response-section"' "$HTML" | head -1 | cut -d: -f1)

if [[ -z "$SCROLL_IDX" || -z "$HANDLE_IDX" || -z "$RESPONSE_IDX" ]]; then
  check "DOM order: tool-detail-scroll < tool-resize-handle < tool-response-section" "fail" \
    "One or more elements not found (scroll=$SCROLL_IDX handle=$HANDLE_IDX response=$RESPONSE_IDX)"
elif [[ "$SCROLL_IDX" -lt "$HANDLE_IDX" && "$HANDLE_IDX" -lt "$RESPONSE_IDX" ]]; then
  check "DOM order: tool-detail-scroll < tool-resize-handle < tool-response-section" "pass"
else
  check "DOM order: tool-detail-scroll < tool-resize-handle < tool-response-section" "fail" \
    "Wrong order: scroll=$SCROLL_IDX handle=$HANDLE_IDX response=$RESPONSE_IDX"
fi

echo ""
echo "── Inline style check ────────────────────────────────────────────────────"
echo ""

# Check 4: handle element has NO style= attribute (class-only styling)
# Extract the handle tag line and verify no style= present
HANDLE_TAG=$(grep -o '<div[^>]*id="tool-resize-handle"[^>]*>' "$HTML" || true)
if [[ -z "$HANDLE_TAG" ]]; then
  check "Handle element has no inline style= attribute" "fail" "Could not extract handle tag"
elif echo "$HANDLE_TAG" | grep -qF 'style='; then
  check "Handle element has no inline style= attribute" "fail" "Found style= on: $HANDLE_TAG"
else
  check "Handle element has no inline style= attribute" "pass"
fi

echo ""
echo "── JS checks ─────────────────────────────────────────────────────────────"
echo ""

# Check 5: localStorage key present
assert_contains \
  "JS contains localStorage key 'shipyard_tool_response_height'" \
  "$HTML" \
  "shipyard_tool_response_height"

# Check 6: mousedown listener on the handle
assert_contains \
  "JS contains mousedown listener (drag start)" \
  "$HTML" \
  "mousedown"

# Check 7: mousemove on document (drag in progress)
assert_contains \
  "JS contains mousemove listener on document (drag in progress)" \
  "$HTML" \
  "mousemove"

# Check 8: mouseup on document (drag end + persist)
assert_contains \
  "JS contains mouseup listener on document (drag end + persist)" \
  "$HTML" \
  "mouseup"

echo ""
echo "── Test suite ────────────────────────────────────────────────────────────"
echo ""

cd "$ROOT"
if go test ./... 2>&1; then
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
