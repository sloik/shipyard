#!/bin/sh
# Rotate launchd stdout/stderr logs with copy-truncate.
#
# launchd holds the log fds open with O_APPEND, so the live file is truncated
# in place (same inode) after being copied to <name>.1; no restart is needed.
#
# Usage: rotate-launchd-logs.sh [LOG_DIR]
# Env:   SHIPYARD_LOG_DIR         log directory (default ~/Library/Logs/Shipyard)
#        SHIPYARD_LOG_MAX_BYTES   rotate files larger than this (default 10485760);
#                                 0 or negative disables rotation
#        SHIPYARD_LOG_KEEP        rotated copies to keep (default 3); 0 = just truncate
set -eu

log_dir="${1:-${SHIPYARD_LOG_DIR:-$HOME/Library/Logs/Shipyard}}"
max_bytes="${SHIPYARD_LOG_MAX_BYTES:-10485760}"
keep="${SHIPYARD_LOG_KEEP:-3}"

mkdir -p "$log_dir"

if [ "$max_bytes" -le 0 ] 2>/dev/null; then
  exit 0
fi

rotate() {
  f="$1"
  if [ "$keep" -gt 0 ]; then
    i=$keep
    rm -f "$f.$i"
    while [ "$i" -gt 1 ]; do
      prev=$((i - 1))
      if [ -e "$f.$prev" ]; then
        mv -f "$f.$prev" "$f.$i"
      fi
      i=$prev
    done
    cp -p "$f" "$f.1"
  fi
  : >"$f"
}

for f in "$log_dir"/*.log; do
  [ -f "$f" ] || continue
  size=$(stat -f %z "$f")
  if [ "$size" -gt "$max_bytes" ]; then
    rotate "$f"
  fi
done
exit 0
