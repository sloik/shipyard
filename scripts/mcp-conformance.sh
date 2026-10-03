#!/usr/bin/env bash
# SPEC-BUG-181 R4: run the official MCP conformance CLI, pinned to an exact
# stable release, against Shipyard's MCP fixture server and fixture clients.
#
# Usage: scripts/mcp-conformance.sh [--result-dir DIR]   (default $TMPDIR/shipyard-mcp-conformance)
#
# Legs:
#   server        legacy fixture server (stateful streamable HTTP), --spec-version 2025-11-25
#   client-legacy fixture client offering 2025-11-25, suite "core"
#   client-modern fixture client offering 2026-07-28 (falls back to initialize), suite "core"
#
# Waivers: test/mcp-conformance/expected-failures.yml is a byte-for-byte copy of
# the pinned go-sdk's conformance/baseline.yml (enforced by
# TestConformanceWaivers_AreVerbatimSDKBaseline). Shipyard adds no waivers.
#
# Not run: a modern-era (2026-07-28) server leg. The pinned stable CLI has no
# 2026-07-28 scenarios; that coverage comes from the golden wire tests in
# internal/mcpfixture until a stable CLI release adds them.
#
# Requires: go, node/npx (network access on first run to fetch the pinned CLI), curl.
# Exit status is non-zero if any leg fails or any leg ran zero scenarios.
set -euo pipefail

CONFORMANCE_VERSION="0.1.16"
CLI="@modelcontextprotocol/conformance@${CONFORMANCE_VERSION}"

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
WAIVERS="$ROOT/test/mcp-conformance/expected-failures.yml"

OUT="${TMPDIR:-/tmp}/shipyard-mcp-conformance"
if [ "${1:-}" = "--result-dir" ]; then
	OUT="${2:?--result-dir needs a directory}"
fi
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
WORK="$(mktemp -d)"
SERVER_PID=""
cleanup() {
	if [ -n "$SERVER_PID" ]; then
		kill "$SERVER_PID" 2>/dev/null || true
		wait "$SERVER_PID" 2>/dev/null || true
	fi
	rm -rf "$WORK"
}
trap cleanup EXIT

command -v npx >/dev/null 2>&1 || { echo "mcp-conformance: npx not found (install Node.js)" >&2; exit 2; }

go build -o "$WORK/mcpfixture" ./internal/mcpfixture/cmd/mcpfixture

FAILED=0
# run_leg NAME CMD... : run one CLI leg from the work dir, tee its log, and
# require a non-zero scenario count.
run_leg() {
	local name="$1"
	shift
	local log="$OUT/$name.log"
	echo "=== conformance leg: $name ($CLI) ==="
	local status=0
	(cd "$WORK" && "$@") >"$log" 2>&1 || status=$?
	grep -E '^(Total:|.*Baseline check)' "$log" || true
	local total
	total="$(sed -n 's/^Total: \([0-9]*\) passed, \([0-9]*\) failed.*/\1 \2/p' "$log" | tail -1)"
	if [ -z "$total" ] || [ "$total" = "0 0" ]; then
		echo "mcp-conformance: leg $name ran zero scenarios (see $log)" >&2
		FAILED=1
	fi
	if [ "$status" -ne 0 ]; then
		echo "mcp-conformance: leg $name failed with exit $status (see $log)" >&2
		FAILED=1
	fi
}

PORT="${MCP_CONFORMANCE_PORT:-39417}"
"$WORK/mcpfixture" server -era legacy -http "127.0.0.1:$PORT" 2>"$OUT/server-fixture.log" &
SERVER_PID=$!
for _ in $(seq 1 60); do
	if curl -s -o /dev/null "http://127.0.0.1:$PORT/mcp"; then
		break
	fi
	sleep 0.25
done

run_leg server npx -y "$CLI" server --url "http://127.0.0.1:$PORT/mcp" \
	--spec-version 2025-11-25 --expected-failures "$WAIVERS" -o "$OUT/server"

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""

for era in legacy modern; do
	run_leg "client-$era" npx -y "$CLI" client --command "$WORK/mcpfixture client -era $era" \
		--suite core --expected-failures "$WAIVERS" -o "$OUT/client-$era"
done

echo "NOTICE: no 2026-07-28 server leg: $CLI has no 2026-07-28 scenarios (see script header)."
if [ "$FAILED" -ne 0 ]; then
	echo "mcp-conformance: FAILED (logs in $OUT)" >&2
	exit 1
fi
echo "mcp-conformance: all legs passed with zero Shipyard-added waivers"
