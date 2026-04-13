#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-003 Verification ==="

grep -q 'secrets-backend-section' internal/web/ui/index.html
check "secrets-backend-section exists in HTML" $?

grep -q 'servers-plain-text-warning' internal/web/ui/index.html
check "servers-plain-text-warning banner exists in HTML" $?

grep -q 'has_plain_text_secrets' internal/web/server.go
check "serverInfoResponse has has_plain_text_secrets field" $?

grep -q 'hasPlainTextSecrets' internal/web/server.go
check "hasPlainTextSecrets helper exists" $?

grep -q 'TestHasPlainTextSecrets' internal/web/server_test.go
check "TestHasPlainTextSecrets test exists" $?

go test ./...
check "go test ./..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
