#!/usr/bin/env python3
"""Read-only provenance and commit admission for managed Nightshift payloads.

The release manifest is the only managed-path authority.  A release marker keeps
the complete manifest that produced an install, so a later audit can prove a
per-file prior-release match instead of guessing from an aggregate fingerprint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


EXACT_CURRENT = "exact-current"
RETAINED_PRIOR_RELEASE = "retained-prior-release"
UNRESOLVED_DIVERGENCE = "unresolved-divergence"
MARKER = "release-marker.json"


class MetadataError(ValueError):
    """Managed provenance cannot be established from trustworthy metadata."""


@dataclass(frozen=True)
class PathProvenance:
    path: str
    classification: str
    actual_sha256: str | None
    current_sha256: str | None
    retained_sha256: str | None
    head_sha256: str | None
    differs_from_head: bool
    staged: bool


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    return _sha256_bytes(path.read_bytes()) if path.is_file() else None


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "fingerprint"}
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(normalized).hexdigest()


def _manifest_index(manifest: Mapping[str, Any], *, label: str) -> dict[str, str]:
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != _manifest_fingerprint(manifest):
        raise MetadataError(f"{label} fingerprint is missing or corrupt")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise MetadataError(f"{label} has no managed file list")
    index: dict[str, str] = {}
    for entry in files:
        if not isinstance(entry, Mapping):
            raise MetadataError(f"{label} contains an invalid managed file entry")
        path = entry.get("path")
        digest = entry.get("sha256")
        candidate = PurePosixPath(path) if isinstance(path, str) else None
        if (
            candidate is None
            or candidate.is_absolute()
            or ".." in candidate.parts
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise MetadataError(f"{label} contains invalid per-file hash metadata")
        if path in index:
            raise MetadataError(f"{label} contains duplicate managed path: {path}")
        index[path] = digest
    return index


def load_manifest(path: Path, *, label: str = "current manifest") -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError(f"{label} is missing or corrupt: {path.name}") from exc
    if not isinstance(data, dict):
        raise MetadataError(f"{label} is not a JSON object")
    _manifest_index(data, label=label)
    return data


def retained_manifest(install: Path) -> dict[str, Any]:
    marker_path = install / MARKER
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError("release marker is missing or corrupt; retained per-file evidence is unavailable") from exc
    if not isinstance(marker, dict) or not isinstance(marker.get("release_manifest"), dict):
        raise MetadataError("release marker has no retained per-file release manifest")
    manifest = marker["release_manifest"]
    _manifest_index(manifest, label="retained release manifest")
    if (
        marker.get("fingerprint") != manifest.get("fingerprint")
        or marker.get("kit_version") != manifest.get("kit_version")
        or marker.get("schema_version") != manifest.get("schema_version")
    ):
        raise MetadataError("release marker and retained manifest disagree")
    return manifest


def recover_historical_manifest(install: Path, canonical: Path) -> dict[str, Any]:
    """Recover exact old per-file evidence from canonical Git by marker fingerprint."""
    try:
        marker = json.loads((install / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataError("release marker is missing or corrupt") from exc
    fingerprint = marker.get("fingerprint") if isinstance(marker, dict) else None
    if not isinstance(fingerprint, str):
        raise MetadataError("release marker has no historical fingerprint")
    repo = _git_root(canonical)
    try:
        manifest_path = (canonical / "release-manifest.json").resolve().relative_to(repo)
    except ValueError as exc:
        raise MetadataError("canonical manifest is outside its Git repository") from exc
    history = _run_git(repo, "log", "--all", "--format=%H", "--", manifest_path.as_posix())
    if history.returncode:
        raise MetadataError("canonical manifest history is unavailable")
    for commit in history.stdout.decode().splitlines():
        shown = _run_git(repo, "show", f"{commit}:{manifest_path.as_posix()}")
        if shown.returncode:
            continue
        try:
            candidate = json.loads(shown.stdout.decode())
            _manifest_index(candidate, label="historical release manifest")
        except (UnicodeDecodeError, json.JSONDecodeError, MetadataError):
            continue
        if candidate.get("fingerprint") == fingerprint:
            return candidate
    raise MetadataError("no exact canonical Git manifest matches the retained fingerprint")


def recover_exact_installed_manifest(
    install: Path,
    canonical: Path,
    *,
    current_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Find a historical manifest whose complete managed payload matches disk."""
    repo = _git_root(canonical)
    manifest_path = (canonical / "release-manifest.json").resolve().relative_to(repo)
    history = _run_git(repo, "log", "--all", "--format=%H", "--", manifest_path.as_posix())
    if history.returncode:
        raise MetadataError("canonical manifest history is unavailable")
    current_paths = set(_manifest_index(current_manifest, label="current manifest"))
    for commit in history.stdout.decode().splitlines():
        shown = _run_git(repo, "show", f"{commit}:{manifest_path.as_posix()}")
        if shown.returncode:
            continue
        try:
            candidate = json.loads(shown.stdout.decode())
            candidate_index = _manifest_index(candidate, label="historical release manifest")
        except (UnicodeDecodeError, json.JSONDecodeError, MetadataError):
            continue
        entries = {entry["path"]: entry for entry in candidate["files"]}
        matched = True
        for path in current_paths:
            installed = install / path
            entry = entries.get(path)
            if entry is None:
                if installed.exists():
                    matched = False
                    break
                continue
            if (
                _sha256_file(installed) != candidate_index[path]
                or bool(installed.stat().st_mode & 0o111) != bool(entry["executable"])
            ):
                matched = False
                break
        if matched:
            return candidate
    raise MetadataError("installed payload does not exactly match canonical Git history")


def recover_exact_canonical_snapshot(
    install: Path,
    canonical: Path,
    *,
    current_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove an install is an exact canonical Git snapshot when no manifest exists."""
    repo = _git_root(canonical)
    prefix = canonical.resolve().relative_to(repo).as_posix().rstrip("/")
    paths = sorted(_manifest_index(current_manifest, label="current manifest"))
    present = [path for path in paths if (install / path).is_file()]
    if not present:
        raise MetadataError("installed payload has no managed file to anchor Git history")
    anchor = "BOOTSTRAP.md" if "BOOTSTRAP.md" in present else present[0]
    anchor_repo_path = f"{prefix}/{anchor}" if prefix else anchor
    history = _run_git(repo, "log", "--all", "--format=%H", "--", anchor_repo_path)
    if history.returncode:
        raise MetadataError("canonical Git history is unavailable")
    for commit in history.stdout.decode().splitlines():
        entries: list[dict[str, Any]] = []
        matched = True
        for path in paths:
            repo_path = f"{prefix}/{path}" if prefix else path
            shown = _run_git(repo, "show", f"{commit}:{repo_path}")
            installed = install / path
            if shown.returncode:
                if installed.exists():
                    matched = False
                    break
                continue
            if not installed.is_file() or _sha256_bytes(shown.stdout) != _sha256_file(installed):
                matched = False
                break
            tree = _run_git(repo, "ls-tree", commit, "--", repo_path)
            mode = tree.stdout.decode().split(maxsplit=1)[0] if tree.returncode == 0 else ""
            executable = mode == "100755"
            if bool(installed.stat().st_mode & 0o111) != executable:
                matched = False
                break
            entries.append(
                {"path": path, "sha256": _sha256_bytes(shown.stdout), "executable": executable}
            )
        if matched and entries:
            payload = {"canonical_commit": commit, "files": entries}
            normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            return {**payload, "fingerprint": hashlib.sha256(normalized).hexdigest()}
    raise MetadataError("installed payload does not exactly match a canonical Git snapshot")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )


def _git_root(install: Path) -> Path:
    result = _run_git(install, "rev-parse", "--show-toplevel")
    if result.returncode:
        raise MetadataError("managed install is not inside a Git repository")
    return Path(result.stdout.decode().strip()).resolve()


def _status(repo: Path) -> tuple[set[str], set[str]]:
    result = _run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode:
        raise MetadataError("git status failed during managed provenance audit")
    dirty: set[str] = set()
    staged: set[str] = set()
    records = result.stdout.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or len(record) < 4:
            continue
        xy = record[:2].decode("ascii", errors="replace")
        path = record[3:].decode("utf-8", errors="surrogateescape")
        dirty.add(path)
        if xy[0] not in {" ", "?"}:
            staged.add(path)
        if "R" in xy or "C" in xy:
            index += 1  # porcelain -z appends the source name after a rename/copy
    return dirty, staged


def _head_hash(repo: Path, repo_relative: str) -> str | None:
    result = _run_git(repo, "show", f"HEAD:{repo_relative}")
    return _sha256_bytes(result.stdout) if result.returncode == 0 else None


def audit_git_install(
    install: Path,
    *,
    current_manifest: Mapping[str, Any] | None = None,
    staged_only: bool = False,
    retained_override: Mapping[str, Any] | None = None,
) -> list[PathProvenance]:
    """Classify dirty managed paths without modifying files or the Git index."""
    install = install.resolve()
    repo = _git_root(install)
    install_prefix = install.relative_to(repo).as_posix().rstrip("/")
    dirty, staged = _status(repo)

    retained: Mapping[str, Any] | None = retained_override
    if retained is not None:
        _manifest_index(retained, label="recovered historical release manifest")
    if current_manifest is not None:
        current_index = _manifest_index(current_manifest, label="current manifest")
        candidate_paths = set(current_index)
    else:
        # Installed hooks use the exact release manifest retained in the marker.
        retained = retained_manifest(install)
        current_manifest = retained
        current_index = _manifest_index(current_manifest, label="current manifest")
        candidate_paths = set(current_index)

    selected = staged if staged_only else dirty
    managed_dirty: list[tuple[str, str]] = []
    for managed_path in sorted(candidate_paths):
        repo_path = f"{install_prefix}/{managed_path}" if install_prefix else managed_path
        if repo_path in selected:
            managed_dirty.append((managed_path, repo_path))
    if not managed_dirty:
        return []

    if retained is None:
        retained = retained_manifest(install)
    retained_index = _manifest_index(retained, label="retained release manifest")

    rows: list[PathProvenance] = []
    for managed_path, repo_path in managed_dirty:
        actual = _sha256_file(install / managed_path)
        current = current_index.get(managed_path)
        prior = retained_index.get(managed_path)
        if actual is not None and actual == current:
            classification = EXACT_CURRENT
        elif (
            actual is not None
            and actual == prior
            and retained.get("fingerprint") != current_manifest.get("fingerprint")
        ):
            classification = RETAINED_PRIOR_RELEASE
        else:
            classification = UNRESOLVED_DIVERGENCE
        head = _head_hash(repo, repo_path)
        rows.append(
            PathProvenance(
                path=managed_path,
                classification=classification,
                actual_sha256=actual,
                current_sha256=current,
                retained_sha256=prior,
                head_sha256=head,
                differs_from_head=actual != head,
                staged=repo_path in staged,
            )
        )
    return rows


def guard_staged_install(install: Path) -> list[PathProvenance]:
    """Return staged managed paths that are not exact release payload bytes."""
    return [
        row
        for row in audit_git_install(install, staged_only=True)
        if row.classification != EXACT_CURRENT
    ]


def classify_partial_install(
    install: Path, *, current_manifest: Mapping[str, Any]
) -> list[PathProvenance]:
    """Classify every managed file in a partial apply without changing Git state."""
    install = install.resolve()
    repo = _git_root(install)
    prefix = install.relative_to(repo).as_posix().rstrip("/")
    _dirty, staged = _status(repo)
    current_index = _manifest_index(current_manifest, label="current manifest")
    try:
        prior_manifest = retained_manifest(install)
        prior_index = _manifest_index(prior_manifest, label="retained release manifest")
        prior_fingerprint = prior_manifest.get("fingerprint")
    except MetadataError:
        prior_index = {}
        prior_fingerprint = None
    rows: list[PathProvenance] = []
    for managed_path, current in sorted(current_index.items()):
        repo_path = f"{prefix}/{managed_path}" if prefix else managed_path
        actual = _sha256_file(install / managed_path)
        prior = prior_index.get(managed_path)
        if actual is not None and actual == current:
            classification = EXACT_CURRENT
        elif (
            actual is not None
            and actual == prior
            and prior_fingerprint != current_manifest.get("fingerprint")
        ):
            classification = RETAINED_PRIOR_RELEASE
        else:
            classification = UNRESOLVED_DIVERGENCE
        head = _head_hash(repo, repo_path)
        rows.append(
            PathProvenance(
                path=managed_path,
                classification=classification,
                actual_sha256=actual,
                current_sha256=current,
                retained_sha256=prior,
                head_sha256=head,
                differs_from_head=actual != head,
                staged=repo_path in staged,
            )
        )
    return rows


def _short(value: str | None) -> str:
    return value[:12] if value else "missing"


def format_rows(rows: Sequence[PathProvenance]) -> str:
    lines = []
    for row in rows:
        lines.append(
            f"{row.path}: {row.classification}; actual={_short(row.actual_sha256)}; "
            f"current={_short(row.current_sha256)}; retained={_short(row.retained_sha256)}; "
            f"head={_short(row.head_sha256)}; differs_from_head={str(row.differs_from_head).lower()}; "
            f"staged={str(row.staged).lower()}"
        )
    return "\n".join(lines)


def format_guidance(rows: Sequence[PathProvenance] = ()) -> str:
    detail = f"\n{format_rows(rows)}" if rows else ""
    return (
        "Managed Nightshift payload divergence detected. Preserve every project delta in place, "
        "create or update a canonical Nightshift spec, and implement and release it through the "
        "canonical flow. Review each unresolved path individually; no provenance was inferred "
        f"from timestamps, similarity, or aggregate fingerprints.{detail}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, default=Path(".nightshift"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument(
        "--recovery",
        action="store_true",
        help="classify every managed path in a preserved partial apply (read-only)",
    )
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest) if args.manifest else None
    if args.recovery and manifest is None:
        parser.error("--recovery requires --manifest")
    try:
        rows = (
            classify_partial_install(args.install, current_manifest=manifest)
            if args.recovery
            else audit_git_install(
                args.install, current_manifest=manifest, staged_only=args.staged
            )
        )
    except MetadataError as exc:
        print(f"managed payload metadata error: {exc}", file=sys.stderr)
        print(format_guidance(), file=sys.stderr)
        return 2
    print(format_rows(rows))
    if args.staged and any(row.classification != EXACT_CURRENT for row in rows):
        print(format_guidance(rows), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
