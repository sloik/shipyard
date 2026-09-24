#!/usr/bin/env python3
"""Private-local Nightshift lifecycle, projection, and privacy gates.

Application code continues to move through Git. This module only handles an explicitly
opted-in private Nightshift control plane and deliberately exposes no heuristic mode switch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

import yaml

from spec_frontmatter import (
    parse_spec_file,
    status_error_for_spec,
    write_spec_frontmatter,
)
from status_store import StatusStore
from worktree_paths import assert_managed_worktree_path, assert_worktree_owner

COMMIT_BACKED = "commit-backed"
PRIVATE_LOCAL = "private-local"
VALID_POLICIES = frozenset({COMMIT_BACKED, PRIVATE_LOCAL})
TERMINAL_STATUSES = frozenset({"done", "blocked"})
FORBIDDEN_PROJECTION_ROOTS = frozenset(
    {"reports", "metrics", "runs", "checkpoints", "failure-ledger.json"}
)


class PrivateStateError(RuntimeError):
    """Raised before a private-state safety invariant would be violated."""


def _git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise PrivateStateError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result


def _merged_yaml(path: Path) -> dict:
    try:
        docs = yaml.safe_load_all(Path(path).read_text(encoding="utf-8"))
        merged: dict = {}
        for doc in docs:
            if isinstance(doc, dict):
                merged.update(doc)
        return merged
    except (OSError, yaml.YAMLError) as exc:
        raise PrivateStateError(f"cannot read Nightshift configuration {path}: {exc}") from exc


def load_state_policy(config_path: Path) -> str:
    """Return the explicit persistence policy; absence preserves commit-backed behavior."""
    config = _merged_yaml(Path(config_path))
    section = config.get("nightshift_state")
    if section is None:
        return COMMIT_BACKED
    if not isinstance(section, dict):
        raise PrivateStateError("nightshift_state must be a mapping")
    value = section.get("policy", COMMIT_BACKED)
    if value not in VALID_POLICIES:
        raise PrivateStateError(
            f"invalid nightshift_state.policy {value!r}; expected commit-backed or private-local"
        )
    return str(value)


def load_private_paths(config_path: Path) -> list[str]:
    """Return validated repo-relative privacy-gate roots for private-local mode."""
    config = _merged_yaml(Path(config_path))
    section = config.get("nightshift_state") or {}
    if not isinstance(section, dict):
        raise PrivateStateError("nightshift_state must be a mapping")
    raw_paths = section.get("private_paths", [".nightshift"])
    if not isinstance(raw_paths, list) or not raw_paths:
        raise PrivateStateError("nightshift_state.private_paths must be a non-empty list")
    paths: list[str] = []
    for raw in raw_paths:
        if not isinstance(raw, str):
            raise PrivateStateError("nightshift_state.private_paths entries must be strings")
        paths.append(str(_safe_relative(raw)))
    return paths


def transition_private_state(
    spec_file: Path,
    store: StatusStore,
    status: str,
    *,
    owner: str,
    assigned_spec: str,
    run_id: str | None = None,
    note: str | None = None,
    payload: dict | None = None,
    actor: str | None = None,
    reason: str | None = None,
    reconsider_when: str | None = None,
    evidence: Iterable[Mapping[str, object]] = (),
) -> dict:
    """Apply one coordinator-owned local lifecycle transition and durable checkpoint.

    Repeating the current transition is idempotent. A run gets its UUID before the first
    checkpoint, so the identifier is stable across process restart and terminal resolution.

    SPEC-357 R3: this is the "private-local (explicit opt-in)" kickoff boundary
    named in R3/AC3 -- it now captures the same ``## State rationale``
    section/artifact pair as the commit-backed path, through the identical
    shared routine (``spec_artifacts.capture_state_rationale``), pinned to the
    pre-mutation ``current`` status so a competing revision is refused rather
    than silently overwritten.
    """
    spec_file = Path(spec_file)
    parsed = parse_spec_file(spec_file)
    spec_id = str(parsed.frontmatter.get("id") or "")
    current = str(parsed.frontmatter.get("status") or "")
    if owner != "coordinator":
        raise PrivateStateError("only the coordinator may transition private Nightshift state")
    if not spec_id or assigned_spec != spec_id:
        raise PrivateStateError(
            f"assigned spec {assigned_spec!r} does not match selected spec {spec_id!r}"
        )
    error = status_error_for_spec(parsed.frontmatter, status)
    if error:
        raise PrivateStateError(error)
    latest = store.get_state(spec_id)
    if latest and latest["status"] in TERMINAL_STATUSES:
        if latest["status"] == status and (run_id is None or latest["run_id"] == run_id):
            return latest
        raise PrivateStateError(
            f"run {latest['run_id']} is already terminal as {latest['status']}"
        )
    reused_in_flight_checkpoint: dict | None = None
    if status == "in_progress":
        if current == "in_progress" and latest and latest["status"] == "in_progress":
            return latest
        if current != "ready":
            raise PrivateStateError(f"private run must start ready, got {current!r}")
        if latest and latest["status"] == "in_progress" and run_id is None:
            # AC3: a prior attempt's checkpoint durably recorded in_progress but
            # a later step (artifact/section or frontmatter write) failed
            # before the frontmatter caught up -- this is a retry of that same
            # in-flight attempt, not a fresh start. Reuse its run_id (and thus
            # its checkpoint) so the retry resolves through the capture
            # routine's own snapshot-equality idempotency check instead of
            # minting a second checkpoint and a second artifact for one
            # transition.
            run_id = str(latest.get("run_id") or "") or None
            reused_in_flight_checkpoint = latest
        run_id = run_id or f"local-{uuid.uuid4()}"
    elif status in TERMINAL_STATUSES:
        if current != "in_progress" or not latest or latest["status"] != "in_progress":
            raise PrivateStateError("terminal transition requires a durable in_progress event")
        expected_run = str(latest.get("run_id") or "")
        run_id = run_id or expected_run
        if not run_id or run_id != expected_run:
            raise PrivateStateError("terminal transition run_id does not match active local run")
    else:
        raise PrivateStateError(f"unsupported private lifecycle transition to {status!r}")

    reason_text = reason.strip() if isinstance(reason, str) else ""
    if not reason_text:
        reason_text = (note or "").strip() if isinstance(note, str) else ""
    if not reason_text:
        reason_text = f"mechanical transition to {status!r} via run {run_id}"

    if reused_in_flight_checkpoint is not None:
        checkpoint = reused_in_flight_checkpoint
    else:
        checkpoint = store.update_state(
            spec_id,
            status,
            run_id=run_id,
            source="private-local-coordinator",
            note=note,
            payload={"owner": owner, "assigned_spec": assigned_spec, **(payload or {})},
        )

    import spec_artifacts

    try:
        spec_artifacts.write_status_transition_artifact(
            spec_artifacts.reports_root_for_spec_path(spec_file), spec_id,
            from_status=current, to_status=status,
            actor=actor or owner, reason=reason_text,
            evidence=[], run_id=run_id,
            spec_path=spec_file, expected_status=current,
            reconsider_when=reconsider_when,
            state_rationale_evidence=evidence,
        )
    except Exception as exc:
        raise PrivateStateError(
            f"private checkpoint {checkpoint.get('checkpoint_id')} persisted but "
            f"status-transition artifact write failed; refusal: {exc}; "
            f"recovery: reconcile {spec_file.name} artifacts and retry"
        ) from exc

    def mutate(frontmatter: dict) -> dict:
        frontmatter["status"] = status
        return frontmatter

    try:
        write_spec_frontmatter(spec_file, mutate)
    except Exception as exc:
        raise PrivateStateError(
            f"private checkpoint {checkpoint.get('checkpoint_id')} persisted but frontmatter "
            f"write failed; refusal: {exc}; recovery: reconcile {spec_file.name} to {status}"
        ) from exc
    return checkpoint


def _safe_relative(raw: str) -> PurePosixPath:
    relative = PurePosixPath(raw)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise PrivateStateError(f"unsafe allowlisted relative path: {raw!r}")
    return relative


def _source_file(root: Path, relative: PurePosixPath) -> Path:
    root = root.resolve()
    lexical = root.joinpath(*relative.parts)
    resolved = lexical.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PrivateStateError(f"source {relative} escapes private root {root}") from exc
    if not resolved.is_file():
        raise PrivateStateError(f"allowlisted source is not a regular file: {relative}")
    return resolved


def _destination_is_private(repo: Path, destination: Path) -> None:
    relative = destination.relative_to(repo).as_posix()
    tracked = _git(repo, "ls-files", "--", relative).stdout.strip()
    if tracked:
        raise PrivateStateError(f"private projection destination is tracked: {relative}")
    ignored = _git(repo, "check-ignore", "-q", "--no-index", "--", relative)
    if ignored.returncode != 0:
        raise PrivateStateError(f"private projection destination is not ignored: {relative}")


def project_private_state(
    repo_root: Path,
    worktree: Path,
    private_root: Path,
    allowlist: Iterable[str],
    *,
    selected_spec_id: str,
) -> dict:
    """Copy only declared private runtime inputs into a verified ignored worktree tree."""
    repo_root, worktree, private_root = (
        Path(path).resolve() for path in (repo_root, worktree, private_root)
    )
    assert_managed_worktree_path(repo_root, worktree)
    assert_worktree_owner(repo_root, worktree)
    entries: list[tuple[PurePosixPath, Path, Path]] = []
    projected_spec_ids: list[str] = []
    for raw in sorted(set(allowlist)):
        relative = _safe_relative(raw)
        if relative.parts[0] in FORBIDDEN_PROJECTION_ROOTS:
            raise PrivateStateError(
                f"private projection category is never an input: {relative.parts[0]}"
            )
        source = _source_file(private_root, relative)
        if relative.parts[0] == "specs":
            try:
                projected_spec_ids.append(
                    str(parse_spec_file(source).frontmatter.get("id") or "")
                )
            except Exception as exc:
                raise PrivateStateError(
                    f"cannot verify projected spec identity: {relative}"
                ) from exc
        destination = worktree / ".nightshift" / Path(*relative.parts)
        _destination_is_private(worktree, destination)
        entries.append((relative, source, destination))
    if projected_spec_ids != [selected_spec_id]:
        raise PrivateStateError(
            "projection must contain exactly the assigned spec; "
            f"expected {selected_spec_id!r}, got {projected_spec_ids!r}"
        )

    stage = Path(tempfile.mkdtemp(prefix="nightshift-projection-", dir=str(worktree.parent)))
    installed: list[Path] = []
    backups: dict[Path, Path] = {}
    try:
        for relative, source, _ in entries:
            staged = stage / Path(*relative.parts)
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged)
        for relative, _, destination in entries:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                backup = stage / ".backup" / Path(*relative.parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                backups[destination] = backup
            os.replace(stage / Path(*relative.parts), destination)
            installed.append(destination)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
            backup = backups.get(path)
            if backup is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, path)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"paths": [str(relative) for relative, _, _ in entries]}


def return_private_evidence(
    repo_root: Path,
    worktree: Path,
    private_root: Path,
    allowlist: Iterable[str],
) -> dict:
    """Return only contract-declared worker evidence to the coordinator's private state."""
    repo_root, worktree, private_root = (
        Path(path).resolve() for path in (repo_root, worktree, private_root)
    )
    assert_managed_worktree_path(repo_root, worktree)
    assert_worktree_owner(repo_root, worktree)
    worker_root = worktree / ".nightshift"
    entries = []
    for raw in sorted(set(allowlist)):
        relative = _safe_relative(raw)
        source = _source_file(worker_root, relative)
        destination = private_root / Path(*relative.parts)
        try:
            destination.resolve().relative_to(private_root)
        except ValueError as exc:
            raise PrivateStateError(f"evidence destination escapes private root: {relative}") from exc
        entries.append((relative, source, destination))
    for _, source, destination in entries:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    return {"paths": [str(relative) for relative, _, _ in entries]}


def assert_private_paths_absent_from_git(
    repo: Path, private_paths: Iterable[str], *, base_ref: str | None = None
) -> None:
    """Refuse tracked, staged, or branch-diff private paths before launch/integration."""
    repo = Path(repo).resolve()
    paths = [str(_safe_relative(path)) for path in private_paths]
    leaked: set[str] = set()
    for args in (
        ("ls-files", "--", *paths),
        ("diff", "--cached", "--name-only", "--", *paths),
    ):
        result = _git(repo, *args)
        if result.returncode != 0:
            raise PrivateStateError(result.stderr.strip() or f"privacy gate Git query failed: {' '.join(args)}")
        leaked.update(line for line in result.stdout.splitlines() if line)
    if base_ref:
        result = _git(repo, "diff", "--name-only", f"{base_ref}...HEAD", "--", *paths)
        if result.returncode != 0:
            raise PrivateStateError(result.stderr.strip() or f"privacy gate cannot compare {base_ref}...HEAD")
        leaked.update(
            line
            for line in result.stdout.splitlines()
            if line
        )
    if leaked:
        raise PrivateStateError(
            "private Nightshift paths are present in Git: " + ", ".join(sorted(leaked))
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    policy = sub.add_parser("policy")
    policy.add_argument("--config", type=Path, required=True)
    privacy = sub.add_parser("privacy-check")
    privacy.add_argument("--repo", type=Path, required=True)
    privacy.add_argument("--private-path", action="append", required=True)
    privacy.add_argument("--base-ref")
    args = parser.parse_args(argv)
    try:
        if args.command == "policy":
            result = {
                "policy": load_state_policy(args.config),
                "private_paths": load_private_paths(args.config),
            }
        else:
            assert_private_paths_absent_from_git(args.repo, args.private_path, base_ref=args.base_ref)
            result = {"ok": True, "private_paths": args.private_path}
    except PrivateStateError as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
