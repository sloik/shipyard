#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/shipyard-spec-125.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: missing required command: $1" >&2
    exit 1
  }
}

require_cmd codex
require_cmd jq
require_cmd curl
require_cmd go

if ! curl -sf http://127.0.0.1:9417/api/servers >/dev/null; then
  echo "FAIL: Shipyard backend is not reachable at http://127.0.0.1:9417" >&2
  exit 1
fi

if ! codex mcp list | grep -q '^shipyard'; then
  echo "FAIL: codex mcp list does not show shipyard enabled" >&2
  exit 1
fi

SHIPYARD_OUT="$TMP_DIR/shipyard-status.jsonl"
LMSTUDIO_OUT="$TMP_DIR/lmstudio-status.jsonl"

codex exec --skip-git-repo-check --ephemeral --json -C "$TMP_DIR" -s workspace-write \
  "Use the available MCP tools to call the Shipyard status tool exactly once and then stop. Report the result in one sentence." \
  >"$SHIPYARD_OUT"

jq -e '
  select(.type == "item.completed")
  | .item
  | select(.type == "mcp_tool_call" and .server == "shipyard" and .tool == "shipyard__status" and .status == "completed")
' "$SHIPYARD_OUT" >/dev/null

codex exec --skip-git-repo-check --ephemeral --json -C "$TMP_DIR" -s workspace-write \
  "Use the available MCP tools to call the LM Studio status tool exposed through Shipyard exactly once and then stop. Report the result in one sentence." \
  >"$LMSTUDIO_OUT"

jq -e '
  select(.type == "item.completed")
  | .item
  | select(.type == "mcp_tool_call" and .server == "shipyard" and .tool == "lmstudio__lms_status" and .status == "completed")
' "$LMSTUDIO_OUT" >/dev/null

go test ./cmd/shipyard-mcp >/dev/null
go build ./cmd/shipyard-mcp >/dev/null

echo "PASS: SPEC-BUG-125 verified"
