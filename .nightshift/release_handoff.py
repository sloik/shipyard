"""Versioned release-handoff contracts for canonical Nightshift changes.

The contract intentionally records portable repository-relative evidence only.
It does not discover releases from ignore rules, paths on the current machine, or
private observability data.  ``release_coordinator`` is the sole fulfiller of a
pending handoff after a successful full-kit rollout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

HANDOFF_DIR = "release-handoffs"
DELIVERY_RECEIPT_SCHEMA_VERSION = 1
DELIVERY_RECEIPT_REPORT = "coordinator-positive-delivery-receipt-v1"
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"
RELEASE_HANDOFF_DECLARATION_POLICY_DATE = date(2026, 8, 8)
CURRENT_SPEC_TEMPLATE_VERSION = 8
MISSING_RELEASE_HANDOFF_DECLARATION_ERROR = (
    "release_handoff declaration required: choose impact: required "
    "or impact: exempt with a reason"
)
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_PRIVATE_KEYS = frozenset(
    {"telemetry", "private_path", "absolute_path", "dropbox_root"}
)


def _contains_private_data(value: Any, key: str = "") -> bool:
    if key.lower() in _PRIVATE_KEYS:
        return True
    if isinstance(value, str):
        return value.startswith("/") or "{{ARGO_HOME}}" in value
    if isinstance(value, Mapping):
        return any(
            _contains_private_data(item, str(name)) for name, item in value.items()
        )
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
    # Hooks predate the manifest contract. The active skill is now an ordinary
    # exact manifest path; never represent it through a parent-directory escape.
    paths.update({"hooks/commit-msg", "hooks/pre-commit"})
    return paths


def release_impact(changed_paths: list[str], manifest: Mapping[str, Any]) -> list[str]:
    known = managed_paths(manifest)
    return sorted(path for path in changed_paths if path in known)


def _manifest_sha256(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(entry.get("path")): str(entry.get("sha256"))
        for entry in manifest.get("files", [])
        if isinstance(entry, Mapping)
    }


def build_delivery_receipt(
    artifact: Mapping[str, Any],
    manifest: Mapping[str, Any],
    release_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Project coordinator state into a portable per-handoff receipt."""
    hashes = _manifest_sha256(manifest)
    changed = artifact.get("changed_managed_paths", [])
    receipt = {
        "schema_version": DELIVERY_RECEIPT_SCHEMA_VERSION,
        "producer": "release_coordinator",
        "kit_version": manifest.get("kit_version"),
        "manifest_fingerprint": fingerprint(manifest),
        "canonical_suite": {
            "probe": release_result.get("canonical_suite_probe"),
            "runs": release_result.get("canonical_suite_runs"),
            "result": release_result.get("canonical_suite_result"),
        },
        "delivery": {
            "managed_payload_mode": release_result.get("managed_payload_mode"),
            "file_level_patch": release_result.get("file_level_patch_attempted"),
            "verified_install_count": len(release_result.get("verified_installs", [])),
        },
        "safety": {
            "unexpected_failure": bool(release_result.get("unexpected_failure")),
            "rollback_attempted": release_result.get("rollback_attempted"),
            "push_attempted": release_result.get("push_attempted"),
        },
        "changed_managed_path_sha256": {
            str(path): hashes.get(str(path), "") for path in changed
        },
    }
    if SKILL_MANAGED_PATH in changed:
        receipt["skill_delivery"] = release_result.get("skill_delivery")
    return receipt


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
    if (
        not isinstance(changed, list)
        or not changed
        or not all(isinstance(path, str) for path in changed)
    ):
        errors.append("release handoff requires changed_managed_paths")
    elif unknown := sorted(set(changed) - managed_paths(manifest)):
        errors.append("release handoff names unmanaged paths: " + ", ".join(unknown))
    if (
        not isinstance(artifact.get("canonical_commit_range"), str)
        or not artifact["canonical_commit_range"]
    ):
        errors.append("release handoff requires canonical_commit_range")
    if (
        not isinstance(artifact.get("changelog_entry"), str)
        or not artifact["changelog_entry"]
    ):
        errors.append("release handoff requires changelog_entry")
    migrations = artifact.get("required_migrations")
    if not isinstance(migrations, list) or not all(
        isinstance(item, str) for item in migrations
    ):
        errors.append("release handoff required_migrations must be a list of strings")
    scope = artifact.get("fleet_sync_scope")
    if not isinstance(scope, str) or scope not in {
        "all-managed-installs",
        "eligible-managed-installs",
    }:
        errors.append("release handoff fleet_sync_scope is invalid")
    if artifact.get("status") not in {"pending", "completed"}:
        errors.append("release handoff status must be pending or completed")
    if artifact.get("status") == "completed" and not artifact.get("release_report"):
        errors.append("completed release handoff requires release_report")
    return errors


def validate_positive_delivery(
    artifact: Mapping[str, Any], *, spec_id: str, manifest: Mapping[str, Any]
) -> list[str]:
    """Require coordinator-authored positive delivery proof for a completed handoff.

    ``validate_artifact`` deliberately remains compatible with historical completed
    records whose ``release_report`` is a string token.  Call this stricter validator
    anywhere a positive managed-install delivery must be proven.
    """
    errors = validate_artifact(artifact, spec_id=spec_id, manifest=manifest)
    receipt = artifact.get("delivery_receipt")
    if not isinstance(receipt, Mapping):
        return errors + ["positive delivery requires a structured delivery_receipt"]
    if receipt.get("schema_version") != DELIVERY_RECEIPT_SCHEMA_VERSION:
        errors.append("delivery receipt schema_version is invalid")
    if receipt.get("producer") != "release_coordinator":
        errors.append("delivery receipt producer must be release_coordinator")
    if receipt.get("kit_version") != manifest.get("kit_version"):
        errors.append("delivery receipt kit version does not match manifest")
    if receipt.get("manifest_fingerprint") != fingerprint(manifest):
        errors.append("delivery receipt fingerprint does not match manifest")

    suite = receipt.get("canonical_suite")
    if not isinstance(suite, Mapping) or dict(suite) != {
        "probe": "passed",
        "runs": 1,
        "result": "passed",
    }:
        errors.append(
            "delivery receipt requires exactly one passing canonical suite run"
        )

    delivery = receipt.get("delivery")
    if not isinstance(delivery, Mapping):
        errors.append("delivery receipt requires whole-kit delivery evidence")
    else:
        if delivery.get("managed_payload_mode") != "canonical_replace":
            errors.append("delivery receipt requires canonical_replace whole-kit mode")
        if delivery.get("file_level_patch") is not False:
            errors.append("delivery receipt must prove no file-level patch was used")
        count = delivery.get("verified_install_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            errors.append("delivery receipt requires a positive verified-install count")

    safety = receipt.get("safety")
    if not isinstance(safety, Mapping) or any(
        safety.get(name) is not False
        for name in ("unexpected_failure", "rollback_attempted", "push_attempted")
    ):
        errors.append(
            "delivery receipt requires no unexpected failure, rollback, or push"
        )

    changed = artifact.get("changed_managed_paths")
    changed_paths = changed if isinstance(changed, list) else []
    expected_hashes = _manifest_sha256(manifest)
    expected = {
        path: expected_hashes[path] for path in changed_paths if path in expected_hashes
    }
    actual = receipt.get("changed_managed_path_sha256")
    if (
        not isinstance(actual, Mapping)
        or dict(actual) != expected
        or len(expected) != len(changed_paths)
    ):
        errors.append(
            "delivery receipt requires the exact manifest SHA-256 for every changed managed path"
        )
    if SKILL_MANAGED_PATH in changed_paths:
        skill = receipt.get("skill_delivery")
        expected_hash = expected_hashes.get(SKILL_MANAGED_PATH)
        if not isinstance(skill, Mapping):
            errors.append("delivery receipt requires canonical skill delivery evidence")
        else:
            verification = skill.get("verification")
            commit = skill.get("commit_evidence")
            if (
                skill.get("source_relative_path") != SKILL_MANAGED_PATH
                or skill.get("target_relative_path") != SKILL_MANAGED_PATH
                or skill.get("sha256") != expected_hash
                or not isinstance(verification, Mapping)
                or any(
                    verification.get(name) is not True
                    for name in ("bytes", "sha256", "mode")
                )
                or not isinstance(commit, Mapping)
                or not re.fullmatch(r"[0-9a-f]{40}", str(commit.get("sha", "")))
                or commit.get("paths") != [SKILL_MANAGED_PATH]
                or commit.get("verified") is not True
                or commit.get("unrelated_staging_preserved") is not True
                or commit.get("mode") != "100644"
            ):
                errors.append(
                    "delivery receipt requires exact verified canonical skill bytes and commit"
                )
    return errors


def validate_spec_handoff(
    frontmatter: Mapping[str, Any], canonical: Path, manifest: Mapping[str, Any]
) -> list[str]:
    """Validate current release-handoff declarations without retrofitting history.

    Specs created on or after the SPEC-189 policy date, or authored from the
    current template, must classify their release impact even if their status is
    later changed to ``done``. Older specs retain compatibility through their
    durable creation/template metadata, not terminal status.
    """
    declaration = frontmatter.get("release_handoff")
    if declaration is None:
        created = frontmatter.get("created")
        try:
            subject_to_policy = (
                date.fromisoformat(str(created))
                >= RELEASE_HANDOFF_DECLARATION_POLICY_DATE
            )
        except ValueError:
            subject_to_policy = False
        template_version = frontmatter.get("template_version")
        try:
            subject_to_current_template = int(template_version) >= CURRENT_SPEC_TEMPLATE_VERSION
        except (TypeError, ValueError):
            subject_to_current_template = False
        if subject_to_policy or subject_to_current_template:
            return [MISSING_RELEASE_HANDOFF_DECLARATION_ERROR]
        return []
    if not isinstance(declaration, Mapping):
        return ["release_handoff must be a mapping"]
    impact = declaration.get("impact")
    if impact == "exempt":
        return (
            []
            if isinstance(declaration.get("reason"), str)
            and declaration["reason"].strip()
            else ["release_handoff exemption requires reason"]
        )
    if impact != "required":
        return ["release_handoff impact must be required or exempt"]
    artifact = artifact_path(canonical, str(frontmatter.get("id", "")))
    if not artifact.is_file():
        return ["release-impact spec requires a release handoff artifact"]
    try:
        data = json.loads(artifact.read_text())
    except json.JSONDecodeError:
        return ["release handoff artifact is invalid JSON"]
    return validate_artifact(
        data, spec_id=str(frontmatter.get("id", "")), manifest=manifest
    )


def complete_pending_handoffs(
    canonical: Path,
    manifest: Mapping[str, Any],
    release_result: Mapping[str, Any],
) -> list[str]:
    """Complete matching records only with coordinator-owned positive delivery."""
    completed: list[str] = []
    if not isinstance(release_result, Mapping):
        return completed
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return completed
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("status") != "pending" or data.get(
            "manifest_fingerprint"
        ) != fingerprint(manifest):
            continue
        if validate_artifact(
            data, spec_id=str(data.get("spec_id", "")), manifest=manifest
        ):
            continue
        candidate = dict(data)
        candidate["status"] = "completed"
        candidate["release_report"] = DELIVERY_RECEIPT_REPORT
        candidate["delivery_receipt"] = build_delivery_receipt(
            candidate, manifest, release_result
        )
        if validate_positive_delivery(
            candidate, spec_id=str(candidate.get("spec_id", "")), manifest=manifest
        ):
            continue
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        completed.append(str(candidate["spec_id"]))
    return completed
