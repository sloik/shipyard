#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  local desc="$1" result="$2"
  if [ "$result" = "0" ]; then echo "  PASS: $desc"; PASS=$((PASS+1))
  else echo "  FAIL: $desc"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-036 Verification ==="

grep -q 'class="ln"' internal/web/ui/index.html
check "highlightJSON emits class=\"ln\" span" $?

grep -q 'class="lc"' internal/web/ui/index.html
check "highlightJSON emits class=\"lc\" span" $?

grep -q 'display.*flex' internal/web/ui/ds.css
check ".json-line has display:flex" $?

grep -q 'user-select.*none' internal/web/ui/ds.css
check ".json-line .ln has user-select:none" $?

grep -q 'white-space.*pre-wrap' internal/web/ui/ds.css
check ".json-line .lc has white-space:pre-wrap" $?

grep -q 'overflow-wrap.*break-word' internal/web/ui/ds.css
check ".json-line .lc has overflow-wrap:break-word" $?

grep -q 'min-width.*0' internal/web/ui/ds.css
check ".json-line .lc has min-width:0" $?

go test ./...
check "go test ./..." $?

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
