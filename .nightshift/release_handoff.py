"""Versioned release-handoff contracts for canonical Nightshift changes.

The contract intentionally records portable repository-relative evidence only.
It does not discover releases from ignore rules, paths on the current machine, or
private observability data.  ``release_coordinator`` is the sole fulfiller of a
pending handoff after a successful full-kit rollout.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping


HANDOFF_DIR = "release-handoffs"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_PRIVATE_KEYS = frozenset({"telemetry", "private_path", "absolute_path", "dropbox_root"})


def _contains_private_data(value: Any, key: str = "") -> bool:
    if key.lower() in _PRIVATE_KEYS:
        return True
    if isinstance(value, str):
        return value.startswith("/") or "{{ARGO_HOME}}" in value
    if isinstance(value, Mapping):
        return any(_contains_private_data(item, str(name)) for name, item in value.items())
    if isinstance(value, list):
        return any(_contains_private_data(item) for item in value)
    return False


def artifact_path(canonical: Path, spec_id: str) -> Path:
    return canonical / HANDOFF_DIR / f"{spec_id}.json"


def fingerprint(manifest: Mapping[str, Any]) -> str:
    return str(manifest.get("fingerprint", ""))


def managed_paths(manifest: Mapping[str, Any]) -> set[str]:
    """Return canonical managed surfaces, including non-manifest release inputs."""
    paths = {str(entry.get("path")) for entry in manifest.get("files", [])}
    paths.update({"config.yaml", "config-reference.yaml", "release-manifest.json"})
    # Kept explicit: these are copied by the sync command but are intentionally
    # outside the release manifest until old installs understand this contract.
    paths.update({"hooks/commit-msg", "hooks/pre-commit", "../Skills/nightshift/SKILL.md"})
    return paths


def release_impact(changed_paths: list[str], manifest: Mapping[str, Any]) -> list[str]:
    known = managed_paths(manifest)
    return sorted(path for path in changed_paths if path in known)


def validate_artifact(
    artifact: Mapping[str, Any], *, spec_id: str, manifest: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if _contains_private_data(artifact):
        errors.append("release handoff artifact contains private path or telemetry")
    if artifact.get("spec_id") != spec_id:
        errors.append("release handoff spec_id does not match spec")
    if not _SEMVER.fullmatch(str(artifact.get("target_version", ""))):
        errors.append("release handoff target_version must be SemVer")
    if artifact.get("target_version") != manifest.get("kit_version"):
        errors.append("release handoff target_version does not match manifest version")
    if artifact.get("manifest_fingerprint") != fingerprint(manifest):
        errors.append("release handoff manifest fingerprint does not match manifest")
    changed = artifact.get("changed_managed_paths")
    if not isinstance(changed, list) or not changed or not all(isinstance(path, str) for path in changed):
        errors.append("release handoff requires changed_managed_paths")
    elif unknown := sorted(set(changed) - managed_paths(manifest)):
        errors.append("release handoff names unmanaged paths: " + ", ".join(unknown))
    if not isinstance(artifact.get("canonical_commit_range"), str) or not artifact["canonical_commit_range"]:
        errors.append("release handoff requires canonical_commit_range")
    if not isinstance(artifact.get("changelog_entry"), str) or not artifact["changelog_entry"]:
        errors.append("release handoff requires changelog_entry")
    migrations = artifact.get("required_migrations")
    if not isinstance(migrations, list) or not all(isinstance(item, str) for item in migrations):
        errors.append("release handoff required_migrations must be a list of strings")
    scope = artifact.get("fleet_sync_scope")
    if not isinstance(scope, str) or scope not in {"all-managed-installs", "eligible-managed-installs"}:
        errors.append("release handoff fleet_sync_scope is invalid")
    if artifact.get("status") not in {"pending", "completed"}:
        errors.append("release handoff status must be pending or completed")
    if artifact.get("status") == "completed" and not artifact.get("release_report"):
        errors.append("completed release handoff requires release_report")
    return errors


def validate_spec_handoff(
    frontmatter: Mapping[str, Any], canonical: Path, manifest: Mapping[str, Any]
) -> list[str]:
    """Validate terminal release-impact declarations without retrofitting history."""
    declaration = frontmatter.get("release_handoff")
    if declaration is None:
        return []
    if not isinstance(declaration, Mapping):
        return ["release_handoff must be a mapping"]
    impact = declaration.get("impact")
    if impact == "exempt":
        return [] if isinstance(declaration.get("reason"), str) and declaration["reason"].strip() else ["release_handoff exemption requires reason"]
    if impact != "required":
        return ["release_handoff impact must be required or exempt"]
    artifact = artifact_path(canonical, str(frontmatter.get("id", "")))
    if not artifact.is_file():
        return ["release-impact spec requires a release handoff artifact"]
    try:
        data = json.loads(artifact.read_text())
    except json.JSONDecodeError:
        return ["release handoff artifact is invalid JSON"]
    return validate_artifact(data, spec_id=str(frontmatter.get("id", "")), manifest=manifest)


def complete_pending_handoffs(canonical: Path, manifest: Mapping[str, Any], report: str) -> list[str]:
    """Mark matching pending records complete after coordinator-owned success."""
    completed: list[str] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return completed
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("status") != "pending" or data.get("manifest_fingerprint") != fingerprint(manifest):
            continue
        if validate_artifact(data, spec_id=str(data.get("spec_id", "")), manifest=manifest):
            continue
        data["status"] = "completed"
        data["release_report"] = report
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        completed.append(str(data["spec_id"]))
    return completed
