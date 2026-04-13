#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0

check() {
  local desc="$1"
  local result="$2"
  if [ "$result" = "0" ]; then
    echo "  PASS: $desc"
    PASS=$((PASS+1))
  else
    echo "  FAIL: $desc"
    FAIL=$((FAIL+1))
  fi
}

echo "=== SPEC-BUG-035 Verification ==="

# Check 1: GatewayDisabled field in Go server handler
grep -q "GatewayDisabled\|gateway_disabled" internal/web/server.go
check "Go handler has GatewayDisabled field" $?

# Check 2: renderServerCards handles gateway_disabled
grep -q "gateway_disabled" internal/web/ui/index.html
check "renderServerCards checks gateway_disabled" $?

# Check 3: Enable button POST call exists
grep -q "enableServer\|gateway/servers" internal/web/ui/index.html
check "Enable button references gateway/servers endpoint" $?

# Check 4: go test
go test ./...
check "go test ./..." $?

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
