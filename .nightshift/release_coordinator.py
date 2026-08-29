#!/usr/bin/env python3
"""Guarded, repository-scoped coordinator for whole-kit Nightshift releases.

The coordinator deliberately owns git integration while ``release.py`` remains
the mechanical copy/verify primitive.  It never pushes and never stages paths
outside the computed release allowlist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import release
import release_handoff
from observability_enroll import release_disposition


@dataclass(frozen=True)
class MigrationRequest:
    install: str
    worker_id: str
    old_schema: str
    required_schema: str
    allowed_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    manifest_fingerprint: str
    isolation: str = "worktree"
    may_commit: bool = False
    may_push: bool = False
    may_merge: bool = False
    may_change_lifecycle: bool = False


@dataclass
class MigrationResult:
    worker_id: str
    changes: dict[str, str]
    validation_passed: bool
    isolation: str = "worktree"
    committed: bool = False
    pushed: bool = False
    merged: bool = False
    lifecycle_changed: bool = False
    details: list[str] = field(default_factory=list)


@dataclass
class RepositoryPlan:
    root: Path
    installs: list[Path]
    allowed_paths: set[str]
    committed_kit_policy: str | None
    policy_sources: tuple[str, ...]
    hook_policies: tuple[tuple[str, str], ...]


MigrationRunner = Callable[[MigrationRequest], MigrationResult]
SuiteRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
CANONICAL_SUITE_TIMEOUT_S = 600
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def _run_canonical_suite_step(
    runner: SuiteRunner,
    argv: list[str],
    canonical: Path,
) -> subprocess.CompletedProcess[str]:
    """Run one canonical-suite command without allowing release to hang forever."""
    try:
        return runner(argv, canonical)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        detail = f"canonical suite command exceeded {CANONICAL_SUITE_TIMEOUT_S}s: {' '.join(argv)}"
        return subprocess.CompletedProcess(
            argv, 124, stdout, f"{stderr}\n{detail}".strip()
        )


def _run_canonical_suite(
    argv: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run release preflight without leaking an operator commit authorization.

    ``NIGHTSHIFT_ESCALATION_SIGNOFF`` is intentionally consumed by a managed
    install's commit gate.  It must not change canonical test behavior, or the
    same release can pass or fail based on an operator decision unrelated to
    the kit under test.
    """
    environment = os.environ.copy()
    environment.pop("NIGHTSHIFT_ESCALATION_SIGNOFF", None)
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=CANONICAL_SUITE_TIMEOUT_S,
        env=environment,
    )


def _git_root(path: Path) -> Path | None:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def _relative(repo: Path, path: Path) -> str:
    return path.resolve().relative_to(repo).as_posix()


def _schema_version(install: Path) -> str:
    config = install / "config.yaml"
    if not config.is_file():
        return "missing"
    match = re.search(
        r'^schema_version:\s*["\']?([^"\'\s#]+)', config.read_text(), re.MULTILINE
    )
    return match.group(1) if match else "missing"


def _committed_kit_policy(install: Path) -> tuple[str | None, str]:
    config = install / "config.yaml"
    source = str(config)
    if not config.is_file():
        return None, source
    section = re.search(
        r"(?ms)^release_policy:\s*(?:#.*)?\n(?P<body>(?:^[ \t]+.*(?:\n|$))*)",
        config.read_text(),
    )
    if section is None:
        return None, source
    value = re.search(
        r'(?m)^[ \t]+committed_kit:\s*["\']?([^"\'\s#]+)',
        section.group("body"),
    )
    return (value.group(1) if value else "invalid:missing"), source


def _commit_hook_policies(repo: Path) -> tuple[tuple[str, str], ...]:
    hooks_result = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=repo)
    if hooks_result.returncode:
        return ()
    hooks = Path(hooks_result.stdout.strip())
    if not hooks.is_absolute():
        hooks = repo / hooks
    policies: list[tuple[str, str]] = []
    for name in ("pre-commit", "prepare-commit-msg", "commit-msg"):
        hook = hooks / name
        if not hook.is_file() or not hook.stat().st_mode & 0o111:
            continue
        marker = re.search(
            r"(?m)^\s*#\s*nightshift-release-policy:\s*"
            r"committed-kit=(allow|opt_out)\s*$",
            hook.read_text(errors="replace"),
        )
        if marker:
            policies.append((marker.group(1), str(hook.resolve())))
    return tuple(policies)


def _release_policy_errors(plan: RepositoryPlan) -> list[str]:
    errors: list[str] = []
    if plan.committed_kit_policy and plan.committed_kit_policy.startswith("invalid:"):
        errors.append(
            "invalid committed-kit release policy in " + ", ".join(plan.policy_sources)
        )
    hook_values = {value for value, _source in plan.hook_policies}
    hook_sources = [source for _value, source in plan.hook_policies]
    if len(hook_values) > 1:
        errors.append("conflicting commit-hook policies: " + ", ".join(hook_sources))
    elif hook_values:
        hook_policy = next(iter(hook_values))
        if plan.committed_kit_policy is None:
            errors.append(
                f"commit-hook policy {hook_policy} requires a project declaration; "
                f"hook source: {hook_sources[0]}; policy sources: "
                + ", ".join(plan.policy_sources)
            )
        elif plan.committed_kit_policy != hook_policy:
            errors.append(
                f"committed-kit policy {plan.committed_kit_policy} conflicts with "
                f"commit-hook policy {hook_policy}; policy sources: "
                + ", ".join(plan.policy_sources)
                + f"; hook source: {hook_sources[0]}"
            )
    return errors


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def _migration_needed(install: Path, required: str) -> bool:
    current = _schema_version(install)
    return not _version_tuple(current) or _version_tuple(current) < _version_tuple(
        required
    )


def _install_allowlist(repo: Path, install: Path, manifest: dict) -> set[str]:
    paths = {_relative(repo, install / entry["path"]) for entry in manifest["files"]}
    paths.add(_relative(repo, install / release.MARKER))
    if _migration_needed(install, manifest["schema_version"]):
        paths.add(_relative(repo, install / "config.yaml"))
    return paths


def _suite_argv(metadata: dict, phase: str) -> list[str]:
    """Build the declared dependency-capable suite command without a shell."""
    if metadata.get("runner") != "uv":
        raise ValueError("canonical suite runner must be uv")
    dependencies = metadata.get("dependencies")
    command = metadata.get(phase)
    if (
        not isinstance(dependencies, list)
        or not dependencies
        or not all(isinstance(item, str) and item.strip() for item in dependencies)
    ):
        raise ValueError("canonical suite dependencies must be non-empty strings")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item.strip() for item in command)
    ):
        raise ValueError(f"canonical suite {phase} must be a non-empty argv list")
    argv = ["uv", "run"]
    for dependency in dependencies:
        argv.extend(("--with", dependency))
    return argv + command


def _project_owned_managed_path(path: str) -> bool:
    """Keep generated project evidence private while admitting the schema."""
    parts = Path(path).parts
    if path == "metrics/_SCHEMA.md":
        return False
    return bool({"specs", "metrics", "knowledge"}.intersection(parts))


def _managed_relative(plan: RepositoryPlan, repo_path: str) -> str:
    """Strip the most-specific install prefix for repositories with nesting."""
    prefixes = sorted(
        (_relative(plan.root, install).rstrip("/") for install in plan.installs),
        key=len,
        reverse=True,
    )
    for prefix in prefixes:
        if repo_path.startswith(prefix + "/"):
            return repo_path.removeprefix(prefix + "/")
    return repo_path


def validate_release_ownership(
    plans: Iterable[RepositoryPlan], manifest: dict
) -> list[str]:
    """Prove copy/stage/commit ownership for every repo before first write."""
    errors: list[str] = []
    managed = {entry["path"] for entry in manifest["files"]}
    conflicts = sorted(path for path in managed if _project_owned_managed_path(path))
    if conflicts:
        errors.append(
            "manifest-managed paths are project-owned: " + ", ".join(conflicts)
        )
    for plan in plans:
        copy_paths = {
            _relative(plan.root, install / entry["path"])
            for install in plan.installs
            for entry in manifest["files"]
        }
        marker_paths = {
            _relative(plan.root, install / release.MARKER) for install in plan.installs
        }
        migration_paths = {
            _relative(plan.root, install / "config.yaml")
            for install in plan.installs
            if _migration_needed(install, manifest["schema_version"])
        }
        expected = copy_paths | marker_paths | migration_paths
        if plan.allowed_paths != expected:
            errors.append(f"release allowlist mismatch for repository: {plan.root}")
        for repo_path in sorted(copy_paths):
            relative = _managed_relative(plan, repo_path)
            if _project_owned_managed_path(relative):
                errors.append(
                    f"project-owned path entered release allowlist: {repo_path}"
                )
    return sorted(set(errors))


def plan_repositories(
    installs: Iterable[Path], manifest: dict
) -> tuple[list[RepositoryPlan], list[dict]]:
    grouped: dict[Path, list[Path]] = {}
    skipped: list[dict] = []
    for install in sorted({path.resolve() for path in installs}):
        repo = _git_root(install)
        if repo is None:
            skipped.append(
                {
                    "install": str(install),
                    "classification": "known_project_local",
                    "reason": "install is not inside a git repository",
                }
            )
            continue
        grouped.setdefault(repo, []).append(install)

    plans = []
    for repo, repo_installs in sorted(grouped.items(), key=lambda item: str(item[0])):
        allowed: set[str] = set()
        declarations = [_committed_kit_policy(install) for install in repo_installs]
        declared_values = {
            value for value, _source in declarations if value is not None
        }
        if len(declared_values) > 1:
            policy = "invalid:conflicting"
        else:
            policy = next(iter(declared_values), None)
        for install in repo_installs:
            allowed.update(_install_allowlist(repo, install, manifest))
        plans.append(
            RepositoryPlan(
                repo,
                repo_installs,
                allowed,
                policy,
                tuple(source for _value, source in declarations),
                _commit_hook_policies(repo),
            )
        )
    return plans, skipped


def _porcelain_paths(repo: Path) -> tuple[set[str], set[str]]:
    result = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    staged: set[str] = set()
    dirty: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1]
        dirty.add(path)
        if line[0] not in {" ", "?"}:
            staged.add(path)
    return staged, dirty


def preflight_repository(
    plan: RepositoryPlan,
    manifest: dict,
) -> list[str]:
    staged, dirty = _porcelain_paths(plan.root)
    errors = []
    unrelated_staged = sorted(staged - plan.allowed_paths)
    if unrelated_staged:
        errors.append("unrelated pre-staged paths: " + ", ".join(unrelated_staged))
    # Manifest payload is canonical-owned and is replaced deterministically on
    # every release.  Only configuration/migration paths are project-owned.
    payload_paths = {
        _relative(plan.root, install / entry["path"])
        for install in plan.installs
        for entry in manifest["files"]
    } | {_relative(plan.root, install / release.MARKER) for install in plan.installs}
    # Project-owned configuration is never canonical payload, even when its
    # schema already needs no migration and therefore is absent from the
    # commit allowlist.  A pre-existing edit must skip this repository before
    # payload copy: its local hook may inspect the whole worktree.
    project_owned_config = {
        _relative(plan.root, install / "config.yaml") for install in plan.installs
    }
    dirty_project_owned = sorted(
        ((dirty & plan.allowed_paths) - payload_paths) | (dirty & project_owned_config)
    )
    if dirty_project_owned:
        errors.append(
            "project-owned release paths require separate configuration migration: "
            + ", ".join(dirty_project_owned)
        )
    return errors


def build_migration_request(
    install: Path,
    manifest: dict,
    sequence: int,
) -> MigrationRequest:
    return MigrationRequest(
        install=str(install),
        worker_id=f"release-migration-{sequence:03d}",
        old_schema=_schema_version(install),
        required_schema=manifest["schema_version"],
        allowed_paths=("config.yaml", ".migrations/"),
        validation_commands=tuple(
            manifest.get("migration_checks", ["python3 validate_specs.py specs/"])
        ),
        manifest_fingerprint=manifest["fingerprint"],
    )


def validate_migration_result(
    request: MigrationRequest, result: MigrationResult
) -> list[str]:
    errors = []
    if result.worker_id != request.worker_id:
        errors.append("migration worker identity mismatch")
    if result.isolation != "worktree":
        errors.append("migration worker was not isolated in a worktree")
    if result.committed or result.pushed or result.merged or result.lifecycle_changed:
        errors.append("migration worker exceeded its coordinator-only authority")
    for path in result.changes:
        if path != "config.yaml" and not path.startswith(".migrations/"):
            errors.append(f"migration worker changed non-allowlisted path: {path}")
    if not result.validation_passed:
        errors.append("migration worker validation failed")
    return errors


def _apply_migration_result(install: Path, result: MigrationResult) -> None:
    for relative, text in result.changes.items():
        destination = install / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)


def _run_declared_checks(
    install: Path,
    commands: Iterable[str],
    *,
    timeout_s: int,
) -> list[str]:
    errors = []
    for command in commands:
        result = subprocess.run(
            shlex.split(command),
            cwd=install,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
        if result.returncode:
            tail = (result.stdout + "\n" + result.stderr).strip()[-1000:]
            errors.append(f"smoke check failed ({command}): {tail}")
    return errors


def _verify_staged(plan: RepositoryPlan, manifest: dict) -> tuple[set[str], list[str]]:
    staged_result = _run(["git", "diff", "--cached", "--name-only"], cwd=plan.root)
    staged = set(staged_result.stdout.splitlines())
    errors = []
    outside = sorted(staged - plan.allowed_paths)
    if outside:
        errors.append("staged path outside release allowlist: " + ", ".join(outside))
    if any(path.endswith("projects-registry.json") for path in staged):
        errors.append("generated registry entered release commit")
    for path in staged:
        relative = _managed_relative(plan, path)
        if _project_owned_managed_path(relative):
            errors.append(f"project-owned path entered release commit: {path}")

    for install in plan.installs:
        ok, details = release.verify_install(install, manifest)
        if not ok:
            errors.extend(f"{install}: {detail}" for detail in details)
    return staged, errors


def _refresh_recognized_nightshift_precommit_hooks(plan: RepositoryPlan) -> list[str]:
    """Refresh only installed hooks that identify themselves as Nightshift.

    A release commit invokes the repository's Git hook, not the just-copied
    managed `.nightshift/hooks/pre-commit` payload.  Refreshing an explicitly
    identified Nightshift hook closes that bootstrap gap without touching a
    project-owned hook.
    """
    errors: list[str] = []
    for install in plan.installs:
        source = install / "hooks" / "pre-commit"
        hooks = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=plan.root)
        if hooks.returncode or not source.is_file():
            continue
        directory = Path(hooks.stdout.strip())
        if not directory.is_absolute():
            directory = plan.root / directory
        target = directory / "pre-commit"
        if (
            not target.is_file()
            or "Nightshift Kit — Pre-commit hook"
            not in target.read_text(errors="replace")[:300]
        ):
            continue
        try:
            shutil.copy2(source, target)
        except OSError as exc:
            errors.append(
                f"could not refresh recognized Nightshift pre-commit hook: {exc}"
            )
    return errors


def _commit_repository(
    plan: RepositoryPlan, manifest: dict
) -> tuple[str | None, list[str]]:
    # Managed kit directories are historically gitignored in some projects.
    # Force-add is safe because every path comes from the release allowlist and
    # the staged set is mechanically rechecked before commit.
    add_result = _run(
        ["git", "add", "-f", "--", *sorted(plan.allowed_paths)], cwd=plan.root
    )
    if add_result.returncode:
        return None, [add_result.stderr.strip() or "git add failed"]
    staged, errors = _verify_staged(plan, manifest)
    if errors:
        return None, errors
    if not staged:
        return None, []

    if hook_errors := _refresh_recognized_nightshift_precommit_hooks(plan):
        return None, hook_errors

    message = (
        f"[SPEC-156] chore: release kit {manifest['kit_version']}\n\n"
        f"Nightshift-Release-Version: {manifest['kit_version']}\n"
        f"Nightshift-Release-Fingerprint: {manifest['fingerprint']}\n"
        f"Nightshift-Verified-Installs: {len(plan.installs)}"
    )
    commit = _run(
        ["git", "commit", "-m", message, "--", *sorted(staged)], cwd=plan.root
    )
    if commit.returncode:
        return None, [
            commit.stderr.strip() or commit.stdout.strip() or "git commit failed"
        ]
    sha = _run(["git", "rev-parse", "HEAD"], cwd=plan.root).stdout.strip()
    committed = set(
        _run(
            ["git", "show", "--pretty=format:", "--name-only", sha], cwd=plan.root
        ).stdout.splitlines()
    )
    if committed != staged or not committed.issubset(plan.allowed_paths):
        return sha, ["post-commit path-set verification failed"]
    return sha, []


def _skill_manifest_entry(manifest: dict) -> dict | None:
    return next(
        (
            entry
            for entry in manifest.get("files", [])
            if entry.get("path") == SKILL_MANAGED_PATH
        ),
        None,
    )


def _skill_delivery_preflight(
    canonical: Path, release_root: Path | None, manifest: dict
) -> tuple[dict | None, list[str]]:
    """Resolve and preflight the separately installed active skill payload."""
    entry = _skill_manifest_entry(manifest)
    if entry is None:
        return None, []
    if release_root is None:
        return None, ["managed canonical skill requires an explicit release root"]
    root = release_root.resolve()
    repo = _git_root(root)
    if repo is None or repo != root:
        return None, ["release root must be the owning git repository root"]
    source = canonical / SKILL_MANAGED_PATH
    target = root / SKILL_MANAGED_PATH
    if not source.is_file() or source.is_symlink():
        return None, ["canonical skill source is missing or unsafe"]
    target_relative = _relative(repo, target)
    if target_relative != SKILL_MANAGED_PATH:
        return None, ["canonical skill target path is not exact"]
    staged, dirty = _porcelain_paths(repo)
    errors = []
    if target_relative in dirty:
        errors.append("canonical skill target is dirty or pre-staged")
    source_mode = stat.S_IMODE(source.stat().st_mode)
    expected_mode = 0o755 if entry.get("executable") else 0o644
    if source_mode != expected_mode:
        errors.append("canonical skill source mode does not match manifest")
    if release.sha256(source) != entry.get("sha256"):
        errors.append("canonical skill source hash does not match manifest")
    return {
        "repo": repo,
        "source": source,
        "target": target,
        "target_relative": target_relative,
        "sha256": entry.get("sha256"),
        "mode": expected_mode,
        "preexisting_staged": staged,
    }, errors


def _atomic_copy_skill(source: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nightshift-skill-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_evidence(
    repo: Path,
    target_relative: str,
    expected_hash: str,
    expected_mode: int,
    preexisting_staged: set[str],
) -> tuple[dict | None, list[str]]:
    staged = set(
        _run(["git", "diff", "--cached", "--name-only"], cwd=repo).stdout.splitlines()
    )
    created_exact_commit = target_relative in staged
    if staged - {target_relative} != preexisting_staged:
        return None, ["canonical skill staging changed unrelated paths"]
    if created_exact_commit:
        commit = _run(
            [
                "git",
                "commit",
                "-m",
                "[SPEC-230] chore: deliver managed Nightshift skill",
                "--",
                target_relative,
            ],
            cwd=repo,
        )
        if commit.returncode:
            return None, [
                commit.stderr.strip() or commit.stdout.strip() or "skill commit failed"
            ]
        remaining = set(
            _run(
                ["git", "diff", "--cached", "--name-only"], cwd=repo
            ).stdout.splitlines()
        )
        if remaining != preexisting_staged:
            return None, ["canonical skill commit consumed unrelated staging"]
    sha = _run(
        ["git", "log", "-1", "--format=%H", "--", target_relative], cwd=repo
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None, ["canonical skill has no owning commit"]
    committed_paths = set(
        _run(
            ["git", "show", "--pretty=format:", "--name-only", sha], cwd=repo
        ).stdout.splitlines()
    )
    blob = _run(["git", "show", f"{sha}:{target_relative}"], cwd=repo)
    tree = _run(["git", "ls-tree", sha, "--", target_relative], cwd=repo)
    expected_git_mode = "100755" if expected_mode == 0o755 else "100644"
    if (
        (created_exact_commit and committed_paths != {target_relative})
        or target_relative not in committed_paths
        or blob.returncode
        or hashlib.sha256(blob.stdout.encode()).hexdigest() != expected_hash
        or tree.returncode
        or not tree.stdout.startswith(expected_git_mode + " ")
    ):
        return None, ["canonical skill commit evidence verification failed"]
    return {
        "sha": sha,
        "paths": sorted(committed_paths),
        "verified": True,
        "unrelated_staging_preserved": True,
        "mode": expected_git_mode,
    }, []


def _deliver_skill(plan: dict) -> tuple[dict | None, list[str]]:
    repo = plan["repo"]
    target = plan["target"]
    target_relative = plan["target_relative"]
    _atomic_copy_skill(plan["source"], target, plan["mode"])
    verification = {
        "bytes": target.read_bytes() == plan["source"].read_bytes(),
        "sha256": release.sha256(target) == plan["sha256"],
        "mode": stat.S_IMODE(target.stat().st_mode) == plan["mode"],
    }
    if not all(verification.values()):
        return None, ["canonical skill target verification failed"]
    add = _run(["git", "add", "-f", "--", target_relative], cwd=repo)
    if add.returncode:
        return None, [add.stderr.strip() or "canonical skill git add failed"]
    commit, errors = _commit_evidence(
        repo,
        target_relative,
        plan["sha256"],
        plan["mode"],
        plan["preexisting_staged"],
    )
    if errors:
        return None, errors
    return {
        "status": "verified",
        "source_relative_path": SKILL_MANAGED_PATH,
        "target_relative_path": target_relative,
        "sha256": plan["sha256"],
        "mode": f"{plan['mode']:04o}",
        "allowlist": [target_relative],
        "verification": verification,
        "commit_evidence": commit,
    }, []


def coordinate_release(
    canonical: Path,
    installs: Iterable[Path],
    manifest: dict,
    *,
    dry_run: bool,
    migration_runner: MigrationRunner | None = None,
    canonical_suite_runner: SuiteRunner | None = None,
    inject_unexpected_after_commits: int | None = None,
    smoke_timeout_s: int = 60,
    include_opt_out: bool = False,
    release_root: Path | None = None,
) -> dict:
    """Coordinate one exact release with known-failure isolation and stop semantics."""
    started = time.monotonic()
    plans, initial_skips = plan_repositories(installs, manifest)
    skill_plan, skill_preflight_errors = _skill_delivery_preflight(
        canonical, release_root, manifest
    )
    result = {
        "release_version": manifest["kit_version"],
        "release_fingerprint": manifest["fingerprint"],
        "dry_run": dry_run,
        "managed_payload_mode": "canonical_replace",
        "file_level_patch_attempted": False,
        "include_opt_out": include_opt_out,
        "planned_installs": sum(len(plan.installs) for plan in plans),
        "planned_repositories": len(plans),
        "eligible_installs": [],
        "verified_installs": [],
        "release_policies": {
            str(plan.root): {
                "committed_kit": plan.committed_kit_policy or "undeclared",
                "policy_sources": list(plan.policy_sources),
                "hook_policies": [
                    {"committed_kit": policy, "source": source}
                    for policy, source in plan.hook_policies
                ],
            }
            for plan in plans
        },
        "skipped": initial_skips,
        "untouched": [],
        "repository_commits": [],
        "migrations": [],
        "conflicts": [],
        "failure_class": None,
        "unexpected_failure": None,
        "rollback_attempted": False,
        "push_attempted": False,
        "canonical_suite_runs": 0,
        "canonical_suite_probe": "not_run",
        "canonical_suite_result": "not_run",
        "smoke_checks_run": 0,
        "producer_session_evidence": {},
        "old_fingerprints": {},
        "post_commit_rebuild_time_s": None,
        "release_handoffs_completed": [],
        "skill_delivery": (
            {
                "status": "planned" if skill_plan else "not_required",
                "source_relative_path": SKILL_MANAGED_PATH,
                "target_relative_path": SKILL_MANAGED_PATH,
                "sha256": skill_plan["sha256"] if skill_plan else None,
                "mode": f"{skill_plan['mode']:04o}" if skill_plan else None,
                "allowlist": [SKILL_MANAGED_PATH] if skill_plan else [],
                "verification": {"bytes": False, "sha256": False, "mode": False},
                "commit_evidence": None,
            }
        ),
        "rerun_command": (
            f"python3 {canonical / 'release_coordinator.py'}"
            f" --root {canonical.parents[2]} --apply"
        ),
    }

    for plan in plans:
        for install in plan.installs:
            marker = install / release.MARKER
            try:
                old = json.loads(marker.read_text()).get("fingerprint")
            except (FileNotFoundError, json.JSONDecodeError):
                old = None
            result["old_fingerprints"][str(install)] = old

    ownership_errors = validate_release_ownership(plans, manifest)
    ownership_errors.extend(skill_preflight_errors)
    if ownership_errors:
        result["failure_class"] = "canonical_preflight"
        result["unexpected_failure"] = "; ".join(ownership_errors)
        result["untouched"] = [
            {
                "repository": str(plan.root),
                "installs": [str(item) for item in plan.installs],
            }
            for plan in plans
        ]
        result["duration_s"] = round(time.monotonic() - started, 3)
        result["completed_at"] = datetime.now(UTC).isoformat()
        result["exit_code"] = 1
        return result

    if not dry_run:
        try:
            probe_argv = _suite_argv(manifest["canonical_suite"], "probe")
            suite_argv = _suite_argv(manifest["canonical_suite"], "command")
        except (KeyError, ValueError) as exc:
            probe_result = subprocess.CompletedProcess([], 2, "", str(exc))
            suite_argv = []
        else:
            runner = canonical_suite_runner or _run_canonical_suite
            probe_result = _run_canonical_suite_step(runner, probe_argv, canonical)
        result["canonical_suite_probe"] = (
            "passed" if probe_result.returncode == 0 else "failed"
        )
        if probe_result.returncode:
            result["failure_class"] = "canonical_preflight"
            result["unexpected_failure"] = (
                probe_result.stdout + "\n" + probe_result.stderr
            ).strip()[-2000:]
            result["untouched"] = [
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                }
                for plan in plans
            ]
            result["duration_s"] = round(time.monotonic() - started, 3)
            result["completed_at"] = datetime.now(UTC).isoformat()
            result["exit_code"] = 1
            return result
        suite_result = _run_canonical_suite_step(runner, suite_argv, canonical)
        result["canonical_suite_runs"] = 1
        result["canonical_suite_result"] = (
            "passed" if suite_result.returncode == 0 else "failed"
        )
        if suite_result.returncode:
            result["failure_class"] = "canonical_preflight"
            result["unexpected_failure"] = (
                suite_result.stdout + "\n" + suite_result.stderr
            ).strip()[-2000:]
            result["untouched"] = [
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                }
                for plan in plans
            ]
            result["duration_s"] = round(time.monotonic() - started, 3)
            result["completed_at"] = datetime.now(UTC).isoformat()
            result["exit_code"] = 1
            return result

    committed_repositories = 0
    for plan_index, plan in enumerate(plans):
        if (
            inject_unexpected_after_commits is not None
            and committed_repositories >= inject_unexpected_after_commits
        ):
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "injected unexpected coordinator failure"
            for later in plans[plan_index:]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break

        policy_errors = _release_policy_errors(plan)
        if policy_errors:
            entry = {
                "repository": str(plan.root),
                "installs": [str(item) for item in plan.installs],
                "classification": "release_policy_conflict",
                "reason": "; ".join(policy_errors),
            }
            result["skipped"].append(entry)
            result["conflicts"].append(entry)
            continue
        if plan.committed_kit_policy == "opt_out" and not include_opt_out:
            result["skipped"].append(
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                    "classification": "committed_kit_opt_out",
                    "reason": "project release policy opts out of committed managed-kit payloads",
                    "policy_sources": list(plan.policy_sources),
                }
            )
            continue

        migration_skips = [
            disposition
            for install in plan.installs
            if (disposition := release_disposition(install)) is not None
        ]
        if migration_skips:
            result["skipped"].append(
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                    "classification": "tracked_private_artifacts_unresolved",
                    "reason": migration_skips[0]["reason"],
                    "migration_reference": migration_skips[0]["migration_reference"],
                }
            )
            continue

        preflight_errors = preflight_repository(
            plan,
            manifest,
        )
        if preflight_errors:
            entry = {
                "repository": str(plan.root),
                "installs": [str(item) for item in plan.installs],
                "classification": "known_project_local",
                "reason": "; ".join(preflight_errors),
            }
            result["skipped"].append(entry)
            result["conflicts"].append(entry)
            continue

        migrations: list[tuple[Path, MigrationResult]] = []
        migration_failed = False
        for sequence, install in enumerate(plan.installs, start=1):
            if not _migration_needed(install, manifest["schema_version"]):
                continue
            request = build_migration_request(install, manifest, sequence)
            if migration_runner is None:
                errors = [
                    "registered config migration requires a fresh migration worker"
                ]
            else:
                worker_result = migration_runner(request)
                errors = validate_migration_result(request, worker_result)
                if not errors:
                    migrations.append((install, worker_result))
            result["migrations"].append(
                {
                    "request": asdict(request),
                    "verified": not errors,
                    "errors": errors,
                }
            )
            if errors:
                result["skipped"].append(
                    {
                        "repository": str(plan.root),
                        "installs": [str(item) for item in plan.installs],
                        "classification": "known_project_local",
                        "reason": "; ".join(errors),
                    }
                )
                migration_failed = True
                break
        if migration_failed:
            continue

        if dry_run:
            result["eligible_installs"].extend(str(item) for item in plan.installs)
            continue

        repository_errors = []
        for install in plan.installs:
            ok, details = release.apply_install(canonical, install, manifest)
            if not ok:
                repository_errors.extend(f"{install}: {detail}" for detail in details)
                break
            for migrated_install, worker_result in migrations:
                if migrated_install == install:
                    _apply_migration_result(install, worker_result)
            smoke_errors = _run_declared_checks(
                install,
                manifest["smoke_checks"],
                timeout_s=smoke_timeout_s,
            )
            result["smoke_checks_run"] += len(manifest["smoke_checks"])
            repository_errors.extend(smoke_errors)
            if smoke_errors:
                break
        if repository_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(repository_errors)
            for later in plans[plan_index + 1 :]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break

        sha, commit_errors = _commit_repository(plan, manifest)
        if commit_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(commit_errors)
            for later in plans[plan_index + 1 :]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break
        result["verified_installs"].extend(str(item) for item in plan.installs)
        if sha:
            result["repository_commits"].append(
                {
                    "repository": str(plan.root),
                    "commit": sha,
                    "verified_installs": len(plan.installs),
                }
            )
            committed_repositories += 1

    producer = canonical / "reflexion_producer.py"
    if producer.is_file():
        result["producer_session_evidence"] = {
            "sha256": release.sha256(producer),
            "contains_producer_session_id": "_producer_session_id"
            in producer.read_text(),
            "verified_install_shas": {
                str(install): release.sha256(Path(install) / "reflexion_producer.py")
                for install in result["verified_installs"]
                if (Path(install) / "reflexion_producer.py").is_file()
            },
        }
    if not dry_run and result["unexpected_failure"] is None and skill_plan is not None:
        # Recheck after managed-install commits so a concurrent edit/stage race
        # cannot be overwritten by the external exact-path delivery.
        refreshed_plan, refreshed_errors = _skill_delivery_preflight(
            canonical, release_root, manifest
        )
        if refreshed_errors or refreshed_plan is None:
            skill_errors = refreshed_errors or ["canonical skill plan disappeared"]
            skill_delivery = None
        else:
            skill_delivery, skill_errors = _deliver_skill(refreshed_plan)
        if skill_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(skill_errors)
            result["skill_delivery"] = {
                **result["skill_delivery"],
                "status": "failed",
            }
        else:
            result["skill_delivery"] = skill_delivery
    # A handoff scoped to eligible installs is complete after every eligible
    # repository verifies. Known local skips remain observable and keep the
    # coordinator exit non-zero, but do not invalidate deliveries already made.
    if (
        not dry_run
        and result["canonical_suite_probe"] == "passed"
        and result["canonical_suite_runs"] == 1
        and result["canonical_suite_result"] == "passed"
        and result["managed_payload_mode"] == "canonical_replace"
        and result["file_level_patch_attempted"] is False
        and len(result["verified_installs"]) >= 1
        and result["unexpected_failure"] is None
        and result["rollback_attempted"] is False
        and result["push_attempted"] is False
    ):
        result["release_handoffs_completed"] = (
            release_handoff.complete_pending_handoffs(canonical, manifest, result)
        )
    result["duration_s"] = round(time.monotonic() - started, 3)
    result["completed_at"] = datetime.now(UTC).isoformat()
    result["exit_code"] = 1 if result["skipped"] or result["unexpected_failure"] else 0
    return result


def write_metrics(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Argo/discovery root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--metrics-out", type=Path)
    parser.add_argument(
        "--include-opt-out",
        action="store_true",
        help="operator-authorized one-release override of committed_kit: opt_out",
    )
    args = parser.parse_args()

    canonical = Path(__file__).resolve().parent
    sys.path.insert(0, str(canonical.parent))
    import importlib.util

    sync_path = canonical.parent / "nightshift-sync.py"
    spec = importlib.util.spec_from_file_location("nightshift_sync", sync_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load nightshift-sync.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)

    valid, errors, manifest = release.validate_manifest(
        canonical, sync.CANONICAL_PROTOCOL_FILES
    )
    if not valid or manifest is None:
        print(json.dumps({"preflight": "failed", "errors": errors}, indent=2))
        return 2

    installs = [
        path
        for path in sync.find_nightshift_dirs(args.root.resolve())
        if path.resolve() != canonical.resolve()
    ]
    result = coordinate_release(
        canonical,
        installs,
        manifest,
        dry_run=args.dry_run,
        include_opt_out=args.include_opt_out,
        release_root=args.root.resolve(),
    )
    result["rerun_command"] = (
        f"python3 {canonical / 'release_coordinator.py'}"
        f" --root {args.root.resolve()} --apply"
        + (" --include-opt-out" if args.include_opt_out else "")
    )
    output = args.metrics_out or canonical / "reports" / "_wip" / (
        f"release-{manifest['kit_version']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_metrics(result, output)
    print(json.dumps({**result, "metrics_path": str(output)}, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
