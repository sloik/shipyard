#!/usr/bin/env python3
"""SPEC-052: Verification report artifact helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - deployed install may be incomplete
    from preflight import KitRootError, load_commands, resolve_kit_root
except Exception:  # pragma: no cover - deployed install may be incomplete
    KitRootError = None  # type: ignore[assignment,misc]
    load_commands = None  # type: ignore[assignment]
    resolve_kit_root = None  # type: ignore[assignment]

SEVERITIES = {"CRITICAL", "WARNING", "SUGGESTION"}
DIMENSIONS = {"completeness", "correctness", "coherence"}
FINAL_ASSESSMENTS = {"pass", "pass_with_warnings", "fail"}

# This is the only generated artifact that an independent verifier may ignore
# when asserting its read-only Git footprint.  Keep the policy exact: a broad
# ``graphify-out/`` exclusion would hide verifier writes to other artifacts.
VERIFIER_FOOTPRINT_EXCLUSIONS = frozenset({"graphify-out/graph.html"})
VERIFIER_REPORT_ROOTS = ("reports/", ".nightshift/reports/", "canonical/reports/")
# Metrics artifacts are never withheld wholesale (unlike reports): an unrelated
# spec's metrics file is ordinary tracked content and must stay reachable (R2).
# Only the subset identified as belonging to the spec under verification is
# withheld, through the same same-spec identity rule already used for reports.
VERIFIER_METRICS_ROOTS = ("metrics/", ".nightshift/metrics/", "canonical/metrics/")
VERIFIER_VERDICT_REQUIRED_KEYS = frozenset({
    "spec_id", "branch", "baseline_commit", "head_commit", "verdict",
    "acs", "suites", "git_footprint", "contamination",
})
VERIFIER_IDENTITY_SCHEMA_VERSION = "1.0.0"
CONTAINMENT_EVIDENCE_SCHEMA_VERSION = "1.2.0"
SPEC_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
GIT_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40,64}")
CANDIDATE_REVISION_DOMAIN = b"nightshift.verifier.candidate-revision.v1\0"
CONTAINMENT_BINDING_DOMAIN = b"nightshift.verifier.containment-binding.v1\0"
IMPLEMENTATION_HEAD_DOMAIN = b"nightshift.verifier.implementation-head.v1\0"


class VerifierSurfacePreparationError(RuntimeError):
    """Controlled pre-dispatch failure; the harness must launch no verifier."""


@dataclass(frozen=True)
class PreparedVerifierDispatch:
    """Validated private preparation state for one harness dispatch.

    ``evidence`` remains parent-owned.  Only :meth:`public_plan` may cross the
    harness boundary, which deliberately omits the source repository, report
    paths, and parent-owned evidence path.
    """

    repository: Path
    evidence_path: Path
    evidence: dict[str, Any]
    evidence_sha256: str
    suite_commands: tuple[str, ...]
    spec_id: str
    run_id: str

    def public_plan(self) -> dict[str, Any]:
        commits = self.evidence["surface_commits"]
        return {
            "schema_version": "2.0.0",
            "identity_schema_version": VERIFIER_IDENTITY_SCHEMA_VERSION,
            "spec_id": self.spec_id,
            "run_id": self.run_id,
            "surface_kind": "standalone-sanitized-git",
            "repository": str(self.repository),
            "baseline_ref": "verifier-baseline",
            "head_ref": "verifier-head",
            "baseline_commit": commits["baseline"],
            "head_commit": commits["head"],
            "implementation_head_digest": self.evidence["implementation_head_digest"],
            "brief_kind": "normal" if self.suite_commands else "no-test-suite",
            "suite_commands": list(self.suite_commands),
            "containment_evidence_sha256": self.evidence_sha256,
        }


def _domain_digest(domain: bytes, *parts: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    for index, part in enumerate(parts):
        if index:
            digest.update(b"\0")
        digest.update(part)
    return digest.hexdigest()


def candidate_revision_digest(candidate_revision: str) -> str:
    """Return the protocol digest for one parent-private exact Git revision."""
    if not isinstance(candidate_revision, str) or not GIT_OBJECT_ID_RE.fullmatch(
        candidate_revision
    ):
        raise ValueError("candidate revision must be a lowercase Git object ID")
    return _domain_digest(CANDIDATE_REVISION_DOMAIN, candidate_revision.encode("ascii"))


def containment_prebinding_projection(
    evidence: dict[str, Any], *, spec_id: str, run_id: str,
    candidate_digest: str,
) -> dict[str, Any]:
    """Build the closed canonical projection used before final evidence hashing."""
    if not isinstance(spec_id, str) or not spec_id or not isinstance(run_id, str) or not run_id:
        raise ValueError("spec and run identity are required")
    if not SHA256_HEX_RE.fullmatch(candidate_digest):
        raise ValueError("candidate revision digest must be lowercase SHA-256")
    excluded = evidence.get("excluded_paths")
    probes = evidence.get("report_reachability")
    if not isinstance(excluded, dict) or not isinstance(probes, list):
        raise ValueError("containment evidence is incomplete")
    excluded_set = sorted({
        path
        for values in excluded.values()
        if isinstance(values, list)
        for path in values
        if isinstance(path, str)
    })
    normalized_probes = sorted(
        (
            {"ref": item.get("ref"), "path": item.get("path"),
             "unreachable": item.get("unreachable")}
            for item in probes if isinstance(item, dict)
        ),
        key=lambda item: (str(item["ref"]), str(item["path"])),
    )
    projection = {
        "identity_schema_version": VERIFIER_IDENTITY_SCHEMA_VERSION,
        "spec_id": spec_id,
        "run_id": run_id,
        "candidate_revision_digest": candidate_digest,
        "synthetic_head_tree": evidence.get("head_tree"),
        "excluded_paths": excluded_set,
        "report_reachability": normalized_probes,
        "shared_object_database": evidence.get("shared_object_database"),
    }
    if not isinstance(projection["synthetic_head_tree"], str):
        raise ValueError("synthetic head tree is missing")
    if projection["shared_object_database"] is not False:
        raise ValueError("verifier surface shares an object database")
    return projection


def derive_verifier_identity(
    evidence: dict[str, Any], *, spec_id: str, run_id: str,
    candidate_revision: str,
) -> dict[str, str]:
    """Derive the three ordered digests for the split identity contract."""
    candidate_digest = candidate_revision_digest(candidate_revision)
    projection = containment_prebinding_projection(
        evidence, spec_id=spec_id, run_id=run_id,
        candidate_digest=candidate_digest,
    )
    canonical_projection = json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    binding_digest = _domain_digest(CONTAINMENT_BINDING_DOMAIN, canonical_projection)
    implementation_digest = _domain_digest(
        IMPLEMENTATION_HEAD_DOMAIN,
        candidate_digest.encode("ascii"),
        binding_digest.encode("ascii"),
    )
    return {
        "identity_schema_version": VERIFIER_IDENTITY_SCHEMA_VERSION,
        "candidate_revision_digest": candidate_digest,
        "containment_binding_digest": binding_digest,
        "implementation_head_digest": implementation_digest,
    }


def validate_dispatch_identity(
    *, dispatch_plan: dict[str, Any], containment_evidence: dict[str, Any],
    verdict: dict[str, Any], spec_id: str, run_id: str,
    candidate_revision: str,
) -> dict[str, str]:
    """Validate the public/private identity pair at the parent admission seam."""
    identity = derive_verifier_identity(
        {
            key: value for key, value in containment_evidence.items()
            if key not in {
                "spec_id", "run_id", "identity_schema_version",
                "candidate_revision_digest", "containment_binding_digest",
                "implementation_head_digest",
            }
        },
        spec_id=spec_id,
        run_id=run_id,
        candidate_revision=candidate_revision,
    )
    evidence_bytes = (
        json.dumps(containment_evidence, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    surface_commits = containment_evidence.get("surface_commits")
    expected_head = (
        surface_commits.get("head") if isinstance(surface_commits, dict) else None
    )
    checks = (
        dispatch_plan.get("schema_version") == "2.0.0",
        dispatch_plan.get("identity_schema_version") == VERIFIER_IDENTITY_SCHEMA_VERSION,
        containment_evidence.get("identity_schema_version") == VERIFIER_IDENTITY_SCHEMA_VERSION,
        dispatch_plan.get("spec_id") == containment_evidence.get("spec_id") == spec_id,
        dispatch_plan.get("run_id") == containment_evidence.get("run_id") == run_id,
        dispatch_plan.get("head_commit") == expected_head == verdict.get("head_commit"),
        dispatch_plan.get("implementation_head_digest")
        == containment_evidence.get("implementation_head_digest")
        == verdict.get("implementation_head_digest")
        == identity["implementation_head_digest"],
        containment_evidence.get("candidate_revision_digest")
        == identity["candidate_revision_digest"],
        containment_evidence.get("containment_binding_digest")
        == identity["containment_binding_digest"],
        dispatch_plan.get("containment_evidence_sha256") == evidence_sha,
        verdict.get("identity_schema_version") == VERIFIER_IDENTITY_SCHEMA_VERSION,
        verdict.get("spec_id") == spec_id,
    )
    if not all(checks):
        raise ValueError("verifier dispatch identity mismatch")
    return identity


@dataclass(frozen=True)
class GitFootprint:
    """A read-only snapshot of the worktree assigned to a verifier.

    The caller supplies the worktree under test.  Deliberately accepting no
    parent-checkout argument prevents a dirty coordinator checkout from
    contaminating the verifier's footprint decision.
    """

    tree: str
    porcelain: str


def _run_git(worktree: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        text=True,
        capture_output=True,
        check=False,
        env=_git_environment(),
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _git_bytes(repository: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *args], capture_output=True, check=False,
        env=_git_environment(),
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode("utf-8", "replace").strip()
            or f"git {' '.join(args)} failed"
        )
    return result.stdout


def _git_environment(**extra: str) -> dict[str, str]:
    """Return a deterministic Git environment without ambient repository links."""
    blocked = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE",
    }
    return {**{key: value for key, value in os.environ.items() if key not in blocked}, **extra}


def _normalise_repo_path(path: str) -> str:
    normalised = path.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    if not normalised or normalised.startswith("/") or ".." in Path(normalised).parts:
        raise ValueError(f"unsafe repository path: {path!r}")
    return normalised


def is_verifier_report_path(path: str, *, explicit: Iterable[str] = ()) -> bool:
    """Return whether a tracked path carries worker/verifier conclusions."""
    normalised = _normalise_repo_path(path)
    exact = {_normalise_repo_path(item) for item in explicit}
    return normalised in exact or normalised.startswith(VERIFIER_REPORT_ROOTS)


def is_verifier_metrics_path(path: str) -> bool:
    """Return whether a tracked path is a per-run metrics artifact.

    Unlike reports, metrics have no explicit-report analogue and no blanket
    withholding: every metrics path stays reachable unless it is separately
    identified as belonging to the spec under verification.
    """
    normalised = _normalise_repo_path(path)
    return normalised.startswith(VERIFIER_METRICS_ROOTS) and normalised.endswith(".yaml")


def normalise_spec_identity(spec_id: str) -> str:
    """Return the spec identity used to scope same-spec containment.

    Deliberately strict and deliberately raising.  Same-spec exclusion cannot be
    computed without an identity to compare against, and SPEC-239 R5 requires that
    case to fail closed rather than emit a surface with the weaker guarantee.
    """
    candidate = spec_id.strip() if isinstance(spec_id, str) else ""
    if not SPEC_IDENTITY_RE.fullmatch(candidate):
        raise ValueError(
            "same-spec containment requires a spec identifier, got: " f"{spec_id!r}"
        )
    return candidate


def _git_batch_blobs(repository: Path, object_ids: Iterable[str]) -> dict[str, bytes]:
    """Read many blobs through one ``git cat-file --batch`` process.

    Content-based same-spec detection reads every tracked report at both refs, and
    the dispatch boundary recomputes it.  One subprocess per blob would put several
    hundred process spawns on the live dispatch path of a repository that already
    carries ~180 reports, several of them tens of kilobytes.
    """
    ids = sorted({object_id for object_id in object_ids})
    if not ids:
        return {}
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "--batch"],
        input=("\n".join(ids) + "\n").encode("ascii"),
        capture_output=True,
        check=False,
        env=_git_environment(),
    )
    if result.returncode:
        raise RuntimeError(
            result.stderr.decode("utf-8", "replace").strip()
            or "git cat-file --batch failed"
        )
    bodies: dict[str, bytes] = {}
    stream = result.stdout
    offset = 0
    for _ in ids:
        newline = stream.find(b"\n", offset)
        if newline < 0:
            raise RuntimeError("truncated git cat-file --batch stream")
        header = stream[offset:newline].decode("ascii", "replace").split()
        if len(header) != 3 or header[1] != "blob":
            raise RuntimeError(f"unexpected git cat-file --batch record: {header}")
        size = int(header[2])
        start = newline + 1
        bodies[header[0]] = stream[start:start + size]
        offset = start + size + 1
    if set(bodies) != set(ids):
        raise RuntimeError("git cat-file --batch did not return every requested blob")
    return bodies


def same_spec_report_exclusions(
    source_repository: Path,
    *,
    spec_id: str,
    report_objects: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Return ``{path: rule}`` for tracked reports that identify *spec_id*.

    Two rules, recorded separately so containment evidence stays auditable.
    ``path`` catches the ordinary sibling — ``…-SPEC-235-001-unblock4.md`` — and
    ``content`` catches the report whose filename says nothing but whose body
    discusses the spec under verification.

    Matching is substring, not exact-token, and that asymmetry is intentional.
    Verifying ``SPEC-235`` withholds ``SPEC-235-001``'s reports as well; verifying
    ``SPEC-235-001`` does not withhold ``SPEC-235``'s by path, and relies on the
    content rule for the ones that actually discuss it.  Over-exclusion costs
    reachability only for *related* specs, while R3's fixture guarantee is scoped
    to unrelated ones.
    """
    token = normalise_spec_identity(spec_id).lower().encode("utf-8")
    rules: dict[str, str] = {}
    by_object: dict[str, set[str]] = {}
    for objects in report_objects.values():
        for path, object_id in objects.items():
            if token in path.lower().encode("utf-8"):
                rules[path] = "path"
            else:
                by_object.setdefault(object_id, set()).add(path)
    pending = {
        object_id: paths
        for object_id, paths in by_object.items()
        if any(path not in rules for path in paths)
    }
    bodies = _git_batch_blobs(source_repository, pending)
    for object_id, paths in sorted(pending.items()):
        if token in bodies[object_id].lower():
            for path in paths:
                rules.setdefault(path, "content")
    return dict(sorted(rules.items()))


def _clear_snapshot(destination: Path) -> None:
    for child in destination.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def _tracked_objects_matching(
    source_repository: Path,
    ref: str,
    *,
    predicate,
) -> dict[str, str]:
    """Return tracked ``{path: blob_id}`` pairs at one trusted ref matching *predicate*."""
    objects: dict[str, str] = {}
    entries = _git_bytes(source_repository, "ls-tree", "-rz", ref).split(b"\0")
    for raw in entries:
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        _mode, kind, object_id = metadata.decode("ascii").split()
        path = _normalise_repo_path(raw_path.decode("utf-8", "surrogateescape"))
        if kind == "blob" and predicate(path):
            objects[path] = object_id
    return objects


def _tracked_report_objects(
    source_repository: Path,
    ref: str,
    *,
    report_paths: Iterable[str],
) -> dict[str, str]:
    """Return tracked report paths and blob IDs for one trusted ref."""
    return _tracked_objects_matching(
        source_repository, ref,
        predicate=lambda path: is_verifier_report_path(path, explicit=report_paths),
    )


def _tracked_metrics_objects(source_repository: Path, ref: str) -> dict[str, str]:
    """Return tracked metrics paths and blob IDs for one trusted ref."""
    return _tracked_objects_matching(
        source_repository, ref, predicate=is_verifier_metrics_path,
    )


def _materialize_ref(
    source_repository: Path,
    destination: Path,
    ref: str,
    *,
    report_paths: Iterable[str],
    retained_report_paths: Iterable[str] = (),
    same_spec_metrics_paths: Iterable[str] = (),
) -> list[str]:
    """Materialize one tracked snapshot without sharing the source object DB."""
    _clear_snapshot(destination)
    excluded: list[str] = []
    retained = set(retained_report_paths)
    same_spec_metrics = set(same_spec_metrics_paths)
    entries = _git_bytes(source_repository, "ls-tree", "-rz", ref).split(b"\0")
    for raw in entries:
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        path = _normalise_repo_path(raw_path.decode("utf-8", "surrogateescape"))
        if path in same_spec_metrics:
            excluded.append(path)
            continue
        if is_verifier_report_path(path, explicit=report_paths) and path not in retained:
            excluded.append(path)
            continue
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError(f"unsupported tracked entry for verifier surface: {path} ({mode} {kind})")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _git_bytes(source_repository, "cat-file", "blob", object_id)
        if mode == "120000":
            link = body.decode("utf-8", "surrogateescape")
            resolved = (target.parent / link).resolve()
            if Path(os.path.commonpath((destination.resolve(), resolved))) != destination.resolve():
                raise ValueError(f"symlink escapes verifier surface: {path}")
            target.symlink_to(link)
        else:
            target.write_bytes(body)
            target.chmod(0o755 if mode == "100755" else 0o644)
    return sorted(excluded)


def prepare_verifier_surface(
    source_repository: Path,
    destination: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    report_paths: Iterable[str],
    evidence_path: Path,
    spec_id: str,
) -> dict[str, Any]:
    """Build a standalone Git repo with candidate conclusions removed.

    A linked worktree is deliberately rejected as the destination: worktrees
    share the source object database and therefore leave excluded candidate
    report blobs reachable through Git even when absent from the checkout.

    Three rules withhold a tracked report, and containment evidence records each
    one separately (``explicit_report_paths``, ``same_spec_excluded_paths``, and
    the remainder of ``excluded_paths``):

    * the explicit run-report paths;
    * every report whose path or content identifies *spec_id* (SPEC-239) —
      keyed on subject matter, not on whether the candidate touched the file,
      because a sibling report from an earlier round of the same spec is
      byte-identical across both arms and would otherwise be retained;
    * every remaining report the candidate added, removed, or changed.

    Byte-identical reports belonging to *other* specs are still retained so
    unchanged canonical tests may consume their own fixtures; their exact
    content hashes are recorded in containment evidence.

    Metrics artifacts (SPEC-243-003) get a narrower, fourth rule recorded in
    ``same_spec_excluded_metrics_paths``: a metrics file whose path or content
    identifies *spec_id* is withheld the same way a same-spec report is.
    Unlike reports, an unrelated spec's metrics file is never withheld and
    needs no retention bookkeeping — it was never a candidate for exclusion.

    Same-spec resolution runs before the destination repository exists, so a
    failure to compute it leaves no surface behind at all.
    """
    source_repository = source_repository.resolve()
    destination = destination.resolve()
    report_paths = tuple(sorted({_normalise_repo_path(path) for path in report_paths}))
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("verifier surface destination must be empty")
    spec_id = normalise_spec_identity(spec_id)
    baseline_report_objects = _tracked_report_objects(
        source_repository, baseline_ref, report_paths=report_paths
    )
    head_report_objects = _tracked_report_objects(
        source_repository, head_ref, report_paths=report_paths
    )
    same_spec_reports = same_spec_report_exclusions(
        source_repository,
        spec_id=spec_id,
        report_objects={
            "baseline": baseline_report_objects, "head": head_report_objects,
        },
    )
    baseline_metrics_objects = _tracked_metrics_objects(source_repository, baseline_ref)
    head_metrics_objects = _tracked_metrics_objects(source_repository, head_ref)
    same_spec_metrics = same_spec_report_exclusions(
        source_repository,
        spec_id=spec_id,
        report_objects={
            "baseline": baseline_metrics_objects, "head": head_metrics_objects,
        },
    )
    destination.mkdir(parents=True, exist_ok=True)
    source_common = Path(_run_git(source_repository, "rev-parse", "--git-common-dir").strip())
    if not source_common.is_absolute():
        source_common = (source_repository / source_common).resolve()
    subprocess.run(
        ["git", "init", "-q", str(destination)], check=True, env=_git_environment()
    )
    target_common = Path(_run_git(destination, "rev-parse", "--git-common-dir").strip())
    if not target_common.is_absolute():
        target_common = (destination / target_common).resolve()
    if target_common.resolve() == source_common.resolve():
        raise ValueError("verifier surface may not share the source Git object database")
    _run_git(destination, "config", "user.name", "Nightshift verifier surface")
    _run_git(destination, "config", "user.email", "verifier@example.invalid")
    explicit_reports = set(report_paths)
    # The three withholding rules are recorded as disjoint sets so a reader can
    # reconstruct which one took which path. A run report that is also same-spec is
    # attributed to the explicit rule, which is the narrower and older claim.
    same_spec_exclusions = {
        path: rule
        for path, rule in same_spec_reports.items()
        if path not in explicit_reports
    }
    retained_reports = {
        path: object_id
        for path, object_id in baseline_report_objects.items()
        if path not in explicit_reports
        and path not in same_spec_reports
        and head_report_objects.get(path) == object_id
    }
    retained_bodies = _git_batch_blobs(source_repository, retained_reports.values())
    retained_hashes = {
        path: hashlib.sha256(retained_bodies[object_id]).hexdigest()
        for path, object_id in sorted(retained_reports.items())
    }
    refs = (("baseline", baseline_ref), ("head", head_ref))
    commits: dict[str, str] = {}
    excluded_by_ref: dict[str, list[str]] = {}
    fixed_env = _git_environment(
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    for label, ref in refs:
        excluded_by_ref[label] = _materialize_ref(
            source_repository,
            destination,
            ref,
            report_paths=report_paths,
            retained_report_paths=retained_reports,
            same_spec_metrics_paths=same_spec_metrics,
        )
        _run_git(destination, "add", "-A")
        result = subprocess.run(
            ["git", "-C", str(destination), "commit", "--allow-empty", "-qm", f"verifier {label} snapshot"],
            env=fixed_env, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"could not commit {label} snapshot")
        commits[label] = _run_git(destination, "rev-parse", "HEAD").strip()
        _run_git(destination, "tag", f"verifier-{label}")

    probes = []
    excluded_paths = sorted(
        set(excluded_by_ref["baseline"]) | set(excluded_by_ref["head"])
    )
    for path in excluded_paths:
        for label in ("baseline", "head"):
            probe = subprocess.run(
                ["git", "-C", str(destination), "cat-file", "-e", f"verifier-{label}:{path}"],
                capture_output=True, check=False, env=_git_environment(),
            )
            probes.append({"ref": label, "path": path, "unreachable": probe.returncode != 0})
    if not probes or not all(probe["unreachable"] for probe in probes):
        raise RuntimeError("worker report remains reachable from verifier surface")
    evidence = {
        "schema_version": CONTAINMENT_EVIDENCE_SCHEMA_VERSION,
        "surface_kind": "standalone-sanitized-git",
        "source_refs": {"baseline": baseline_ref, "head": head_ref},
        "surface_commits": commits,
        "excluded_paths": excluded_by_ref,
        "explicit_report_paths": list(report_paths),
        "same_spec_id": spec_id,
        "same_spec_excluded_paths": same_spec_exclusions,
        "same_spec_excluded_metrics_paths": dict(sorted(same_spec_metrics.items())),
        "retained_historical_report_sha256": retained_hashes,
        "report_reachability": probes,
        "shared_object_database": False,
        "head_tree": _run_git(destination, "rev-parse", "HEAD^{tree}").strip(),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def configured_suite_command(source_repository: Path) -> str | None:
    """Read the declared canonical suite command for verifier dispatch (SPEC-243-001).

    Resolves *source_repository*'s Nightshift kit root the same way the LOOP's
    own command execution does (``preflight.resolve_kit_root``) and reads
    ``commands.test`` from that project's ``config.yaml`` with the kit's one
    shared multi-document config reader (``preflight.load_commands``) --
    reusing both rather than adding a second, independently-drifting parser.

    Fails closed to ``None`` on any absence or malformation: a missing kit
    root, an unreadable/malformed config.yaml, or a ``commands.test`` value
    that is missing, null, empty, or not a string. Callers must treat
    ``None`` as "no configured suite" and select the no-test-suite dispatch
    path rather than fabricate suite evidence (R3).
    """
    if load_commands is None or resolve_kit_root is None or KitRootError is None:
        return None
    try:
        kit_root = resolve_kit_root(source_repository)
    except KitRootError:
        return None
    except Exception:
        return None
    try:
        commands = load_commands(kit_root / "config.yaml")
    except Exception:
        return None
    if not isinstance(commands, dict):
        return None
    command = commands.get("test")
    if not isinstance(command, str) or not command.strip():
        return None
    return command.strip()


def prepare_verifier_dispatch(
    source_repository: Path,
    destination: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    report_paths: Iterable[str],
    evidence_path: Path,
    spec_id: str,
    run_id: str,
    suite_commands: Iterable[str] = (),
) -> PreparedVerifierDispatch:
    """Prepare the sole verifier surface and emit a sanitized launch plan.

    Normal and no-test-suite routes call this same boundary.  The durable
    evidence is reloaded and independently checked before a plan exists, so a
    preparation or reachability failure cannot degrade to the source worktree.
    """
    try:
        source_repository = source_repository.resolve()
        destination = destination.resolve()
        normalized_reports = tuple(sorted({_normalise_repo_path(path) for path in report_paths}))
        suites = tuple(suite_commands)
        if (
            destination == source_repository
            or destination.is_relative_to(source_repository)
            or source_repository.is_relative_to(destination)
        ):
            raise ValueError("verifier surface must be outside the source repository")
        if not all(isinstance(command, str) and command.strip() for command in suites):
            raise ValueError("suite commands must be non-empty strings")
        source_text = str(source_repository)
        if any(
            source_text in command
            or any(report_path in command for report_path in normalized_reports)
            for command in suites
        ):
            raise ValueError("suite command discloses the source repository or report path")
        evidence = prepare_verifier_surface(
            source_repository,
            destination,
            baseline_ref=baseline_ref,
            head_ref=head_ref,
            report_paths=normalized_reports,
            evidence_path=evidence_path,
            spec_id=spec_id,
        )
        exact_candidate_revision = _run_git(
            source_repository, "rev-parse", "--verify", f"{head_ref}^{{commit}}"
        ).strip()
        identity = derive_verifier_identity(
            evidence,
            spec_id=spec_id,
            run_id=run_id,
            candidate_revision=exact_candidate_revision,
        )
        evidence = {
            **evidence,
            "spec_id": spec_id,
            "run_id": run_id,
            **identity,
        }
        evidence_bytes_to_write = (
            json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        evidence_tmp = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
        evidence_tmp.write_bytes(evidence_bytes_to_write)
        os.replace(evidence_tmp, evidence_path)
        evidence_bytes = evidence_path.read_bytes()
        durable_evidence = json.loads(evidence_bytes)
        probes = durable_evidence.get("report_reachability")
        excluded = durable_evidence.get("excluded_paths")
        excluded_paths = (
            {
                path
                for values in excluded.values()
                if isinstance(values, list)
                for path in values
                if isinstance(path, str)
            }
            if isinstance(excluded, dict)
            else set()
        )
        expected_probes = {
            (label, report_path)
            for report_path in excluded_paths
            for label in ("baseline", "head")
        }
        observed_probes = {
            (probe.get("ref"), probe.get("path"))
            for probe in probes
            if isinstance(probe, dict) and probe.get("unreachable") is True
        } if isinstance(probes, list) else set()
        commits = durable_evidence.get("surface_commits")
        retained = durable_evidence.get("retained_historical_report_sha256")
        # Recompute same-spec scope from the source rather than trusting the record
        # the same call just wrote, and require it to be a strict subset of what the
        # surface actually withheld.
        same_spec = durable_evidence.get("same_spec_excluded_paths")
        observed_same_spec = {
            path: rule
            for path, rule in same_spec_report_exclusions(
                source_repository,
                spec_id=spec_id,
                report_objects={
                    "baseline": _tracked_report_objects(
                        source_repository, baseline_ref, report_paths=normalized_reports
                    ),
                    "head": _tracked_report_objects(
                        source_repository, head_ref, report_paths=normalized_reports
                    ),
                },
            ).items()
            if path not in set(normalized_reports)
        }
        same_spec_metrics = durable_evidence.get("same_spec_excluded_metrics_paths")
        observed_same_spec_metrics = same_spec_report_exclusions(
            source_repository,
            spec_id=spec_id,
            report_objects={
                "baseline": _tracked_metrics_objects(source_repository, baseline_ref),
                "head": _tracked_metrics_objects(source_repository, head_ref),
            },
        )
        observed_retained: dict[str, str] = {}
        if isinstance(retained, dict):
            for path in retained:
                baseline_body = _git_bytes(
                    destination, "show", f"verifier-baseline:{path}"
                )
                head_body = _git_bytes(destination, "show", f"verifier-head:{path}")
                if baseline_body != head_body:
                    raise ValueError("retained historical report differs between refs")
                observed_retained[path] = hashlib.sha256(head_body).hexdigest()
        ready = (
            durable_evidence == evidence
            and bool(normalized_reports)
            and durable_evidence.get("surface_kind") == "standalone-sanitized-git"
            and durable_evidence.get("shared_object_database") is False
            and observed_probes == expected_probes
            and isinstance(retained, dict)
            and observed_retained == retained
            and isinstance(same_spec, dict)
            and same_spec == observed_same_spec
            and isinstance(same_spec_metrics, dict)
            and same_spec_metrics == observed_same_spec_metrics
            and durable_evidence.get("same_spec_id")
            == normalise_spec_identity(spec_id)
            and set(same_spec) <= excluded_paths
            and set(same_spec_metrics) <= excluded_paths
            and not set(same_spec) & set(retained)
            and not set(same_spec_metrics) & set(retained)
            and isinstance(commits, dict)
            and set(commits) == {"baseline", "head"}
            and durable_evidence.get("spec_id") == spec_id
            and durable_evidence.get("run_id") == run_id
            and all(
                SHA256_HEX_RE.fullmatch(str(durable_evidence.get(key, "")))
                for key in (
                    "candidate_revision_digest",
                    "containment_binding_digest",
                    "implementation_head_digest",
                )
            )
            and derive_verifier_identity(
                {
                    key: value for key, value in durable_evidence.items()
                    if key not in {
                        "spec_id", "run_id", "identity_schema_version",
                        "candidate_revision_digest", "containment_binding_digest",
                        "implementation_head_digest",
                    }
                },
                spec_id=spec_id,
                run_id=run_id,
                candidate_revision=exact_candidate_revision,
            ) == identity
            and _run_git(destination, "rev-parse", "verifier-baseline").strip() == commits["baseline"]
            and _run_git(destination, "rev-parse", "verifier-head").strip() == commits["head"]
        )
    except Exception as exc:
        raise VerifierSurfacePreparationError("verifier surface preparation failed") from exc

    if not ready:
        raise VerifierSurfacePreparationError("verifier surface reachability assertion failed")
    return PreparedVerifierDispatch(
        repository=destination,
        evidence_path=evidence_path.resolve(),
        evidence=durable_evidence,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        suite_commands=suites,
        spec_id=spec_id,
        run_id=run_id,
    )


def validate_verifier_verdict_dict(data: dict[str, Any]) -> list[str]:
    """Validate the independent-verifier envelope fields owned by the kit."""
    errors = [f"missing top-level key '{key}'" for key in sorted(VERIFIER_VERDICT_REQUIRED_KEYS - data.keys())]
    if data.get("verdict") not in {"pass", "fail", "disputes_premise"}:
        errors.append(f"verdict not in enum: {data.get('verdict')!r}")
    identity_present = any(
        key in data for key in ("identity_schema_version", "implementation_head_digest")
    )
    if identity_present:
        if data.get("identity_schema_version") != VERIFIER_IDENTITY_SCHEMA_VERSION:
            errors.append("unknown verifier identity schema")
        if not SHA256_HEX_RE.fullmatch(str(data.get("implementation_head_digest", ""))):
            errors.append("invalid implementation_head_digest")
    return errors


def verifier_surface_self_test() -> dict[str, Any]:
    """Managed release smoke contract for containment and verdict semantics."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "source"
        surface = root / "surface"
        no_suite_surface = root / "surface-no-suite"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        _run_git(source, "config", "user.name", "Nightshift smoke")
        _run_git(source, "config", "user.email", "smoke@example.invalid")
        (source / "code.py").write_text("VALUE = 1\n", encoding="utf-8")
        # An earlier round of the spec under verification and an unrelated spec's
        # fixture, both byte-identical across the two arms. The smoke contract is
        # that the first is withheld and the second stays reachable (SPEC-239).
        sibling = source / "canonical/reports/SMOKE/earlier-round.md"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("earlier SMOKE conclusion\n", encoding="utf-8")
        unrelated = source / "canonical/reports/OTHER-SPEC/fixture.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("unrelated fixture\n", encoding="utf-8")
        # SPEC-243-003: a same-spec metrics artifact and an unrelated spec's
        # metrics artifact, both present unmodified across both arms. The smoke
        # contract is that the first is withheld and the second stays reachable.
        same_spec_metrics_fixture = source / "canonical/metrics/2026-01-01_001_SMOKE.yaml"
        same_spec_metrics_fixture.parent.mkdir(parents=True, exist_ok=True)
        same_spec_metrics_fixture.write_text("task_id: SMOKE\nstatus: completed\n", encoding="utf-8")
        unrelated_metrics_fixture = source / "canonical/metrics/2026-01-01_001_OTHER-SPEC.yaml"
        unrelated_metrics_fixture.write_text("task_id: OTHER-SPEC\nstatus: completed\n", encoding="utf-8")
        _run_git(source, "add", "-A")
        _run_git(source, "commit", "-qm", "baseline")
        baseline = _run_git(source, "rev-parse", "HEAD").strip()
        report = source / "canonical/reports/nightshift-report.md"
        report.write_text("worker conclusion\n", encoding="utf-8")
        (source / "code.py").write_text("VALUE = 2\n", encoding="utf-8")
        _run_git(source, "add", "-A")
        _run_git(source, "commit", "-qm", "head")
        head = _run_git(source, "rev-parse", "HEAD").strip()
        prepared = prepare_verifier_dispatch(
            source, surface, baseline_ref=baseline, head_ref=head,
            report_paths=["canonical/reports/nightshift-report.md"],
            evidence_path=root / "containment.json",
            spec_id="SMOKE", run_id="smoke-run",
            suite_commands=["python -m pytest -q"],
        )
        no_suite = prepare_verifier_dispatch(
            source, no_suite_surface, baseline_ref=baseline, head_ref=head,
            report_paths=["canonical/reports/nightshift-report.md"],
            evidence_path=root / "containment-no-suite.json",
            spec_id="SMOKE", run_id="smoke-run-no-suite",
        )
        plan = prepared.public_plan()
        no_suite_plan = no_suite.public_plan()
        forbidden_values = {str(source.resolve()), "canonical/reports/nightshift-report.md"}
        serialized_plans = json.dumps([plan, no_suite_plan], sort_keys=True)
        if any(value in serialized_plans for value in forbidden_values):
            raise RuntimeError("dispatch plan disclosed source repository or report path")
        if (
            plan["repository"] != str(surface.resolve())
            or plan["brief_kind"] != "normal"
            or no_suite_plan["repository"] != str(no_suite_surface.resolve())
            or no_suite_plan["brief_kind"] != "no-test-suite"
            or no_suite_plan["suite_commands"]
        ):
            raise RuntimeError("normal/no-test-suite dispatch plan contract failed")
        evidence = prepared.evidence
        if evidence["same_spec_excluded_paths"] != {
            "canonical/reports/SMOKE/earlier-round.md": "path"
        } or set(evidence["retained_historical_report_sha256"]) != {
            "canonical/reports/OTHER-SPEC/fixture.md"
        }:
            raise RuntimeError("same-spec containment smoke contract failed")
        if (surface / "canonical/reports/SMOKE/earlier-round.md").exists() or not (
            surface / "canonical/reports/OTHER-SPEC/fixture.md"
        ).exists():
            raise RuntimeError("same-spec containment surface contract failed")
        if evidence["same_spec_excluded_metrics_paths"] != {
            "canonical/metrics/2026-01-01_001_SMOKE.yaml": "path"
        }:
            raise RuntimeError("same-spec metrics containment smoke contract failed")
        if (surface / "canonical/metrics/2026-01-01_001_SMOKE.yaml").exists() or not (
            surface / "canonical/metrics/2026-01-01_001_OTHER-SPEC.yaml"
        ).exists():
            raise RuntimeError("same-spec metrics containment surface contract failed")
        for ref in ("verifier-baseline", "verifier-head"):
            probe = subprocess.run(
                ["git", "-C", str(surface), "cat-file", "-e",
                 f"{ref}:canonical/metrics/2026-01-01_001_SMOKE.yaml"],
                capture_output=True, check=False, env=_git_environment(),
            )
            if probe.returncode == 0:
                raise RuntimeError("same-spec metrics blob remains reachable from verifier surface")
        verdict = {
            "spec_id": "SMOKE", "branch": "smoke", "baseline_commit": baseline,
            "head_commit": plan["head_commit"],
            "identity_schema_version": plan["identity_schema_version"],
            "implementation_head_digest": plan["implementation_head_digest"],
            "verdict": "pass", "acs": [{"id": "AC1", "status": "pass", "evidence": "smoke"}],
            "suites": [], "git_footprint": {"tree_before": evidence["head_tree"], "tree_after": evidence["head_tree"], "porcelain": ""},
        }
        missing_errors = validate_verifier_verdict_dict(verdict)
        verdict["contamination"] = None
        if not missing_errors or validate_verifier_verdict_dict(verdict):
            raise RuntimeError("verifier verdict contamination contract failed")
        return evidence


def capture_verifier_footprint(worktree: Path) -> GitFootprint:
    """Capture the verifier footprint from its assigned worktree only."""
    return GitFootprint(
        tree=_run_git(worktree, "rev-parse", "HEAD^{tree}").strip(),
        porcelain=_run_git(worktree, "status", "--porcelain=v1", "--untracked-files=all"),
    )


def is_excluded_verifier_footprint_path(path: str) -> bool:
    """Return whether *path* is the one allowed generated-file artifact."""
    return path.replace("\\", "/") in VERIFIER_FOOTPRINT_EXCLUSIONS


def verifier_footprint_errors(before: GitFootprint, after: GitFootprint) -> list[str]:
    """Validate a verifier's worktree-local, read-only Git footprint."""
    errors: list[str] = []
    if before.tree != after.tree:
        errors.append(f"verifier mutated the repo tree: {before.tree} -> {after.tree}")
    dirty_paths = [
        line[3:]
        for line in after.porcelain.splitlines()
        if line.strip() and not is_excluded_verifier_footprint_path(line[3:])
    ]
    if dirty_paths:
        errors.append("verifier left the worktree dirty: " + "; ".join(dirty_paths))
    return errors


def acceptance_criterion_ids(spec_text: str) -> set[str]:
    """Extract AC IDs from this spec's Acceptance Criteria section only."""
    section = re.search(
        r"^##\s+Acceptance Criteria\s*$(.*?)(?=^##\s|\Z)",
        spec_text,
        re.MULTILINE | re.DOTALL,
    )
    return set(re.findall(r"\bAC\d+\b", section.group(1) if section else ""))


def uncovered_acceptance_criteria(spec_text: str, reported_ids: Iterable[str]) -> list[str]:
    """Return current-spec AC IDs absent from a verifier's per-AC evidence."""
    return sorted(acceptance_criterion_ids(spec_text) - set(reported_ids))


def verifier_worktree_boundary(worktree: Path) -> str:
    """Canonical wording for the parent/verifier isolation boundary."""
    return (
        f"Run every read-only Git footprint command against the assigned worktree "
        f"({worktree}), never the parent or coordinator checkout. Parent-checkout "
        "dirtiness is outside the verifier footprint."
    )


@dataclass
class VerificationIssue:
    severity: str
    dimension: str
    summary: str
    evidence: str
    recommendation: str
    file: str | None = None
    line: int | None = None
    rationale: str | None = None
    follow_up: str | None = None

    def validate(self) -> list[str]:
        errors = []
        if self.severity not in SEVERITIES:
            errors.append(f"invalid severity: {self.severity}")
        if self.dimension not in DIMENSIONS:
            errors.append(f"invalid dimension: {self.dimension}")
        for field_name in ("summary", "evidence", "recommendation"):
            if not getattr(self, field_name):
                errors.append(f"missing issue field: {field_name}")
        if self.severity == "WARNING" and not (self.rationale or self.follow_up):
            errors.append("WARNING issue requires rationale or follow_up")
        return errors


@dataclass
class VerificationReport:
    spec_id: str
    generated_at: str
    dimensions: dict[str, dict[str, Any]]
    issues: list[VerificationIssue] = field(default_factory=list)
    commands_run: list[dict[str, Any]] = field(default_factory=list)
    tool: str = "nightshift"
    model: str | None = None
    skipped_checks: list[dict[str, str]] = field(default_factory=list)

    @property
    def final_assessment(self) -> str:
        if any(issue.severity == "CRITICAL" for issue in self.issues):
            return "fail"
        if any(issue.severity == "WARNING" for issue in self.issues):
            return "pass_with_warnings"
        return "pass"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        data["final_assessment"] = self.final_assessment
        return data


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_report(spec_id: str, *, issues: Iterable[VerificationIssue] = (), commands_run: list[dict[str, Any]] | None = None, dimensions: dict[str, dict[str, Any]] | None = None, skipped_checks: list[dict[str, str]] | None = None) -> VerificationReport:
    base_dimensions = {
        "completeness": {"status": "pass", "summary": "No completeness issues found."},
        "correctness": {"status": "pass", "summary": "No correctness issues found."},
        "coherence": {"status": "pass", "summary": "No coherence issues found."},
    }
    if dimensions:
        base_dimensions.update(dimensions)
    issue_list = list(issues)
    for issue in issue_list:
        if issue.severity == "CRITICAL":
            base_dimensions[issue.dimension]["status"] = "fail"
        elif issue.severity == "WARNING" and base_dimensions[issue.dimension].get("status") != "fail":
            base_dimensions[issue.dimension]["status"] = "warning"
    return VerificationReport(
        spec_id=spec_id,
        generated_at=now_iso(),
        dimensions=base_dimensions,
        issues=issue_list,
        commands_run=commands_run or [],
        skipped_checks=skipped_checks or [],
    )


def validate_report_dict(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("spec_id", "generated_at", "dimensions", "issues", "commands_run", "final_assessment"):
        if key not in data:
            errors.append(f"missing required key: {key}")
    if data.get("final_assessment") not in FINAL_ASSESSMENTS:
        errors.append(f"invalid final_assessment: {data.get('final_assessment')}")
    dimensions = data.get("dimensions") or {}
    for dim in DIMENSIONS:
        if dim not in dimensions:
            errors.append(f"missing dimension: {dim}")
    for idx, raw in enumerate(data.get("issues") or []):
        try:
            issue = VerificationIssue(**{k: raw.get(k) for k in VerificationIssue.__dataclass_fields__})
        except TypeError as exc:
            errors.append(f"issue {idx} malformed: {exc}")
            continue
        errors.extend(f"issue {idx}: {err}" for err in issue.validate())
    if data.get("final_assessment") == "fail" and not any((i or {}).get("severity") == "CRITICAL" for i in data.get("issues") or []):
        errors.append("final_assessment fail requires at least one CRITICAL issue")
    return errors


def render_markdown(data: dict[str, Any]) -> str:
    lines = [f"# Verification Report: {data.get('spec_id', 'UNKNOWN')}", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append("| Dimension | Status | Summary |")
    lines.append("|---|---|---|")
    for dim in ("completeness", "correctness", "coherence"):
        info = (data.get("dimensions") or {}).get(dim, {})
        lines.append(f"| {dim.title()} | {info.get('status', 'unknown')} | {info.get('summary', '')} |")
    lines.append("")
    lines.append(f"Final assessment: **{data.get('final_assessment', 'unknown')}**")
    for severity in ("CRITICAL", "WARNING", "SUGGESTION"):
        lines += ["", f"## {severity}"]
        issues = [i for i in data.get("issues", []) if i.get("severity") == severity]
        if not issues:
            lines.append("None.")
            continue
        for issue in issues:
            loc = f" ({issue.get('file')}:{issue.get('line')})" if issue.get("file") and issue.get("line") else ""
            lines.append(f"- **{issue.get('dimension')}**: {issue.get('summary')}{loc}")
            lines.append(f"  Evidence: {issue.get('evidence')}")
            lines.append(f"  Recommendation: {issue.get('recommendation')}")
            if issue.get("rationale"):
                lines.append(f"  Rationale: {issue.get('rationale')}")
            if issue.get("follow_up"):
                lines.append(f"  Follow-up: {issue.get('follow_up')}")
    lines += ["", "## Commands Run"]
    if not data.get("commands_run"):
        lines.append("None recorded.")
    for command in data.get("commands_run", []):
        lines.append(f"- `{command.get('command')}` -> exit {command.get('exit_code')}: {command.get('summary', '')}")
    if data.get("skipped_checks"):
        lines += ["", "## Skipped Checks"]
        for skipped in data["skipped_checks"]:
            lines.append(f"- {skipped.get('name')}: {skipped.get('reason')}")
    return "\n".join(lines) + "\n"


def write_report(report: VerificationReport, reports_root: Path) -> tuple[Path, Path]:
    report_dir = reports_root / report.spec_id
    report_dir.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    json_path = report_dir / "verification.json"
    md_path = report_dir / "verification.md"
    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_md = md_path.with_suffix(".md.tmp")
    tmp_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_md.write_text(render_markdown(data), encoding="utf-8")
    os.replace(tmp_json, json_path)
    os.replace(tmp_md, md_path)
    return json_path, md_path


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def completion_gate(report_json: Path, *, override_reason_file: Path | None = None) -> tuple[bool, list[str]]:
    if not report_json.exists():
        return False, [f"verification report missing: {report_json}"]
    data = load_report(report_json)
    errors = validate_report_dict(data)
    if errors:
        return False, errors
    if data.get("final_assessment") == "fail":
        critical = [i.get("summary", "critical issue") for i in data.get("issues", []) if i.get("severity") == "CRITICAL"]
        return False, ["verification has CRITICAL issue(s): " + "; ".join(critical)]
    warnings = [i for i in data.get("issues", []) if i.get("severity") == "WARNING" and not (i.get("rationale") or i.get("follow_up"))]
    if warnings:
        return False, ["WARNING issue lacks rationale/follow_up: " + warnings[0].get("summary", "warning")]
    if data.get("final_assessment") == "pass_with_warnings" and override_reason_file and not override_reason_file.exists():
        return False, [f"warning acceptance requires override reason file: {override_reason_file}"]
    return True, []


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and not raw_argv[0].startswith("-") and raw_argv[0] not in {
        "prepare-dispatch",
        "prepare-surface",
        "verifier-self-test",
    }:
        data = load_report(Path(raw_argv[0]))
        errors = validate_report_dict(data)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 1
        print(render_markdown(data))
        return 0
    parser = argparse.ArgumentParser(description="Nightshift verification helpers")
    subparsers = parser.add_subparsers(dest="command")
    prepare = subparsers.add_parser("prepare-surface")
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--destination", required=True, type=Path)
    prepare.add_argument("--baseline", required=True)
    prepare.add_argument("--head", required=True)
    prepare.add_argument("--report-path", action="append", required=True)
    prepare.add_argument("--evidence", required=True, type=Path)
    prepare.add_argument("--spec-id", required=True)
    dispatch = subparsers.add_parser("prepare-dispatch")
    dispatch.add_argument("--source", required=True, type=Path)
    dispatch.add_argument("--destination", required=True, type=Path)
    dispatch.add_argument("--baseline", required=True)
    dispatch.add_argument("--head", required=True)
    dispatch.add_argument("--report-path", action="append", required=True)
    dispatch.add_argument("--evidence", required=True, type=Path)
    dispatch.add_argument("--spec-id", required=True)
    dispatch.add_argument("--run-id", required=True)
    dispatch.add_argument("--suite-command", action="append", default=[])
    subparsers.add_parser("verifier-self-test")
    args = parser.parse_args(raw_argv)
    if args.command == "prepare-surface":
        prepare_verifier_surface(
            args.source, args.destination, baseline_ref=args.baseline,
            head_ref=args.head, report_paths=args.report_path, evidence_path=args.evidence,
            spec_id=args.spec_id,
        )
        return 0
    if args.command == "prepare-dispatch":
        # R2/SPEC-243-001: when the caller supplies no explicit --suite-command,
        # derive the default from the source project's own declared config
        # rather than falling back silently to the no-test-suite brief.
        suite_commands = list(args.suite_command)
        if not suite_commands:
            configured = configured_suite_command(args.source)
            if configured is not None:
                suite_commands = [configured]
        try:
            prepared = prepare_verifier_dispatch(
                args.source, args.destination, baseline_ref=args.baseline,
                head_ref=args.head, report_paths=args.report_path,
                evidence_path=args.evidence, suite_commands=suite_commands,
                spec_id=args.spec_id, run_id=args.run_id,
            )
        except VerifierSurfacePreparationError:
            print(json.dumps({
                "status": "evidence_gap",
                "controller_reason": "verifier_surface_unavailable",
            }, sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps(prepared.public_plan(), sort_keys=True))
        return 0
    if args.command == "verifier-self-test":
        verifier_surface_self_test()
        return 0
    parser.error("a report path or subcommand is required")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
