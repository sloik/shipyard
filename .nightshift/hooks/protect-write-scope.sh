#!/bin/sh
# protect-write-scope.sh — SPEC-300-003 git pre-commit write-scope guard
#
# Portable backstop for SPEC-300 (write-scope lock): rejects a commit that
# stages any path outside the active spec's declared `scope.write`, using the
# shared `scope_guard.py` resolver (SPEC-300-001) so every enforcement point
# agrees on the same classification. Git hooks live in the shared common
# directory, so this fires in every worktree of the repository regardless of
# harness.
#
# Active-spec resolution (R1): `scope_guard.py active_spec` — env var
# (NIGHTSHIFT_ACTIVE_SPEC) first, then the `nightshift/<SPEC-ID>-<run-id>`
# branch name. With no active spec, only the two universal rules apply
# (spec-home, malformed-target); everything else is allowed (R1, R13).
#
# With an active spec (R2), scope is read from the *main* branch via
# `scope_guard.py`'s public `scope_from_main` — never from this worktree or
# branch — and every staged path is classified with `classify_write`. The
# staged-path list comes from `git diff --cached --name-status
# --diff-filter=ACDMR -M -z` rather than the literal `--name-only` shape:
# `--name-only` never reports the pre-image of a detected rename, and AC7
# requires the guard to name the *destination* of a `git mv`. `--name-status`
# gives both sides for a rename (`R100<NUL>old<NUL>new<NUL>`) and every path
# it yields is fed through the same `classify_write` used everywhere else —
# nothing here reimplements the glob matching, only the "which paths did this
# commit touch" extraction that scope_guard.py's own CLI performs internally
# with `--paths-from-stdin`. `-z` avoids git's C-style quoting of paths with
# unusual bytes, matching AC7's malformed-target fixture.
#
# Fails OPEN on internal error — resolver missing, git failure, unparsable
# spec — printing a one-line `[nightshift write-scope]` warning and allowing
# the commit (R3). This mirrors protect-live-data.sh. Only the dedicated exit
# code below (WRITE_SCOPE_BLOCK_CODE) blocks; protect-live-data.sh already
# uses 97, so this guard uses 96.
#
# No environment-variable bypass (R4, SPEC-300 Out of Scope). The only way to
# commit an out-of-scope path is a human-approved `## Scope Amendments` row on
# main widening `scope.write`, or removing the path from the index with
# `git reset HEAD -- <path>`.

WRITE_SCOPE_BLOCK_CODE=96

warn() {
  printf '[nightshift write-scope] %s\n' "$1" >&2
}

toplevel=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$toplevel" ]; then
  warn "git toplevel unavailable; failing open"
  exit 0
fi

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

# The main branch scope is always read from, per SPEC-300 R3/§ Enforcement.
# Resolve it the same way protect-primary-branch.sh does: configured
# main_branch first, then the remote's default, then a literal fallback.
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
  main_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
fi
[ -n "$main_branch" ] || main_branch="main"

python3 - "$toplevel" "$resolver" "$main_branch" "$WRITE_SCOPE_BLOCK_CODE" <<'PY'
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

project_root = Path(sys.argv[1])
resolver_path = sys.argv[2]
main_branch = sys.argv[3]
block_code = int(sys.argv[4])


def warn(message: str) -> None:
    print(f"[nightshift write-scope] {message}", file=sys.stderr)


try:
    spec = importlib.util.spec_from_file_location("scope_guard", resolver_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scope_guard"] = module
    spec.loader.exec_module(module)
except Exception as exc:  # pragma: no cover - defensive, fail open
    warn(f"scope_guard.py failed to load ({exc}); failing open")
    raise SystemExit(0)

try:
    branch_proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else None

    spec_id = module.active_spec(dict(os.environ), branch)

    diff_proc = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--diff-filter=ACDMR", "-M", "-z"],
        cwd=project_root, capture_output=True,
    )
    if diff_proc.returncode != 0:
        warn("git diff --cached failed; failing open")
        raise SystemExit(0)

    tokens = [
        token.decode("utf-8", errors="surrogateescape")
        for token in diff_proc.stdout.split(b"\0")
        if token != b""
    ]

    # SPEC-375: each collected path carries whether it must skip the
    # universal spec_wrong_home check. A rename's OLD (source) path and a
    # plain deletion's path are the vanishing/departing side of the change —
    # spec_wrong_home denying them would trap a misplaced spec file forever
    # (it could never be deleted or renamed away). A rename's NEW
    # (destination) path and every added/modified path are classified
    # exactly as before (R1/R2).
    entries: list[tuple[str, bool]] = []  # (path, skip_spec_home)
    i = 0
    while i < len(tokens):
        status = tokens[i]
        i += 1
        if status[:1] in ("R", "C") and i + 1 < len(tokens):
            entries.append((tokens[i], True))       # rename source
            entries.append((tokens[i + 1], False))  # rename destination
            i += 2
        elif status[:1] == "D" and i < len(tokens):
            entries.append((tokens[i], True))        # plain deletion
            i += 1
        elif i < len(tokens):
            entries.append((tokens[i], False))       # added/modified
            i += 1

    # Dedupe while unioning per-path flags: if the same path appears both as
    # a skip-worthy occurrence (rename source / deletion) and as an
    # added/modified or rename-destination occurrence, the latter always
    # wins — a path must never escape spec_wrong_home just because one of
    # several diff entries naming it happened to be a departing side.
    skip_spec_home: dict[str, bool] = {}
    unique_paths: list[str] = []
    for p, skip in entries:
        if p not in skip_spec_home:
            unique_paths.append(p)
            skip_spec_home[p] = skip
        else:
            skip_spec_home[p] = skip_spec_home[p] and skip

    if not unique_paths:
        raise SystemExit(0)

    spec_file = None
    if spec_id:
        specs_dirs = (
            project_root / "canonical" / "specs",
            project_root / "specs",
            project_root / ".nightshift" / "specs",
        )
        for specs_dir in specs_dirs:
            if not specs_dir.is_dir():
                continue
            matches = sorted(specs_dir.glob(f"{spec_id}-*.md")) + sorted(specs_dir.glob(f"{spec_id}.md"))
            if matches:
                spec_file = matches[0]
                break

    if spec_file is not None:
        spec_relpath = str(spec_file.relative_to(project_root)).replace("\\", "/")
        kit_dir = spec_file.parent.parent
        scope = module.scope_from_main(project_root, spec_relpath, main_branch)
    else:
        spec_relpath = spec_id or None
        kit_dir = project_root / "canonical" if (project_root / "canonical").is_dir() else project_root / ".nightshift"
        scope = None

    # SPEC-375: for a path whose only diff occurrences skip spec_wrong_home
    # (a rename source or a plain deletion), override classify_write's
    # specs-directory discovery with the path's own parent directory. Every
    # OTHER rule (malformed_target, denied_glob, outside_root, ...) still
    # runs unmodified on the same call — only the spec-home violation is
    # forced to `False` for this one path, because its own parent trivially
    # satisfies "parent_dir in specs_dirs" for _is_spec_home_violation.
    # SPEC-376: a root-level path (no "/" at all) has no parent to pass
    # through `_known_specs_dirs`'s realpath-relative-to-project_root
    # resolution — that resolution can only ever produce the literal string
    # "." for `project_root` itself (never the empty string
    # `_is_spec_home_violation`'s own `parent_dir` computation uses for a
    # root-level path), so passing `{project_root}` here can never match.
    # An empty set instead makes `_known_specs_dirs` report "discovery
    # failed" and `_is_spec_home_violation` fall open (no violation) for
    # this one classify_write call — the same "exempt this one path" effect
    # AC1 requires, achieved without changing scope_guard.py itself.
    def _spec_375_home_override(path_str: str) -> set:
        normalized = path_str.replace("\\", "/")
        parent = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
        return {project_root / parent} if parent else set()

    decisions = [
        module.classify_write(
            p, scope, project_root, kit_dir, spec_relpath,
            known_specs_dirs=_spec_375_home_override(p),
        )
        if skip_spec_home[p]
        else module.classify_write(p, scope, project_root, kit_dir, spec_relpath)
        for p in unique_paths
    ]
    denies = [d for d in decisions if not d.allowed]
    if not denies:
        raise SystemExit(0)

    if scope is not None and scope.write:
        declared = ", ".join(scope.write)
    else:
        declared = "**"
    header_spec = spec_id or "(no active spec)"

    warn(f"BLOCKED — spec {header_spec} declares write scope: {declared}")
    warn("The following staged paths are out of scope:")
    for d in denies:
        warn(f"  DENY {d.reason} {d.path}")
    warn("Retry in the declared scope, or record a Scope Blocker and ask a human to")
    warn("add a '## Scope Amendments' row on main. There is no environment-variable")
    warn("bypass; to commit without the path, remove it from the index with:")
    warn("  git reset HEAD -- <path>")
    raise SystemExit(block_code)
except SystemExit:
    raise
except Exception as exc:  # pragma: no cover - defensive, fail open
    warn(f"internal error ({exc}); failing open")
    raise SystemExit(0)
PY
exit $?
