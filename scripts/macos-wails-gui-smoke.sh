#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/macos-wails-gui-smoke.sh [--skip-build] [--app PATH] [--evidence-dir DIR]

Runs the macOS Wails v3 native GUI smoke for Shipyard and writes a Markdown
evidence artifact. The script automates the build, launch, process check, HTTP
health check, and window-count probe. Native menu-bar tray interaction is kept as
a structured manual checklist because macOS menu-bar extras are not reliably
observable without user Accessibility permissions.

Checklist coverage:
  - tray icon visibility or accessibility
  - tray click show/toggle behavior
  - right-click menu items: Show Dashboard, Quit
  - close-to-tray behavior
  - panel detach opens a separate native window

Default evidence path: reports/gui-smoke/SPEC-BUG-129-<timestamp>.md
USAGE
}

skip_build=0
app_path="./bin/shipyard"
evidence_dir="reports/gui-smoke"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build)
      skip_build=1
      shift
      ;;
    --app)
      app_path="${2:?missing --app path}"
      shift 2
      ;;
    --evidence-dir)
      evidence_dir="${2:?missing --evidence-dir path}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This smoke script must run on macOS." >&2
  exit 1
fi

command -v osascript >/dev/null || { echo "osascript is required." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
if [[ ! -r /dev/tty || ! -w /dev/tty ]]; then
  echo "This smoke script needs an interactive terminal for manual tray/menu evidence." >&2
  exit 1
fi

if [[ "$skip_build" -eq 0 ]]; then
  command -v wails3 >/dev/null || { echo "wails3 is required unless --skip-build is used." >&2; exit 1; }
  wails3 task build
fi

if [[ ! -x "$app_path" ]]; then
  echo "Shipyard binary is not executable: $app_path" >&2
  exit 1
fi

mkdir -p "$evidence_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
evidence_path="$evidence_dir/SPEC-BUG-129-$timestamp.md"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/shipyard-gui-smoke.XXXXXX")"
log_path="$tmp_dir/shipyard.log"
config_path="$tmp_dir/servers.json"
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"

cat > "$config_path" <<JSON
{
  "web": { "port": $port },
  "servers": {
    "gui-smoke-test": {
      "command": "/usr/bin/true",
      "args": []
    }
  }
}
JSON

pid=""
cleanup() {
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

"$app_path" --config "$config_path" >"$log_path" 2>&1 &
pid=$!

ready=0
for _ in {1..80}; do
  if curl -fsS "http://127.0.0.1:$port/api/servers" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    break
  fi
  sleep 0.25
done

if [[ "$ready" -ne 1 ]]; then
  echo "Shipyard did not become ready. Log: $log_path" >&2
  exit 1
fi

window_count_before="$(osascript -e 'on run argv
  set targetPID to item 1 of argv as integer
  tell application "System Events"
    set matches to processes whose unix id is targetPID
    if (count matches) is 0 then return "unknown"
    return count windows of item 1 of matches
  end tell
end run' "$pid" 2>/dev/null || echo "unknown")"

answer() {
  local prompt="$1"
  local value=""
  while true; do
    printf "%s [y/n]: " "$prompt" > /dev/tty
    IFS= read -r value < /dev/tty
    case "$value" in
      y|Y) echo "PASS"; return 0 ;;
      n|N) echo "FAIL"; return 1 ;;
      *) echo "Please answer y or n." > /dev/tty ;;
    esac
  done
}

set +e
tray_visible="$(answer "Tray icon is visible in the macOS menu bar or exposed as a menu-bar extra")"; tray_visible_rc=$?
tray_toggle="$(answer "Clicking the tray icon hides/shows or focuses the Shipyard dashboard")"; tray_toggle_rc=$?
tray_menu="$(answer "Right-clicking the tray icon shows Show Dashboard and Quit")"; tray_menu_rc=$?
panel_detach="$(answer "Right-clicking a detachable panel tab and choosing Open in New Window opens a separate native window")"; panel_detach_rc=$?
close_to_tray="$(answer "Closing the main window hides it while the shipyard process keeps running")"; close_to_tray_rc=$?
set -e

process_alive_after_close="FAIL"
if kill -0 "$pid" 2>/dev/null; then
  process_alive_after_close="PASS"
fi
window_count_after="$(osascript -e 'on run argv
  set targetPID to item 1 of argv as integer
  tell application "System Events"
    set matches to processes whose unix id is targetPID
    if (count matches) is 0 then return "unknown"
    return count windows of item 1 of matches
  end tell
end run' "$pid" 2>/dev/null || echo "unknown")"

overall="PASS"
for rc in "$tray_visible_rc" "$tray_toggle_rc" "$tray_menu_rc" "$close_to_tray_rc" "$panel_detach_rc"; do
  if [[ "$rc" -ne 0 ]]; then
    overall="FAIL"
  fi
done

cat > "$evidence_path" <<EOF
# SPEC-BUG-129 macOS Wails v3 GUI Smoke

- Timestamp UTC: $timestamp
- Result: $overall
- Command: \`scripts/macos-wails-gui-smoke.sh\`
- App path: \`$app_path\`
- Config path: \`$config_path\`
- Log path: \`$log_path\`
- HTTP health: PASS (\`/api/servers\` on port $port)
- Process PID: $pid
- Process alive after close-to-tray step: $process_alive_after_close
- Native window count before manual steps: $window_count_before
- Native window count after manual steps: $window_count_after

## Checklist

- Tray icon visible or accessible: $tray_visible
- Tray click show/toggle behavior: $tray_toggle
- Tray right-click menu contains \`Show Dashboard\` and \`Quit\`: $tray_menu
- Main window close hides to tray instead of exiting: $close_to_tray
- Panel detach opens a separate native window: $panel_detach

## Notes

Use this artifact as the linked evidence in the Nightshift report. If any item is
FAIL, keep the app log path and attach a short reproduction note before retrying.
EOF

echo "Evidence written: $evidence_path"
if [[ "$overall" != "PASS" ]]; then
  exit 1
fi
