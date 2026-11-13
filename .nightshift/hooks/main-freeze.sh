#!/usr/bin/env bash
# main-freeze.sh -- Nightshift advisory main-branch freeze lease (SPEC-NS-KIT-001)
#
# A freeze is a local-coordinator path claim on a reserved key, held by the
# requesting session. This script is the one implementation of the read side:
# the kit's pre-commit hook and the coordinator's merge path both call it.
#
# Usage:
#   main-freeze.sh check [--assume-main]  exit 0 = allow (a warning may print),
#                                         exit 3 = refuse (message on stderr).
#                                         --assume-main skips the branch test
#                                         (merge path: the target is main).
#   main-freeze.sh key                    print the reserved claim key
#   main-freeze.sh status                 print the live lease, if any
#
# Reserved key: <realpath of git common dir>/.nightshift-main-freeze. Every
# worktree of a repository shares one common dir, so they share one key; the
# path is never an ancestor or descendant of a working path.
#
# Read path (one bounded call per commit): one read-only sqlite connection to
# the coordinator store ($AGENT_CHAT_LOCAL_COORDINATOR_DB, default
# ~/.agent-chat-mcp/local-coordinator.db), 0.2 s busy timeout, hard 2 s alarm.
# Fail open (R5): a schema error, lock, timeout or crash warns and exits 0.
# A store file that does not exist (project never ran the coordinator) is not
# a failure: check allows silently (BUG-NS-KIT-103); NIGHTSHIFT_MAIN_FREEZE_VERBOSE=1
# restores a one-line note. The freeze is a coordination aid, not a security control;
# `git commit --no-verify` bypasses it like every other kit hook.
#
# Holder identity: NIGHTSHIFT_COORDINATOR_SESSION (a coordinator session id),
# else the first set of CLAUDE_CODE_SESSION_ID / CODEX_THREAD_ID /
# HERMES_SESSION_ID, mapped through local_sessions.external_id (not ended).
# With a live lease and an unresolved committer the commit is refused.

mode="${1:-check}"
assume_main=0
if [ "${2:-}" = "--assume-main" ]; then assume_main=1; fi

warn() {
    printf '%s\n' "[nightshift main-freeze] WARNING: $1; the freeze lease could not be checked, so this was allowed (advisory lease, SPEC-NS-KIT-001)" >&2
}

common_dir=$(git rev-parse --git-common-dir 2>/dev/null) || common_dir=""
if [ -z "$common_dir" ]; then
    if [ "$mode" = "check" ]; then exit 0; fi
    echo "main-freeze: not inside a git repository" >&2
    exit 1
fi

if [ "$mode" = "check" ] && [ "$assume_main" -eq 0 ]; then
    branch=$(git symbolic-ref -q --short HEAD 2>/dev/null) || branch=""
    main_branch=""
    here=$(cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || here=""
    if [ -n "$here" ] && [ -f "$here/../config.yaml" ]; then
        main_branch=$(grep -E '^[[:space:]]*main_branch:' "$here/../config.yaml" 2>/dev/null | head -1 \
            | sed -E 's/.*main_branch:[[:space:]]*"?([^"#[:space:]]+)"?.*/\1/') || main_branch=""
    fi
    if [ -z "$main_branch" ]; then main_branch=main; fi
    # Off the main branch (feature branch, run branch, detached HEAD): no probe.
    if [ "$branch" != "$main_branch" ]; then exit 0; fi
fi

if ! command -v python3 >/dev/null 2>&1; then
    if [ "$mode" = "check" ]; then warn "python3 is unavailable"; exit 0; fi
    echo "main-freeze: python3 is unavailable" >&2
    exit 1
fi

rc=0
python3 - "$mode" "$common_dir" <<'PY' || rc=$?
import os
import signal
import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import quote

HEADER = "BLOCKED by main-freeze lease (SPEC-NS-KIT-001)"
REASON_PREFIX = "main-freeze: "
mode, common_dir = sys.argv[1], sys.argv[2]
signal.alarm(2)  # default SIGALRM action kills the probe; the caller then fails open.

key = os.path.join(os.path.realpath(common_dir), ".nightshift-main-freeze")
if mode == "key":
    print(key)
    raise SystemExit(0)

db_path = os.environ.get("AGENT_CHAT_LOCAL_COORDINATOR_DB") or os.path.expanduser(
    "~/.agent-chat-mcp/local-coordinator.db")


if not os.path.exists(db_path):
    if mode == "status":
        print(f"no coordinator store at {db_path}; no main freeze is possible")
    elif os.environ.get("NIGHTSHIFT_MAIN_FREEZE_VERBOSE") == "1":
        print(f"[nightshift main-freeze] no coordinator store at {db_path}; no freeze lease to check", file=sys.stderr)
    raise SystemExit(0)


def fail_open(reason):
    print(f"[nightshift main-freeze] WARNING: {reason}; the freeze lease could not be checked, "
          "so this was allowed (advisory lease, SPEC-NS-KIT-001)", file=sys.stderr)
    raise SystemExit(0)


def parse(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


try:
    con = sqlite3.connect(f"file:{quote(db_path)}?mode=ro", uri=True, timeout=0.2)
    row = con.execute(
        "SELECT c.session_id, c.purpose, c.expires_at, s.label, s.status "
        "FROM local_path_claims c LEFT JOIN local_sessions s ON s.session_id = c.session_id "
        "WHERE c.canonical_path = ?", (key,)).fetchone()
    expires = parse(row[2]) if row else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    live = bool(row) and row[4] is not None and row[4] != "ended" and expires is not None and expires > now
    committers = set()
    if live:
        override = os.environ.get("NIGHTSHIFT_COORDINATOR_SESSION", "").strip()
        external = next((os.environ.get(n, "").strip() for n in
                         ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID")
                         if os.environ.get(n, "").strip()), "")
        if override:
            query, arg = "SELECT session_id FROM local_sessions WHERE session_id = ? AND status != 'ended'", override
        elif external:
            query, arg = "SELECT session_id FROM local_sessions WHERE external_id = ? AND status != 'ended'", external
        else:
            query, arg = None, None
        if query:
            committers = {r[0] for r in con.execute(query, (arg,))}
    con.close()
except SystemExit:
    raise
except Exception as error:  # noqa: BLE001 - any read failure is advisory-outage fail-open
    fail_open(f"coordinator store unreadable ({type(error).__name__}: {error})")

if not live:
    if mode == "status":
        print("no live main freeze for this repository")
    raise SystemExit(0)

holder, purpose, expires_at, label = row[0], row[1] or "", row[2], row[3] or "(no label)"
reason = purpose[len(REASON_PREFIX):] if purpose.startswith(REASON_PREFIX) else purpose or "(no reason recorded)"
minutes = max(0, int((expires - now).total_seconds() // 60))
is_holder = holder in committers
if mode == "status":
    print(f"live main freeze held by {holder} [{label}]{' (this session)' if is_holder else ''}: "
          f"{reason}; expires {expires_at} (~{minutes} min)")
    raise SystemExit(0)
if is_holder:
    raise SystemExit(0)

lines = [
    f"X {HEADER}: commits to the main branch are frozen",
    f"   Holder:  {holder} [{label}]",
    f"   Reason:  {reason}",
    f"   Expires: {expires_at} (~{minutes} min; renewal extends it)",
    f'   Release: the holder calls local_session_release_claim("{holder}", "{key}") or ends its session;',
    "            a human can run the same call with the holder's session id, or wait for expiry.",
]
if not committers:
    lines.append("   This committer's coordinator session could not be resolved; set "
                 "NIGHTSHIFT_COORDINATOR_SESSION=<coordinator session id> if you are the holder.")
lines.append("   Deliberate override: git commit --no-verify")
print("\n".join(lines), file=sys.stderr)
raise SystemExit(3)
PY

case "$rc" in
    0|3) exit "$rc" ;;
esac
if [ "$mode" = "check" ]; then
    warn "the freeze probe failed or timed out (exit $rc)"
    exit 0
fi
exit "$rc"
