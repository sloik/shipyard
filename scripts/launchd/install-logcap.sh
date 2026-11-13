#!/bin/sh
# Render and (un)install the com.argo.shipyard.logcap LaunchAgent.
#
# Usage: install-logcap.sh install | uninstall | render
#   render     print the plist with paths substituted (no side effects)
# Env:   SHIPYARD_LOG_DIR  log directory (default ~/Library/Logs/Shipyard)
set -eu

label="com.argo.shipyard.logcap"
here=$(cd "$(dirname "$0")" && pwd)
script="$(cd "$here/.." && pwd)/rotate-launchd-logs.sh"
log_dir="${SHIPYARD_LOG_DIR:-$HOME/Library/Logs/Shipyard}"
target="$HOME/Library/LaunchAgents/$label.plist"
domain="gui/$(id -u)"

render() {
  sed -e "s|__SCRIPT_PATH__|$script|g" -e "s|__LOG_DIR__|$log_dir|g" \
    "$here/$label.plist"
}

case "${1:-}" in
  render)
    render
    ;;
  install)
    mkdir -p "$log_dir" "$(dirname "$target")"
    render >"$target"
    plutil -lint "$target" >/dev/null
    launchctl bootout "$domain/$label" 2>/dev/null || true
    launchctl bootstrap "$domain" "$target"
    launchctl kickstart -k "$domain/$label"
    ;;
  uninstall)
    launchctl bootout "$domain/$label" 2>/dev/null || true
    rm -f "$target"
    ;;
  *)
    echo "usage: $0 install|uninstall|render" >&2
    exit 2
    ;;
esac
