#!/usr/bin/env python3
"""Safe, project-owned paths for Nightshift linked worktrees."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path


class WorktreePathError(RuntimeError):
    """Raised when a worktree path is unsafe or belongs to another repository."""


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_SYNC_ROOT_NAMES = {"dropbox", "onedrive", "icloud drive"}


def _component(value: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("-", value.strip()).strip("-.")
    if not cleaned:
        raise WorktreePathError(f"unsafe empty path component derived from {value!r}")
    return cleaned


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sync_root(path: Path) -> Path | None:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if candidate.name.casefold() in _SYNC_ROOT_NAMES:
            return candidate
    return None


def repository_namespace(repo_root: Path) -> str:
    """Return a stable namespace that distinguishes equal repository basenames."""
    resolved = Path(repo_root).resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return f"{_component(resolved.name)}-{digest}"


def worktree_base(repo_root: Path, *, base_root: Path | None = None) -> Path:
    """Return the safe, deterministic worktree base for one repository."""
    repo = Path(repo_root).resolve()
    configured = base_root or os.environ.get("NIGHTSHIFT_WORKTREE_ROOT")
    root = Path(configured).expanduser().resolve() if configured else Path(tempfile.gettempdir()).resolve() / "nightshift-worktrees"

    if _is_within(root, repo):
        raise WorktreePathError(f"worktree root must be outside the repository: {root}")
    sync_root = _sync_root(repo)
    if sync_root is not None and _is_within(root, sync_root):
        raise WorktreePathError(f"worktree root must be outside synchronized root {sync_root}: {root}")
    return root / repository_namespace(repo)


def worktree_path(repo_root: Path, spec_id: str, *, base_root: Path | None = None) -> Path:
    """Compute the canonical local-temp path for a spec worktree."""
    return worktree_base(repo_root, base_root=base_root) / _component(spec_id)


def git_common_dir(checkout: Path) -> Path:
    """Resolve the Git common directory for a primary or linked checkout."""
    checkout = Path(checkout).resolve()
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise WorktreePathError(f"not a Git checkout: {checkout}")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = checkout / common
    return common.resolve()


def assert_worktree_owner(repo_root: Path, candidate: Path) -> None:
    """Fail unless candidate is a linked checkout owned by repo_root."""
    expected = git_common_dir(repo_root)
    actual = git_common_dir(candidate)
    if actual != expected:
        raise WorktreePathError(
            f"foreign worktree {Path(candidate).resolve()}: common dir {actual} != {expected}"
        )


def assert_managed_worktree_path(repo_root: Path, candidate: Path) -> None:
    """Fail unless candidate is inside this repository's canonical temp namespace."""
    base = worktree_base(repo_root)
    resolved = Path(candidate).resolve()
    if not _is_within(resolved, base) or resolved == base:
        raise WorktreePathError(f"worktree path is outside managed namespace {base}: {resolved}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--repo", required=True, type=Path)
    plan.add_argument("--spec", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo", required=True, type=Path)
    verify.add_argument("--worktree", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "plan":
        print(worktree_path(args.repo, args.spec))
    else:
        assert_managed_worktree_path(args.repo, args.worktree)
        assert_worktree_owner(args.repo, args.worktree)
        print(Path(args.worktree).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
