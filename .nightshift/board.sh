#!/usr/bin/env bash
# Launch Nightshift Board for this project.
# Port is hash-based per project (range 7800-7999) — same project always gets the same port.
# Usage: board.sh [--port N] [extra args passed to board.py]
#        board.sh stop
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Deployed board starts must not materialise interpreter bytecode beside the
# immutable managed payload. Keep this scoped to board.sh's process tree.
export PYTHONDONTWRITEBYTECODE=1
PID_FILE="$DIR/board.pid"
LOG_FILE="$DIR/board.restart.log"
STOP_COMMAND="$0 stop"
if [[ -n "${NIGHTSHIFT_BOARD_PYTHON:-}" ]]; then
  PYTHON_RUNTIME="$NIGHTSHIFT_BOARD_PYTHON"
elif [[ -x "$DIR/.board-venv/bin/python" ]]; then
  # A project-local runtime makes the canonical board independently runnable
  # when macOS's system Python lacks FastAPI/Uvicorn.
  PYTHON_RUNTIME="$DIR/.board-venv/bin/python"
else
  PYTHON_RUNTIME="python3"
fi

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

if ! "$PYTHON_RUNTIME" -c 'import fastapi, uvicorn, yaml' 2>/dev/null; then
  echo "Board runtime lacks required dependencies. Set NIGHTSHIFT_BOARD_PYTHON to a supported project Python." >&2
  exit 1
fi
nohup "$PYTHON_RUNTIME" "$DIR/board.py" --open "$@" >>"$LOG_FILE" 2>&1 < /dev/null &
pid="$!"
port=""
previous=""
for argument in "$@"; do
  if [[ "$previous" == "--port" ]]; then port="$argument"; break; fi
  previous="$argument"
done
if [[ -z "$port" ]]; then
  port="$("$PYTHON_RUNTIME" -c "print(7800 + sum(ord(c) for c in '${DIR##*/}'.lstrip('.').upper()) % 200)" 2>/dev/null || true)"
fi
for _ in {1..50}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Board failed to start; see $LOG_FILE. No PID record was written." >&2
    exit 1
  fi
  if curl --fail --silent --show-error "http://127.0.0.1:${port}/api/health" >/dev/null 2>&1; then
    printf '%s\n' "$pid" >"$PID_FILE"
    echo "Board HTTP-ready (PID $pid). Stop it with: $STOP_COMMAND"
    exit 0
  fi
  sleep 0.1
done
kill -TERM "$pid" 2>/dev/null || true
echo "Board probe timed out; see $LOG_FILE. No PID record was written." >&2
exit 1
