#!/bin/zsh
# Promote Shipyard's one canonical launchd runtime only after a clean smoke.
set -euo pipefail

repo_root="${0:A:h:h}"
runtime_dir="$repo_root/bin"
canonical_bin="$runtime_dir/shipyard"
archive_dir="$repo_root/archive/runtime/$(date -u +%Y%m%dT%H%M%SZ)"
plist="$HOME/Library/LaunchAgents/com.argo.shipyard.app.plist"
label="com.argo.shipyard.app"
service="gui/$(id -u)/$label"
candidate="$(mktemp "${TMPDIR:-/tmp}/shipyard-runtime.XXXXXX")"
prior_runtime="$(mktemp "${TMPDIR:-/tmp}/shipyard-prior.XXXXXX")"

cleanup() { rm -f "$candidate" "$prior_runtime"; }
trap cleanup EXIT

cd "$repo_root"
[[ -f "$plist" ]] || { print -u2 "missing launchd plist: $plist"; exit 1; }

# This proves the replacement source before touching either launchd or bin/.
make smoke-full
go build -o "$candidate" ./cmd/shipyard/

mkdir -p "$runtime_dir" "$archive_dir"

# macOS rejects an in-place overwrite for this ad-hoc signed service. Stop the
# old job first, then install the candidate under the canonical name.
launchctl bootout "$service" 2>/dev/null || true
[[ -e "$canonical_bin" ]] && cp -p "$canonical_bin" "$prior_runtime"
mv "$candidate" "$canonical_bin"
chmod 755 "$canonical_bin"

/usr/libexec/PlistBuddy -c "Set :ProgramArguments:0 $canonical_bin" "$plist"
plutil -lint "$plist"
launchctl bootstrap "gui/$(id -u)" "$plist"
launchctl kickstart -k "$service"

# `launchctl print` is the authoritative supervisor state. Do not archive the
# old runtime set until it names the canonical executable.
if ! launchctl print "$service" | grep -Fq "program = $canonical_bin"; then
  [[ -s "$prior_runtime" ]] && mv "$prior_runtime" "$canonical_bin"
  print -u2 "launchd did not adopt $canonical_bin; restored prior runtime and retained legacy binaries"
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
