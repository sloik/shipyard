#!/bin/zsh
# Promote Shipyard's one canonical launchd runtime only after a clean smoke.
set -euo pipefail

repo_root="${0:A:h:h}"
runtime_dir="$repo_root/bin"
canonical_bin="$runtime_dir/shipyard"
archive_dir="$repo_root/archive/runtime/$(date -u +%Y%m%dT%H%M%SZ)"
legacy_plist="$HOME/Library/LaunchAgents/com.argo.shipyard.app.plist"
legacy_label="com.argo.shipyard.app"
legacy_service="gui/$(id -u)/$legacy_label"
# A fresh label avoids launchd's ad-hoc-code-hash cache for the old service.
label="com.argo.shipyard.app.canonical"
plist="$HOME/Library/LaunchAgents/$label.plist"
service="gui/$(id -u)/$label"
health_url="http://127.0.0.1:9417/api/servers"
candidate="$(mktemp "${TMPDIR:-/tmp}/shipyard-runtime.XXXXXX")"
prior_runtime="$(mktemp "${TMPDIR:-/tmp}/shipyard-prior.XXXXXX")"
live_payload="$(mktemp "${TMPDIR:-/tmp}/shipyard-servers.XXXXXX")"

cleanup() { rm -f "$candidate" "$prior_runtime" "$live_payload"; }
trap cleanup EXIT

restore_legacy() {
  launchctl bootout "$service" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$legacy_plist" 2>/dev/null || true
  launchctl kickstart -k "$legacy_service" 2>/dev/null || true
}

cd "$repo_root"
[[ -f "$legacy_plist" ]] || { print -u2 "missing legacy launchd plist: $legacy_plist"; exit 1; }

# This proves the replacement source before touching either launchd or bin/.
make smoke-full
go build -o "$candidate" ./cmd/shipyard/

mkdir -p "$runtime_dir" "$archive_dir"

# macOS rejects a rebuilt executable under the old ad-hoc-signed label. Clone
# its operating settings to a fresh label, then start the canonical binary.
cp "$legacy_plist" "$plist"
/usr/libexec/PlistBuddy -c "Set :Label $label" "$plist"
[[ -e "$canonical_bin" ]] && cp -p "$canonical_bin" "$prior_runtime"
mv "$candidate" "$canonical_bin"
chmod 755 "$canonical_bin"

/usr/libexec/PlistBuddy -c "Set :ProgramArguments:0 $canonical_bin" "$plist"
plutil -lint "$plist"
launchctl bootout "$legacy_service" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
launchctl kickstart -k "$service"

# `launchctl print` is the authoritative supervisor state. Do not archive the
# old runtime set until it names the canonical executable.
if ! launchctl print "$service" | grep -Fq "program = $canonical_bin"; then
  [[ -s "$prior_runtime" ]] && mv "$prior_runtime" "$canonical_bin"
  restore_legacy
  print -u2 "canonical launchd service failed; restored legacy service and retained legacy binaries"
  exit 1
fi

# AC-4 is an application-level assertion, not merely a supervisor assertion.
# Wait briefly for child MCP discovery, then require each managed child to
# publish a tool_count field before anything is archived.
for _ in {1..15}; do
  if curl --fail --silent --show-error "$health_url" > "$live_payload"; then
    if python3 - "$live_payload" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
servers = payload.get("servers", payload) if isinstance(payload, dict) else payload
children = [server for server in servers if not server.get("is_self")]
if children and all("tool_count" in server for server in children):
    print(f"live child tool counts verified for {len(children)} managed servers")
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
      break
    fi
  fi
  sleep 1
done
if ! python3 - "$live_payload" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
servers = payload.get("servers", payload) if isinstance(payload, dict) else payload
children = [server for server in servers if not server.get("is_self")]
raise SystemExit(0 if children and all("tool_count" in server for server in children) else 1)
PY
then
  restore_legacy
  print -u2 "Shipyard did not expose populated managed-child tool counts; legacy binaries retained"
  exit 1
fi

[[ -s "$prior_runtime" ]] && mv "$prior_runtime" "$archive_dir/shipyard-prior"

for old in "$runtime_dir"/*(N); do
  [[ "$old" == "$canonical_bin" ]] && continue
  [[ -f "$old" && -x "$old" ]] || continue
  mv "$old" "$archive_dir/${old:t}"
done

print "Shipyard launchd runtime is canonical: $canonical_bin"
print "Archived legacy binaries: $archive_dir"
