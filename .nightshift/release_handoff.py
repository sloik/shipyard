"""Versioned release-handoff contracts for canonical Nightshift changes.

The contract intentionally records portable repository-relative evidence only.
It does not discover releases from ignore rules, paths on the current machine, or
private observability data.  ``release_coordinator`` is the sole fulfiller of a
pending handoff after a successful full-kit rollout.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import yaml

import lifecycle

HANDOFF_DIR = "release-handoffs"
DELIVERY_RECEIPT_SCHEMA_VERSION = 1
DELIVERY_RECEIPT_REPORT = "coordinator-positive-delivery-receipt-v1"
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"
SKILL_ASSET_PATHS = frozenset({"Skills/nightshift/prompts/prebuilt.json"})
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
RELEASE_PLAN_REQUIRED_ERROR = "release-impact spec requires a valid release_plan before Ready"
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


def _spec_status(canonical: Path, spec_id: str) -> str | None:
    """Return the frontmatter ``status`` of the spec file declaring ``spec_id``.

    SPEC-334: mirrors the local frontmatter-parsing convention already used by
    ``audit_nfr._parse_frontmatter`` and ``validate_specs._spec_status_by_file``
    rather than importing either module (``validate_specs`` already imports
    this module, so importing it back would be circular; see SPEC-334 R4).
    Returns ``None`` when ``spec_id`` does not resolve to any spec file on
    disk (deleted, renamed, or malformed) -- callers must treat that the same
    as "not done" (SPEC-334 R3), never raise.
    """
    specs_dir = canonical / "specs"
    if not specs_dir.is_dir():
        return None
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        try:
            frontmatter = yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError:
            continue
        if isinstance(frontmatter, Mapping) and str(frontmatter.get("id", "")) == spec_id:
            return str(frontmatter.get("status", ""))
    return None


def _pending_handoff_blocked_by_spec_status(canonical: Path, data: Mapping[str, Any]) -> bool:
    """SPEC-334 R1/R2: True when the source spec is not resolvable to ``status: done``."""
    return _spec_status(canonical, str(data.get("spec_id", ""))) != "done"


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
    suite_receipt = {
        "probe": release_result.get("canonical_suite_probe"),
        "runs": release_result.get("canonical_suite_runs"),
        "result": release_result.get("canonical_suite_result"),
    }
    if suite_receipt["result"] == "reused":
        # SPEC-NS-KIT-126 R3: a reuse names its source record and subset outcome.
        suite_receipt["reused_from"] = release_result.get("canonical_suite_reused_from")
        suite_receipt["subset_result"] = release_result.get("canonical_suite_subset_result")
    if suite_receipt["result"] == "repair-composed":
        suite_receipt["composition"] = release_result.get("canonical_suite_composition")
    receipt = {
        "schema_version": DELIVERY_RECEIPT_SCHEMA_VERSION,
        "producer": "release_coordinator",
        "kit_version": manifest.get("kit_version"),
        "manifest_fingerprint": fingerprint(manifest),
        "canonical_suite": suite_receipt,
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
    provenance = artifact.get('range_provenance')
    if provenance is not None:
        if not isinstance(provenance, Mapping) or provenance.get('status') not in {'bound', 'unresolved'}:
            errors.append('release handoff range provenance is invalid')
        elif provenance['status'] == 'bound':
            if (not all(isinstance(provenance.get(k), str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', provenance[k]) for k in ('base', 'end'))
                    or artifact.get('canonical_commit_range') != provenance.get('base', '') + '..' + provenance.get('end', '')
                    or not re.fullmatch(r'[0-9a-f]{64}', str(provenance.get('repository_identity', '')))
                    or not isinstance(provenance.get('changed_paths'), list)
                    or not provenance.get('original_range')):
                errors.append('release handoff bound range identity is invalid')
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


REPAIR_READER = "tests/test_spec_229_006_live_e2e.py"
REPAIR_RECORD = "tests/fixtures/spec-229-006/le2-installed-allow.json"
REPAIR_FAILED_TEST = REPAIR_READER + "::test_ac1_le2_real_install_reaches_allow_in_installed_profile"


def _repair_ref(canonical: Path, reference: Mapping) -> tuple[Path, bytes]:
    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
        raise ValueError("repair reference schema")
    relative = reference["path"]
    if not isinstance(relative, str) or not relative.startswith("reports/_wip/"):
        raise ValueError("repair evidence must remain in private reports")
    path = canonical / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or any(parent.is_symlink() for parent in (path, *path.parents))
            or not path.resolve().is_relative_to(canonical.resolve())):
        raise ValueError("repair reference escapes canonical")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != reference["sha256"]:
        raise ValueError("repair reference changed")
    return path, body


def _repair_native_inventory(record: Mapping, record_path: Path) -> dict[str, str]:
    """Reconcile complete native collection/events with every JUnit case."""
    import xml.etree.ElementTree as ET
    proof = record["native_proof"]
    obs = proof["observation"]
    if (proof.get("schema_version") != 1 or proof.get("record_mode") is not False
            or proof.get("complete_selection") is not True
            or obs.get("schema_version") != "1.0.0" or obs.get("completed") is not True
            or obs.get("errors") != [] or type(proof.get("native_exit_code")) is not int
            or obs.get("session_exitstatus") != proof["native_exit_code"]):
        raise ValueError("incomplete native repair proof")
    groups, workers = obs["collections"], obs["workers"]
    if not isinstance(groups, dict) or not groups or not isinstance(workers, list):
        raise ValueError("missing complete collection")
    if set(groups) != (set(workers) if workers else {"serial"}) or len(set(workers)) != len(workers):
        raise ValueError("incomplete worker collection")
    catalog = next(iter(groups.values()))
    if (not isinstance(catalog, list) or not catalog or len(set(catalog)) != len(catalog)
            or any(not isinstance(node, str) or "::" not in node for node in catalog)
            or any(not isinstance(ids, list) or len(ids) != len(catalog) or set(ids) != set(catalog)
                   for ids in groups.values())):
        raise ValueError("inconsistent complete collection")
    phases = {node: {} for node in catalog}
    for event in obs["reports"]:
        if (not isinstance(event, dict) or set(event) != {"nodeid", "when", "outcome", "wasxfail", "rerun"}
                or event["nodeid"] not in phases or event["when"] not in {"setup", "call", "teardown"}
                or event["outcome"] not in {"passed", "failed", "skipped"}
                or type(event["wasxfail"]) is not bool or event["rerun"] is not False):
            raise ValueError("unattributed or unsupported native event")
        bucket = phases[event["nodeid"]]
        if event["when"] in bucket:
            raise ValueError("duplicate native phase")
        bucket[event["when"]] = event
    outcomes = {}
    for node, events in phases.items():
        if ("setup" not in events or "teardown" not in events
                or events["teardown"]["outcome"] != "passed"):
            raise ValueError("incomplete terminal native phases")
        setup = events["setup"]["outcome"]
        if setup == "passed":
            if set(events) != {"setup", "call", "teardown"}:
                raise ValueError("missing call outcome")
            call = events["call"]
            outcomes[node] = ("XFAIL" if call["wasxfail"] and call["outcome"] == "skipped"
                              else "XPASS" if call["wasxfail"] else
                              {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[call["outcome"]])
        elif setup == "skipped" and set(events) == {"setup", "teardown"}:
            outcomes[node] = "XFAIL" if events["setup"]["wasxfail"] else "SKIP"
        else:
            raise ValueError("unsupported setup failure")
    name = record["test_durations_artifact"]
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("unsafe native JUnit reference")
    junit = record_path.parent / name
    if junit.is_symlink() or hashlib.sha256(junit.read_bytes()).hexdigest() != proof["junit_sha256"]:
        raise ValueError("native JUnit changed")
    cases = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        key = (case.get("classname"), case.get("name"))
        if key in cases:
            raise ValueError("duplicate native JUnit case")
        cases[key] = ("ERROR" if case.find("error") is not None else "FAIL" if case.find("failure") is not None
                      else "SKIP" if case.find("skipped") is not None else "PASS")
    expected = {}
    for node, outcome in outcomes.items():
        parts = node.split("::")
        key = (parts[0][:-3].replace("/", ".") + ("." + ".".join(parts[1:-1]) if len(parts) > 2 else ""), parts[-1])
        expected[key] = "SKIP" if outcome in {"SKIP", "XFAIL"} else outcome
    if len(expected) != len(outcomes) or cases != expected:
        raise ValueError("native JUnit/catalog mismatch")
    failures = any(value in {"FAIL", "ERROR", "XPASS"} for value in outcomes.values())
    if proof["native_exit_code"] != (1 if failures else 0):
        raise ValueError("native exit/catalog mismatch")
    return outcomes


def record_repair_coverage(canonical: Path, receipt: Mapping) -> dict[str, int]:
    """The one closed composition contract used by release and handoff consumers.

    Evidence is owner retained and hash addressed. Legacy aggregate measurements
    lack this proof and cannot be upgraded into it retrospectively.
    """
    import subprocess
    from datetime import datetime, timezone
    from release_coordinator import _repair_environment_digest
    canonical = canonical.resolve()
    if (not isinstance(receipt, Mapping) or receipt.get("schema_version") != 1
            or receipt.get("outcome") != "repair-composed"
            or set(receipt) - {"schema_version", "outcome", "manifest_fingerprint", "original_record", "closure_record", "review", "approval", "coverage"}):
        raise ValueError("repair composition schema")
    def load(key):
        path, body = _repair_ref(canonical, receipt[key])
        return path, json.loads(body)
    full_path, full = load("original_record")
    closure_path, closure = load("closure_record")
    review_path, review = load("review")
    _, approval = load("approval")
    if (not str(approval.get("approved_by", "")).startswith("human:")
            or approval.get("compose") is not True or approval.get("reader_paths") != [REPAIR_READER]
            or approval.get("original_record_sha256") != receipt["original_record"]["sha256"]
            or approval.get("closure_record_sha256") != receipt["closure_record"]["sha256"]
            or approval.get("review_sha256") != receipt["review"]["sha256"]):
        raise ValueError("missing exact composition authority/reader closure")
    if full.get("suite_passed") is not False or closure.get("suite_passed") is not True:
        raise ValueError("failed-full and passing normal closure required")
    for record in (full, closure):
        if record.get("tree_clean_start") is not True or record.get("tree_clean_end") is not True:
            raise ValueError("unclean repair run")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(record["recorded_at"])).total_seconds()
        if not 0 <= age <= 86400:
            raise ValueError("stale repair evidence")
    def git(*args):
        result = subprocess.run(["git", "-C", str(canonical), *args], capture_output=True, check=True)
        return result.stdout
    base, head = full["canonical_commit"], closure["canonical_commit"]
    if (not re.fullmatch(r"[0-9a-f]{40}", base) or not re.fullmatch(r"[0-9a-f]{40}", head)
            or git("rev-parse", "HEAD").decode().strip() != head
            or git("status", "--porcelain", "--", ".").strip()):
        raise ValueError("current source identity/cleanliness drift")
    git("merge-base", "--is-ancestor", base, head)
    prefix = git("rev-parse", "--show-prefix").decode().strip()
    changed = git("diff", "--name-only", "--no-renames", "--relative", "-z", base, head, "--", ".")
    if changed.split(b"\0") != [REPAIR_RECORD.encode(), b""]:
        raise ValueError("repair changed source/assertions or unrelated data")
    old_bytes = git("show", f"{base}:{prefix}{REPAIR_RECORD}")
    old, new = json.loads(old_bytes), json.loads(git("show", f"{head}:{prefix}{REPAIR_RECORD}"))
    manifest = json.loads((canonical / "release-manifest.json").read_text())
    if receipt.get("manifest_fingerprint") != manifest["fingerprint"]:
        raise ValueError("repair manifest drift")
    from release import release_entries
    a, b = old["stable"], new["stable"]
    changed_keys = {key for key in a.keys() | b.keys() if a.get(key) != b.get(key)}
    if (old.get("scenario") != "LE2" or new.get("scenario") != "LE2"
            or changed_keys != {"manifest_files_checked"} or type(b["manifest_files_checked"]) is not int
            or b["manifest_files_checked"] != len(release_entries(manifest))
            or b.get("admission") != "allow" or b.get("exit_code") != 0 or b.get("returncode") != 0):
        raise ValueError("not an installed-allow inventory-only stable repair")
    retained = review_path.parent / "retained-original-le2.json"
    proposal = review_path.parent / "proposed-le2.json"
    diff = review_path.parent / "approved-stable-diff.json"
    if any(path.is_symlink() for path in (retained, proposal, diff)):
        raise ValueError("symlinked reviewed evidence")
    if (retained.read_bytes() != old_bytes or json.loads(proposal.read_bytes()) != new
            or json.loads(diff.read_bytes()) != {"stable.manifest_files_checked": {"before": a["manifest_files_checked"], "after": b["manifest_files_checked"]}}
            or not str(review.get("approved_by", "")).startswith("human:")
            or review.get("allowed_fields") != ["stable.manifest_files_checked"]
            or review.get("old_record_sha256") != hashlib.sha256(old_bytes).hexdigest()
            or review.get("manifest_fingerprint") != manifest["fingerprint"]
            or review.get("source_sha256") != hashlib.sha256((canonical / REPAIR_READER).read_bytes()).hexdigest()):
        raise ValueError("SPEC191 reviewed repair identity changed")
    fp, cp = full["native_proof"], closure["native_proof"]
    command = manifest["canonical_suite"]["command"]
    if (not command or command[-1] != "tests" or fp["command"] != command or fp["base_command"] != command
            or cp["base_command"] != command or cp["command"] != command[:-1] + [REPAIR_READER]
            or fp["environment_sha256"] != cp["environment_sha256"]
            or cp["environment_sha256"] != _repair_environment_digest()
            or not fp.get("runtime") or fp["runtime"] != cp["runtime"]):
        raise ValueError("repair command/runtime/dependency environment drift")
    for row in cp["runtime"]:
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("repair runtime/dependency identity changed")
    original = _repair_native_inventory(full, full_path)
    repaired = _repair_native_inventory(closure, closure_path)
    affected = {node for node in original if node.split("::", 1)[0] == REPAIR_READER}
    failures = {node for node, status in original.items() if status in {"FAIL", "ERROR", "XPASS"}}
    if failures != {REPAIR_FAILED_TEST} or set(repaired) != affected:
        raise ValueError("unrelated failure or incomplete affected-reader closure")
    if any(status != "PASS" and status != original[node] for node, status in repaired.items()) or repaired[REPAIR_FAILED_TEST] != "PASS":
        raise ValueError("new skip/xfail/failure or unresolved repaired failure")
    covered = {node for node, status in original.items() if status in {"PASS", "SKIP", "XFAIL"}} | set(repaired)
    coverage = {"collected": len(original), "original_passed": sum(v == "PASS" for v in original.values()),
                "original_failed": len(failures), "repaired_failed": len(failures & set(repaired)),
                "covered_union": len(covered), "retained_skipped": sum(v in {"SKIP", "XFAIL"} for v in original.values())}
    if covered != set(original) or receipt.get("coverage", coverage) != coverage:
        raise ValueError("repair coverage union mismatch")
    return coverage


def validate_record_repair_composition(canonical: Path | None, receipt: Mapping) -> list[str]:
    if canonical is None:
        return ["repair composition requires retained canonical proof"]
    try:
        if not isinstance(receipt, Mapping) or not isinstance(receipt.get("coverage"), Mapping):
            raise ValueError("repair receipt lacks explicit coverage accounting")
        record_repair_coverage(canonical, receipt)
    except Exception as exc:  # all missing/malformed/stale native proof fails closed
        return ["repair composition refused: " + type(exc).__name__]
    return []


def _suite_receipt_accepted(suite: Mapping, *, canonical: Path | None = None) -> bool:
    """One passing run, or a reuse (SPEC-NS-KIT-126) naming its record and commit
    whose release-mechanical test subset passed."""
    suite = dict(suite)
    if suite.get("result") == "repair-composed":
        return (set(suite) == {"probe", "runs", "result", "composition"}
                and suite.get("probe") == "passed" and suite.get("runs") == 0
                and not validate_record_repair_composition(canonical, suite.get("composition")))
    if suite == {"probe": "passed", "runs": 1, "result": "passed"}:
        return True
    source = suite.get("reused_from")
    return (
        suite.get("probe") == "passed"
        and suite.get("runs") == 0
        and suite.get("result") == "reused"
        and suite.get("subset_result") == "passed"
        and isinstance(source, Mapping)
        and bool(source.get("record"))
        and bool(source.get("commit"))
        and set(suite) == {"probe", "runs", "result", "reused_from", "subset_result"}
    )


def _skill_allowlist(manifest: Mapping[str, Any]) -> set[str]:
    """Skill surfaces the release delivers, derived from the judged manifest."""
    allowed = {SKILL_MANAGED_PATH}
    for entry in manifest.get("files", []):
        path = str(entry.get("path", "")) if isinstance(entry, Mapping) else ""
        if path in SKILL_ASSET_PATHS:
            allowed.add(path)
        if path.startswith("guides/"):
            allowed.add(f"Skills/nightshift/{path}")
    return allowed


def _skill_commit_paths_accepted(paths: Any, manifest: Mapping[str, Any]) -> bool:
    """BUG-NS-KIT-132 R1: SKILL.md plus only manifest-derived skill/guide paths."""
    if not isinstance(paths, list) or not paths:
        return False
    if not all(isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
        return False
    return SKILL_MANAGED_PATH in paths and set(paths) <= _skill_allowlist(manifest)


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
    if not isinstance(suite, Mapping) or not _suite_receipt_accepted(suite, canonical=canonical):
        errors.append(
            "delivery receipt requires exactly one passing canonical suite run "
            "or a verified reuse of a recorded green run or approved record-repair composition"
        )

    if (isinstance(suite, Mapping) and suite.get("result") == "repair-composed"
            and (suite.get("composition") or {}).get("manifest_fingerprint") != fingerprint(manifest)):
        errors.append("repair composition fingerprint does not match judged manifest")

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
                or not _skill_commit_paths_accepted(commit.get("paths"), manifest)
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
    plan_errors = validate_release_plan(frontmatter, manifest)
    artifact = artifact_path(canonical, str(frontmatter.get("id", "")))
    if not artifact.is_file():
        if str(frontmatter.get("status", "")) not in {"draft", "planned", "ready", "in_progress", "blocked"}:
            return plan_errors + ["release-impact spec requires a release handoff artifact"]
        return plan_errors
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
    return plan_errors + errors


def validate_release_plan(frontmatter: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[str]:
    """Validate the reviewed pre-implementation plan needed at Ready and later."""
    declaration = frontmatter.get("release_handoff")
    if (not isinstance(declaration, Mapping) or declaration.get("impact") != "required"
            or str(frontmatter.get("status", "")) not in {"ready", "in_progress", "done"}):
        return []
    plan = frontmatter.get("release_plan")
    if not isinstance(plan, Mapping):
        return [RELEASE_PLAN_REQUIRED_ERROR]
    errors = []
    paths = plan.get("expected_managed_paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(item, str) and item for item in paths):
        errors.append("release_plan expected_managed_paths must be a non-empty list of paths")
    else:
        unknown = sorted(set(paths) - managed_paths(manifest))
        if unknown:
            errors.append("release_plan names unmanaged paths: " + ", ".join(unknown))
    if not isinstance(plan.get("required_migrations"), list) or not all(isinstance(item, str) for item in plan["required_migrations"]):
        errors.append("release_plan required_migrations must be a list of strings")
    if plan.get("fleet_sync_scope") not in {"all-managed-installs", "eligible-managed-installs"}:
        errors.append("release_plan fleet_sync_scope is invalid")
    if not isinstance(plan.get("summary"), str) or not plan["summary"].strip():
        errors.append("release_plan summary requires non-empty text")
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
    """Complete matching records only with coordinator-owned positive delivery.

    SPEC-334 R2: a record is never completed unless its ``spec_id`` resolves
    to a spec file whose own ``status`` is ``done`` -- otherwise the record
    proves delivery of code the source spec never actually shipped. A record
    skipped for this reason is also reported by
    ``pending_handoffs_blocked_by_spec_status`` (R5).
    """
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
        if _pending_handoff_blocked_by_spec_status(canonical, data):
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


def _range_git(canonical: Path, *args: str) -> str:
    import subprocess
    try:
        result = subprocess.run(['git', *args], cwd=canonical, capture_output=True, text=True,
                                env={**os.environ, 'LC_ALL': 'C'}, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('commit_range_source_unavailable') from exc
    if result.returncode or 'ambiguous' in result.stderr.lower():
        raise ValueError('commit_range_unresolved_or_ambiguous')
    return result.stdout


def _range_binding(canonical: Path, artifact: Mapping[str, Any]) -> dict:
    root = Path(_range_git(canonical, 'rev-parse', '--show-toplevel').strip()).resolve()
    common = _range_git(canonical, 'rev-parse', '--path-format=absolute', '--git-common-dir').strip()
    identity = hashlib.sha256(str(Path(common).resolve()).encode()).hexdigest()
    prefix = canonical.resolve().relative_to(root).as_posix()
    value = artifact.get('canonical_commit_range', '')
    if not isinstance(value, str) or value.count('..') != 1 or '...' in value:
        raise ValueError('commit_range_requires_two_actual_endpoints')
    names = value.split('..')
    if any(not part or part.startswith('-') for part in names):
        raise ValueError('commit_range_invalid_endpoint')
    endpoints = [_range_git(canonical, 'rev-parse', '--verify', '--end-of-options', part + '^{commit}').strip() for part in names]
    if any(not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value) for value in endpoints):
        raise ValueError('commit_range_invalid_object')
    base, end = endpoints
    _range_git(canonical, 'merge-base', '--is-ancestor', base, end)
    raw = _range_git(root, '--literal-pathspecs', 'diff', '--name-only', '-z', '--no-renames', base, end, '--', prefix)
    paths = sorted(Path(name).relative_to(prefix).as_posix() if prefix != '.' else name
                   for name in raw.split('\0') if name)
    result = {'status': 'bound', 'repository_identity': identity, 'canonical_prefix': prefix,
              'base': base, 'end': end, 'changed_paths': paths}
    prior = artifact.get('range_provenance')
    if isinstance(prior, Mapping) and prior.get('status') == 'bound':
        if any(prior.get(key) != value for key, value in result.items()):
            raise ValueError('commit_range_source_identity_or_diff_drift')
        if artifact['canonical_commit_range'] != base + '..' + end:
            raise ValueError('bound_commit_range_must_be_immutable')
        if not isinstance(prior.get('original_range'), str) or not prior['original_range']:
            raise ValueError('commit_range_original_spelling_missing')
        result['original_range'] = prior['original_range']
    else:
        result['original_range'] = value
    return result


def pin_commit_range(canonical: Path, artifact: Mapping[str, Any], manifest: Mapping[str, Any],
                     *, expected_binding: Mapping[str, Any] | None = None) -> dict:
    """Pure authoring helper: resolve real endpoints, check/recheck source and preserve history."""
    if artifact.get('status') == 'completed':
        raise ValueError('completed_handoff_is_immutable')
    binding = _range_binding(canonical, artifact)
    if expected_binding is not None and dict(expected_binding) != binding:
        raise ValueError('commit_range_ref_drift_before_authoring')
    declared = artifact.get('changed_managed_paths')
    actual = set(release_impact(binding['changed_paths'], manifest))
    if not isinstance(declared, list) or not declared or not set(declared) <= actual:
        raise ValueError('commit_range_declared_managed_paths_not_in_actual_diff')
    if _range_binding(canonical, artifact) != binding:
        raise ValueError('commit_range_ref_drift_before_authoring')
    result = dict(artifact)
    result['canonical_commit_range'] = binding['base'] + '..' + binding['end']
    result['range_provenance'] = binding
    history = result.get('range_history', [])
    if not isinstance(history, list) or not all(isinstance(item, str) for item in history):
        raise ValueError('commit_range_history_invalid')
    history = list(history)
    if binding['original_range'] not in history:
        history.append(binding['original_range'])
    result['range_history'] = history
    return result


def check_range_retention(canonical: Path, artifact: Mapping[str, Any], *, spec_id: str,
                          run_id: str, main_branch: str = 'main', candidate_revision: str | None = None) -> dict:
    """Require existing main ancestry or the exact checked-cleanup owned recovery root."""
    if (not isinstance(artifact.get('range_provenance'), Mapping)
            or artifact['range_provenance'].get('status') != 'bound'):
        raise ValueError('commit_range_unbound_retention_unproven')
    binding = _range_binding(canonical, artifact)
    for ref in (f'refs/heads/{main_branch}', f'refs/nightshift/recovery/{spec_id}/{run_id}'):
        try:
            revision = _range_git(canonical, 'show-ref', '--verify', '--hash', ref).strip()
            if ref.startswith('refs/nightshift/recovery/') and revision != (candidate_revision or binding['end']):
                continue
            for endpoint in (binding['base'], binding['end']):
                _range_git(canonical, 'merge-base', '--is-ancestor', endpoint, revision)
            return {'ref': ref, 'revision': revision, 'base': binding['base'], 'end': binding['end'],
                    'repository_identity': binding['repository_identity']}
        except ValueError:
            continue
    raise ValueError('commit_range_retention_missing_for_both_endpoints')


def _pin_range_for_repin(canonical: Path, artifact: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict:
    try:
        return pin_commit_range(canonical, artifact, manifest)
    except ValueError:
        if isinstance(artifact.get('range_provenance'), Mapping) and artifact['range_provenance'].get('status') == 'bound':
            raise  # A known binding can never silently degrade into legacy evidence.
        result = dict(artifact)
        result['range_provenance'] = {'status': 'unresolved', 'original_range': artifact.get('canonical_commit_range'),
                                      'reason_code': 'legacy_source_objects_or_diff_unresolved'}
        return result


def repin_pending_handoffs(canonical: Path, manifest: Mapping[str, Any]) -> list[str]:
    """Mechanically seal eligible placeholder records for this coordinator run.

    Callers must invoke this only after a successful full-kit rollout and
    immediately before ``complete_pending_handoffs``.  A raw placeholder stays
    uncompletable through ``complete_pending_handoffs`` itself, preventing any
    non-coordinator path from bypassing real-fingerprint verification.

    SPEC-334 R1: a placeholder is never re-pinned unless its ``spec_id``
    resolves to a spec file whose own ``status`` is ``done`` -- otherwise a
    draft/in-progress spec's authoring placeholder gets stamped with a real
    fingerprint for code that was never actually shipped. A record skipped
    for this reason is also reported by
    ``pending_handoffs_blocked_by_spec_status`` (R5).
    """
    repinned: list[str] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return repinned
    for path in sorted(directory.glob("*.json")):
        original = path.read_bytes()
        data = json.loads(original)
        if not _has_pending_manifest_placeholder(data):
            continue
        if _pending_handoff_blocked_by_spec_status(canonical, data):
            continue
        try:
            candidate = _pin_range_for_repin(canonical, data, manifest)
        except ValueError:
            continue
        candidate["target_version"] = manifest.get("kit_version")
        candidate["manifest_fingerprint"] = fingerprint(manifest)
        if validate_artifact(
            candidate, spec_id=str(candidate.get("spec_id", "")), manifest=manifest
        ):
            continue
        if path.read_bytes() != original:
            continue
        if candidate.get('range_provenance', {}).get('status') == 'bound':
            try:
                pin_commit_range(canonical, data, manifest, expected_binding=candidate['range_provenance'])
            except ValueError:
                continue
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        repinned.append(str(candidate["spec_id"]))
    return repinned


def _preceding_release_version(manifest: Mapping[str, Any]) -> tuple[int, int, int] | None:
    current = _semver(manifest.get("kit_version"))
    if current is None:
        return None
    lower = [
        v
        for r in manifest.get("retained_manifests", [])
        if isinstance(r, Mapping)
        and (v := _semver(r.get("kit_version"))) is not None
        and v < current
    ]
    return max(lower) if lower else None


def _folded_repin_candidate(
    canonical: Path, data: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, Any] | None:
    """BUG-NS-KIT-132 R3 a-f: the re-pinned candidate, or None when refused."""
    if not _is_stranded(data, manifest):
        return None
    disposition = data.get("disposition")
    if disposition_errors(disposition) or disposition.get("decision") != "fold":
        return None
    if _pending_handoff_blocked_by_spec_status(canonical, data):
        return None
    target = _semver(data.get("target_version"))
    current = _semver(manifest.get("kit_version"))
    if (
        target is None
        or current is None
        or target >= current
        or target != _preceding_release_version(manifest)
    ):
        return None
    changed = data.get("changed_managed_paths")
    if not isinstance(changed, list) or not set(changed) <= managed_paths(manifest):
        return None
    try:
        candidate = _pin_range_for_repin(canonical, data, manifest)
    except ValueError:
        return None
    candidate["repinned_from"] = {
        "target_version": data.get("target_version"),
        "manifest_fingerprint": data.get("manifest_fingerprint"),
    }
    candidate["target_version"] = manifest.get("kit_version")
    candidate["manifest_fingerprint"] = fingerprint(manifest)
    if validate_artifact(
        candidate, spec_id=str(candidate.get("spec_id", "")), manifest=manifest
    ):
        return None
    return candidate


def pending_handoff_reachability(canonical: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Classify pending handoffs without re-pinning, completing, or writing bytes."""
    results = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return results
    current = manifest.get("kit_version")
    for path in sorted(directory.glob("*.json")):
        raw = path.read_bytes()
        try:
            data = json.loads(raw)
        except ValueError:
            results.append({"path": path.name, "classification": "unresolved", "reason": "invalid JSON",
                            "sha256": hashlib.sha256(raw).hexdigest()})
            continue
        entry = {"path": path.name, "spec_id": data.get("spec_id"),
                 "sha256": hashlib.sha256(raw).hexdigest(), "target_version": data.get("target_version")}
        if data.get("status") != "pending":
            results.append({**entry, "classification": "non_applicable", "reason": "not pending"})
        elif _has_pending_manifest_placeholder(data):
            results.append({**entry, "classification": "non_applicable", "reason": "awaits a future coordinator release"})
        elif _matches_current_manifest_fingerprint(data, manifest):
            results.append({**entry, "classification": "exact_target", "reason": "candidate fingerprint matches"})
        elif _folded_repin_candidate(canonical, data, manifest) is not None:
            results.append({**entry, "classification": "eligible_future_repin", "reason": "existing folded-repin predicate accepts"})
        elif data.get("disposition", {}).get("decision") == "fold" and data.get("target_version") == current:
            results.append({**entry, "classification": "stranded", "reason": "same version has a different fingerprint"})
        elif data.get("target_version") != current:
            results.append({**entry, "classification": "non_applicable", "reason": "targets another release version"})
        else:
            results.append({**entry, "classification": "unresolved", "reason": "pending handoff is not reachable by existing predicates"})
    return results


def repin_folded_handoffs(canonical: Path, manifest: Mapping[str, Any]) -> list[str]:
    """BUG-NS-KIT-132 R3: re-pin the preceding release's ``fold`` records.

    Same call contract as ``repin_pending_handoffs``. It never completes
    anything; ``complete_pending_handoffs`` still gates on positive delivery.
    """
    repinned: list[str] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return repinned
    for path in sorted(directory.glob("*.json")):
        original = path.read_bytes()
        data = json.loads(original)
        candidate = _folded_repin_candidate(canonical, data, manifest)
        if candidate is None:
            continue
        if path.read_bytes() != original:
            continue
        if candidate.get('range_provenance', {}).get('status') == 'bound':
            try:
                pin_commit_range(canonical, data, manifest, expected_binding=candidate['range_provenance'])
            except ValueError:
                continue
        path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        repinned.append(str(candidate["spec_id"]))
    return repinned


def pending_handoffs_not_completed(
    canonical: Path, manifest: Mapping[str, Any], release_result: Mapping[str, Any]
) -> list[dict[str, str]]:
    """BUG-NS-KIT-132 R2: completable-looking pending records refused, with error."""
    refused: list[dict[str, str]] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return refused
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("status") != "pending" or not (
            _matches_current_manifest_fingerprint(data, manifest)
        ):
            continue
        if _pending_handoff_blocked_by_spec_status(canonical, data):
            continue
        spec_id = str(data.get("spec_id", ""))
        errors = validate_artifact(data, spec_id=spec_id, manifest=manifest)
        if not errors:
            candidate = dict(data)
            candidate["status"] = "completed"
            candidate["release_report"] = DELIVERY_RECEIPT_REPORT
            candidate["delivery_receipt"] = build_delivery_receipt(
                candidate, manifest, release_result, canonical=canonical
            )
            errors = validate_positive_delivery(
                candidate, spec_id=spec_id, manifest=manifest, canonical=canonical
            )
        if errors:
            refused.append({"spec_id": spec_id, "error": errors[0]})
    return refused


def pending_handoffs_blocked_by_spec_status(
    canonical: Path, manifest: Mapping[str, Any]
) -> list[str]:
    """SPEC-334 R5: spec IDs of records ``repin``/``complete`` skipped this run.

    Reports every record that would otherwise be eligible for
    ``repin_pending_handoffs`` (a raw placeholder) or ``complete_pending_handoffs``
    (a fingerprint-matching pending record) but whose source spec does not
    resolve to ``status: done``. This is the caller-observable signal R5
    requires without changing either function's existing return-value
    contract: ``release_coordinator`` records it alongside
    ``release_handoffs_repinned``/``release_handoffs_completed`` in its result
    dict, which is what ``write_metrics`` serializes.
    """
    blocked: list[str] = []
    directory = canonical / HANDOFF_DIR
    if not directory.is_dir():
        return blocked
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        eligible = _has_pending_manifest_placeholder(data) or (
            data.get("status") == "pending"
            and _matches_current_manifest_fingerprint(data, manifest)
        )
        if not eligible:
            continue
        if _pending_handoff_blocked_by_spec_status(canonical, data):
            blocked.append(str(data.get("spec_id", "")))
    return blocked
