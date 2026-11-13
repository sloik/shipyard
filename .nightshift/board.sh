#!/usr/bin/env bash
# Launch Nightshift Board for this project.
# Port is hash-based per project (range 7800-7999) — same project always gets the same port.
# Usage: board.sh [--no-open] [--port N] [extra args passed to board.py]
#        --no-open: start without opening a browser (SPEC-417-003; board_ctl.py uses it)
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

OPEN_ARGS=(--open)
PASS_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--no-open" ]]; then OPEN_ARGS=(); else PASS_ARGS+=("$arg"); fi
done
set -- ${PASS_ARGS[@]+"${PASS_ARGS[@]}"}

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
# Ask board.py before spawning; argparse owns --specs/--port resolution too.
# run_path preserves a script's imports while keeping the selected runtime.
port="$("$PYTHON_RUNTIME" -c 'import os, runpy, sys; sys.argv = sys.argv[1:]; sys.path.insert(0, os.path.dirname(sys.argv[0])); runpy.run_path(sys.argv[0], run_name="__main__")' "$DIR/board.py" --print-port "$@")"
nohup "$PYTHON_RUNTIME" "$DIR/board.py" ${OPEN_ARGS[@]+"${OPEN_ARGS[@]}"} "$@" >>"$LOG_FILE" 2>&1 < /dev/null &
pid="$!"
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
