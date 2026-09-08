#!/bin/sh
# install-write-scope-hook.sh (SPEC-300-004)
# Wire write-scope-hook.sh into THIS project's Claude Code project settings
# (`.claude/settings.json` at the git toplevel) as three `PreToolUse` entries
# -- one matcher per tool set from the spec (Edit|Write|MultiEdit|NotebookEdit,
# Bash, Read|Grep|Glob) -- each carrying a `nightshift-write-scope: true`
# marker key so the installer, `--uninstall`, and `doctor.py`'s D8 finding can
# all recognise them without disturbing any other configured hook.
#
# Idempotent: re-running removes and re-adds exactly the three marked
# entries, so a second run never duplicates them. `--uninstall` removes only
# the marked entries and leaves every other `PreToolUse` entry (and the rest
# of settings.json) untouched.
#
# Run once per project. Init/retrofit offer this alongside the pre-commit
# write-scope guard offer (SPEC-300-003's install-write-scope-guard.sh).
#
# Confirmed live (SPEC-318): a marked `PreToolUse` entry installed before a
# session starts IS fired by a genuinely fresh Claude Code session, with the
# `nightshift-write-scope` sibling key intact -- Claude Code's `PreToolUse[]`
# loader tolerates the unrecognised marker key rather than rejecting or
# dropping the entry. BUG-022's original symptom (installing the hook, then
# immediately attempting a deny-candidate write in the same already-running
# session, was not denied) is explained by ordinary session-lifecycle timing:
# that session's hook config predated the installer's write, not by any
# schema issue. No marker-key change is needed. Test method: a disposable
# git-initialized project, hook installed via this script, then a separate
# `claude -p` process (a genuinely new OS process/session) started afterward
# against that project attempted the same malformed_target deny-candidate
# BUG-022 used; the write was denied on 3/3 runs (see
# canonical/reports/SPEC-318/artifacts/). One caveat surfaced during this
# testing, unrelated to the marker key: do not root a test project for this
# hook under `/tmp`, `/private/tmp`, `/var/folders`, or `$TMPDIR` --
# write-scope-hook.sh's own scratch-write exemption unconditionally allows
# any absolute path under those roots, which will falsely look like a denied
# write never fired.
set -eu

command -v python3 >/dev/null 2>&1 || { echo "install-write-scope-hook: python3 not found" >&2; exit 1; }

toplevel=$(git rev-parse --show-toplevel 2>/dev/null) || toplevel="$PWD"

hook_script=""
for h in "$toplevel/ManagedProjects/Nightshift/canonical/hooks/write-scope-hook.sh" \
         "$toplevel/canonical/hooks/write-scope-hook.sh" \
         "$toplevel/.nightshift/hooks/write-scope-hook.sh"; do
  if [ -f "$h" ]; then hook_script="$h"; break; fi
done
if [ -z "$hook_script" ]; then
  echo "install-write-scope-hook: write-scope-hook.sh not found in this checkout" >&2
  exit 1
fi

settings="$toplevel/.claude/settings.json"
MARKER="nightshift-write-scope"

ACTION="install"
if [ "${1:-}" = "--uninstall" ]; then
  ACTION="uninstall"
fi

python3 - "$settings" "$hook_script" "$MARKER" "$ACTION" <<'PY'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
hook_script = sys.argv[2]
marker = sys.argv[3]
action = sys.argv[4]

if settings_path.is_file():
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"install-write-scope-hook: {settings_path} is not valid JSON ({exc}); refusing to modify", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(data, dict):
        print(f"install-write-scope-hook: {settings_path} is not a JSON object; refusing to modify", file=sys.stderr)
        raise SystemExit(1)
else:
    data = {}

hooks = data.setdefault("hooks", {})
pretooluse = hooks.get("PreToolUse", [])
if not isinstance(pretooluse, list):
    print(f"install-write-scope-hook: hooks.PreToolUse in {settings_path} is not a list; refusing to modify", file=sys.stderr)
    raise SystemExit(1)

# Idempotency and --uninstall share one step: drop every previously marked
# entry, then (install only) re-add the current set. This means a second
# install run never duplicates entries, and an uninstall after a stale
# install still removes exactly what's marked, even if the hook script path
# changed since.
kept = [e for e in pretooluse if not (isinstance(e, dict) and e.get(marker) is True)]
removed = len(pretooluse) - len(kept)

if action == "install":
    matchers = [
        "Edit|Write|MultiEdit|NotebookEdit",
        "Bash",
        "Read|Grep|Glob",
    ]
    for matcher in matchers:
        kept.append({
            "matcher": matcher,
            marker: True,
            "hooks": [
                # `timeout` is seconds, not milliseconds (verified against
                # the current Claude Code hooks reference: "Seconds before
                # canceling"; default 600 for a command hook). 10s is
                # generous for a python3 subprocess plus a couple of git
                # calls while still bounding a hung hook well under that
                # default (R4).
                {"type": "command", "command": hook_script, "timeout": 10},
            ],
        })
    hooks["PreToolUse"] = kept
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  PreToolUse: write-scope hook installed ({settings_path})")
else:
    if kept:
        hooks["PreToolUse"] = kept
    elif "PreToolUse" in hooks:
        del hooks["PreToolUse"]
    if settings_path.is_file():
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if removed:
        print(f"  PreToolUse: write-scope hook uninstalled ({settings_path})")
    else:
        print(f"  PreToolUse: write-scope hook was not installed ({settings_path})")
PY
