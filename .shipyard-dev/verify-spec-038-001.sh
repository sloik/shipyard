#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
check() {
  if [ "$2" = "0" ]; then echo "  PASS: $1"; PASS=$((PASS+1))
  else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi
}

echo "=== SPEC-038-001 Verification ==="

[ -f internal/secrets/resolver.go ]
check "resolver.go exists" $?

grep -q 'CanResolve' internal/secrets/resolver.go
check "SecretResolver has CanResolve" $?

grep -q 'Resolve' internal/secrets/resolver.go
check "SecretResolver has Resolve" $?

[ -f internal/secrets/registry.go ]
check "registry.go exists" $?

[ -f internal/secrets/ref.go ]
check "ref.go exists" $?

[ -f internal/secrets/keychain/resolver_darwin.go ]
check "keychain/resolver_darwin.go exists" $?

grep -q 'go:build darwin' internal/secrets/keychain/resolver_darwin.go
check "keychain resolver has darwin build tag" $?

[ -f internal/secrets/op/resolver.go ]
check "op/resolver.go exists" $?

[ -f internal/secrets/env/resolver.go ]
check "env/resolver.go exists" $?

go test ./internal/secrets/...
check "go test ./internal/secrets/..." $?

go build ./...
check "go build ./..." $?

echo ""; echo "Results: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
