#!/usr/bin/env bash
# Launch Nightshift Board for this project.
# Port is hash-based per project (range 7800-7999) — same project always gets the same port.
# Usage: .nightshift/board.sh [--port N] [extra args passed to board.py]
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/board.py" --open "$@"
