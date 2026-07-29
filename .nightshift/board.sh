#!/usr/bin/env bash
# Launch Nightshift Board for this project.
# Port is hash-based per project (range 7800-7999) — same project always gets the same port.
# Usage: board.sh [--port N] [extra args passed to board.py]
#        board.sh stop
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/board.pid"
LOG_FILE="$DIR/board.restart.log"
STOP_COMMAND="$0 stop"

board_process_matches() {
  local pid="$1"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == *"$DIR/board.py"* ]]
}

stop_board() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "Board is not running."
    return 0
  fi

  local pid
  pid="$(<"$PID_FILE")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    rm -f "$PID_FILE"
    echo "Board is not running (removed an invalid PID record)."
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Board is not running (removed a stale PID record)."
    return 0
  fi

  if ! board_process_matches "$pid"; then
    echo "Refusing to stop PID $pid: it is not this board process." >&2
    exit 1
  fi

  kill -TERM "$pid"
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "Board stopped."
      return 0
    fi
    sleep 0.1
  done

  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "Board stopped."
}

if [[ "${1:-}" == "stop" ]]; then
  if [[ "$#" -ne 1 ]]; then
    echo "Usage: $0 stop" >&2
    exit 2
  fi
  stop_board
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(<"$PID_FILE")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null && board_process_matches "$existing_pid"; then
    echo "Board is already running (PID $existing_pid). Stop it with: $STOP_COMMAND"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

python3 "$DIR/board.py" --open "$@" >>"$LOG_FILE" 2>&1 &
pid="$!"
printf '%s\n' "$pid" >"$PID_FILE"
echo "Board started (PID $pid). Stop it with: $STOP_COMMAND"
