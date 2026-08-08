#!/bin/zsh
# Promote Shipyard's one canonical launchd runtime only after a clean smoke.
set -euo pipefail

repo_root="${SHIPYARD_REPO_ROOT:-${0:A:h:h}}"
runtime_dir="$repo_root/bin"
canonical_bin="$runtime_dir/shipyard"
archive_dir="$repo_root/archive/runtime/$(date -u +%Y%m%dT%H%M%SZ)"
home_root="${SHIPYARD_HOME:-$HOME}"
launchd_uid="${SHIPYARD_LAUNCHD_UID:-$(id -u)}"
launchctl_cmd="${SHIPYARD_LAUNCHCTL:-launchctl}"
plist_buddy_cmd="${SHIPYARD_PLISTBUDDY:-/usr/libexec/PlistBuddy}"
plutil_cmd="${SHIPYARD_PLUTIL:-plutil}"
make_cmd="${SHIPYARD_MAKE:-make}"
go_cmd="${SHIPYARD_GO:-go}"
curl_cmd="${SHIPYARD_CURL:-curl}"
sleep_cmd="${SHIPYARD_SLEEP:-sleep}"
health_attempts="${SHIPYARD_HEALTH_ATTEMPTS:-15}"
legacy_plist="$home_root/Library/LaunchAgents/com.argo.shipyard.app.plist"
legacy_label="com.argo.shipyard.app"
legacy_service="gui/$launchd_uid/$legacy_label"
# A fresh label avoids launchd's ad-hoc-code-hash cache for the old service.
label="com.argo.shipyard.app.canonical"
plist="$home_root/Library/LaunchAgents/$label.plist"
service="gui/$launchd_uid/$label"
health_url="http://127.0.0.1:9417/api/servers"
candidate="$(mktemp "${TMPDIR:-/tmp}/shipyard-runtime.XXXXXX")"
prior_runtime="$(mktemp "${TMPDIR:-/tmp}/shipyard-prior.XXXXXX")"
prior_plist="$(mktemp "${TMPDIR:-/tmp}/shipyard-plist.XXXXXX")"
live_payload="$(mktemp "${TMPDIR:-/tmp}/shipyard-servers.XXXXXX")"
prior_service_state="$(mktemp "${TMPDIR:-/tmp}/shipyard-service.XXXXXX")"
had_prior_runtime=false
had_prior_service=false
prior_pid=""

cleanup() { rm -f "$candidate" "$prior_runtime" "$prior_plist" "$live_payload" "$prior_service_state"; }
trap cleanup EXIT

restore_legacy() {
  "$launchctl_cmd" bootout "$service" 2>/dev/null || true
  "$launchctl_cmd" bootstrap "gui/$launchd_uid" "$legacy_plist" 2>/dev/null || true
  "$launchctl_cmd" kickstart -k "$legacy_service" 2>/dev/null || true
}

restore_prior_runtime() {
  if [[ "$had_prior_runtime" == true ]]; then
    mv "$prior_runtime" "$canonical_bin"
  fi
  "$launchctl_cmd" bootout "$service" 2>/dev/null || true
  if [[ "$had_prior_service" == true ]]; then
    [[ -s "$prior_plist" ]] && cp -p "$prior_plist" "$plist"
    "$launchctl_cmd" bootstrap "gui/$launchd_uid" "$plist" 2>/dev/null || true
    "$launchctl_cmd" kickstart -k "$service" 2>/dev/null || true
  else
    restore_legacy
  fi
}

fail_and_restore() {
  restore_prior_runtime
  print -u2 "$1"
  exit 1
}

cd "$repo_root"
[[ -f "$legacy_plist" ]] || { print -u2 "missing legacy launchd plist: $legacy_plist"; exit 1; }

# This proves the replacement source before touching either launchd or bin/.
"$make_cmd" smoke-full
"$go_cmd" build -o "$candidate" ./cmd/shipyard/

mkdir -p "$runtime_dir" "$archive_dir"

if "$launchctl_cmd" print "$service" > "$prior_service_state" 2>/dev/null; then
  had_prior_service=true
  prior_pid="$(sed -nE 's/^[[:space:]]*pid = ([0-9]+).*/\1/p' "$prior_service_state" | head -n 1)"
fi
if [[ -f "$plist" ]]; then
  cp -p "$plist" "$prior_plist"
fi

# macOS rejects a rebuilt executable under the old ad-hoc-signed label. Clone
# its operating settings to a fresh label, then start the canonical binary.
cp "$legacy_plist" "$plist"
"$plist_buddy_cmd" -c "Set :Label $label" "$plist"
if [[ -e "$canonical_bin" ]]; then
  cp -p "$canonical_bin" "$prior_runtime"
  had_prior_runtime=true
fi
mv "$candidate" "$canonical_bin"
chmod 755 "$canonical_bin"

"$plist_buddy_cmd" -c "Set :ProgramArguments:0 $canonical_bin" "$plist"
"$plutil_cmd" -lint "$plist"
"$launchctl_cmd" bootout "$legacy_service" 2>/dev/null || true
# bootstrap fails with error 5 for an already-loaded label. Unload the canonical
# service first so both initial installation and replacement use one path.
"$launchctl_cmd" bootout "$service" 2>/dev/null || true
if ! "$launchctl_cmd" bootstrap "gui/$launchd_uid" "$plist"; then
  fail_and_restore "canonical launchd bootstrap failed; restored the prior runtime and service"
fi
if ! "$launchctl_cmd" kickstart -k "$service"; then
  fail_and_restore "canonical launchd service failed to start; restored the prior runtime and service"
fi

# `launchctl print` is the authoritative supervisor state. Do not archive the
# old runtime set until it names the canonical executable.
if ! live_service_state="$("$launchctl_cmd" print "$service")"; then
  fail_and_restore "canonical launchd service could not be inspected; restored the prior runtime and service"
fi
if ! print -r -- "$live_service_state" | grep -Fq "program = $canonical_bin"; then
  fail_and_restore "canonical launchd service failed; restored the prior runtime and service"
fi
live_pid="$(print -r -- "$live_service_state" | sed -nE 's/^[[:space:]]*pid = ([0-9]+).*/\1/p' | head -n 1)"
if [[ -z "$live_pid" || ( -n "$prior_pid" && "$live_pid" == "$prior_pid" ) ]]; then
  fail_and_restore "canonical launchd service did not expose a changed live PID; restored the prior runtime and service"
fi

# AC-4 is an application-level assertion, not merely a supervisor assertion.
# Wait briefly for child MCP discovery, then require each managed child to
# publish a tool_count field before anything is archived.
for _ in {1..$health_attempts}; do
  if "$curl_cmd" --fail --silent --show-error "$health_url" > "$live_payload"; then
    if python3 - "$live_payload" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
servers = payload.get("servers", payload) if isinstance(payload, dict) else payload
children = [server for server in servers if not server.get("is_self")]
if children and all(isinstance(server.get("tool_count"), int) and not isinstance(server.get("tool_count"), bool) and server["tool_count"] > 0 for server in children):
    print(f"live child tool counts verified for {len(children)} managed servers")
    raise SystemExit(0)
raise SystemExit(1)
PY
    then
      break
    fi
  fi
  "$sleep_cmd" 1
done
if ! python3 - "$live_payload" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
servers = payload.get("servers", payload) if isinstance(payload, dict) else payload
children = [server for server in servers if not server.get("is_self")]
raise SystemExit(0 if children and all(isinstance(server.get("tool_count"), int) and not isinstance(server.get("tool_count"), bool) and server["tool_count"] > 0 for server in children) else 1)
PY
then
  fail_and_restore "Shipyard did not expose populated managed-child tool counts; restored the prior runtime and service"
fi

[[ -s "$prior_runtime" ]] && mv "$prior_runtime" "$archive_dir/shipyard-prior"

for old in "$runtime_dir"/*(N); do
  [[ "$old" == "$canonical_bin" ]] && continue
  [[ -f "$old" && -x "$old" ]] || continue
  mv "$old" "$archive_dir/${old:t}"
done

print "Shipyard launchd runtime is canonical: $canonical_bin"
print "Archived legacy binaries: $archive_dir"
