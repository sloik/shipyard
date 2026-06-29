#!/usr/bin/env bash
# Focused validation for .nightshift/hooks/commit-msg.
# Runs sample commit messages through the hook without making real commits.

set -euo pipefail

HOOK="${1:-.nightshift/hooks/commit-msg}"

if [ ! -x "$HOOK" ]; then
    echo "ERROR: commit-msg hook is not executable: $HOOK" >&2
    exit 2
fi

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/shipyard-commit-msg.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT

pass_count=0
fail_count=0

check_msg() {
    local label="$1"
    local expected_rc="$2"
    local message="$3"
    local msg_file="$TMP_DIR/message"
    local output_file="$TMP_DIR/output"
    local rc=0

    printf '%s\n' "$message" > "$msg_file"
    if "$HOOK" "$msg_file" >"$output_file" 2>&1; then
        rc=0
    else
        rc=$?
    fi

    if [ "$expected_rc" = "0" ] && [ "$rc" -eq 0 ]; then
        printf 'PASS: %s\n' "$label"
        pass_count=$((pass_count + 1))
        return 0
    fi

    if [ "$expected_rc" != "0" ] && [ "$rc" -ne 0 ]; then
        printf 'PASS: %s\n' "$label"
        pass_count=$((pass_count + 1))
        return 0
    fi

    printf 'FAIL: %s\n' "$label"
    printf '  expected rc: %s\n' "$expected_rc"
    printf '  actual rc:   %s\n' "$rc"
    sed 's/^/  hook: /' "$output_file"
    fail_count=$((fail_count + 1))
}

check_msg "accepts SPEC-BUG ID" 0 \
    "[SPEC-BUG-154] fix: accept SPEC-BUG commit IDs"
check_msg "accepts existing numeric child spec ID" 0 \
    "[SPEC-004-002] test: validate child spec commit prefix"
check_msg "rejects missing bracketed spec ID" 1 \
    "fix: missing traceability prefix"
check_msg "rejects malformed spec ID" 1 \
    "[SPECBUG-154] fix: malformed spec prefix"
check_msg "rejects unbracketed status commit" 1 \
    "chore: mark SPEC-BUG-154 done"

printf '\nSummary: %s passed, %s failed\n' "$pass_count" "$fail_count"

if [ "$fail_count" -ne 0 ]; then
    exit 1
fi
