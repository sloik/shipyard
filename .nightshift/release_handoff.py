"""Versioned release-handoff contracts for canonical Nightshift changes.

The contract intentionally records portable repository-relative evidence only.
It does not discover releases from ignore rules, paths on the current machine, or
private observability data.  ``release_coordinator`` is the sole fulfiller of a
pending handoff after a successful full-kit rollout.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

HANDOFF_DIR = "release-handoffs"
DELIVERY_RECEIPT_SCHEMA_VERSION = 1
DELIVERY_RECEIPT_REPORT = "coordinator-positive-delivery-receipt-v1"
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"
# The spelling ``managed_paths`` used for the same surface before SPEC-230 made
# the skill an ordinary manifest entry, and the closed set of handoffs sealed
# while it was the managed spelling.  Both are frozen history: nothing new may
# join the set, and no other parent-directory escape is ever accepted.
LEGACY_SKILL_PATH = "../Skills/nightshift/SKILL.md"
LEGACY_SKILL_PATH_SPEC_IDS = frozenset(
    {"SPEC-203", "SPEC-207", "SPEC-208", "SPEC-225", "SPEC-226", "SPEC-228"}
)
RELEASE_HANDOFF_DECLARATION_POLICY_DATE = date(2026, 8, 8)
CURRENT_SPEC_TEMPLATE_VERSION = 8
MISSING_RELEASE_HANDOFF_DECLARATION_ERROR = (
    "release_handoff declaration required: choose impact: required "
    "or impact: exempt with a reason"
)
# A pending handoff whose target manifest was superseded before delivery can
# never complete as written: ``complete_pending_handoffs`` skips it by
# fingerprint forever.  It is a distinct situation from "authored against the
# current manifest but not delivered yet" and from "delivered at an earlier
# version", and it gets its own diagnostic so a reader can tell the three apart.
STRANDED_PENDING_HANDOFF_ERROR = (
    "release handoff is stranded: its pending target manifest was superseded "
    "before delivery"
)
# Handoff validation is otherwise driven from the spec side, so an artifact no
# spec declares is reachable by nothing: never validated, never completed, and
# never reported.  These three name what the directory-level sweep can find.
# An orphan and a doubly-declared artifact are different failures of the same
# reachability invariant and get separate diagnostics.
ORPHANED_HANDOFF_ARTIFACT_ERROR = (
    "orphaned release handoff artifact: no spec declares it, so nothing validates it"
)
AMBIGUOUS_HANDOFF_ARTIFACT_ERROR = (
    "ambiguous release handoff artifact: more than one spec declares it"
)
UNTRACKED_HANDOFF_ARTIFACT_ERROR = (
    "untracked release handoff artifact: it is absent from committed content, so "
    "a working-tree measurement and a checkout disagree about the corpus"
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
    # Records sealed before that move spelled it as an escape and are read
    # through ``accepted_artifact_paths``, never through this membership.
    paths.update({"hooks/commit-msg", "hooks/pre-commit"})
    return paths


def accepted_artifact_paths(manifest: Mapping[str, Any], *, spec_id: str) -> set[str]:
    """Managed paths, plus the retired spelling the enumerated records sealed.

    SPEC-230 moved the delivered skill into the manifest as
    ``SKILL_MANAGED_PATH``.  Until then ``managed_paths`` named the same surface
    through ``LEGACY_SKILL_PATH``, and the handoffs in
    ``LEGACY_SKILL_PATH_SPEC_IDS`` recorded what was managed on the day they
    shipped.  A sealed record is judged on its own terms (SPEC-244), so the
    retired spelling stays readable for exactly those records rather than
    rewriting history to today's spelling.

    The admission is an enumeration, not a relaxation: ``managed_paths`` still
    refuses the escape for every other record, only this one spelling is
    accepted, and it holds only while the surface it renames is managed today.
    """
    paths = managed_paths(manifest)
    if spec_id in LEGACY_SKILL_PATH_SPEC_IDS and SKILL_MANAGED_PATH in paths:
        paths.add(LEGACY_SKILL_PATH)
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


def _semver(value: Any) -> tuple[int, int, int] | None:
    """Parse a SemVer string through the module's single version grammar."""
    text = str(value)
    if not _SEMVER.fullmatch(text):
        return None
    major, minor, patch = text.split(".")
    return int(major), int(minor), int(patch)


def _is_stranded(artifact: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    """True when an undelivered record targets a manifest already superseded."""
    target = _semver(artifact.get("target_version"))
    current = _semver(manifest.get("kit_version"))
    return target is not None and current is not None and target < current


def _sealed_record_errors(artifact: Mapping[str, Any]) -> list[str]:
    """Validate a completed handoff against the record it sealed at delivery.

    A completed handoff is a historical delivery record.  It names the kit
    version and fingerprint it shipped against, so those fields are checked for
    internal consistency — never against whatever manifest happens to be checked
    out now, which is a question history cannot answer.
    """
    errors: list[str] = []
    sealed_fingerprint = artifact.get("manifest_fingerprint")
    if not isinstance(sealed_fingerprint, str) or not sealed_fingerprint:
        errors.append("completed release handoff requires a sealed manifest_fingerprint")
    receipt = artifact.get("delivery_receipt")
    # Historical completed records predate the receipt schema and carry a
    # ``release_report`` token instead; ``validate_positive_delivery`` is the
    # stricter surface that requires a structured receipt.  When one is present
    # it must agree with the record it seals.
    if isinstance(receipt, Mapping):
        if receipt.get("kit_version") != artifact.get("target_version"):
            errors.append(
                "delivery receipt kit version does not match the sealed target_version"
            )
        if receipt.get("manifest_fingerprint") != sealed_fingerprint:
            errors.append(
                "delivery receipt fingerprint does not match the sealed "
                "manifest_fingerprint"
            )
    return errors


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
    if artifact.get("status") == "completed":
        # Delivered: judge the sealed record, not today's manifest.
        errors.extend(_sealed_record_errors(artifact))
    elif _is_stranded(artifact, manifest):
        # Undelivered and unreachable: name that, rather than reusing the
        # not-yet-delivered messages below.
        errors.append(
            f"{STRANDED_PENDING_HANDOFF_ERROR} "
            f"(target {artifact.get('target_version')}, "
            f"current {manifest.get('kit_version')})"
        )
    else:
        # Undelivered and still reachable: it must target the current manifest.
        if artifact.get("target_version") != manifest.get("kit_version"):
            errors.append(
                "release handoff target_version does not match manifest version"
            )
        if artifact.get("manifest_fingerprint") != fingerprint(manifest):
            errors.append("release handoff manifest fingerprint does not match manifest")
    changed = artifact.get("changed_managed_paths")
    if (
        not isinstance(changed, list)
        or not changed
        or not all(isinstance(path, str) for path in changed)
    ):
        errors.append("release handoff requires changed_managed_paths")
    elif unknown := sorted(
        set(changed) - accepted_artifact_paths(manifest, spec_id=spec_id)
    ):
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


def sweep_handoff_directory(
    canonical: Path,
    declaring_spec_ids: Iterable[str],
    *,
    tracked_paths: Collection[str] | None = None,
) -> dict[str, list[str]]:
    """Judge the handoff directory from the artifact side.

    ``validate_spec_handoff`` resolves an artifact only after reading a spec's
    declaration, so it structurally cannot see an artifact that no spec
    declares.  This sweep walks the directory instead and reports each finding
    against the artifact's own repository-relative path, because for an orphan
    there is by definition no spec ID to attribute it to.

    ``declaring_spec_ids`` is supplied by the caller — the module stays free of
    spec parsing — and may repeat an ID, which is how a doubly-declared
    artifact is detected.  ``tracked_paths`` holds canonical-relative paths that
    git reports as tracked; ``None`` means tracking could not be judged here (no
    repository, or a deliberately ignored private install) and the assertion is
    skipped rather than reported as a finding against every artifact.
    """
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return {}
    declared = Counter(str(spec_id) for spec_id in declaring_spec_ids)
    findings: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.json")):
        relative = f"{HANDOFF_DIR}/{path.name}"
        errors: list[str] = []
        declarations = declared[path.stem]
        if declarations == 0:
            errors.append(f"{relative}: {ORPHANED_HANDOFF_ARTIFACT_ERROR}")
        elif declarations > 1:
            errors.append(
                f"{relative}: {AMBIGUOUS_HANDOFF_ARTIFACT_ERROR} "
                f"({declarations} specs declare {path.stem})"
            )
        if tracked_paths is not None and relative not in tracked_paths:
            errors.append(f"{relative}: {UNTRACKED_HANDOFF_ARTIFACT_ERROR}")
        if errors:
            findings[relative] = errors
    return findings


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
