#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-002 Verification ==="

grep -q 'SecretsConfig' cmd/shipyard/main.go
check "SecretsConfig type exists in main.go" $?

grep -q 'Secrets.*SecretsConfig' cmd/shipyard/main.go
check "Config struct has Secrets field" $?

grep -q 'resolveEnv' cmd/shipyard/main.go
check "resolveEnv called in main.go" $?

# Verify resolveEnv is called inside the restart goroutine
grep -A 50 'runServerWithRestart' cmd/shipyard/main.go | grep -q 'resolveEnv'
check "resolveEnv called inside runServerWithRestart" $?

# API must not leak env values
! grep -q '"env"' internal/web/server.go || grep -q 'json:"-"' internal/web/server.go
check "serverInfoResponse does not expose env field" $?

go test ./...
check "go test ./..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
