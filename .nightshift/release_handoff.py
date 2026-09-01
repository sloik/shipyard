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
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import lifecycle

HANDOFF_DIR = "release-handoffs"
DELIVERY_RECEIPT_SCHEMA_VERSION = 1
DELIVERY_RECEIPT_REPORT = "coordinator-positive-delivery-receipt-v1"
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"
# A handoff author cannot know the fingerprint of the release that will carry
# their implementation.  This exact sentinel is the only permitted unpinned
# value; the coordinator replaces it immediately before delivery validation.
PENDING_MANIFEST_FINGERPRINT = "pending-release-manifest-fingerprint-v1"
RELEASE_HANDOFF_DECLARATION_POLICY_DATE = date(2026, 8, 8)
CURRENT_SPEC_TEMPLATE_VERSION = 8
# SPEC-271 R1: the terminal non-delivering status set, derived structurally
# from ``lifecycle.LIFECYCLE_TRANSITIONS`` -- never redefined independently,
# so code and docs (SPEC-GUIDE.md) cannot drift from the registry's own
# transition table. ``lifecycle.terminal_statuses()`` returns every status
# with no outgoing transition ({"done", "superseded"} today). Of those,
# "done" is delivering by definition and stays fully gated by R4; the one
# terminal status that is also non-delivering is "superseded".
TERMINAL_NON_DELIVERING_STATUSES = lifecycle.terminal_statuses() - {"done"}
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
# SPEC-251 R1/R3: a stranded record never resolves itself -- it needs an
# operator-authorized disposition recorded beside it. The key name and shape
# are deliberately independent of ``status``/``manifest_fingerprint`` so
# recording a disposition never changes whether a record still reports
# ``STRANDED_PENDING_HANDOFF_ERROR`` (R4): a disposition documents a decision,
# it does not repair the fingerprint.
DISPOSITION_KEY = "disposition"
RE_PIN_DISPOSITION = "re-pin"
FOLD_DISPOSITION = "fold"
RETIRE_DISPOSITION = "retire"
VALID_DISPOSITIONS = frozenset({RE_PIN_DISPOSITION, FOLD_DISPOSITION, RETIRE_DISPOSITION})
DISPOSITION_REQUIRED_FIELDS = ("decision", "fleet_presence", "reason", "decided_by", "decided_at", "run_id")
MISSING_STRANDED_DISPOSITION_ERROR = (
    "stranded release handoff has no recorded disposition: R1 requires one of "
    "re-pin, fold, or retire"
)
INVALID_STRANDED_DISPOSITION_ERROR = "release handoff disposition is malformed"
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


def accepted_artifact_paths(manifest: Mapping[str, Any]) -> set[str]:
    """Return the exact managed paths of the manifest being judged."""
    return managed_paths(manifest)


def resolve_manifest_membership(
    artifact: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve path-membership evidence without falling back to present data."""
    version = str(artifact.get("target_version", ""))
    sealed_fingerprint = str(artifact.get("manifest_fingerprint", ""))
    if (
        manifest.get("kit_version") == version
        and fingerprint(manifest) == sealed_fingerprint
    ):
        return {"outcome": "current", "manifest": manifest, "reason": ""}
    for retained in manifest.get("retained_manifests", []):
        if not isinstance(retained, Mapping):
            continue
        if (
            retained.get("kit_version") == version
            and fingerprint(retained) == sealed_fingerprint
        ):
            return {"outcome": "retained", "manifest": retained, "reason": ""}
    for entry in manifest.get("unretained_manifests", []):
        if not isinstance(entry, Mapping) or entry.get("version") != version:
            continue
        reason = str(entry.get("reason", "")).strip()
        if reason:
            return {
                "outcome": "explicitly-unretained",
                "manifest": None,
                "reason": reason,
            }
    return {
        "outcome": "missing",
        "manifest": None,
        "reason": "target release is neither retained nor explicitly unretained",
    }


def release_impact(changed_paths: list[str], manifest: Mapping[str, Any]) -> list[str]:
    known = managed_paths(manifest)
    return sorted(path for path in changed_paths if path in known)


# Non-manifest release inputs named by ``managed_paths()`` (see its docstring)
# that never appear in ``manifest["files"]``: ``config.yaml`` is project-owned
# per install and deliberately excluded from the shipped payload list;
# ``release-manifest.json`` is canonical-only release bookkeeping, never
# copied to fleet installs. ``config-reference.yaml`` is not listed here
# because it already appears in ``manifest["files"]`` as an ordinary
# ``CANONICAL_PROTOCOL_FILES`` entry.
_NON_MANIFEST_HASHED_INPUTS = ("config.yaml", "release-manifest.json")


def _manifest_sha256(
    manifest: Mapping[str, Any], canonical: Path | None = None
) -> dict[str, str]:
    """Return verifiable SHA-256 hashes for manifest-listed and named inputs.

    ``manifest["files"]`` covers the ordinary managed payload. When
    ``canonical`` is supplied, also hash the current bytes of the
    non-manifest release inputs ``managed_paths()`` accepts
    (``config.yaml``, ``release-manifest.json``) so that a handoff naming
    them can be positively verified, exactly as it can be for a
    manifest-listed path. A path already present from ``manifest["files"]``
    is never overwritten by this step.
    """
    hashes = {
        str(entry.get("path")): str(entry.get("sha256"))
        for entry in manifest.get("files", [])
        if isinstance(entry, Mapping)
    }
    if canonical is not None:
        for name in _NON_MANIFEST_HASHED_INPUTS:
            if name in hashes:
                continue
            candidate = canonical / name
            if candidate.is_file():
                hashes[name] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return hashes


def _semver(value: Any) -> tuple[int, int, int] | None:
    """Parse a SemVer string through the module's single version grammar."""
    text = str(value)
    if not _SEMVER.fullmatch(text):
        return None
    major, minor, patch = text.split(".")
    return int(major), int(minor), int(patch)


def _matches_current_manifest_fingerprint(
    artifact: Mapping[str, Any], manifest: Mapping[str, Any]
) -> bool:
    """Return the coordinator's completion-eligibility fingerprint predicate."""
    return artifact.get("manifest_fingerprint") == fingerprint(manifest)


def _has_pending_manifest_placeholder(artifact: Mapping[str, Any]) -> bool:
    """Return whether an undelivered handoff uses the one authoring sentinel."""
    return (
        artifact.get("status") == "pending"
        and artifact.get("manifest_fingerprint") == PENDING_MANIFEST_FINGERPRINT
    )


def _is_stranded(artifact: Mapping[str, Any], manifest: Mapping[str, Any]) -> bool:
    """True when a pending record can no longer complete against this manifest."""
    return (
        not _has_pending_manifest_placeholder(artifact)
        and artifact.get("status") == "pending"
        and not _matches_current_manifest_fingerprint(artifact, manifest)
    )


def _stranded_disposition(
    artifact: Mapping[str, Any], manifest: Mapping[str, Any]
) -> str:
    """Describe how the target version relates to its superseding manifest."""
    target = _semver(artifact.get("target_version"))
    current = _semver(manifest.get("kit_version"))
    if target is not None and target == current:
        return "same version re-fingerprinted"
    if target is not None and current is not None and target < current:
        return "older target version"
    return "version relationship unavailable"


def disposition_errors(disposition: Any) -> list[str]:
    """Validate one recorded stranded-handoff disposition (SPEC-251 R1/R2).

    Every field is required regardless of ``decision``: R2 requires the
    fleet-presence finding on every record including retirements, and R1
    requires the reason and the who/when of the decision on every record, not
    only retirements.
    """
    if not isinstance(disposition, Mapping):
        return [f"{INVALID_STRANDED_DISPOSITION_ERROR}: must be a mapping"]
    errors: list[str] = []
    if disposition.get("decision") not in VALID_DISPOSITIONS:
        errors.append(
            f"{INVALID_STRANDED_DISPOSITION_ERROR}: decision must be one of "
            f"{sorted(VALID_DISPOSITIONS)}"
        )
    for field in DISPOSITION_REQUIRED_FIELDS:
        if field == "decision":
            continue
        value = disposition.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{INVALID_STRANDED_DISPOSITION_ERROR}: {field} is required")
    return errors


def stranded_disposition_findings(
    canonical: Path, manifest: Mapping[str, Any]
) -> dict[str, list[str]]:
    """R3 regrowth guard: every stranded record must carry a recorded disposition.

    Reuses SPEC-244's ``_is_stranded`` predicate rather than reimplementing
    strandedness, and never mutates the artifact it reads -- a disposition
    finding never suppresses ``STRANDED_PENDING_HANDOFF_ERROR`` in
    ``validate_artifact``. Findings are keyed by the artifact's own
    repository-relative path, matching ``sweep_handoff_directory``.
    """
    directory = canonical / HANDOFF_DIR
    findings: dict[str, list[str]] = {}
    if not directory.is_dir():
        return findings
    for path in sorted(directory.glob("*.json")):
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(artifact, Mapping) or not _is_stranded(artifact, manifest):
            continue
        relative = f"{HANDOFF_DIR}/{path.name}"
        disposition = artifact.get(DISPOSITION_KEY)
        if disposition is None:
            findings[relative] = [MISSING_STRANDED_DISPOSITION_ERROR]
            continue
        errors = disposition_errors(disposition)
        if errors:
            findings[relative] = errors
    return findings


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
    *,
    canonical: Path | None = None,
) -> dict[str, Any]:
    """Project coordinator state into a portable per-handoff receipt.

    ``canonical``, when supplied, lets the receipt's hash source also cover
    the non-manifest release inputs named in ``changed_managed_paths`` (see
    ``_manifest_sha256``).
    """
    hashes = _manifest_sha256(manifest, canonical)
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
    elif _has_pending_manifest_placeholder(artifact):
        # This is an intentionally unsealed authoring record.  It remains
        # structurally valid while the manifest moves; only the coordinator can
        # turn it into a real release fingerprint before completion.
        pass
    elif _is_stranded(artifact, manifest):
        # Undelivered and unreachable: name that, rather than reusing the
        # not-yet-delivered messages below.
        errors.append(
            f"{STRANDED_PENDING_HANDOFF_ERROR} "
            f"(target {artifact.get('target_version')}, "
            f"current {manifest.get('kit_version')}; "
            f"{_stranded_disposition(artifact, manifest)}; needs operator attention)"
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
    else:
        resolution = resolve_manifest_membership(artifact, manifest)
        membership_manifest = resolution["manifest"]
        if isinstance(membership_manifest, Mapping):
            unknown = sorted(
                set(changed) - accepted_artifact_paths(membership_manifest)
            )
            if unknown:
                errors.append(
                    "release handoff names unmanaged paths: " + ", ".join(unknown)
                )
        elif (
            resolution["outcome"] == "missing"
            and artifact.get("status") != "completed"
        ):
            # Pending records are present-tense release inputs.  A historical
            # resolution applies only when they explicitly target an older,
            # unretained release; otherwise retain the existing current gate.
            unknown = sorted(set(changed) - accepted_artifact_paths(manifest))
            if unknown:
                errors.append(
                    "release handoff names unmanaged paths: " + ", ".join(unknown)
                )
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
    artifact: Mapping[str, Any],
    *,
    spec_id: str,
    manifest: Mapping[str, Any],
    canonical: Path | None = None,
) -> list[str]:
    """Require coordinator-authored positive delivery proof for a completed handoff.

    ``validate_artifact`` deliberately remains compatible with historical completed
    records whose ``release_report`` is a string token.  Call this stricter validator
    anywhere a positive managed-install delivery must be proven.

    ``canonical``, when supplied, extends the exact-hash check to the
    non-manifest release inputs ``managed_paths()`` accepts (``config.yaml``,
    ``release-manifest.json``) by hashing their actual current bytes under
    ``canonical`` (see ``_manifest_sha256``). Without it, those two paths keep
    their prior behavior of never satisfying the exact-hash check.
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
    expected_hashes = _manifest_sha256(manifest, canonical)
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
    if str(frontmatter.get("status", "")) in TERMINAL_NON_DELIVERING_STATUSES:
        # R2 (SPEC-271): once a spec reaches a terminal non-delivering status
        # (currently just "superseded"), the impact: required declaration it
        # carried while live describes past intent, not a live obligation.
        # This is the default outcome of reaching that status -- no action
        # required, and the declaration itself is never touched here. R4
        # keeps every other status (including "done") on the unchanged gate
        # below.
        return []
    artifact = artifact_path(canonical, str(frontmatter.get("id", "")))
    if not artifact.is_file():
        return ["release-impact spec requires a release handoff artifact"]
    try:
        data = json.loads(artifact.read_text())
    except json.JSONDecodeError:
        return ["release handoff artifact is invalid JSON"]
    errors = validate_artifact(
        data, spec_id=str(frontmatter.get("id", "")), manifest=manifest
    )
    if _has_pending_manifest_placeholder(data):
        errors.append(
            "WARNING: release handoff awaits coordinator re-pin at the next qualifying release"
        )
    return errors


def reclassify_terminal_declaration(
    spec_path: Path,
    *,
    new_impact: str,
    reason: str,
    run_id: str,
    status_store: Any,
    source: str = "release-handoff-reclassification",
) -> dict[str, Any]:
    """Re-classify a ``superseded`` spec's ``release_handoff`` declaration (R3).

    This is the *only* sanctioned way to change a declaration once a spec has
    gone terminal (R2's suppression above is the default, no-action outcome;
    this function is the deliberate, evidenced exception). It:

    - refuses to run on a spec whose status is not a terminal
      non-delivering status (``TERMINAL_NON_DELIVERING_STATUSES``);
    - requires a non-empty ``reason``;
    - records a durable checkpoint via ``status_store`` whose ``status``
      value does not change (unlike a real transition) and whose ``source``
      is distinct from ``status_store.transition_commit_backed``'s default
      ``"coordinator"``, so it is never confused with a status-transition
      commit;
    - is never called from ``transition_commit_backed`` or any other status
      change -- it must be invoked explicitly, by whoever already has
      authority to edit that spec's frontmatter.

    The checkpoint is written before the frontmatter mutation, matching
    ``StatusStore.transition_commit_backed``'s durability ordering: a crash
    between the two leaves a precise, append-only recovery record instead of
    an unrecorded frontmatter change.
    """
    from spec_frontmatter import parse_spec_file, write_spec_frontmatter

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("release_handoff reclassification requires a non-empty reason")
    if new_impact not in {"required", "exempt"}:
        raise ValueError("release_handoff reclassification impact must be required or exempt")

    path = Path(spec_path).resolve()
    parsed = parse_spec_file(path)
    fm = parsed.frontmatter
    status = str(fm.get("status", ""))
    if status not in TERMINAL_NON_DELIVERING_STATUSES:
        raise ValueError(
            "release_handoff reclassification refused: spec status "
            f"{status!r} is not a terminal non-delivering status "
            f"({sorted(TERMINAL_NON_DELIVERING_STATUSES)!r})"
        )
    spec_id = str(fm.get("id", ""))
    if not spec_id:
        raise ValueError(f"spec id missing from {path.name}")

    reason_text = reason.strip()
    old_declaration = fm.get("release_handoff")
    new_declaration: dict[str, Any] = {"impact": new_impact, "reason": reason_text}

    checkpoint = status_store.update_state(
        spec_id,
        status,
        run_id=run_id,
        source=source,
        note=reason_text,
        payload={
            "spec_path": str(path),
            "release_handoff_reclassification": {
                "from": old_declaration,
                "to": new_declaration,
            },
        },
    )

    def _mutate(current: dict[str, Any]) -> dict[str, Any]:
        return {**current, "release_handoff": new_declaration}

    updated = write_spec_frontmatter(path, _mutate)
    return {"checkpoint": checkpoint, "frontmatter": updated.frontmatter}


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
        if data.get("status") != "pending" or not (
            _matches_current_manifest_fingerprint(data, manifest)
        ):
            continue
        if validate_artifact(
            data, spec_id=str(data.get("spec_id", "")), manifest=manifest
        ):
            continue
        candidate = dict(data)
        candidate["status"] = "completed"
        candidate["release_report"] = DELIVERY_RECEIPT_REPORT
        candidate["delivery_receipt"] = build_delivery_receipt(
            candidate, manifest, release_result, canonical=canonical
        )
        if validate_positive_delivery(
            candidate,
            spec_id=str(candidate.get("spec_id", "")),
            manifest=manifest,
            canonical=canonical,
        ):
            continue
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        completed.append(str(candidate["spec_id"]))
    return completed


def repin_pending_handoffs(canonical: Path, manifest: Mapping[str, Any]) -> list[str]:
    """Mechanically seal eligible placeholder records for this coordinator run.

    Callers must invoke this only after a successful full-kit rollout and
    immediately before ``complete_pending_handoffs``.  A raw placeholder stays
    uncompletable through ``complete_pending_handoffs`` itself, preventing any
    non-coordinator path from bypassing real-fingerprint verification.
    """
    repinned: list[str] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return repinned
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if not _has_pending_manifest_placeholder(data):
            continue
        candidate = dict(data)
        candidate["target_version"] = manifest.get("kit_version")
        candidate["manifest_fingerprint"] = fingerprint(manifest)
        if validate_artifact(
            candidate, spec_id=str(candidate.get("spec_id", "")), manifest=manifest
        ):
            continue
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        repinned.append(str(candidate["spec_id"]))
    return repinned
