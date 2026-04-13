#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-BUG-037 Verification ==="

grep -q 'word-break.*normal' internal/web/ui/ds.css
check ".json-line .lc has word-break:normal" $?

grep -q 'overflow-wrap.*normal' internal/web/ui/ds.css
check ".json-line .lc has overflow-wrap:normal" $?

! grep -q 'overflow-wrap.*break-word' internal/web/ui/ds.css
check ".json-line .lc does not have overflow-wrap:break-word" $?

go test ./...
check "go test ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
