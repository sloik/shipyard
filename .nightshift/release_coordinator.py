#!/usr/bin/env python3
"""Guarded, repository-scoped coordinator for whole-kit Nightshift releases.

The coordinator deliberately owns git integration while ``release.py`` remains
the mechanical copy/verify primitive.  It never pushes and never stages paths
outside the computed release allowlist.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import release


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
SuiteRunner = Callable[[str, Path], subprocess.CompletedProcess[str]]


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
        declared_values = {value for value, _source in declarations if value is not None}
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


def preflight_repository(plan: RepositoryPlan, manifest: dict) -> list[str]:
    staged, dirty = _porcelain_paths(plan.root)
    errors = []
    unrelated_staged = sorted(staged - plan.allowed_paths)
    dirty_managed = sorted(dirty & plan.allowed_paths)
    if unrelated_staged:
        errors.append("unrelated pre-staged paths: " + ", ".join(unrelated_staged))
    if dirty_managed:
        # A prior coordinator attempt may have copied and staged the exact
        # release before a commit hook stopped it. It is safely resumable when
        # either the current release verifies, or the complete previous release
        # path set (including the marker written last) remains staged.
        exact_release = all(
            release.verify_install(install, manifest)[0] for install in plan.installs
        )
        complete_staged_release = all(
            {
                _relative(plan.root, install / entry["path"])
                for entry in manifest["files"]
            }
            | {_relative(plan.root, install / release.MARKER)}
            <= staged
            for install in plan.installs
        )
        if not exact_release and not complete_staged_release:
            errors.append("dirty managed paths: " + ", ".join(dirty_managed))
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
    forbidden_parts = {"specs", "metrics", "knowledge"}
    for path in staged:
        if forbidden_parts.intersection(Path(path).parts):
            errors.append(f"project-owned path entered release commit: {path}")

    for install in plan.installs:
        ok, details = release.verify_install(install, manifest)
        if not ok:
            errors.extend(f"{install}: {detail}" for detail in details)
    return staged, errors


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
) -> dict:
    """Coordinate one exact release with known-failure isolation and stop semantics."""
    started = time.monotonic()
    plans, initial_skips = plan_repositories(installs, manifest)
    result = {
        "release_version": manifest["kit_version"],
        "release_fingerprint": manifest["fingerprint"],
        "dry_run": dry_run,
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
        "smoke_checks_run": 0,
        "producer_session_evidence": {},
        "old_fingerprints": {},
        "post_commit_rebuild_time_s": None,
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

    if not dry_run:
        command = manifest["canonical_suite"]
        if canonical_suite_runner is None:
            suite_result = subprocess.run(
                shlex.split(command),
                cwd=canonical,
                text=True,
                capture_output=True,
                check=False,
            )
        else:
            suite_result = canonical_suite_runner(command, canonical)
        result["canonical_suite_runs"] = 1
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
        if plan.committed_kit_policy == "opt_out":
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

        preflight_errors = preflight_repository(plan, manifest)
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

        for install, worker_result in migrations:
            _apply_migration_result(install, worker_result)

        repository_errors = []
        for install in plan.installs:
            ok, details = release.apply_install(canonical, install, manifest)
            if not ok:
                repository_errors.extend(f"{install}: {detail}" for detail in details)
                break
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
    result = coordinate_release(canonical, installs, manifest, dry_run=args.dry_run)
    result["rerun_command"] = (
        f"python3 {canonical / 'release_coordinator.py'}"
        f" --root {args.root.resolve()} --apply"
    )
    output = args.metrics_out or canonical / "reports" / "_wip" / (
        f"release-{manifest['kit_version']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_metrics(result, output)
    print(json.dumps({**result, "metrics_path": str(output)}, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
