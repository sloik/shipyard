"""Deterministic, whole-kit release manifests and install verification (SPEC-156)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

MARKER = "release-marker.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kit_version(canonical: Path) -> str:
    match = re.search(
        r'^kit_version:\s*"([^"]+)"',
        (canonical / "config.yaml").read_text(),
        re.MULTILINE,
    )
    if not match:
        raise ValueError("canonical config.yaml is missing kit_version")
    return match.group(1)


def manifest_files(canonical: Path, names: list[str]) -> list[dict]:
    entries = []
    for name in sorted(names):
        path = canonical / name
        if not path.is_file():
            raise ValueError(f"managed file missing: {name}")
        entries.append(
            {
                "path": name,
                "sha256": sha256(path),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        )
    return entries


def managed_import_gaps(canonical: Path, names: list[str]) -> list[str]:
    """Report managed Python files whose local imports are absent from the release set.

    Only imports that resolve to a sibling module in ``canonical`` are relevant:
    standard-library and third-party dependencies are supplied by the target project,
    whereas a sibling module must be copied by the kit release itself.  ``ast.walk``
    deliberately visits imports in function bodies as well as module scope.
    """
    managed = set(names)
    gaps: list[str] = []
    for name in sorted(managed):
        if not name.endswith(".py"):
            continue
        source = canonical / name
        try:
            tree = ast.parse(source.read_text(), filename=str(source))
        except SyntaxError as exc:
            gaps.append(f"managed Python file cannot be parsed: {name}: {exc.msg}")
            continue
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                else []
            )
            for module in modules:
                local = Path(*module.split(".")).with_suffix(".py")
                if (canonical / local).is_file() and str(local) not in managed:
                    gaps.append(
                        f"managed import missing from release set: {name} imports {local}"
                    )
    return sorted(set(gaps))


def build_manifest(
    canonical: Path, names: list[str], *, smoke_checks: list[str] | None = None
) -> dict:
    payload = {
        "kit_version": kit_version(canonical),
        "schema_version": "3.0.0",
        "files": manifest_files(canonical, names),
        "smoke_checks": smoke_checks
        or [
            (
                'python3 -c "import ast,pathlib; '
                "[ast.parse(pathlib.Path(p).read_text()) for p in "
                "('board.py','release.py','reflexion_producer.py')]\""
            )
        ],
        "canonical_suite": "python3 -m pytest -q tests",
        "migration_checks": ["python3 validate_specs.py specs/"],
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "fingerprint": hashlib.sha256(normalized).hexdigest()}


def write_manifest(canonical: Path, names: list[str]) -> dict:
    manifest = build_manifest(canonical, names)
    (canonical / "release-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    return manifest


def validate_manifest(
    canonical: Path, names: list[str]
) -> tuple[bool, list[str], dict | None]:
    path = canonical / "release-manifest.json"
    if not path.exists():
        return False, ["release manifest missing"], None
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False, ["release manifest invalid JSON"], None
    expected = build_manifest(
        canonical, names, smoke_checks=manifest.get("smoke_checks")
    )
    errors = []
    for key in (
        "kit_version",
        "schema_version",
        "files",
        "smoke_checks",
        "canonical_suite",
        "migration_checks",
        "fingerprint",
    ):
        if manifest.get(key) != expected.get(key):
            errors.append(f"manifest {key} does not match canonical")
    changelog = canonical / "CHANGELOG.md"
    headings = (
        re.findall(r"^##\s+(\d+\.\d+\.\d+)\b", changelog.read_text(), re.MULTILINE)
        if changelog.is_file()
        else []
    )
    if not headings or max(
        headings, key=lambda value: tuple(map(int, value.split(".")))
    ) != kit_version(canonical):
        errors.append("manifest version does not match newest changelog release")
    if not manifest.get("smoke_checks") or not all(
        isinstance(command, str) and command.strip()
        for command in manifest["smoke_checks"]
    ):
        errors.append("manifest smoke-check metadata is invalid")
    errors.extend(managed_import_gaps(canonical, names))
    return not errors, errors, manifest


def verify_install(install: Path, manifest: dict) -> tuple[bool, list[str]]:
    errors = []
    for entry in manifest["files"]:
        path = install / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            errors.append(f"managed file mismatch: {entry['path']}")
        elif bool(path.stat().st_mode & 0o111) != entry["executable"]:
            errors.append(f"managed mode mismatch: {entry['path']}")
    marker = install / MARKER
    if not marker.exists():
        errors.append("release marker missing")
    else:
        marker_data = json.loads(marker.read_text())
        if (
            marker_data.get("fingerprint") != manifest["fingerprint"]
            or marker_data.get("kit_version") != manifest["kit_version"]
        ):
            errors.append("release marker is not exact")
    return not errors, errors


def apply_install(
    canonical: Path, install: Path, manifest: dict, *, dry_run: bool = False
) -> tuple[bool, list[str]]:
    """Copy whole managed set, verify it, then write marker last. No partial mode."""
    if dry_run:
        return True, [f"would copy {len(manifest['files'])} managed files"]
    for entry in manifest["files"]:
        dst = install / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((canonical / entry["path"]).read_bytes())
        os.chmod(dst, 0o755 if entry["executable"] else 0o644)
    # Verify content before the marker exists; marker is deliberately final.
    for entry in manifest["files"]:
        if sha256(install / entry["path"]) != entry["sha256"]:
            return False, [f"copy verification failed: {entry['path']}"]
    (install / MARKER).write_text(
        json.dumps(
            {
                "kit_version": manifest["kit_version"],
                "fingerprint": manifest["fingerprint"],
                "schema_version": manifest["schema_version"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return verify_install(install, manifest)


def managed_drift(install: Path, manifest: dict) -> list[str]:
    """Return staged/unstaged managed paths; only git-tracked drift is a conflict."""
    result = subprocess.run(
        ["git", "-C", str(install), "status", "--porcelain", "--"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return []
    managed = {entry["path"] for entry in manifest["files"]} | {MARKER}
    return sorted(
        {
            line[3:]
            for line in result.stdout.splitlines()
            if len(line) > 3 and line[3:] in managed
        }
    )


def apply_fleet(
    canonical: Path, installs: list[Path], manifest: dict, *, dry_run: bool = False
) -> dict:
    """Independent repositories continue after known drift; no repository is partially applied."""
    outcome = {"verified": [], "skipped": [], "unexpected": []}
    for install in installs:
        drift = managed_drift(install, manifest)
        if drift:
            outcome["skipped"].append(
                {
                    "install": str(install),
                    "reason": "dirty managed path",
                    "paths": drift,
                }
            )
            continue
        ok, details = apply_install(canonical, install, manifest, dry_run=dry_run)
        if ok:
            outcome["verified"].append(str(install))
        else:
            outcome["unexpected"].append({"install": str(install), "details": details})
            break  # unexpected failure stops later independent repositories
    return outcome
