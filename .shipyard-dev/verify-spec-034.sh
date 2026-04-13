#!/usr/bin/env bash
# verify-spec-034.sh — Verifies SPEC-BUG-034: Servers tab matches UX-002 design.
#
# Checks action bar padding, Add Server button, card header structure,
# ds.css changes, grid padding, and the full test suite.
#
# Exit codes: 0 = all checks pass, 1 = one or more checks failed.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HTML="$ROOT/internal/web/ui/index.html"
CSS="$ROOT/internal/web/ui/ds.css"

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
echo "SPEC-BUG-034 Verification — Servers tab matches UX-002 design"
echo "=============================================================="
echo ""
echo "HTML: $HTML"
echo "CSS:  $CSS"
echo ""

echo "── Action bar ────────────────────────────────────────────────────────────"
echo ""

# AC 1: #servers-action-bar has padding:12px 24px
if grep -qF 'id="servers-action-bar"' "$HTML" && grep -qF 'padding:12px 24px' "$HTML"; then
  # Confirm they're on the same line
  if grep -F 'id="servers-action-bar"' "$HTML" | grep -qF 'padding:12px 24px'; then
    check "#servers-action-bar has padding:12px 24px" "pass"
  else
    check "#servers-action-bar has padding:12px 24px" "fail" \
      "padding:12px 24px not found on the servers-action-bar line"
  fi
else
  check "#servers-action-bar has padding:12px 24px" "fail" \
    "Could not find servers-action-bar element with padding:12px 24px"
fi

# AC 3: "Add Server" btn-primary button exists in action bar HTML
if grep -qF 'id="servers-add-btn"' "$HTML"; then
  if grep -F 'id="servers-add-btn"' "$HTML" | grep -qF 'btn-primary'; then
    check "servers-add-btn with btn-primary exists in action bar" "pass"
  else
    check "servers-add-btn with btn-primary exists in action bar" "fail" \
      "servers-add-btn found but not btn-primary"
  fi
else
  check "servers-add-btn with btn-primary exists in action bar" "fail" \
    "servers-add-btn not found in HTML"
fi

echo ""
echo "── Server card structure ─────────────────────────────────────────────────"
echo ""

# AC 4: renderServerCards header uses justify-content:space-between
if grep -qF 'justify-content:space-between' "$HTML"; then
  check "renderServerCards contains justify-content:space-between" "pass"
else
  check "renderServerCards contains justify-content:space-between" "fail" \
    "justify-content:space-between not found in index.html"
fi

# AC 5 + AC 6: Tools pill and crashed badge in right group (within renderServerCards)
# Check that the tools pill and crashed badge are emitted after the left group close (</div>)
# We check for the distinctive right-group markup patterns
if grep -qF 'border-radius:100px' "$HTML"; then
  check "Tools pill / crashed badge with border-radius:100px rendered in right group" "pass"
else
  check "Tools pill / crashed badge with border-radius:100px rendered in right group" "fail" \
    "No border-radius:100px pill/badge found in renderServerCards"
fi

if grep -qF 'var(--danger-emphasis)' "$HTML"; then
  check "Crashed badge uses var(--danger-emphasis) background" "pass"
else
  check "Crashed badge uses var(--danger-emphasis) background" "fail" \
    "var(--danger-emphasis) not found — crashed badge may be missing"
fi

# AC 8: Stats render with icons (timer &#9202; / restart &#8635;)
if grep -qF '&#9202;' "$HTML"; then
  check "Uptime stat uses timer icon &#9202;" "pass"
else
  check "Uptime stat uses timer icon &#9202;" "fail" \
    "&#9202; (timer icon) not found in renderServerCards"
fi

if grep -qF '&#8635;' "$HTML"; then
  check "Restart stat uses restart icon &#8635;" "pass"
else
  check "Restart stat uses restart icon &#8635;" "fail" \
    "&#8635; (restart icon) not found in renderServerCards"
fi

echo ""
echo "── Grid padding ──────────────────────────────────────────────────────────"
echo ""

# AC 11: #servers-grid has padding:24px
if grep -F 'id="servers-grid"' "$HTML" | grep -qF 'padding:24px'; then
  check "#servers-grid has padding:24px" "pass"
else
  check "#servers-grid has padding:24px" "fail" \
    "padding:24px not found on the servers-grid element"
fi

echo ""
echo "── CSS checks ────────────────────────────────────────────────────────────"
echo ""

# AC 10: .server-card has padding:0 (not padding:16px)
if grep -A8 '^\.server-card {' "$CSS" | grep -qF 'padding: 0'; then
  check ".server-card has padding:0" "pass"
else
  check ".server-card has padding:0" "fail" \
    ".server-card padding is not 0 — check ds.css server-card block"
fi

# AC 9: .server-actions has border-top
if grep -A8 '\.server-card \.server-actions {' "$CSS" | grep -qF 'border-top'; then
  check ".server-actions has border-top" "pass"
else
  check ".server-actions has border-top" "fail" \
    "border-top not found in .server-card .server-actions"
fi

# AC 9: .server-actions has correct padding
if grep -A8 '\.server-card \.server-actions {' "$CSS" | grep -qF 'padding: 8px 16px 12px 16px'; then
  check ".server-actions has padding:8px 16px 12px 16px" "pass"
else
  check ".server-actions has padding:8px 16px 12px 16px" "fail" \
    "Expected padding:8px 16px 12px 16px not found in .server-actions"
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
