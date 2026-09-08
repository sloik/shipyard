#!/bin/sh
# write-scope-hook.sh — SPEC-300-004 Claude Code PreToolUse write-scope hook
#
# Earliest enforcement point for SPEC-300 (write-scope lock): stops an
# out-of-scope write before the tool call executes, using the shared
# `scope_guard.py` resolver (SPEC-300-001) so this hook, the git pre-commit
# guard (SPEC-300-003) and the evidence gate all agree on one classification.
#
# PreToolUse contract (verified against the current Claude Code hooks
# reference, not from memory): the event JSON arrives on stdin with at least
# `tool_name`, `tool_input`, and `cwd`; a decision is returned as
#   {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#     "permissionDecision": "deny"|"allow", "permissionDecisionReason": "..."}}
# on stdout, or by staying silent and exiting 0 to let the normal permission
# flow apply (mirrors ~/.claude/hooks/devkb-enforce.sh, the precedent named
# in the spec's Context).
#
# Coverage:
#   - Edit|Write|MultiEdit|NotebookEdit (R1): classify `tool_input.file_path`
#     (or `notebook_path`) with `scope_guard.classify_write` against the
#     active spec's scope as committed on main. No active spec -> only the
#     two universal rules (spec-home, malformed-target) apply; everything
#     else allows (`no_active_spec`).
#   - Bash (R2): best-effort extraction of write targets from a bounded
#     pattern list (redirects, cp/mv/install/rsync, mkdir/touch, tee,
#     sed -i). Unparseable commands are ignored -- the git guard and the
#     evidence gate are the backstops (Out of Scope: complete Bash write
#     detection). The heartbeat `cp` to
#     `.../reports/_wip/orchestrator-progress-<spec-id>.md` is explicitly
#     allowed (SKILL.md "Worktree-isolation write method") even when that
#     destination sits outside this worktree, in the sibling main checkout.
#   - Read|Grep|Glob (R3): only enforced when the active spec's `scope.read`
#     is a list; `unrestricted` (the default) exits 0 without ever calling
#     the resolver.
#
# Fails OPEN on any internal error -- missing `jq`/`python3`, a missing or
# unreadable `scope_guard.py`, unparsable input -- with a one-line stderr
# warning (R4). No environment-variable bypass exists (R5): the only way to
# widen scope is a human-approved amendment row on main.
#
# A per-event debug line (tool, reason, path) is appended to
# reports/_wip/write-scope-hook-debug.log under the resolved kit dir --
# never to the tool's own stdout/stderr the way the deny message is, per the
# spec's Research Hints.

warn() {
  printf '[nightshift write-scope] %s\n' "$1" >&2
}

command -v jq >/dev/null 2>&1 || { warn "jq not found; failing open"; exit 0; }
command -v python3 >/dev/null 2>&1 || { warn "python3 not found; failing open"; exit 0; }

INPUT=$(cat) || { warn "failed to read stdin; failing open"; exit 0; }
[ -n "$INPUT" ] || exit 0

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[ -n "$TOOL_NAME" ] || exit 0

case "$TOOL_NAME" in
  Edit|Write|MultiEdit|NotebookEdit|Bash|Read|Grep|Glob) ;;
  *) exit 0 ;;
esac

CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$CWD" ] || CWD="$PWD"

toplevel=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null)
[ -n "$toplevel" ] || { warn "git toplevel unavailable for $CWD; failing open"; exit 0; }

resolver=""
for r in "$toplevel/ManagedProjects/Nightshift/canonical/scope_guard.py" \
         "$toplevel/canonical/scope_guard.py" \
         "$toplevel/.nightshift/scope_guard.py"; do
  if [ -f "$r" ]; then resolver="$r"; break; fi
done
if [ -z "$resolver" ]; then
  warn "scope_guard.py not found in this checkout; failing open"
  exit 0
fi

branch=$(git -C "$toplevel" rev-parse --abbrev-ref HEAD 2>/dev/null)

main_branch=""
for cfg in "$toplevel/.nightshift/config.yaml" \
           "$toplevel/ManagedProjects/Nightshift/canonical/config.yaml" \
           "$toplevel/canonical/config.yaml"; do
  if [ -f "$cfg" ]; then
    main_branch=$(grep -E '^[[:space:]]*main_branch:' "$cfg" 2>/dev/null | head -1 \
      | sed -E 's/.*main_branch:[[:space:]]*"?([^"#[:space:]]*)"?.*/\1/')
    [ -n "$main_branch" ] && break
  fi
done
if [ -z "$main_branch" ]; then
  main_branch=$(git -C "$toplevel" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
fi
[ -n "$main_branch" ] || main_branch="main"

TMP_INPUT=$(mktemp "${TMPDIR:-/tmp}/nightshift-write-scope-input.XXXXXX" 2>/dev/null) || { warn "mktemp failed; failing open"; exit 0; }
trap 'rm -f "$TMP_INPUT"' EXIT
printf '%s' "$INPUT" > "$TMP_INPUT"

python3 - "$toplevel" "$resolver" "$main_branch" "$branch" "$TMP_INPUT" <<'PY'
import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path


def warn(message: str) -> None:
    print(f"[nightshift write-scope] {message}", file=sys.stderr)


try:
    project_root = Path(sys.argv[1])
    resolver_path = sys.argv[2]
    main_branch = sys.argv[3]
    branch = sys.argv[4] or None
    input_path = sys.argv[5]

    try:
        spec = importlib.util.spec_from_file_location("scope_guard", resolver_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["scope_guard"] = module
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - defensive, fail open
        warn(f"scope_guard.py failed to load ({exc}); failing open")
        raise SystemExit(0)

    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            payload = json.loads(fh.read())
    except Exception as exc:
        warn(f"unparsable PreToolUse input ({exc}); failing open")
        raise SystemExit(0)

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    _debug_log_path: Path | None = None

    def log_debug(line: str) -> None:
        global _debug_log_path
        try:
            if _debug_log_path is None:
                _debug_log_path = kit_dir / "reports" / "_wip" / "write-scope-hook-debug.log"
                _debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(_debug_log_path, "a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
        except Exception:  # pragma: no cover - debug log is best-effort only
            pass

    def emit_deny(message: str) -> None:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }))

    env = dict(os.environ)
    active_spec_id = module.active_spec(env, branch)
    spec_label = active_spec_id or "(no active spec)"

    spec_file = None
    spec_relpath = None
    kit_dir = project_root / "canonical" if (project_root / "canonical").is_dir() else project_root / ".nightshift"
    scope = None

    if active_spec_id:
        for specs_dir in (
            project_root / "canonical" / "specs",
            project_root / "specs",
            project_root / ".nightshift" / "specs",
        ):
            if not specs_dir.is_dir():
                continue
            matches = sorted(specs_dir.glob(f"{active_spec_id}-*.md")) + sorted(specs_dir.glob(f"{active_spec_id}.md"))
            if matches:
                spec_file = matches[0]
                break
        if spec_file is not None:
            spec_relpath = str(spec_file.relative_to(project_root)).replace("\\", "/")
            kit_dir = spec_file.parent.parent
            scope = module.scope_from_main(project_root, spec_relpath, main_branch)
        else:
            spec_relpath = active_spec_id

    def declared_write() -> str:
        if scope is not None and scope.write:
            return ", ".join(scope.write)
        return "**"

    def deny_write_message(path: str, reason: str) -> str:
        return (
            f"{spec_label}: {path} is outside the declared write scope ({reason}). "
            f"Declared write: [{declared_write()}]. Retry in the correct location; if "
            "this write is genuinely required, do not perform it — record it under "
            "\"## Scope Blockers\" in your report and return worker-blocked."
        )

    def deny_read_message(path: str, declared: str) -> str:
        return (
            f"{spec_label}: {path} is outside the declared read scope. "
            f"Declared read: [{declared}]."
        )

    # A tool call's destination is not always a project path at all: /dev/null
    # (idiomatic in `> /dev/null 2>&1`) and the harness's own scratch
    # directories (TMPDIR, /tmp, /var/folders — this repo's own Nightshift
    # scratchpad convention lives there) are never part of any spec's
    # write-scope contract and were never in the git guard's domain either
    # (a scratch write is never staged). scope_guard.classify_write has no
    # concept of "not a project path" for an absolute destination outside the
    # project root -- it correctly reports outside_root -- so this hook (the
    # only enforcement point that sees every tool call, not just staged
    # paths) carves those two cases out before classification, never after.
    def _scratch_roots() -> list[str]:
        roots = ["/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"]
        tmpdir = os.environ.get("TMPDIR")
        if tmpdir:
            roots.append(tmpdir.replace("\\", "/").rstrip("/") + "/")
        return roots

    def _is_scratch_or_devnull(path_str: str) -> bool:
        normalized = path_str.replace("\\", "/")
        if normalized == "/dev/null" or normalized.startswith("/dev/"):
            return True
        if not normalized.startswith("/"):
            return False
        return any(normalized.startswith(root) for root in _scratch_roots())

    EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    READ_TOOLS = {"Read", "Grep", "Glob"}

    if tool_name in EDIT_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not path:
            raise SystemExit(0)
        if _is_scratch_or_devnull(path):
            log_debug(f"{tool_name} scratch_path {path}")
            raise SystemExit(0)
        decision = module.classify_write(path, scope, project_root, kit_dir, spec_relpath)
        log_debug(f"{tool_name} {decision.reason} {path}")
        if not decision.allowed:
            emit_deny(deny_write_message(path, decision.reason))
        raise SystemExit(0)

    if tool_name == "Bash":
        command = tool_input.get("command") or ""

        _HEARTBEAT_TARGET_RE = re.compile(r"(?:^|/)reports/_wip/orchestrator-progress-(?P<spec_id>.+)\.md$")
        _SEGMENT_RE = re.compile(r"&&|\|\||;|\|")
        _REDIRECT_RE = re.compile(r'(?:^|\s)(>{1,2})\s*("(?:[^"\\]|\\.)*"|\'[^\']*\'|\S+)')

        def _unquote(raw: str) -> str:
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
                inner = raw[1:-1]
                if raw[0] == '"':
                    inner = inner.replace('\\"', '"')
                return inner
            return raw

        # An unresolvable destination (`$VAR`, `` `cmd` ``, `$(cmd)`) cannot be
        # safely classified at all -- attempting to would compare the literal
        # token text against scope globs, which is not the actual write
        # destination and produces a false DENY (a variable heartbeat
        # destination is the sharpest case: R2's carve-out exists precisely
        # to protect that write). R2's "targets it cannot parse are ignored"
        # license covers this: an unresolvable token is treated the same as
        # no extractable target at all, logged `unparsed`.
        _UNRESOLVABLE_RE = re.compile(r"[$`]")

        def _extractable(target: str) -> bool:
            return not _UNRESOLVABLE_RE.search(target)

        def extract_targets(cmd: str) -> list[tuple[str, str]]:
            found: list[tuple[str, str]] = []

            def add(base: str, target: str) -> None:
                if _extractable(target):
                    found.append((base, target))

            for segment in _SEGMENT_RE.split(cmd):
                segment = segment.strip()
                if not segment:
                    continue
                for match in _REDIRECT_RE.finditer(segment):
                    add("redirect", _unquote(match.group(2)))
                try:
                    tokens = shlex.split(segment)
                except ValueError:
                    continue
                if not tokens:
                    continue
                base = tokens[0].rsplit("/", 1)[-1]
                args = tokens[1:]
                positional = [a for a in args if not a.startswith("-")]
                if base in ("cp", "mv", "install", "rsync"):
                    if positional:
                        add(base, positional[-1])
                elif base in ("mkdir", "touch"):
                    for p in positional:
                        add(base, p)
                elif base == "tee":
                    for p in positional:
                        add(base, p)
                elif base == "sed":
                    if any(a == "-i" or a.startswith("-i") for a in args) and positional:
                        add(base, positional[-1])
            return found

        targets = extract_targets(command)
        if not targets:
            log_debug(f"Bash unparsed {command[:200]}")
            raise SystemExit(0)

        for cmd_base, target in targets:
            if _is_scratch_or_devnull(target):
                log_debug(f"Bash scratch_path {target}")
                continue
            heartbeat_match = _HEARTBEAT_TARGET_RE.search(target.replace("\\", "/"))
            if cmd_base == "cp" and heartbeat_match and (
                active_spec_id is None or heartbeat_match.group("spec_id") == active_spec_id
            ):
                log_debug(f"Bash heartbeat {target}")
                continue
            decision = module.classify_write(target, scope, project_root, kit_dir, spec_relpath)
            log_debug(f"Bash {decision.reason} {target}")
            if not decision.allowed:
                emit_deny(deny_write_message(target, decision.reason))
                raise SystemExit(0)
        raise SystemExit(0)

    if tool_name in READ_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern")
        if not path:
            raise SystemExit(0)
        if scope is None or scope.read == "unrestricted":
            raise SystemExit(0)
        decision = module.classify_read(path, scope, project_root)
        log_debug(f"{tool_name} {decision.reason} {path}")
        if not decision.allowed:
            declared = ", ".join(scope.read) if isinstance(scope.read, list) else "unrestricted"
            emit_deny(deny_read_message(path, declared))
        raise SystemExit(0)

    raise SystemExit(0)
except SystemExit:
    raise
except Exception as exc:  # pragma: no cover - defensive, fail open
    warn(f"internal error ({exc}); failing open")
    raise SystemExit(0)
PY
exit $?
