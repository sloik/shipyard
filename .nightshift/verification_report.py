#!/usr/bin/env python3
"""SPEC-052: Verification report artifact helpers."""

from __future__ import annotations

import argparse
import contextlib
import copy
import fnmatch
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

try:  # pragma: no cover - deployed install may be incomplete
    from preflight import KitRootError, load_commands, resolve_kit_root
except Exception:  # pragma: no cover - deployed install may be incomplete
    KitRootError = None  # type: ignore[assignment,misc]
    load_commands = None  # type: ignore[assignment]
    resolve_kit_root = None  # type: ignore[assignment]

try:  # pragma: no cover - deployed install may be incomplete
    from preflight import sanitized_preflight_projection as _preflight_projection
except Exception:  # pragma: no cover - deployed install may be incomplete
    _preflight_projection = None  # type: ignore[assignment]

# SPEC-289: the canonical, fail-closed anchor vocabulary shared with
# validate_specs.py. It is imported, never reimplemented: a second token parser
# is exactly how the two gates came to disagree about what a portable path is.
# An install missing the module does not silently fall back to literal tokens --
# `_resolve_declared_root` refuses any anchored declaration instead.
try:  # pragma: no cover - deployed install may be incomplete
    import path_vars
except Exception:  # pragma: no cover - deployed install may be incomplete
    path_vars = None  # type: ignore[assignment]

SEVERITIES = {"CRITICAL", "WARNING", "SUGGESTION"}
DIMENSIONS = {"completeness", "correctness", "coherence"}
FINAL_ASSESSMENTS = {"pass", "pass_with_warnings", "fail"}

# SPEC-284 retired ``VERIFIER_FOOTPRINT_EXCLUSIONS`` from this module.  It named
# a single project's generated artifact in order to paper over an emptiness test
# on the *after* snapshot.  The before/after set comparison in
# ``verifier_footprint_errors`` cancels pre-existing dirt of every kind, in every
# project, without the shared kit hardcoding anyone's tooling.
VERIFIER_REPORT_ROOTS = ("reports/", ".nightshift/reports/", "canonical/reports/")
# Metrics artifacts are never withheld wholesale (unlike reports): an unrelated
# spec's metrics file is ordinary tracked content and must stay reachable (R2).
# Only the subset identified as belonging to the spec under verification is
# withheld, through the same same-spec identity rule already used for reports.
VERIFIER_METRICS_ROOTS = ("metrics/", ".nightshift/metrics/", "canonical/metrics/")
VERIFIER_VERDICT_REQUIRED_KEYS = frozenset({
    "spec_id", "branch", "baseline_commit", "head_commit", "verdict",
    "acs", "suites", "git_footprint", "scope", "contamination",
})
# SPEC-NS-KIT-002-005 R2: a non-null `contamination` is one exposure object or a list of them.
CONTAMINATION_CLASSES = frozenset({
    "spec_bookkeeping", "author_artifact_name", "required_deliverable", "author_conclusion",
})
CONTAMINATION_TIMINGS = frozenset({"before_derivation", "after_derivation"})
CONTAMINATION_KEYS = frozenset({"class", "timing", "detail"})
VERIFIER_IDENTITY_SCHEMA_VERSION = "1.0.0"
CONTAINMENT_EVIDENCE_SCHEMA_VERSION = "1.7.0"
# SPEC-398: the one fixed body written at a withheld same-spec report path that
# exists in an arm's own tree, so a retained document linking to that report
# still resolves. It is a module constant, never derived from the withheld blob.
PLACEHOLDER_REPORT_BODY = (
    "Nightshift verifier surface placeholder.\n"
    "The original report at this path is withheld from the verifier surface.\n"
    "This file is intentionally content-free; it is not evidence about the spec.\n"
)
PLACEHOLDER_REPORT_SHA256 = hashlib.sha256(PLACEHOLDER_REPORT_BODY.encode("utf-8")).hexdigest()
# SPEC-288: the one declaration form that turns a `context.required_inputs` entry
# into external evidence. Two parts, deliberately: the source repository root is
# *declared*, not inferred from the path, so a human reading the spec sees which
# repository is being trusted, and so "an absolute path escaping its source
# repository" stays a constructible, separately-diagnosable refusal instead of
# collapsing into "that directory is not a repository".
EXTERNAL_INPUT_PREFIX = "external-evidence:"
EXTERNAL_INPUT_SEPARATOR = "#"
EXTERNAL_INPUT_NAMESPACE = ".nightshift-verifier-inputs"
EXTERNAL_INPUT_MANIFEST = "MANIFEST.json"
# Bounds for a declared directory snapshot. They exist so "a directory" can never
# mean "an unbounded import"; a declaration needing more than this should name the
# individual files its ACs actually read.
EXTERNAL_INPUT_MAX_MEMBERS = 256
EXTERNAL_INPUT_MAX_BYTES = 8 * 1024 * 1024
EXTERNAL_SOURCE_DOMAIN = b"nightshift.verifier.external-source.v1\0"
# SPEC-390-002: a retained preflight result is declared as
# `preflight-proof:<project-relative-path>` in `context.required_inputs`. It is not
# external evidence: the retained file is ignored, untracked, and holds local
# paths and test output, so only a sanitized, parsed projection is ever shown to
# a verifier -- in its own namespace, never inside the external-input one.
PREFLIGHT_PROOF_PREFIX = "preflight-proof:"
PREFLIGHT_PROOF_NAMESPACE = ".nightshift-verifier-proof"
PREFLIGHT_PROOF_FILE = "preflight-proof.json"
PREFLIGHT_PROOF_SCHEMA_VERSION = "1.0.0"
PREFLIGHT_PROOF_MAX_BYTES = 1024 * 1024
PREFLIGHT_PROOF_KEYS = frozenset({
    "schema_version", "retrieval", "result_sha256", "projection",
    "bound_candidate_revision_digest",
})
PREFLIGHT_PROOF_RETRIEVALS = frozenset({
    "ok", "missing", "path_not_contained", "digest_mismatch", "no_reference_digest",
    "malformed", "declaration_invalid",
})
PREFLIGHT_PROJECTION_KEYS = frozenset({
    "schema_version", "result_sha256", "spec_id", "timestamp", "ok",
    "blocking_failure_count", "git_clean", "install_admission", "declared_test",
})
# SPEC-390-002-001: which trusted copy of this module the verifier runs for
# `verify-preflight-proof` -- never the candidate arm's own copy.
PREFLIGHT_CHECKER_PROVENANCE = frozenset({"baseline_arm", "installed"})
PREFLIGHT_CHECKER_RELATIVE_PATHS = (
    "canonical/verification_report.py",
    ".nightshift/verification_report.py",
    "verification_report.py",
)
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
    # SPEC-NS-KIT-002-002 R5: absent (None) unless the caller supplied a ledger.
    ledger_baseline: dict[str, Any] | None = None
    # SPEC-NS-KIT-002-003 R1: true only from ledger evidence of an active flaky entry.
    flaky_suspected: bool = False
    # SPEC-NS-KIT-002-004 R3/R5: isolation assignment, dispatch-time arm footprints and the
    # trusted-tooling record (the last only when a CLI caller resolved one).
    arm_isolation: dict[str, Any] | None = None
    footprint_before: dict[str, Any] | None = None
    trusted_tooling: dict[str, Any] | None = None
    # SPEC-NS-KIT-008 R2: true when a spec path was given and projection was declined.
    spec_projection_declined: bool = False

    def public_plan(self) -> dict[str, Any]:
        commits = self.evidence["surface_commits"]
        surface_repositories = self.evidence["surface_repositories"]
        plan = {
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
            # SPEC-282 (R1/R2/AC3): each arm is already materialized as its own
            # runnable, read-only working directory under the same standalone
            # surface -- the verifier never checks out or materializes a ref
            # itself, it only names the already-assigned directory per arm.
            "arm_working_directories": dict(surface_repositories),
            "implementation_head_digest": self.evidence["implementation_head_digest"],
            "brief_kind": "normal" if self.suite_commands else "no-test-suite",
            "suite_commands": list(self.suite_commands),
            "containment_evidence_sha256": self.evidence_sha256,
            # SPEC-NS-KIT-002-003 R1/R5: counts come from the one canonical rule.
            "sampling": sampling_plan(flaky_suspected=self.flaky_suspected),
            "arm_isolation": self.arm_isolation or build_arm_isolation(),
        }
        normalisation = self.evidence.get("spec_normalisation")
        if isinstance(normalisation, dict) and normalisation.get("scope_summary"):
            # SPEC-NS-KIT-002-005 R1a: the brief's `{scope_summary}`, with withheld
            # earlier-attempt names already neutral; the exact scope stays with the gate.
            plan["scope_summary"] = normalisation["scope_summary"]
        if self.spec_projection_declined:
            plan["spec_projection"] = "declined"
        if self.footprint_before is not None:
            plan["footprint_before"] = self.footprint_before
        if self.trusted_tooling is not None:
            plan["trusted_tooling"] = self.trusted_tooling
        proof = self.evidence.get("declared_preflight_proof")
        if proof is not None:
            # SPEC-390-002: present only when the spec declared a preflight proof, so a
            # dispatch without one keeps its exact prior plan. The digest, not the
            # revision, is what the verifier binds the projected proof to.
            plan["preflight_proof"] = {
                "projected_path": proof["projected_path"],
                "projected_sha256": proof["projected_sha256"],
                "candidate_revision_digest": self.evidence["candidate_revision_digest"],
            }
            # SPEC-390-002-001: name the trusted copy of this checker the verifier must
            # run, and flag a candidate that edited the checker itself.
            baseline_checker = _arm_checker_bytes(surface_repositories.get("baseline"))
            head_checker = _arm_checker_bytes(surface_repositories.get("head"))
            plan["preflight_proof"]["checker_provenance"] = (
                "baseline_arm" if baseline_checker is not None else "installed"
            )
            plan["preflight_proof"]["candidate_changed_checker"] = (
                baseline_checker != head_checker
            )
        projection = self.evidence.get("declared_evidence_projection")
        if projection is not None:
            # SPEC-391: present only when the spec declared an evidence projection.
            plan["evidence_projection"] = {
                "projected_path": projection["projected_path"],
                "projected_sha256": projection["projected_sha256"],
                "candidate_revision_digest": self.evidence["candidate_revision_digest"],
                **_checker_provenance(surface_repositories),
            }
        if self.ledger_baseline is not None:
            plan["ledger_baseline"] = dict(self.ledger_baseline)
        return plan


def _arm_checker_bytes(arm: Any) -> bytes | None:
    """Bytes of the arm's own `verification_report.py`, or None when it has none."""
    if not arm:
        return None
    for relative in PREFLIGHT_CHECKER_RELATIVE_PATHS:
        candidate = Path(arm) / relative
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.read_bytes()
    return None


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


def _force_add_tracked_paths(worktree: Path, paths: Iterable[str]) -> None:
    """Force-add exactly *paths* into *worktree*'s index (SPEC-342).

    Uses ``--pathspec-from-file``/``--pathspec-file-nul`` rather than a plain
    argv pathspec list for two reasons that a small fixture cannot surface but
    a real kit checkout (thousands of tracked paths) can: argv length limits
    (``ARG_MAX``), and paths whose bytes are not valid UTF-8 (materialized via
    ``surrogateescape`` upstream in ``_materialize_ref``, then round-tripped
    here through ``os.fsencode`` rather than a text-mode subprocess argv).
    """
    paths = list(paths)
    if not paths:
        return
    payload = b"\0".join(os.fsencode(path) for path in paths)
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pathspec")
    try:
        handle.write(payload)
        handle.close()
        result = subprocess.run(
            [
                "git", "-C", str(worktree), "add", "-f",
                f"--pathspec-from-file={handle.name}", "--pathspec-file-nul",
            ],
            capture_output=True, check=False, env=_git_environment(),
        )
        if result.returncode:
            raise RuntimeError(
                result.stderr.decode("utf-8", "replace").strip()
                or "git add -f --pathspec-from-file failed"
            )
    finally:
        os.unlink(handle.name)


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


class DeclaredInputRefusal(ValueError):
    """One predeclared external input that may not be materialized (SPEC-288 R3).

    Carries the declaration, a stable machine reason, and the human detail, so a
    refusal is never a bare "escapes" and never a silent skip. ``records`` holds
    the containment-evidence rows computed up to and including the refusal, so the
    caller can persist refusal evidence before failing the dispatch closed (R4).
    """

    def __init__(
        self, declaration: str, reason: str, detail: str,
        *, records: list[dict[str, Any]] | None = None,
    ) -> None:
        self.declaration = declaration
        self.reason = reason
        self.detail = detail
        self.records = records or []
        super().__init__(
            f"declared external input refused: {declaration!r} [{reason}] {detail}"
        )


@dataclass(frozen=True)
class ProjectedInputFile:
    """One byte-exact projection target inside the verifier surface."""

    path: str
    body: bytes


@dataclass(frozen=True)
class ResolvedExternalInput:
    """One admitted declaration: its evidence row and its projected bytes."""

    record: dict[str, Any]
    files: tuple[ProjectedInputFile, ...]


def _unquote_yaml_scalar(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return re.sub(r"\s+#.*$", "", text).strip()


def _spec_frontmatter(spec_text: str) -> str:
    lines = spec_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index])
    return ""


def spec_required_inputs(spec_text: str) -> list[str]:
    """Return ``context.required_inputs`` from one spec's frontmatter.

    A deliberately small reader rather than a YAML dependency: this module already
    runs in deployed installs that may not carry PyYAML, and the declaration it
    must read is a flat list of scalars under one nested key. Anything it cannot
    read is simply not a declaration, which fails closed — an entry this parser
    drops is an entry that grants no evidence authority.
    """
    block: list[str] = []
    inside = False
    for line in _spec_frontmatter(spec_text).splitlines():
        if not inside:
            inside = line.rstrip() == "context:"
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break
        block.append(line)
    items: list[str] = []
    collecting = False
    for line in block:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if collecting:
            if stripped.startswith("- "):
                items.append(_unquote_yaml_scalar(stripped[2:]))
                continue
            collecting = False
        match = re.fullmatch(r"required_inputs:\s*(.*)", stripped)
        if match is None:
            continue
        inline = match.group(1).strip()
        if inline.startswith("[") and inline.endswith("]"):
            items.extend(
                _unquote_yaml_scalar(part)
                for part in inline[1:-1].split(",")
                if part.strip()
            )
        elif not inline:
            collecting = True
    return [item for item in items if item]


def declared_external_inputs(spec_text: str) -> list[str]:
    """Return the external-evidence declarations, in declaration order."""
    return [
        item for item in spec_required_inputs(spec_text)
        if item.startswith(EXTERNAL_INPUT_PREFIX)
    ]


def _blob_text_at_ref(repository: Path, ref: str, path: str) -> str | None:
    """Return one tracked file's text at *ref*, or None when it is not a blob."""
    probe = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "-t", f"{ref}:{path}"],
        capture_output=True, check=False, env=_git_environment(),
    )
    if probe.returncode or probe.stdout.decode("ascii", "replace").strip() != "blob":
        return None
    return _git_bytes(repository, "cat-file", "blob", f"{ref}:{path}").decode(
        "utf-8", "surrogateescape"
    )


def _tracked_entries(repository: Path, ref: str) -> dict[str, tuple[str, str]]:
    """Return ``{path: (mode, object_id)}`` for every tracked entry at *ref*."""
    entries: dict[str, tuple[str, str]] = {}
    for raw in _git_bytes(repository, "ls-tree", "-rz", ref).split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, _kind, object_id = metadata.decode("ascii").split()
        entries[raw_path.decode("utf-8", "surrogateescape")] = (mode, object_id)
    return entries


def _external_source_identity(repository: Path) -> str:
    """Return a host-path-free identity for one external source repository.

    Derived from the repository's root commit(s), so the same repository yields
    the same identity from any checkout location and the identity discloses no
    filesystem path to the verifier (R2/R4).
    """
    roots = sorted(_run_git(repository, "rev-list", "--max-parents=0", "HEAD").split())
    if not roots:
        raise ValueError("external source repository has no commits")
    return _domain_digest(
        EXTERNAL_SOURCE_DOMAIN, *(root.encode("ascii") for root in roots)
    )[:16]


def _refuse(declaration: str, reason: str, detail: str) -> DeclaredInputRefusal:
    return DeclaredInputRefusal(declaration, reason, detail)


def _resolve_declared_root(declaration: str, raw_root: str, project_root: Path) -> Path:
    """Resolve the *repository-root component* of a declaration (SPEC-289 R1).

    A stored spec may not carry a literal host path -- SPEC-071 rejects one as a
    leak -- so the only portable spelling of a source repository is an anchored
    token such as ``{{ARGO_HOME}}/...``. SPEC-288 expanded ``~`` and nothing else,
    which made that spelling refusable as "not a Git repository" and left no form
    that both gates accept. Resolution therefore goes through the same
    ``path_vars`` primitive the validator's vocabulary comes from, in fail-closed
    ``execute`` mode, against *project_root* -- never ``Path.home()``, never the
    ambient working directory.

    Scope is deliberately the root component only: the repository-relative half of
    the declaration has already passed the absolute/traversal checks as a literal
    string and is never token-expanded, so no anchor can move a member outside the
    repository it was declared against.

    Every failure is a refusal, named ``anchor_resolution`` so it is not confused
    with a resolved root that turns out not to be a repository, and every detail is
    built from the *declared* text: a refusal record must not publish the host path
    an anchor would have resolved to.
    """
    if "{{" not in raw_root:
        # Unanchored declaration: SPEC-288 behaviour, byte for byte.
        return Path(os.path.expanduser(raw_root))
    if path_vars is None:  # pragma: no cover - incomplete install
        raise _refuse(
            declaration, "anchor_resolution",
            f"declared source repository {raw_root!r} is anchored, but this install "
            "has no path_vars module to resolve it",
        )
    try:
        resolved = path_vars.resolve(raw_root, project_root, mode="execute")
    except path_vars.ResolutionError as exc:
        raise _refuse(
            declaration, "anchor_resolution",
            f"declared source repository {raw_root!r} names anchor "
            f"{{{{{exc.token}}}}}, which does not resolve from the subject project root",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - any resolver failure fails closed
        raise _refuse(
            declaration, "anchor_resolution",
            f"declared source repository {raw_root!r} could not be resolved",
        ) from exc
    if "{{" in resolved:
        # ``path_vars`` leaves tokens inside code fences/spans verbatim. A root
        # that survives resolution with a token still in it is not an anchor, and
        # admitting it literally would be the inline-token escape hatch R4 forbids.
        raise _refuse(
            declaration, "anchor_resolution",
            f"declared source repository {raw_root!r} still holds an unresolved "
            "token after anchor resolution",
        )
    return Path(os.path.expanduser(resolved))


def _resolve_one_declaration(
    declaration: str, *, spec_id: str, report_paths: Iterable[str],
    total_bytes: int, project_root: Path,
) -> ResolvedExternalInput:
    """Resolve one declaration to pinned, projectable bytes, or refuse it.

    Every exit that is not an admission raises :class:`DeclaredInputRefusal` with
    a distinct reason. Declaration alone never overrides containment: the
    same-spec and report-root rules are applied first, so a declared own report is
    refused *as* an own report rather than admitted because it was declared (R3).

    SPEC-289 adds one seam and moves nothing else: the repository-root component is
    resolved through ``path_vars`` against *project_root* where SPEC-288 called
    ``os.path.expanduser``. It sits after the containment rules and before the
    first source read, so an anchor can neither buy its way past same-spec
    withholding nor cause a byte to be read before it is known to be resolvable.
    """
    value = declaration[len(EXTERNAL_INPUT_PREFIX):].strip()
    if EXTERNAL_INPUT_SEPARATOR not in value:
        raise _refuse(
            declaration, "malformed_declaration",
            f"expected {EXTERNAL_INPUT_PREFIX}<repository-root>"
            f"{EXTERNAL_INPUT_SEPARATOR}<repository-relative-path>",
        )
    raw_root, raw_path = value.split(EXTERNAL_INPUT_SEPARATOR, 1)
    raw_root, raw_path = raw_root.strip(), raw_path.strip()
    if not raw_root or not raw_path:
        raise _refuse(declaration, "malformed_declaration", "empty repository root or path")
    if PurePosixPath(raw_path).is_absolute():
        raise _refuse(
            declaration, "absolute_path_escapes_source_repository",
            f"declared path {raw_path!r} is absolute and therefore names content "
            "outside its declared source repository",
        )
    if ".." in PurePosixPath(raw_path).parts:
        raise _refuse(
            declaration, "path_traversal",
            f"declared path {raw_path!r} traverses out of its source repository",
        )
    try:
        relative_path = _normalise_repo_path(raw_path)
    except ValueError as exc:
        raise _refuse(declaration, "path_traversal", str(exc)) from exc

    token = normalise_spec_identity(spec_id).lower()
    if token in relative_path.lower():
        raise _refuse(
            declaration, "same_spec_report",
            f"declared path {relative_path!r} identifies the spec under "
            "verification; declaration does not override same-spec containment",
        )
    if is_verifier_report_path(relative_path, explicit=report_paths):
        raise _refuse(
            declaration, "report_root",
            f"declared path {relative_path!r} lies in a withheld report root",
        )

    root = _resolve_declared_root(declaration, raw_root, project_root)
    if not root.is_absolute():
        raise _refuse(
            declaration, "not_a_git_repository",
            f"declared source repository {raw_root!r} is not an absolute path",
        )
    if not root.is_dir():
        raise _refuse(
            declaration, "not_a_git_repository",
            f"declared source repository {raw_root!r} is not a directory",
        )
    try:
        toplevel = Path(_run_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    except Exception as exc:  # noqa: BLE001 - any git failure is the same refusal
        raise _refuse(
            declaration, "not_a_git_repository",
            f"declared source repository {raw_root!r} is not a Git repository",
        ) from exc
    if toplevel != root.resolve():
        raise _refuse(
            declaration, "not_a_git_repository",
            f"declared source repository {raw_root!r} is not a repository root",
        )

    absolute = root / relative_path
    if absolute.is_symlink() or any(
        (root / PurePosixPath(relative_path).parents[index]).is_symlink()
        for index in range(len(PurePosixPath(relative_path).parents) - 1)
    ):
        raise _refuse(
            declaration, "symlink",
            f"declared path {relative_path!r} is, or is reached through, a symlink",
        )

    entries = _tracked_entries(root, "HEAD")
    prefix = relative_path + "/"
    members = {
        path: entry for path, entry in entries.items() if path.startswith(prefix)
    }
    if relative_path not in entries and not members:
        raise _refuse(
            declaration,
            "untracked" if absolute.exists() else "missing",
            f"declared path {relative_path!r} is "
            + ("not tracked at HEAD" if absolute.exists() else "absent"),
        )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all",
         "--", relative_path],
        capture_output=True, check=False, env=_git_environment(),
    )
    if status.returncode:
        raise _refuse(declaration, "mutable", "could not read source repository status")
    dirt = [line for line in status.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if dirt:
        untracked = [line for line in dirt if line.startswith("??")]
        raise _refuse(
            declaration,
            "untracked_member" if untracked and relative_path not in entries else "mutable",
            f"declared path {relative_path!r} is not immutable at HEAD: "
            f"{(untracked or dirt)[0]}",
        )

    identity = _external_source_identity(root)
    commit = _run_git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    namespace = f"{EXTERNAL_INPUT_NAMESPACE}/{identity}"
    selected = (
        {relative_path: entries[relative_path]} if relative_path in entries else members
    )
    kind = "file" if relative_path in entries else "directory"
    if kind == "directory" and len(selected) > EXTERNAL_INPUT_MAX_MEMBERS:
        raise _refuse(
            declaration, "directory_bounds_exceeded",
            f"declared directory {relative_path!r} has {len(selected)} tracked members, "
            f"over the {EXTERNAL_INPUT_MAX_MEMBERS} bound",
        )
    files: list[ProjectedInputFile] = []
    member_records: list[dict[str, Any]] = []
    running = total_bytes
    for path, (mode, object_id) in sorted(selected.items()):
        if mode == "120000":
            raise _refuse(
                declaration, "symlink_member" if kind == "directory" else "symlink",
                f"tracked entry {path!r} is a symlink and may not be projected",
            )
        if mode not in {"100644", "100755"}:
            raise _refuse(
                declaration, "unsupported_entry_type",
                f"tracked entry {path!r} has unsupported mode {mode}",
            )
        body = _git_bytes(root, "cat-file", "blob", object_id)
        running += len(body)
        if running > EXTERNAL_INPUT_MAX_BYTES:
            raise _refuse(
                declaration, "directory_bounds_exceeded",
                f"declared inputs exceed the {EXTERNAL_INPUT_MAX_BYTES}-byte projection bound",
            )
        if is_verifier_metrics_path(path) and token.encode("utf-8") in body.lower():
            raise _refuse(
                declaration, "same_spec_content",
                f"tracked entry {path!r} is a metrics artifact whose content "
                "identifies the spec under verification",
            )
        files.append(ProjectedInputFile(path=f"{namespace}/{path}", body=body))
        member_records.append({
            "source_path": path,
            "object_id": object_id,
            "projected_path": f"{namespace}/{path}",
            "sha256": hashlib.sha256(body).hexdigest(),
            "byte_count": len(body),
        })
    record: dict[str, Any] = {
        "declaration": declaration,
        "source_repository": str(root.resolve()),
        "source_repository_id": identity,
        "source_commit": commit,
        "source_path": relative_path,
        "kind": kind,
        "object_id": _run_git(root, "rev-parse", f"HEAD:{relative_path}").strip(),
        "projected_path": f"{namespace}/{relative_path}",
        "byte_count": sum(member["byte_count"] for member in member_records),
        "handling": "admitted",
    }
    if kind == "file":
        record["sha256"] = member_records[0]["sha256"]
    else:
        record["member_count"] = len(member_records)
        record["members"] = member_records
    return ResolvedExternalInput(record=record, files=tuple(files))


def resolve_declared_external_inputs(
    source_repository: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    spec_path: str | None,
    spec_id: str,
    report_paths: Iterable[str] = (),
) -> tuple[list[ResolvedExternalInput], list[dict[str, Any]]]:
    """Resolve the spec's declared external inputs for one dispatch (R1/R2/R3).

    The declaration is read from the *spec file as committed at each verifier
    arm*, never from the working tree. Both arms must carry the identical
    external-evidence declaration list: a candidate that adds, changes, or removes
    one during its own run gains no evidence authority, and the disagreement is
    refused before a surface exists rather than resolved in either arm's favour.

    Entries without the ``external-evidence:`` marker are ordinary upstream-artifact
    declarations. They are left exactly as they were before SPEC-288 — not resolved,
    not projected, not recorded — so a dispatch that declares no external evidence
    is unchanged in every observable way.

    *source_repository* is also the anchor-resolution context for SPEC-289: it is
    the subject project root this dispatch was constructed against. It is derived
    here rather than passed in, deliberately — the surface build and the after-the-
    fact re-derivation that compares against the recorded rows both enter through
    this function, and a resolution context they could supply separately is one
    they could supply differently.
    """
    if spec_path is None:
        return [], []
    normalized_spec_path = _normalise_repo_path(spec_path)
    baseline_text = _blob_text_at_ref(source_repository, baseline_ref, normalized_spec_path)
    head_text = _blob_text_at_ref(source_repository, head_ref, normalized_spec_path)
    baseline_declarations = declared_external_inputs(baseline_text or "")
    head_declarations = declared_external_inputs(head_text or "")
    if baseline_declarations != head_declarations:
        raise DeclaredInputRefusal(
            json.dumps(
                {"baseline": baseline_declarations, "head": head_declarations},
                sort_keys=True,
            ),
            "declaration_not_identical",
            f"external-evidence declarations in {normalized_spec_path} differ between "
            "the verifier arms; a candidate may not change its own spec's declared "
            "inputs during its run",
            records=[{
                "declaration": declaration,
                "handling": "refused",
                "reason": "declaration_not_identical",
                "arm": arm,
            } for arm, declarations in (
                ("baseline", baseline_declarations), ("head", head_declarations)
            ) for declaration in declarations],
        )
    resolved: list[ResolvedExternalInput] = []
    records: list[dict[str, Any]] = []
    total = 0
    for declaration in baseline_declarations:
        try:
            item = _resolve_one_declaration(
                declaration, spec_id=spec_id, report_paths=report_paths,
                total_bytes=total, project_root=source_repository,
            )
        except DeclaredInputRefusal as refusal:
            refusal.records = records + [{
                "declaration": refusal.declaration,
                "handling": "refused",
                "reason": refusal.reason,
                "detail": refusal.detail,
            }]
            raise
        total += int(item.record["byte_count"])
        claimed = {
            projected.path for earlier in resolved for projected in earlier.files
        } & {projected.path for projected in item.files}
        if claimed:
            # Two declarations that project to the same path -- a directory and a
            # file inside it, most plausibly. Caught here, before the destination
            # exists, rather than mid-materialization: a refusal must never leave a
            # half-built surface behind.
            refusal = _refuse(
                declaration, "projection_collision",
                f"declaration projects to {sorted(claimed)[0]!r}, which an earlier "
                "declaration already claims",
            )
            refusal.records = records + [{
                "declaration": refusal.declaration,
                "handling": "refused",
                "reason": refusal.reason,
                "detail": refusal.detail,
            }]
            raise refusal
        resolved.append(item)
        records.append(item.record)
    if resolved:
        for label, ref in (("baseline", baseline_ref), ("head", head_ref)):
            colliding = sorted(
                path for path in _tracked_entries(source_repository, ref)
                if path == EXTERNAL_INPUT_NAMESPACE
                or path.startswith(EXTERNAL_INPUT_NAMESPACE + "/")
            )
            if colliding:
                raise DeclaredInputRefusal(
                    baseline_declarations[0], "namespace_collision",
                    f"the subject repository tracks {colliding[0]!r} at {label}, which "
                    f"would collide with the projected evidence namespace",
                    records=records,
                )
    return resolved, records


def external_input_manifest(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the verifier-visible manifest for projected external evidence (R4).

    Deliberately a *sanitized* view of the same rows the parent records: the
    declaration string and the source repository's filesystem location are dropped,
    because neither is needed to tell a projection from native subject-repository
    content, and a host path in the surface is exactly what this mechanism must
    never hand a verifier.
    """
    return {
        "schema_version": "1.0.0",
        "namespace": EXTERNAL_INPUT_NAMESPACE,
        "note": (
            "Files under this namespace are byte-exact projections of tracked, "
            "committed content from another repository, declared in advance by "
            "this spec's context.required_inputs and identical at both verifier "
            "arms. They are not part of the subject repository under verification."
        ),
        "inputs": [
            {
                key: value for key, value in record.items()
                if key not in {"declaration", "source_repository"}
            }
            for record in records
            if record.get("handling") == "admitted"
        ],
    }


def declared_preflight_proofs(spec_text: str) -> list[str]:
    """Return the ``preflight-proof:`` declarations in ``context.required_inputs``."""
    return [
        item for item in spec_required_inputs(spec_text)
        if item.startswith(PREFLIGHT_PROOF_PREFIX)
    ]


def resolve_declared_preflight_proofs(
    source_repository: Path, *, baseline_ref: str, head_ref: str, spec_path: str | None,
) -> list[str]:
    """Return the spec's preflight-proof declarations, identical at both arms (R2).

    Same rule as external evidence: a candidate that adds, changes, or removes the
    declaration during its own run gains no evidence authority, so a disagreement
    between the arms is refused before any surface exists.
    """
    if spec_path is None:
        return []
    normalized = _normalise_repo_path(spec_path)
    baseline = declared_preflight_proofs(
        _blob_text_at_ref(source_repository, baseline_ref, normalized) or ""
    )
    head = declared_preflight_proofs(
        _blob_text_at_ref(source_repository, head_ref, normalized) or ""
    )
    if baseline != head:
        raise DeclaredInputRefusal(
            json.dumps({"baseline": baseline, "head": head}, sort_keys=True),
            "declaration_not_identical",
            f"preflight-proof declarations in {normalized} differ between the verifier "
            "arms; a candidate may not change its own spec's declared proof",
        )
    return baseline


def _contained_retained_path(source_repository: Path, raw_path: str) -> tuple[str, Path] | None:
    """Return a project-relative path and file for a declared retained result.

    None unless the path is relative, free of traversal, and neither it nor any
    parent is a symlink, so the parent never reads outside the source repository.
    """
    if not raw_path or PurePosixPath(raw_path.replace("\\", "/")).is_absolute():
        return None
    try:
        relative = _normalise_repo_path(raw_path)
    except ValueError:
        return None
    root = source_repository.resolve()
    parts = PurePosixPath(relative).parts
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            return None
    if not _within_surface(current.resolve(), root):
        return None
    return relative, current


def resolve_preflight_proof(
    source_repository: Path, declarations: list[str], *, reference_sha256: str | None,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Build the sanitized proof document for one declared retained preflight result.

    Returns ``(document, evidence_record, projected_bytes)``. Only a closed,
    parsed projection ever leaves this function (never the retained bytes, a host
    path, or the raw candidate revision), and a proof that cannot be established
    is *reported* with a stable reason rather than refused, so the verifier can
    answer ``unverifiable`` (R4). ``reference_sha256`` is the digest the parent
    recorded for the retained result out of band; the author's own summary is not
    a reference, and without one the result is unverifiable.
    """
    retrieval = "ok"
    declared_path: str | None = None
    result_digest: str | None = None
    projection: dict[str, Any] | None = None
    bound_digest: str | None = None
    if len(declarations) != 1:
        retrieval = "declaration_invalid"
    else:
        contained = _contained_retained_path(
            source_repository, declarations[0][len(PREFLIGHT_PROOF_PREFIX):].strip()
        )
        if contained is None:
            retrieval = "path_not_contained"
        else:
            declared_path, target = contained
            if not target.is_file():
                retrieval = "missing"
            elif target.stat().st_size > PREFLIGHT_PROOF_MAX_BYTES:
                retrieval = "malformed"
            else:
                body = target.read_bytes()
                observed = hashlib.sha256(body).hexdigest()
                if reference_sha256 is None:
                    retrieval = "no_reference_digest"
                elif observed != reference_sha256:
                    retrieval = "digest_mismatch"
                else:
                    try:
                        if _preflight_projection is None:
                            raise ValueError("preflight projection is unavailable")
                        projection = _preflight_projection(
                            json.loads(body.decode("utf-8")), result_sha256=observed
                        )
                        result_digest = observed
                        head = projection.pop("repository_head", None)
                        bound_digest = candidate_revision_digest(head) if head else None
                    except (ValueError, UnicodeDecodeError):
                        retrieval, projection, result_digest = "malformed", None, None
    document = {
        "schema_version": PREFLIGHT_PROOF_SCHEMA_VERSION,
        "retrieval": retrieval,
        "result_sha256": result_digest,
        "projection": projection,
        "bound_candidate_revision_digest": bound_digest,
    }
    body_out = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    projected_path = f"{PREFLIGHT_PROOF_NAMESPACE}/{PREFLIGHT_PROOF_FILE}"
    record = {
        "kind": "preflight-proof",
        "declared_path": declared_path,
        "retrieval": retrieval,
        "reference_sha256": reference_sha256,
        "result_sha256": result_digest,
        "bound_candidate_revision_digest": bound_digest,
        "projected_path": projected_path,
        "projected_sha256": hashlib.sha256(body_out).hexdigest(),
    }
    return document, record, body_out


def verify_preflight_proof(
    proof: Any, *, expected_candidate_revision_digest: str,
) -> dict[str, Any]:
    """Judge one projected proof document for the verifier (R3/R4).

    Trusts nothing but the closed document: its shape, its digest consistency,
    its binding to the expected candidate digest, and the ``ok``, installation
    admission and declared-test outcomes recorded in it. Anything missing,
    foreign or contradictory is ``unverifiable`` with every applicable reason.
    """
    def unverifiable(*reasons: str) -> dict[str, Any]:
        return {"result": "unverifiable", "reasons": list(reasons)}

    if not isinstance(proof, dict) or set(proof) != PREFLIGHT_PROOF_KEYS:
        return unverifiable("malformed")
    if proof["schema_version"] != PREFLIGHT_PROOF_SCHEMA_VERSION:
        return unverifiable("malformed")
    retrieval = proof["retrieval"]
    if retrieval not in PREFLIGHT_PROOF_RETRIEVALS:
        return unverifiable("malformed")
    if retrieval != "ok":
        return unverifiable(retrieval)
    projection = proof["projection"]
    if (
        not isinstance(projection, dict)
        or set(projection) != PREFLIGHT_PROJECTION_KEYS
        or not isinstance(proof["result_sha256"], str)
        or projection["result_sha256"] != proof["result_sha256"]
        or not isinstance(projection["install_admission"], dict)
        or not isinstance(projection["declared_test"], dict)
    ):
        return unverifiable("malformed")
    reasons: list[str] = []
    bound = proof["bound_candidate_revision_digest"]
    if bound is None:
        reasons.append("unbound")
    elif bound != expected_candidate_revision_digest:
        reasons.append("wrong_candidate")
    if projection["ok"] is not True or projection["blocking_failure_count"] != 0:
        reasons.append("not_ok")
    admission = projection["install_admission"]
    coverage = admission.get("coverage")
    covered = (
        isinstance(coverage, dict)
        and isinstance(coverage.get("applicable"), int)
        and coverage["applicable"] > 0
        and coverage.get("checked") == coverage["applicable"]
        and coverage.get("failed") == 0
    )
    if admission.get("ok") is not True or admission.get("admission") != "allow" or not covered:
        reasons.append("admission_not_allowed")
    test = projection["declared_test"]
    if test.get("configured") is not True or test.get("skipped") is not False or test.get("exit") != 0:
        reasons.append("test_not_passed")
    if admission.get("invocation_id") is None or admission.get("artifact_sha256") is None:
        reasons.append("invocation_unidentified")
    if reasons:
        return unverifiable(*reasons)
    return {"result": "verified", "reasons": []}


def check_projected_preflight_proof(
    surface_root: Path, *, expected_candidate_revision_digest: str,
) -> dict[str, Any]:
    """Read the projected proof from one verifier arm and judge it (R3)."""
    target = Path(surface_root) / PREFLIGHT_PROOF_NAMESPACE / PREFLIGHT_PROOF_FILE
    if target.is_symlink() or not target.is_file():
        return {"result": "unverifiable", "reasons": ["missing"]}
    try:
        proof = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"result": "unverifiable", "reasons": ["malformed"]}
    return verify_preflight_proof(
        proof, expected_candidate_revision_digest=expected_candidate_revision_digest
    )


def _project_preflight_proof(destination: Path, body: bytes) -> list[str]:
    """Write the proof document into one materialized arm snapshot (R2)."""
    relative = f"{PREFLIGHT_PROOF_NAMESPACE}/{PREFLIGHT_PROOF_FILE}"
    target = destination / relative
    if target.exists():
        raise ValueError(f"projected preflight proof collides inside the surface: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _within_surface(target.resolve(), destination.resolve()):
        raise ValueError(f"projected preflight proof resolves outside the surface: {relative}")
    target.write_bytes(body)
    target.chmod(0o644)
    return [relative]


# SPEC-391: a spec may declare, in its own frontmatter, a bounded projection of
# same-spec report-only artifacts the verifier needs but may not read. Only the
# declared JSON fields -- never the blob -- reach the verifier, each document
# bound to the exact candidate and baseline revisions and to the source blob
# digests. A spec that declares nothing is untouched.
EVIDENCE_PROJECTION_KEY = "verifier_evidence_projection"
EVIDENCE_PROJECTION_NAMESPACE = ".nightshift-verifier-evidence"
EVIDENCE_PROJECTION_FILE = "evidence-projection.json"
EVIDENCE_PROJECTION_SCHEMA_VERSION = "1.0.0"
EVIDENCE_MAX_ARTIFACTS = 8
EVIDENCE_MAX_FIELDS = 32
EVIDENCE_MAX_SOURCE_BYTES = 1024 * 1024
EVIDENCE_MAX_ITEMS = 256
EVIDENCE_MAX_STRING = 512
EVIDENCE_MAX_DOCUMENT_BYTES = 256 * 1024
EVIDENCE_DOCUMENT_KEYS = frozenset({
    "schema_version", "candidate_revision_digest", "baseline_revision_digest", "entries",
})
EVIDENCE_ENTRY_KEYS = frozenset({
    "path", "retrieval", "head_sha256", "baseline_sha256", "declared_fields", "fields",
})
EVIDENCE_RETRIEVALS = frozenset({"ok", "missing", "malformed", "field_missing", "overbroad"})
# A field naming an author conclusion is never projected: the verifier derives
# its own outcome from facts, not from the author's pass/fail.
EVIDENCE_CONCLUSION_TOKENS = frozenset({
    "pass", "passed", "passes", "fail", "failed", "fails", "failure", "failures", "verdict",
    "conclusion", "conclusions", "summary", "result", "results", "status", "ok", "success",
    "succeeded", "approved", "approval", "assessment", "outcome", "satisfied", "green",
    "secret", "token", "password", "credential", "credentials", "log", "logs", "stdout",
    "stderr", "output",
})
_EVIDENCE_SEGMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}(\[\*\])?")
_EVIDENCE_HOST_PATH_RE = re.compile(
    r"(?:^|[\s\"'=(])(?:/(?:Users|home|private|var|tmp|etc|opt|root)\b|[A-Za-z]:[\\/]|~/)"
)
_EVIDENCE_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _evidence_tokens(segment: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", segment.replace("[*]", ""))
    return {part for part in _EVIDENCE_TOKEN_SPLIT_RE.split(spaced.lower()) if part}


def declared_evidence_projection(spec_text: str) -> list[dict[str, Any]] | None:
    """Return the spec's ``verifier_evidence_projection`` declaration, or None when absent.

    Same small hand-reader as :func:`spec_required_inputs` (no YAML dependency in
    installs), but a declaration that is present and unreadable raises ValueError so
    the dispatch fails closed instead of silently granting nothing.
    """
    lines = _spec_frontmatter(spec_text).splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.rstrip() == f"{EVIDENCE_PROJECTION_KEY}:"),
        None,
    )
    if start is None:
        return None
    items: list[dict[str, Any]] = []
    collecting = False
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith((" ", "\t")):
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if collecting and stripped.startswith("- ") and not stripped.startswith("- path:"):
            items[-1]["fields"].append(_unquote_yaml_scalar(stripped[2:]))
            continue
        collecting = False
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
            items.append({"path": None, "fields": []})
        if not items:
            raise ValueError("projection entry must start with '- path:'")
        key, sep, value = stripped.partition(":")
        value = value.strip()
        if not sep or key not in {"path", "fields"}:
            raise ValueError(f"unsupported projection key: {key!r}")
        if key == "path":
            if items[-1]["path"] is not None or not value:
                raise ValueError("projection entry needs exactly one path")
            items[-1]["path"] = _unquote_yaml_scalar(value)
        elif value.startswith("[") and value.endswith("]"):
            items[-1]["fields"].extend(
                _unquote_yaml_scalar(part) for part in value[1:-1].split(",") if part.strip()
            )
        elif not value:
            collecting = True
        else:
            raise ValueError("projection fields must be a list")
    if not items or any(item["path"] is None or not item["fields"] for item in items):
        raise ValueError("projection declaration is empty or incomplete")
    return items


def _validate_evidence_declaration(items: list[dict[str, Any]], withheld: set[str]) -> list[dict[str, Any]]:
    """Refuse an overbroad or undeclared projection before any surface exists."""
    def refuse(reason: str, detail: str) -> DeclaredInputRefusal:
        return _refuse(json.dumps(items, sort_keys=True), reason, detail)

    if len(items) > EVIDENCE_MAX_ARTIFACTS:
        raise refuse("projection_overbroad", f"more than {EVIDENCE_MAX_ARTIFACTS} artifacts")
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        try:
            path = _normalise_repo_path(item["path"])
        except ValueError as error:
            raise refuse("projection_path_invalid", str(error)) from error
        if not path.endswith(".json"):
            raise refuse("projection_path_not_json", f"{path} is not a JSON artifact")
        if path in seen:
            raise refuse("declaration_invalid", f"{path} is declared twice")
        seen.add(path)
        if path not in withheld:
            raise refuse(
                "projection_path_not_withheld",
                f"{path} is not a withheld same-spec report; nothing to project",
            )
        if len(item["fields"]) > EVIDENCE_MAX_FIELDS or len(set(item["fields"])) != len(item["fields"]):
            raise refuse("projection_overbroad", f"{path} declares too many or repeated fields")
        for selector in item["fields"]:
            segments = selector.split(".")
            if (
                len(segments) > 6
                or not all(_EVIDENCE_SEGMENT_RE.fullmatch(segment) for segment in segments)
            ):
                raise refuse("projection_selector_invalid", f"{path}: {selector!r}")
            denied = set().union(*(_evidence_tokens(segment) for segment in segments)) & EVIDENCE_CONCLUSION_TOKENS
            if denied:
                raise refuse(
                    "projection_selector_denied",
                    f"{path}: {selector!r} names {sorted(denied)}; conclusions, logs and secrets are never projected",
                )
        checked.append({"path": path, "fields": list(item["fields"])})
    return checked


class _FieldMissing(Exception):
    pass


def _select_evidence_field(value: Any, segments: list[str]) -> Any:
    segment, rest = segments[0], segments[1:]
    wildcard = segment.endswith("[*]")
    key = segment[:-3] if wildcard else segment
    if not isinstance(value, dict) or key not in value:
        raise _FieldMissing(segment)
    value = value[key]
    if wildcard:
        if not isinstance(value, list):
            raise _FieldMissing(segment)
        if len(value) > EVIDENCE_MAX_ITEMS:
            raise ValueError("too many items")
        return [_select_evidence_field(item, rest) if rest else item for item in value]
    return _select_evidence_field(value, rest) if rest else value


def _evidence_leaf_ok(value: Any) -> bool:
    if isinstance(value, list):
        return len(value) <= EVIDENCE_MAX_ITEMS and all(_evidence_leaf_ok(item) for item in value)
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return value == value and abs(value) != float("inf")
    return (
        isinstance(value, str)
        and len(value) <= EVIDENCE_MAX_STRING
        and _EVIDENCE_HOST_PATH_RE.search(value) is None
    )


def _evidence_entry(path: str, fields: list[str], head_body: bytes | None, baseline_body: bytes | None) -> dict[str, Any]:
    """Project one artifact: closed shape, scalar leaves only, never the blob itself."""
    entry: dict[str, Any] = {
        "path": path, "retrieval": "ok",
        "head_sha256": hashlib.sha256(head_body).hexdigest() if head_body is not None else None,
        "baseline_sha256": hashlib.sha256(baseline_body).hexdigest() if baseline_body is not None else None,
        "declared_fields": list(fields), "fields": {},
    }
    if head_body is None:
        entry["retrieval"] = "missing"
        return entry
    if len(head_body) > EVIDENCE_MAX_SOURCE_BYTES:
        entry["retrieval"] = "overbroad"
        return entry
    try:
        data = json.loads(head_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        entry["retrieval"] = "malformed"
        return entry
    projected: dict[str, Any] = {}
    for selector in fields:
        try:
            value = _select_evidence_field(data, selector.split("."))
        except _FieldMissing:
            entry["retrieval"] = "field_missing"
            return entry
        except ValueError:
            entry["retrieval"] = "overbroad"
            return entry
        if not _evidence_leaf_ok(value):
            entry["retrieval"] = "overbroad"
            return entry
        projected[selector] = value
    entry["fields"] = projected
    return entry


def _git_blob_or_none(repository: Path, ref: str, path: str) -> bytes | None:
    probe = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "-t", f"{ref}:{path}"],
        capture_output=True, check=False, env=_git_environment(),
    )
    if probe.returncode or probe.stdout.decode("ascii", "replace").strip() != "blob":
        return None
    return _git_bytes(repository, "cat-file", "blob", f"{ref}:{path}")


def resolve_evidence_projection(
    source_repository: Path, *, baseline_ref: str, head_ref: str, spec_path: str | None,
    withheld_paths: Any,
) -> tuple[dict[str, Any], dict[str, Any], bytes] | None:
    """Build the sanitized evidence document for a declared report-only projection.

    None when the spec declares nothing (the unchanged dispatch). The declaration is
    read at both arms and must be identical, so a candidate cannot widen its own
    evidence. *withheld_paths* is a callable returning the set the surface withholds;
    a declared path outside it is refused. Sources are the committed blobs at the
    exact refs -- never the working tree -- so the document is bound to the candidate.
    """
    if spec_path is None:
        return None
    normalized = _normalise_repo_path(spec_path)
    parsed: dict[str, list[dict[str, Any]] | None] = {}
    for label, ref in (("baseline", baseline_ref), ("head", head_ref)):
        try:
            parsed[label] = declared_evidence_projection(
                _blob_text_at_ref(source_repository, ref, normalized) or ""
            )
        except ValueError as error:
            raise _refuse(EVIDENCE_PROJECTION_KEY, "declaration_invalid", str(error)) from error
    if parsed["baseline"] != parsed["head"]:
        raise _refuse(
            EVIDENCE_PROJECTION_KEY, "declaration_not_identical",
            f"{EVIDENCE_PROJECTION_KEY} in {normalized} differs between the verifier arms; "
            "a candidate may not change its own spec's declared evidence",
        )
    if parsed["head"] is None:
        return None
    declarations = _validate_evidence_declaration(parsed["head"], set(withheld_paths()))
    candidate = candidate_revision_digest(
        _run_git(source_repository, "rev-parse", "--verify", f"{head_ref}^{{commit}}").strip()
    )
    baseline = candidate_revision_digest(
        _run_git(source_repository, "rev-parse", "--verify", f"{baseline_ref}^{{commit}}").strip()
    )
    entries = [
        _evidence_entry(
            item["path"], item["fields"],
            _git_blob_or_none(source_repository, head_ref, item["path"]),
            _git_blob_or_none(source_repository, baseline_ref, item["path"]),
        )
        for item in declarations
    ]
    document = {
        "schema_version": EVIDENCE_PROJECTION_SCHEMA_VERSION,
        "candidate_revision_digest": candidate,
        "baseline_revision_digest": baseline,
        "entries": entries,
    }
    body = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(body) > EVIDENCE_MAX_DOCUMENT_BYTES:
        raise _refuse(EVIDENCE_PROJECTION_KEY, "projection_overbroad", "projected document exceeds its cap")
    record = {
        "kind": "evidence-projection",
        "declared": declarations,
        "candidate_revision_digest": candidate,
        "baseline_revision_digest": baseline,
        "entries": [
            {key: entry[key] for key in ("path", "retrieval", "head_sha256", "baseline_sha256")}
            for entry in entries
        ],
        "projected_path": f"{EVIDENCE_PROJECTION_NAMESPACE}/{EVIDENCE_PROJECTION_FILE}",
        "projected_sha256": hashlib.sha256(body).hexdigest(),
    }
    return document, record, body


def verify_evidence_projection(
    document: Any, *, expected_candidate_revision_digest: str,
) -> dict[str, Any]:
    """Judge one projected evidence document for the verifier (SPEC-391 R2/R3).

    Generic and closed: shape, binding to the expected candidate, per-artifact
    retrieval, declared-vs-projected field equality, and a re-scan for conclusion
    names and private paths. Anything missing, foreign or contradictory is
    ``unverifiable`` with every applicable reason. What the facts *mean* is the
    verifier's own independent check, not this function's.
    """
    def unverifiable(*reasons: str) -> dict[str, Any]:
        return {"result": "unverifiable", "reasons": sorted(set(reasons))}

    if (
        not isinstance(document, dict) or set(document) != EVIDENCE_DOCUMENT_KEYS
        or document["schema_version"] != EVIDENCE_PROJECTION_SCHEMA_VERSION
        or not isinstance(document["entries"], list) or not document["entries"]
    ):
        return unverifiable("malformed")
    reasons: list[str] = []
    for key in ("candidate_revision_digest", "baseline_revision_digest"):
        if not isinstance(document[key], str) or not SHA256_HEX_RE.fullmatch(document[key]):
            return unverifiable("malformed")
    if document["candidate_revision_digest"] != expected_candidate_revision_digest:
        reasons.append("wrong_candidate")
    for entry in document["entries"]:
        if (
            not isinstance(entry, dict) or set(entry) != EVIDENCE_ENTRY_KEYS
            or entry["retrieval"] not in EVIDENCE_RETRIEVALS
            or not isinstance(entry["fields"], dict)
            or not isinstance(entry["declared_fields"], list)
        ):
            return unverifiable("malformed")
        if entry["retrieval"] != "ok":
            reasons.append(entry["retrieval"])
            continue
        if not isinstance(entry["head_sha256"], str) or not SHA256_HEX_RE.fullmatch(entry["head_sha256"]):
            reasons.append("unbound")
        if sorted(entry["fields"]) != sorted(entry["declared_fields"]):
            reasons.append("fields_mismatch")
        if any(_evidence_tokens(name) & EVIDENCE_CONCLUSION_TOKENS for name in entry["fields"]):
            reasons.append("conclusion_field")
        if not all(_evidence_leaf_ok(value) for value in entry["fields"].values()):
            reasons.append("overbroad")
    return unverifiable(*reasons) if reasons else {"result": "verified", "reasons": []}


def check_projected_evidence(
    surface_root: Path, *, expected_candidate_revision_digest: str,
) -> dict[str, Any]:
    """Read the projected evidence from one verifier arm and judge it."""
    target = Path(surface_root) / EVIDENCE_PROJECTION_NAMESPACE / EVIDENCE_PROJECTION_FILE
    if target.is_symlink() or not target.is_file():
        return {"result": "unverifiable", "reasons": ["missing"]}
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"result": "unverifiable", "reasons": ["malformed"]}
    return verify_evidence_projection(
        document, expected_candidate_revision_digest=expected_candidate_revision_digest
    )


def _project_evidence_projection(destination: Path, body: bytes) -> list[str]:
    """Write the evidence document into one materialized arm snapshot."""
    relative = f"{EVIDENCE_PROJECTION_NAMESPACE}/{EVIDENCE_PROJECTION_FILE}"
    target = destination / relative
    if target.exists():
        raise ValueError(f"projected evidence collides inside the surface: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _within_surface(target.resolve(), destination.resolve()):
        raise ValueError(f"projected evidence resolves outside the surface: {relative}")
    target.write_bytes(body)
    target.chmod(0o644)
    return [relative]


def _withheld_report_paths(
    report_paths: Iterable[str], baseline_objects: dict[str, str], head_objects: dict[str, str],
    same_spec_reports: Iterable[str], same_spec_metrics: Iterable[str],
) -> set[str]:
    """Every path the surface withholds: the complement of the retained-report rule."""
    changed = {
        path for path in {*baseline_objects, *head_objects}
        if baseline_objects.get(path) != head_objects.get(path)
    }
    return {*report_paths, *same_spec_reports, *same_spec_metrics, *changed}


def _checker_provenance(surface_repositories: dict[str, Any]) -> dict[str, Any]:
    baseline_checker = _arm_checker_bytes(surface_repositories.get("baseline"))
    head_checker = _arm_checker_bytes(surface_repositories.get("head"))
    return {
        "checker_provenance": "baseline_arm" if baseline_checker is not None else "installed",
        "candidate_changed_checker": baseline_checker != head_checker,
    }


def _project_external_inputs(
    destination: Path, resolved: Iterable[ResolvedExternalInput],
    records: list[dict[str, Any]],
) -> list[str]:
    """Write the projected evidence into one materialized arm snapshot (R2).

    Only regular files are ever created, always beneath *destination*, and each
    target is re-checked against the surface root after its parents exist. Nothing
    here can produce a link the verifier could follow out of the surface.
    """
    items = list(resolved)
    if not items:
        return []
    surface_root = destination.resolve()
    written: list[str] = []
    for item in items:
        for projected in item.files:
            target = destination / projected.path
            if target.exists():
                raise ValueError(
                    f"projected external input collides inside the surface: {projected.path}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            if not _within_surface(target.resolve(), surface_root):
                raise ValueError(
                    f"projected external input resolves outside the verifier surface: "
                    f"{projected.path}"
                )
            target.write_bytes(projected.body)
            target.chmod(0o644)
            written.append(projected.path)
    manifest = destination / EXTERNAL_INPUT_NAMESPACE / EXTERNAL_INPUT_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(external_input_manifest(records), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest.chmod(0o644)
    written.append(f"{EXTERNAL_INPUT_NAMESPACE}/{EXTERNAL_INPUT_MANIFEST}")
    return sorted(written)


def _seal_projected_inputs(roots: Iterable[Path], projected_paths: Iterable[str]) -> None:
    """Make every projection read-only in every materialized location (AC2).

    Runs last, after both arm working directories exist, so no snapshot rebuild
    ever has to clear a read-only file. Git records only the executable bit, so
    dropping write permission leaves both arms byte- and status-clean.
    """
    paths = list(projected_paths)
    for root in roots:
        for relative in paths:
            candidate = root / relative
            if candidate.is_file() and not candidate.is_symlink():
                candidate.chmod(0o444)


def _clear_snapshot(destination: Path) -> None:
    for child in destination.iterdir():
        if child.name == ".git":
            continue
        if child.is_symlink() or child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def _within_surface(candidate: Path, destination: Path) -> bool:
    """True when *candidate* is *destination* itself or lives beneath it."""
    try:
        return Path(os.path.commonpath((destination, candidate))) == destination
    except ValueError:
        # Unrelated roots (or a relative/absolute mix) share no common path.
        return False


def _materialize_symlink(
    link: str, *, target: Path, destination: Path, path: str
) -> dict[str, str] | None:
    """Materialize one tracked symlink into the surface, or refuse it (SPEC-285).

    Three cases, and the distinction the previous single check could not draw:

    * **Relative link text.** Resolved against the entry's own parent inside the
      surface. This is the traversal the containment guard exists for, so a
      resolution outside *destination* is still refused — fail-closed, with the
      path and the link text named (R2/R5).
    * **Absolute link text landing inside the surface.** Kept as a symlink; it
      is already contained.
    * **Absolute link text landing outside the surface.** Not a traversal
      attempt but ordinary out-of-repo content — Argo Home's tracked
      ``AGENTS.md -> ~/.claude/CLAUDE.md`` is the motivating case. Materialized
      as a regular file holding the link text: the entry stays visible and the
      verifier can see what it pointed at, while a plain file cannot be followed
      anywhere, so containment holds trivially (R1/R3/R4).

    ``(target.parent / link)`` is deliberately *not* used for an absolute link:
    pathlib discards the left operand for an absolute right-hand side, which is
    exactly how the old check came to reject every absolute target.

    Returns the containment-evidence record for a transformed entry, or ``None``
    when the entry was materialized as an ordinary symlink.
    """
    if not link:
        raise ValueError(
            f"unrepresentable tracked symlink for verifier surface: {path} "
            f"(empty link target)"
        )
    if PurePosixPath(link).is_absolute():
        if _within_surface(Path(link).resolve(), destination):
            target.symlink_to(link)
            return None
        target.write_bytes(link.encode("utf-8", "surrogateescape"))
        target.chmod(0o644)
        return {"path": path, "target": link, "handling": "link-text-file"}
    if not _within_surface((target.parent / link).resolve(), destination):
        raise ValueError(
            f"relative tracked symlink traverses out of the verifier surface: "
            f"{path} -> {link} (resolves outside the surface destination)"
        )
    target.symlink_to(link)
    return None


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


_LINK_TOKEN_RE = re.compile(r"[^\s()<>\"'`\[\]{},;|]+")


def _referenced_placeholder_paths(
    source_repository: Path,
    ref: str,
    *,
    candidates: Iterable[str],
    report_paths: Iterable[str],
    retained_report_paths: Iterable[str],
    same_spec_metrics_paths: Iterable[str],
) -> set[str]:
    """Return the withheld *candidates* that this arm's retained text refers to (SPEC-398).

    A placeholder exists to keep a retained document's link to a withheld report
    resolvable. A candidate is therefore given one only when it is tracked in this
    arm's own tree *and* some file that survives into the arm names it, either as a
    relative link that resolves to it (or as its exact repo-root-relative path). A candidate nothing
    refers to stays fully absent and unreachable, exactly as before. The scan is the
    same one the dispatch gate recomputes from the source.
    """
    wanted = set(candidates)
    if not wanted:
        return set()
    retained = set(retained_report_paths)
    same_spec_metrics = set(same_spec_metrics_paths)
    present: set[str] = set()
    scannable: dict[str, str] = {}
    for raw in _git_bytes(source_repository, "ls-tree", "-rz", ref).split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        path = _normalise_repo_path(raw_path.decode("utf-8", "surrogateescape"))
        if kind != "blob":
            continue
        if path in same_spec_metrics:
            continue
        if path in wanted and path not in retained:
            present.add(path)
            continue
        if is_verifier_report_path(path, explicit=report_paths) and path not in retained:
            continue
        if mode in {"100644", "100755"}:
            scannable[path] = object_id
    if not present:
        return set()
    bodies = _git_batch_blobs(source_repository, scannable.values())
    referenced: set[str] = set()
    for path, object_id in sorted(scannable.items()):
        try:
            text = bodies[object_id].decode("utf-8")
        except UnicodeDecodeError:
            continue
        directory = str(PurePosixPath(path).parent)
        for token in _LINK_TOKEN_RE.findall(text):
            if "/" not in token:
                continue
            target = token.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            try:
                resolved = _normalise_repo_path(
                    os.path.normpath(os.path.join(directory, target))
                )
            except ValueError:
                resolved = ""
            if resolved in present:
                referenced.add(resolved)
            elif target in present:
                referenced.add(target)
    return referenced


def _materialize_ref(
    source_repository: Path,
    destination: Path,
    ref: str,
    *,
    report_paths: Iterable[str],
    retained_report_paths: Iterable[str] = (),
    same_spec_metrics_paths: Iterable[str] = (),
    placeholder_paths: Iterable[str] = (),
    placeholders_written: list[str] | None = None,
) -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Materialize one tracked snapshot without sharing the source object DB.

    Returns the withheld paths, the per-entry record of every tracked symlink
    materialized as something other than a symlink (SPEC-285), and every path
    actually written to *destination* from the source ref's tracked tree (SPEC-342).
    The withheld-paths list and the materialized-paths list are kept apart
    deliberately: a withheld path must be *unreachable* from the surface, while a
    materialized entry is present on disk and must survive into the arm's commit
    even if the destination's own (also source-tracked) ``.gitignore`` would
    otherwise cause a plain ``git add -A`` to skip it -- a source-tracked file
    that also matches an ignore pattern (e.g. a force-added, intentionally
    retained report) must still end up in the commit with identical bytes.
    """
    _clear_snapshot(destination)
    surface_root = destination.resolve()
    excluded: list[str] = []
    transformed: list[dict[str, str]] = []
    materialized: list[str] = []
    placeholders: list[str] = []
    placeholder_set = _referenced_placeholder_paths(
        source_repository, ref,
        candidates=placeholder_paths,
        report_paths=report_paths,
        retained_report_paths=retained_report_paths,
        same_spec_metrics_paths=same_spec_metrics_paths,
    )
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
            if path in placeholder_set and kind == "blob":
                # SPEC-398: only because the withheld path exists in this arm's
                # own tree. The withheld blob is never read here.
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(PLACEHOLDER_REPORT_BODY.encode("utf-8"))
                target.chmod(0o644)
                placeholders.append(path)
                materialized.append(path)
            continue
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise ValueError(f"unsupported tracked entry for verifier surface: {path} ({mode} {kind})")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _git_bytes(source_repository, "cat-file", "blob", object_id)
        if mode == "120000":
            record = _materialize_symlink(
                body.decode("utf-8", "surrogateescape"),
                target=target, destination=surface_root, path=path,
            )
            if record is not None:
                transformed.append(record)
        else:
            target.write_bytes(body)
            target.chmod(0o755 if mode == "100755" else 0o644)
        materialized.append(path)
    if placeholders_written is not None:
        placeholders_written.extend(sorted(placeholders))
    return sorted(excluded), sorted(transformed, key=lambda record: record["path"]), sorted(materialized)


def _placeholder_intact(repository: Path, ref: str, path: str) -> bool:
    """True when *path* at *ref* holds exactly the fixed placeholder body (SPEC-398)."""
    probe = subprocess.run(
        ["git", "-C", str(repository), "show", f"{ref}:{path}"],
        capture_output=True, check=False, env=_git_environment(),
    )
    return probe.returncode == 0 and probe.stdout == PLACEHOLDER_REPORT_BODY.encode("utf-8")


# ---- SPEC-NS-KIT-002-005: contractual spec projection (R1/R1a/R1b)

SPEC_PROJECTION_MARKER = "<!-- nightshift-verifier-projection: contractual sections only -->"
SPEC_PROOF_SECTIONS = ("Requirements", "Acceptance Criteria")
SPEC_CONTRACT_SECTIONS = (*SPEC_PROOF_SECTIONS, "Out of Scope")
_CHECKBOX_LINE_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)\[([xX ])\]((?:\s.*)?)$")


class SpecProjectionError(ValueError):
    """The verifier's spec copy could not be proven to keep the contract text."""


def _neutralise_checkboxes(text: str) -> str:
    return "\n".join(
        f"{m.group(1)}[ ]{m.group(3)}" if (m := _CHECKBOX_LINE_RE.match(line)) else line
        for line in text.split("\n")
    )


def _spec_section(text: str, heading: str) -> str | None:
    start = re.search(r"(?m)^## " + re.escape(heading) + r"[ \t]*$", text)
    if start is None:
        return None
    following = re.search(r"(?m)^## ", text[start.end():])
    end = start.end() + following.start() if following else len(text)
    return text[start.start():end].rstrip("\n")


def _same_apart_from_checkbox_state(original: str, projected: str) -> bool:
    """True when the two texts differ only by checkbox markers, the projected one unticked."""
    left, right = original.split("\n"), projected.split("\n")
    if len(left) != len(right):
        return False
    for before, after in zip(left, right):
        if before == after:
            continue
        a, b = _CHECKBOX_LINE_RE.match(before), _CHECKBOX_LINE_RE.match(after)
        if not (a and b and a.group(1) == b.group(1) and a.group(3) == b.group(3) and b.group(2) == " "):
            return False
    return True


def _prove_contract_unchanged(original: str, projected: str) -> None:
    for heading in SPEC_PROOF_SECTIONS:
        before, after = _spec_section(original, heading), _spec_section(projected, heading)
        if before is None:
            if after is not None:
                raise SpecProjectionError(f"projection invented section {heading!r}")
            continue
        if after is None or not _same_apart_from_checkbox_state(before, after):
            raise SpecProjectionError(f"projection alters the {heading!r} text")


def _spec_scope_block(frontmatter_lines: list[str]) -> list[str]:
    for index, line in enumerate(frontmatter_lines):
        if line.rstrip() == "scope:":
            end = index + 1
            while end < len(frontmatter_lines) and (
                not frontmatter_lines[end].strip() or frontmatter_lines[end].startswith((" ", "\t"))
            ):
                end += 1
            return [item for item in frontmatter_lines[index:end] if item.strip()]
    return []


class _AttemptNames:
    """Neutral, indexed placeholders for withheld earlier-attempt artifact names (R1a)."""

    def __init__(self, names: Iterable[str]) -> None:
        self._names = sorted({name for name in names if name}, key=lambda item: (-len(item), item))
        self.used: dict[str, str] = {}

    def _pattern(self, name: str) -> re.Pattern[str]:
        return re.compile(r"(?<![\w./*-])" + re.escape(name) + r"(?![\w/*-]|\.\w)")

    def mentions(self, text: str) -> list[str]:
        return sorted(name for name in self._names if self._pattern(name).search(text))

    def replace(self, text: str) -> str:
        for name in self._names:
            def token(_match: re.Match[str], name: str = name) -> str:
                return self.used.setdefault(name, f"<earlier-attempt-artifact-{len(self.used) + 1}>")
            text = self._pattern(name).sub(token, text)
        return text

    def records(self) -> list[dict[str, str]]:
        return sorted(
            ({"placeholder": value, "name": name} for name, value in self.used.items()),
            key=lambda item: item["placeholder"],
        )


def _scope_summary(block: list[str]) -> str | None:
    entries: list[str] = []
    key: str | None = None
    items: list[str] = []

    def flush() -> None:
        if key is not None and items:
            entries.append(f"{key}: " + ", ".join(items))

    for line in block[1:]:
        header = re.match(r"^\s+([A-Za-z_]+):\s*(.*)$", line)
        if header:
            flush()
            key, items = header.group(1), []
            value = header.group(2).strip()
            if value.startswith("[") and value.endswith("]"):
                items.extend(_unquote_yaml_scalar(part) for part in value[1:-1].split(",") if part.strip())
            elif value:
                items.append(_unquote_yaml_scalar(value))
            continue
        item = re.match(r"^\s*-\s+(.*?)\s*$", line)
        if item and key is not None:
            items.append(_unquote_yaml_scalar(item.group(1)))
    flush()
    return "; ".join(entries) or None


def project_spec_for_verifier(
    spec_text: str, *, withheld_names: Iterable[str] = (),
) -> tuple[str, dict[str, Any]]:
    """The verifier's spec copy: contractual sections only, checkboxes neutralised.

    Keeps the frontmatter ``id`` and ``scope:`` block (a missing ``scope:`` would
    resolve to the permissive default), the exact Requirements / Acceptance Criteria /
    Out of Scope sections and the ``## Scope Amendments`` table (so a hand-written
    verdict's ``amended`` classification still recomputes without ``--main-root``), and
    nothing else: no status, State rationale, unblock history or report links.  Names of withheld earlier-attempt
    artifacts become neutral placeholders in the scope block and in Out of Scope (the
    gate then refuses to classify from this copy without ``--main-root``, so a placeholder
    can never loosen a ``deny:``); Requirements and Acceptance Criteria are never rewritten.
    A spec without an Acceptance Criteria section is not projected.  The projection
    is proven against the original (:func:`_prove_contract_unchanged`) or this raises.
    """
    original_sha = hashlib.sha256(spec_text.encode("utf-8", "surrogateescape")).hexdigest()
    if _spec_section(spec_text, "Acceptance Criteria") is None:
        return spec_text, {
            "projection": "skipped_no_acceptance_criteria",
            "original_sha256": original_sha, "projected_sha256": original_sha,
        }
    names = _AttemptNames(withheld_names)
    frontmatter = _spec_frontmatter(spec_text).split("\n")
    spec_id = next((line for line in frontmatter if re.match(r"^id:\s*\S", line)), None)
    block = _spec_scope_block(frontmatter)
    kept_block = [names.replace(line) for line in block]
    mentions: list[str] = []
    sections: list[str] = []
    for heading in (*SPEC_CONTRACT_SECTIONS, "Scope Amendments"):
        section = _spec_section(spec_text, heading)
        if section is None:
            continue
        if heading in SPEC_PROOF_SECTIONS:
            mentions.extend(names.mentions(section))
        else:
            section = names.replace(section)
        sections.append(_neutralise_checkboxes(section) + "\n")
    head = ["---", *([spec_id] if spec_id else []), *kept_block, "---"]
    projected = "\n".join(head) + "\n" + SPEC_PROJECTION_MARKER + "\n\n" + "\n".join(sections)
    _prove_contract_unchanged(spec_text, projected)
    return projected, {
        "projection": "contractual_sections",
        "original_sha256": original_sha,
        "projected_sha256": hashlib.sha256(projected.encode("utf-8", "surrogateescape")).hexdigest(),
        "withheld_names": names.records(),
        "contract_mentions_withheld": sorted(set(mentions)),
        "scope_summary": _scope_summary(kept_block),
    }


def _spec_projection_for_ref(
    source_repository: Path, ref: str, spec_path: str, withheld_names: Iterable[str],
) -> tuple[bytes | None, dict[str, Any]]:
    """Recomputable per-arm projection of the spec at *ref* (``None`` body when absent)."""
    original = _blob_text_at_ref(source_repository, ref, spec_path)
    if original is None:
        return None, {"present": False}
    projected, record = project_spec_for_verifier(original, withheld_names=withheld_names)
    return projected.encode("utf-8", "surrogateescape"), {"present": True, **record}


def _write_spec_projection(
    destination: Path, spec_path: str, body: bytes | None, record: dict[str, Any],
) -> dict[str, Any]:
    target = destination / spec_path
    if body is not None and target.is_file() and not target.is_symlink():
        target.write_bytes(body)
    elif body is not None:
        record = {"present": False, "projection": "skipped_not_a_regular_file"}
    return record


def spec_normalisation_evidence(
    arms: Mapping[str, dict[str, Any]], spec_path: str,
) -> dict[str, Any]:
    head = arms.get("head", {})
    return {
        "spec_path": spec_path,
        "arms": {label: dict(arms[label]) for label in ARM_LABELS},
        "scope_summary": head.get("scope_summary") or arms.get("baseline", {}).get("scope_summary"),
    }


def _write_refusal_evidence(
    evidence_path: Path, spec_id: str, spec_path: str | None, refusal: DeclaredInputRefusal,
) -> None:
    # R4: a refused input is recorded, not merely raised. The record is durable
    # before the failure propagates, and is deliberately not a surface: nothing
    # of the refused source was read into a snapshot, so no rejected byte can
    # reach either arm.
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps({
            "schema_version": CONTAINMENT_EVIDENCE_SCHEMA_VERSION,
            "surface_kind": "refused-declared-external-input",
            "same_spec_id": spec_id,
            "spec_path": spec_path,
            "refusal": {
                "declaration": refusal.declaration,
                "reason": refusal.reason,
                "detail": refusal.detail,
            },
            "declared_external_inputs": refusal.records,
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_verifier_surface(
    source_repository: Path,
    destination: Path,
    *,
    baseline_ref: str,
    head_ref: str,
    report_paths: Iterable[str],
    evidence_path: Path,
    spec_id: str,
    spec_path: str | None = None,
    preflight_proof_sha256: str | None = None,
    project_spec: bool = False,
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

    A tracked symlink whose target is absolute and lands outside the surface is
    materialized as a regular file holding the link text and recorded in
    ``transformed_symlinks`` (SPEC-285); a *relative* link that traverses out is
    still refused outright.

    When *spec_path* names the spec under verification, its predeclared
    external-evidence inputs are resolved before the destination exists, pinned to
    the source repository's committed objects, and projected byte-exactly into
    ``.nightshift-verifier-inputs/`` inside *both* arms (SPEC-288). Evidence
    provenance is not an arm-dependent variable: only the subject repository
    content differs between arms, so the same projection is committed to each. A
    refusal writes durable refusal evidence and leaves no surface at all. Omitting
    *spec_path* — or declaring no external evidence — leaves every byte of this
    function's behaviour as it was.

    With *project_spec* (and *spec_path*), each arm's copy of that spec is replaced by its
    contractual projection (SPEC-NS-KIT-002-005, :func:`project_spec_for_verifier`); the
    original hashes and withheld names go to parent-owned containment evidence under
    ``spec_normalisation``.  Off by default at this library seam (SPEC-NS-KIT-008 flips the default at the
    ``prepare-dispatch`` CLI, whose ``--no-project-spec`` passes False): an unprojected dispatch is unchanged.

    A ``preflight-proof:`` declaration (SPEC-390-002) is projected the same way
    but as a *sanitized parsed document* in ``.nightshift-verifier-proof/``, built
    from the retained result and bound to the candidate by digest; *preflight_proof_sha256*
    is the coordinator's out-of-band digest of that retained result. An absent,
    altered, uncontained, or differently-bound proof is recorded and projected as
    unverifiable, never silently dropped.
    """
    source_repository = source_repository.resolve()
    destination = destination.resolve()
    report_paths = tuple(sorted({_normalise_repo_path(path) for path in report_paths}))
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("verifier surface destination must be empty")
    spec_id = normalise_spec_identity(spec_id)
    try:
        resolved_inputs, input_records = resolve_declared_external_inputs(
            source_repository,
            baseline_ref=baseline_ref,
            head_ref=head_ref,
            spec_path=spec_path,
            spec_id=spec_id,
            report_paths=report_paths,
        )
        proof_declarations = resolve_declared_preflight_proofs(
            source_repository, baseline_ref=baseline_ref, head_ref=head_ref,
            spec_path=spec_path,
        )
    except DeclaredInputRefusal as refusal:
        _write_refusal_evidence(evidence_path, spec_id, spec_path, refusal)
        raise
    proof_record: dict[str, Any] | None = None
    proof_body = b""
    if proof_declarations:
        _document, proof_record, proof_body = resolve_preflight_proof(
            source_repository, proof_declarations,
            reference_sha256=preflight_proof_sha256,
        )
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
    # SPEC-391: resolved before any surface exists; a refusal leaves nothing behind.
    try:
        evidence_resolved = resolve_evidence_projection(
            source_repository, baseline_ref=baseline_ref, head_ref=head_ref,
            spec_path=spec_path,
            withheld_paths=lambda: _withheld_report_paths(
                report_paths, baseline_report_objects, head_report_objects,
                same_spec_reports, same_spec_metrics,
            ),
        )
    except DeclaredInputRefusal as refusal:
        _write_refusal_evidence(evidence_path, spec_id, spec_path, refusal)
        raise
    # R1: proven before any surface exists, so an unprovable projection leaves nothing behind.
    spec_projections: dict[str, tuple[bytes | None, dict[str, Any]]] = {}
    if spec_path and project_spec:
        withheld_spec_names = sorted({*report_paths, *same_spec_reports, *same_spec_metrics})
        spec_projections = {
            label: _spec_projection_for_ref(
                source_repository, ref, _normalise_repo_path(spec_path), withheld_spec_names,
            )
            for label, ref in (("baseline", baseline_ref), ("head", head_ref))
        }
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
    projected_paths: list[str] = []
    excluded_by_ref: dict[str, list[str]] = {}
    transformed_by_ref: dict[str, list[dict[str, str]]] = {}
    placeholders_by_ref: dict[str, list[str]] = {}
    spec_arms: dict[str, dict[str, Any]] = {}
    fixed_env = _git_environment(
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    for label, ref in refs:
        placeholders_by_ref[label] = []
        excluded_by_ref[label], transformed_by_ref[label], materialized_paths = _materialize_ref(
            source_repository,
            destination,
            ref,
            report_paths=report_paths,
            retained_report_paths=retained_reports,
            same_spec_metrics_paths=same_spec_metrics,
            placeholder_paths=same_spec_exclusions,
            placeholders_written=placeholders_by_ref[label],
        )
        if spec_path and project_spec:
            spec_arms[label] = _write_spec_projection(
                destination, _normalise_repo_path(spec_path), *spec_projections[label],
            )
        projected_paths = _project_external_inputs(
            destination, resolved_inputs, input_records
        )
        proof_paths = (
            _project_preflight_proof(destination, proof_body) if proof_record else []
        )
        # SPEC-342: force-add exactly the paths this ref's source tree actually
        # tracked (and this function chose to materialize). A plain `add -A`
        # respects the destination's own `.gitignore` -- which is itself a
        # source-tracked file and may deliberately match a retained, tracked
        # path (e.g. a force-added report under an otherwise-ignored
        # directory) -- and would silently drop that file from the arm's
        # commit even though it is genuinely tracked in the source at *ref*.
        # Everything else (external-input projections, worktree bookkeeping)
        # still goes through a plain `add -A` and remains subject to
        # `.gitignore` exactly as before.
        evidence_paths = (
            _project_evidence_projection(destination, evidence_resolved[2])
            if evidence_resolved else []
        )
        _force_add_tracked_paths(destination, materialized_paths)
        _run_git(destination, "add", "-A")
        result = subprocess.run(
            ["git", "-C", str(destination), "commit", "--allow-empty", "-qm", f"verifier {label} snapshot"],
            env=fixed_env, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"could not commit {label} snapshot")
        commits[label] = _run_git(destination, "rev-parse", "HEAD").strip()
        _run_git(destination, "tag", f"verifier-{label}")

    # R1/R2 (SPEC-282): both refs so far exist only as tags inside the
    # standalone repository's single working tree (left checked out at
    # whichever ref was materialized last). A verifier confined to read-only
    # commands cannot turn a tag into a runnable filesystem tree itself, so the
    # parent-owned boundary must do it here, from the same sanitized
    # containment projection and without touching the source repository's
    # object database. Two linked worktrees of the standalone repo (not of the
    # source) satisfy that: they share only the *standalone* repo's own object
    # database with each other, never with `source_repository`.
    surface_repositories: dict[str, str] = {}
    for label in ("baseline", "head"):
        arm_dir = destination / f"verifier-{label}"
        _run_git(destination, "worktree", "add", "--detach", str(arm_dir), f"verifier-{label}")
        surface_repositories[label] = str(arm_dir)
    _seal_projected_inputs(
        [destination, *(Path(path) for path in surface_repositories.values())],
        [*projected_paths, *proof_paths, *evidence_paths],
    )

    placeholder_records = [
        {"arm": label, "path": path, "sha256": PLACEHOLDER_REPORT_SHA256}
        for label in ("baseline", "head")
        for path in placeholders_by_ref[label]
    ]
    placeholder_keys = {(record["arm"], record["path"]) for record in placeholder_records}
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
            if (label, path) in placeholder_keys:
                # SPEC-398: present by design, but only as the fixed placeholder.
                if not _placeholder_intact(destination, f"verifier-{label}", path):
                    raise RuntimeError("worker report remains reachable from verifier surface")
                probes.append({
                    "ref": label, "path": path, "unreachable": False, "placeholder": True,
                })
                continue
            probes.append({"ref": label, "path": path, "unreachable": probe.returncode != 0})
    if not probes or not all(probe["unreachable"] or probe.get("placeholder") for probe in probes):
        raise RuntimeError("worker report remains reachable from verifier surface")
    evidence = {
        "schema_version": CONTAINMENT_EVIDENCE_SCHEMA_VERSION,
        "surface_kind": "standalone-sanitized-git",
        "source_refs": {"baseline": baseline_ref, "head": head_ref},
        "surface_commits": commits,
        "surface_repositories": surface_repositories,
        "excluded_paths": excluded_by_ref,
        # SPEC-285: entries that are present in the surface but not as the type
        # the source tree carries. Recorded per ref, per entry, with the original
        # link target, so a verifier can tell a transformed entry from one whose
        # content simply differs.
        "transformed_symlinks": transformed_by_ref,
        "explicit_report_paths": list(report_paths),
        "same_spec_id": spec_id,
        "same_spec_excluded_paths": same_spec_exclusions,
        "same_spec_excluded_metrics_paths": dict(sorted(same_spec_metrics.items())),
        "retained_historical_report_sha256": retained_hashes,
        "report_reachability": probes,
        "placeholder_report_paths": placeholder_records,
        "shared_object_database": False,
        "head_tree": _run_git(destination, "rev-parse", "HEAD^{tree}").strip(),
    }
    if input_records:
        # SPEC-288 R4. Absent, not empty, when nothing was declared: a dispatch
        # that imports no external evidence stays byte-identical to a pre-SPEC-288
        # one, including this file and every digest derived from it.
        evidence["declared_external_inputs"] = input_records
        evidence["declared_external_input_spec_path"] = _normalise_repo_path(spec_path or "")
        evidence["projected_external_input_paths"] = projected_paths
    if spec_arms and any(arm.get("present") for arm in spec_arms.values()):
        # SPEC-NS-KIT-002-005 R1: absent when no spec was supplied or it exists in neither
        # arm, so such a dispatch stays byte-identical. Parent-owned: the original hashes
        # and the withheld names never reach the verifier.
        evidence["spec_normalisation"] = spec_normalisation_evidence(
            spec_arms, _normalise_repo_path(spec_path),
        )
    if proof_record is not None:
        # SPEC-390-002: absent, not empty, when no proof was declared, for the same
        # byte-identity reason as the external-input rows above.
        evidence["declared_preflight_proof"] = proof_record
        evidence["projected_preflight_proof_paths"] = proof_paths
    if evidence_resolved:
        # SPEC-391: absent, not empty, when nothing was declared (byte-identical dispatch).
        evidence["declared_evidence_projection"] = evidence_resolved[1]
        evidence["projected_evidence_projection_paths"] = evidence_paths
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


def _projection_is_contained(root: Path, relative: str, digest: str) -> bool:
    """True when one projected input is a contained, read-only, byte-exact file."""
    target = root / relative
    return (
        not target.is_symlink()
        and target.is_file()
        and _within_surface(target.resolve(), root.resolve())
        and hashlib.sha256(target.read_bytes()).hexdigest() == digest
        and not target.stat().st_mode & 0o222
    )


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
    spec_path: str | None = None,
    preflight_proof_sha256: str | None = None,
    ledger_path: Path | None = None,
    ledger_identity: dict[str, Any] | None = None,
    ledger_now: Any = None,
    arm_isolation: dict[str, Any] | None = None,
    trusted_tooling: dict[str, Any] | None = None,
    project_spec: bool = False,
) -> PreparedVerifierDispatch:
    """Prepare the sole verifier surface and emit a sanitized launch plan.

    Normal and no-test-suite routes call this same boundary.  The durable
    evidence is reloaded and independently checked before a plan exists, so a
    preparation or reachability failure cannot degrade to the source worktree.
    """
    # SPEC-NS-KIT-002-004 R3: refuse a plan whose arms share a device or differ in runtime
    # before any surface exists (ArmIsolationError, never degraded to a preparation error).
    arm_isolation = build_arm_isolation(
        (arm_isolation or {}).get("devices"), (arm_isolation or {}).get("runtime"),
    )
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
            spec_path=spec_path,
            preflight_proof_sha256=preflight_proof_sha256,
            project_spec=project_spec,
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
        # SPEC-398: a withheld path may be present only as a recorded placeholder
        # whose arm commit and checked-out file both hold exactly the fixed body.
        # The expected placeholder set is recomputed from the source (the same-spec
        # rule applied to each arm's own tree), not trusted from the written record.
        expected_placeholders = sorted(
            (
                {"arm": label, "path": path, "sha256": PLACEHOLDER_REPORT_SHA256}
                for label, ref in (("baseline", baseline_ref), ("head", head_ref))
                for path in _referenced_placeholder_paths(
                    source_repository, ref,
                    candidates=observed_same_spec,
                    report_paths=normalized_reports,
                    retained_report_paths=retained if isinstance(retained, dict) else (),
                    same_spec_metrics_paths=observed_same_spec_metrics,
                )
            ),
            key=lambda record: (record["arm"], record["path"]),
        )
        placeholders_ready = (
            durable_evidence.get("placeholder_report_paths") == expected_placeholders
        )
        if placeholders_ready:
            arm_roots = durable_evidence.get("surface_repositories", {})
            for record in expected_placeholders:
                arm_file = Path(arm_roots[record["arm"]]) / record["path"]
                placeholders_ready = (
                    placeholders_ready
                    and _placeholder_intact(
                        destination, f"verifier-{record['arm']}", record["path"]
                    )
                    and arm_file.is_file()
                    and not arm_file.is_symlink()
                    and arm_file.read_bytes() == PLACEHOLDER_REPORT_BODY.encode("utf-8")
                )
                if placeholders_ready:
                    observed_probes.add((record["arm"], record["path"]))
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
        # SPEC-288 R2/R4: recompute the declared-input resolution from the source
        # instead of trusting the record this same call just wrote, then require the
        # projection to be present, byte-exact, regular, read-only, and contained in
        # *both* arms. A projection that cannot be re-derived is not evidence.
        recorded_inputs = durable_evidence.get("declared_external_inputs")
        observed_inputs, observed_records = resolve_declared_external_inputs(
            source_repository,
            baseline_ref=baseline_ref,
            head_ref=head_ref,
            spec_path=spec_path,
            spec_id=spec_id,
            report_paths=normalized_reports,
        )
        projection_ready = recorded_inputs is None and not observed_records
        if not projection_ready:
            arm_directories = [
                Path(path)
                for path in durable_evidence.get("surface_repositories", {}).values()
            ]
            expected_projection = {
                projected.path: hashlib.sha256(projected.body).hexdigest()
                for item in observed_inputs for projected in item.files
            }
            manifest_relative = f"{EXTERNAL_INPUT_NAMESPACE}/{EXTERNAL_INPUT_MANIFEST}"
            projection_ready = (
                recorded_inputs == observed_records
                and bool(expected_projection)
                and durable_evidence.get("projected_external_input_paths")
                == sorted([*expected_projection, manifest_relative])
                and len(arm_directories) == 2
                and all(
                    _projection_is_contained(arm, relative, digest)
                    for arm in arm_directories
                    for relative, digest in expected_projection.items()
                )
                and all(
                    json.loads((arm / manifest_relative).read_text(encoding="utf-8"))
                    == external_input_manifest(observed_records)
                    for arm in arm_directories
                )
                and not any(
                    entry.is_symlink()
                    for arm in arm_directories
                    for entry in (arm / EXTERNAL_INPUT_NAMESPACE).rglob("*")
                )
            )
        # SPEC-390-002: recompute the proof from the retained result and require the
        # recorded row and both arms' projected bytes to match it exactly; absent on
        # both sides is the unchanged no-proof dispatch.
        recorded_proof = durable_evidence.get("declared_preflight_proof")
        observed_declarations = resolve_declared_preflight_proofs(
            source_repository, baseline_ref=baseline_ref, head_ref=head_ref,
            spec_path=spec_path,
        )
        if not observed_declarations:
            proof_ready = (
                recorded_proof is None
                and "projected_preflight_proof_paths" not in durable_evidence
            )
        else:
            _document, observed_proof, observed_body = resolve_preflight_proof(
                source_repository, observed_declarations,
                reference_sha256=preflight_proof_sha256,
            )
            proof_arms = [
                Path(path)
                for path in durable_evidence.get("surface_repositories", {}).values()
            ]
            proof_ready = (
                recorded_proof == observed_proof
                and durable_evidence.get("projected_preflight_proof_paths")
                == [observed_proof["projected_path"]]
                and len(proof_arms) == 2
                and all(
                    _projection_is_contained(
                        arm, observed_proof["projected_path"],
                        hashlib.sha256(observed_body).hexdigest(),
                    )
                    for arm in proof_arms
                )
            )
        # SPEC-391: recompute the evidence projection from the source (withheld set
        # included) and require the record and both arms' bytes to match exactly.
        recorded_evidence = durable_evidence.get("declared_evidence_projection")
        observed_evidence = resolve_evidence_projection(
            source_repository, baseline_ref=baseline_ref, head_ref=head_ref,
            spec_path=spec_path,
            withheld_paths=lambda: _withheld_report_paths(
                normalized_reports,
                _tracked_report_objects(source_repository, baseline_ref, report_paths=normalized_reports),
                _tracked_report_objects(source_repository, head_ref, report_paths=normalized_reports),
                observed_same_spec, observed_same_spec_metrics,
            ),
        )
        if observed_evidence is None:
            evidence_ready = (
                recorded_evidence is None
                and "projected_evidence_projection_paths" not in durable_evidence
            )
        else:
            evidence_arms = [
                Path(path) for path in durable_evidence.get("surface_repositories", {}).values()
            ]
            evidence_ready = (
                recorded_evidence == observed_evidence[1]
                and durable_evidence.get("projected_evidence_projection_paths")
                == [observed_evidence[1]["projected_path"]]
                and len(evidence_arms) == 2
                and all(
                    _projection_is_contained(
                        arm, observed_evidence[1]["projected_path"],
                        hashlib.sha256(observed_evidence[2]).hexdigest(),
                    )
                    for arm in evidence_arms
                )
            )
        # SPEC-NS-KIT-002-005 R1: recompute each arm's spec projection from the source and
        # require the recorded evidence, the arm commit and the checked-out file to match it.
        recorded_spec = durable_evidence.get("spec_normalisation")
        spec_ready = recorded_spec is None and "spec_normalisation" not in durable_evidence
        if spec_path and project_spec:
            spec_rel = _normalise_repo_path(spec_path)
            withheld_now = sorted({*normalized_reports, *observed_same_spec, *observed_same_spec_metrics})
            observed_arms: dict[str, dict[str, Any]] = {}
            spec_ready = True
            for label, ref in (("baseline", baseline_ref), ("head", head_ref)):
                body, observed_arms[label] = _spec_projection_for_ref(
                    source_repository, ref, spec_rel, withheld_now,
                )
                if body is None:
                    continue
                arm_dir = Path(durable_evidence["surface_repositories"][label])
                arm_file = arm_dir / spec_rel
                spec_ready = spec_ready and (
                    observed_arms[label].get("projection") == "skipped_not_a_regular_file"
                    or (
                        _git_bytes(destination, "show", f"verifier-{label}:{spec_rel}") == body
                        and arm_file.is_file() and not arm_file.is_symlink()
                        and arm_file.read_bytes() == body
                    )
                )
            if any(arm.get("present") for arm in observed_arms.values()):
                spec_ready = spec_ready and recorded_spec == spec_normalisation_evidence(
                    observed_arms, spec_rel,
                )
            else:
                spec_ready = spec_ready and recorded_spec is None
        ready = (
            projection_ready
            and proof_ready
            and evidence_ready
            and spec_ready
            and placeholders_ready
            and durable_evidence == evidence
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
            # R1/R2 (SPEC-282): both arms must already be runnable, checked-out
            # working directories -- not merely tags -- before dispatch, and each
            # must actually resolve to its own arm's commit.
            and isinstance(durable_evidence.get("surface_repositories"), dict)
            and set(durable_evidence["surface_repositories"]) == {"baseline", "head"}
            and all(
                Path(durable_evidence["surface_repositories"][label]).is_dir()
                for label in ("baseline", "head")
            )
            and all(
                _run_git(
                    Path(durable_evidence["surface_repositories"][label]), "rev-parse", "HEAD"
                ).strip() == commits[label]
                for label in ("baseline", "head")
            )
        )
    except Exception as exc:
        raise VerifierSurfacePreparationError("verifier surface preparation failed") from exc

    if not ready:
        raise VerifierSurfacePreparationError("verifier surface reachability assertion failed")
    ledger_baseline = None
    if ledger_path is not None:
        ledger_baseline = _project_ledger_baseline(
            source_repository, destination, durable_evidence, baseline_ref,
            Path(ledger_path), ledger_identity or {}, evidence_path, ledger_now,
        )
    flaky = False
    if ledger_path is not None:
        flaky = flaky_suspected_from_evidence(
            load_ledger(Path(ledger_path)), now=ledger_now,
        )
    return PreparedVerifierDispatch(
        repository=destination,
        evidence_path=evidence_path.resolve(),
        evidence=durable_evidence,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        suite_commands=suites,
        spec_id=spec_id,
        run_id=run_id,
        ledger_baseline=ledger_baseline,
        spec_projection_declined=bool(spec_path and not project_spec),
        flaky_suspected=flaky,
        arm_isolation=arm_isolation,
        footprint_before={
            label: {"tree": fp.tree, "porcelain": fp.porcelain}
            for label, fp in capture_verifier_footprints({
                arm: Path(durable_evidence["surface_repositories"][arm]) for arm in ARM_LABELS
            }).items()
        },
        trusted_tooling=trusted_tooling,
    )


def _project_ledger_baseline(
    source_repository: Path,
    destination: Path,
    evidence: dict[str, Any],
    baseline_ref: str,
    ledger_path: Path,
    identity_extras: dict[str, Any],
    evidence_path: Path,
    now: Any,
) -> dict[str, Any]:
    """SPEC-NS-KIT-002-002 R5: project a matching main ledger read-only into both arms.

    Never raises and never weakens the dispatch: any doubt (missing module, unreadable or
    tampered ledger, identity/coverage/staleness mismatch, a projection that cannot be
    re-derived) yields `not_matched` and the verifier runs a real baseline. The head arm
    is never affected; it always gets its own full run.
    """
    outcome: dict[str, Any] = {"status": "not_matched", "reason": "ledger_error"}
    try:
        record = load_ledger(ledger_path)
        try:
            relative = ledger_path.resolve().relative_to(source_repository).as_posix()
        except ValueError:
            relative = LEDGER_RELATIVE_PATH
        identity = identity_from_extras(
            source_repository, baseline_ref, identity_extras, exempt=[relative],
        )
        moment = now or utc_now()
        decision = reuse_decision(record, identity, now=moment)
        if not decision["reuse"]:
            outcome = {"status": "not_matched", "reason": decision["reason"]}
        else:
            arms = [Path(p) for p in evidence["surface_repositories"].values()]
            body = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
            exclude = destination / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                handle.write("/.nightshift-ledger/\n")
            for arm in arms:
                target = arm / PROJECTED_RELATIVE_PATH
                target.parent.mkdir(parents=True, exist_ok=True)
                if not _within_surface(target.resolve(), arm.resolve()):
                    raise ValueError("ledger projection resolves outside the arm")
                target.write_bytes(body)
                target.chmod(0o444)
            # Re-derive from what is actually on disk in every arm, not from the record
            # this same call just wrote.
            for arm in arms:
                reread = json.loads((arm / PROJECTED_RELATIVE_PATH).read_bytes())
                again = reuse_decision(reread, identity, now=moment)
                if not again["reuse"] or again["record_digest"] != decision["record_digest"]:
                    raise ValueError("projected ledger failed re-derivation")
            outcome = {
                "status": "matched", "reason": decision["reason"], "label": "reused",
                "record_digest": decision["record_digest"],
                "identity_digest": decision["identity_digest"],
                "projected_path": PROJECTED_RELATIVE_PATH,
            }
    except Exception:  # noqa: BLE001 - fail closed to a real baseline run
        outcome = {"status": "not_matched", "reason": "ledger_error"}
        for raw in evidence.get("surface_repositories", {}).values():
            stale = Path(raw) / ".nightshift-ledger" / "baseline.json"
            if stale.exists():
                stale.chmod(0o644)
                stale.unlink()
    try:
        sidecar = evidence_path.with_name(evidence_path.stem + ".ledger-match.json")
        sidecar.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    return outcome


def contamination_exposures(value: Any) -> list[dict[str, Any]] | None:
    """The classified exposures of a verdict's ``contamination``; ``None`` when unclassified.

    ``null`` is no exposure (``[]``).  A legacy free-text or otherwise malformed value
    is *unclassified* (``None``) and callers must treat it as blocking.
    """
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    if not all(isinstance(item, dict) for item in items):
        return None
    for item in items:
        if (
            item.get("class") not in CONTAMINATION_CLASSES
            or item.get("timing") not in CONTAMINATION_TIMINGS
            or not set(item) <= CONTAMINATION_KEYS
            or not isinstance(item.get("detail", ""), str)
        ):
            return None
    return list(items)


def contamination_errors(value: Any) -> list[str]:
    """Schema errors for a *structured* contamination value (strings are legacy, see above)."""
    if value is None or (not isinstance(value, (dict, list))):
        return []
    if contamination_exposures(value) is None:
        return ["contamination must be null or {class, timing[, detail]} objects with closed class/timing values"]
    return []


def validate_verifier_verdict_dict(data: dict[str, Any]) -> list[str]:
    """Validate the independent-verifier envelope fields owned by the kit."""
    errors = [f"missing top-level key '{key}'" for key in sorted(VERIFIER_VERDICT_REQUIRED_KEYS - data.keys())]
    if data.get("kind") == "budget_expiry" or data.get("verdict") == "budget_expiry":
        errors.append("budget_expiry is evidence of an expired budget, never a verdict (SPEC-NS-KIT-002-007 R3)")
    if data.get("verdict") not in {"pass", "fail", "disputes_premise"}:
        errors.append(f"verdict not in enum: {data.get('verdict')!r}")
    errors.extend(contamination_errors(data.get("contamination")))
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
        # SPEC-285: the tracked-symlink pair a real repository carries — one
        # absolute link to ordinary content outside the repo, one relative link
        # that stays inside it. The smoke contract is that the surface builds at
        # all, that the first becomes a visible link-text file recorded in
        # containment evidence, and that the second is still a working symlink.
        outside_target = root / "outside-the-repository" / "CLAUDE.md"
        outside_target.parent.mkdir(parents=True, exist_ok=True)
        outside_target.write_text("out-of-repository content\n", encoding="utf-8")
        os.symlink(str(outside_target), source / "AGENTS.md")
        in_surface_link = source / "docs/AGENTS.md"
        in_surface_link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink("../AGENTS.md", in_surface_link)
        # SPEC-288: a second repository holding committed evidence, and the two
        # spec files that declare it -- one admissible, one that declares a report
        # path and must be refused even though it is declared. Both declarations
        # are committed at the baseline, which is the whole point: a declaration
        # the candidate could add mid-run would not be identical across the arms.
        evidence_source = root / "evidence-source"
        evidence_source.mkdir()
        subprocess.run(["git", "init", "-q", str(evidence_source)], check=True)
        _run_git(evidence_source, "config", "user.name", "Nightshift smoke evidence")
        _run_git(evidence_source, "config", "user.email", "evidence@example.invalid")
        (evidence_source / "results").mkdir()
        (evidence_source / "results/run-manifest.json").write_text(
            '{"run": "smoke", "models": 2}\n', encoding="utf-8"
        )
        _run_git(evidence_source, "add", "-A")
        _run_git(evidence_source, "commit", "-qm", "retained evidence")
        smoke_spec = source / "canonical/specs/SMOKE.md"
        smoke_spec.parent.mkdir(parents=True, exist_ok=True)
        smoke_spec.write_text(
            "---\nid: SMOKE\ncontext:\n  required_inputs:\n"
            f"  - {EXTERNAL_INPUT_PREFIX}{evidence_source}"
            f"{EXTERNAL_INPUT_SEPARATOR}results/run-manifest.json\n---\n\n# smoke\n",
            encoding="utf-8",
        )
        denied_spec = source / "canonical/specs/SMOKE-DENIED.md"
        denied_spec.write_text(
            "---\nid: SMOKE\ncontext:\n  required_inputs:\n"
            f"  - {EXTERNAL_INPUT_PREFIX}{source}"
            f"{EXTERNAL_INPUT_SEPARATOR}canonical/reports/OTHER-SPEC/fixture.md\n---\n",
            encoding="utf-8",
        )
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
        # R1/R2/AC1/AC3 (SPEC-282): each arm is its own already-materialized,
        # runnable, checked-out working directory under the same standalone
        # surface -- distinct from each other and from `repository` -- and a
        # read-only command against each succeeds without any verifier-side
        # checkout or file-materialization step.
        for one_plan, one_surface in ((plan, surface), (no_suite_plan, no_suite_surface)):
            arms = one_plan["arm_working_directories"]
            if set(arms) != {"baseline", "head"}:
                raise RuntimeError("dispatch plan did not assign both arm working directories")
            head_dir = Path(arms["head"])
            baseline_dir = Path(arms["baseline"])
            if head_dir == baseline_dir:
                raise RuntimeError("baseline and head arms resolved to the same directory")
            if not head_dir.is_relative_to(one_surface.resolve()) or not baseline_dir.is_relative_to(
                one_surface.resolve()
            ):
                raise RuntimeError("arm working directory escaped the standalone surface")
            for label, workdir in (("baseline", baseline_dir), ("head", head_dir)):
                probe = subprocess.run(
                    ["git", "-C", str(workdir), "status", "--porcelain=v1"],
                    capture_output=True, check=False, env=_git_environment(),
                )
                if probe.returncode:
                    raise RuntimeError(f"read-only command failed against {label} arm surface")
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
        # SPEC-285 containment: the absolute out-of-repo link is a plain file
        # holding its link text and is declared as transformed; the in-surface
        # relative link is untouched and still followable in the head arm.
        transformed = evidence.get("transformed_symlinks")
        expected_transform = {
            "path": "AGENTS.md",
            "target": str(outside_target),
            "handling": "link-text-file",
        }
        if not isinstance(transformed, dict) or set(transformed) != {"baseline", "head"} or any(
            expected_transform not in transformed[label] for label in ("baseline", "head")
        ):
            raise RuntimeError("transformed symlink containment evidence contract failed")
        materialized_link_text = surface / "AGENTS.md"
        arm_relative_link = Path(evidence["surface_repositories"]["head"]) / "docs/AGENTS.md"
        if (
            materialized_link_text.is_symlink()
            or not materialized_link_text.is_file()
            or materialized_link_text.read_text(encoding="utf-8") != str(outside_target)
            or not arm_relative_link.is_symlink()
            or os.readlink(arm_relative_link) != "../AGENTS.md"
        ):
            raise RuntimeError("tracked symlink materialization contract failed")
        # SPEC-288: the declared-external-input contract, both halves. An admitted
        # declaration is projected byte-exactly, read-only, into both arms and is
        # described to the verifier without a host path; a declared report path is
        # refused with durable refusal evidence and no surface at all.
        external = prepare_verifier_dispatch(
            source, root / "surface-external", baseline_ref=baseline, head_ref=head,
            report_paths=["canonical/reports/nightshift-report.md"],
            evidence_path=root / "containment-external.json",
            spec_id="SMOKE", run_id="smoke-run-external",
            spec_path="canonical/specs/SMOKE.md",
        )
        admitted = external.evidence.get("declared_external_inputs")
        projected_relative = (
            f"{EXTERNAL_INPUT_NAMESPACE}/{admitted[0]['source_repository_id']}"
            "/results/run-manifest.json"
        ) if isinstance(admitted, list) and admitted else ""
        if (
            not isinstance(admitted, list)
            or len(admitted) != 1
            or admitted[0].get("handling") != "admitted"
            or admitted[0].get("sha256") != hashlib.sha256(
                b'{"run": "smoke", "models": 2}\n'
            ).hexdigest()
            or admitted[0].get("projected_path") != projected_relative
        ):
            raise RuntimeError("declared external input evidence contract failed")
        for label in ("baseline", "head"):
            arm = Path(external.evidence["surface_repositories"][label])
            projected = arm / projected_relative
            manifest_path = arm / EXTERNAL_INPUT_NAMESPACE / EXTERNAL_INPUT_MANIFEST
            manifest_text = manifest_path.read_text(encoding="utf-8")
            if (
                projected.is_symlink()
                or not projected.is_file()
                or projected.read_bytes() != b'{"run": "smoke", "models": 2}\n'
                or projected.stat().st_mode & 0o222
                or str(evidence_source) in manifest_text
                or str(source) in manifest_text
                or json.loads(manifest_text)["inputs"][0]["source_path"]
                != "results/run-manifest.json"
            ):
                raise RuntimeError(
                    f"projected external evidence contract failed in the {label} arm"
                )
        refused_surface = root / "surface-refused"
        refused_evidence_path = root / "containment-refused.json"
        try:
            prepare_verifier_dispatch(
                source, refused_surface, baseline_ref=baseline, head_ref=head,
                report_paths=["canonical/reports/nightshift-report.md"],
                evidence_path=refused_evidence_path,
                spec_id="SMOKE", run_id="smoke-run-refused",
                spec_path="canonical/specs/SMOKE-DENIED.md",
            )
        except VerifierSurfacePreparationError:
            refusal = json.loads(refused_evidence_path.read_text(encoding="utf-8"))
        else:
            raise RuntimeError("declared report-root input was not refused")
        if (
            refusal.get("refusal", {}).get("reason") != "report_root"
            or refusal.get("surface_kind") != "refused-declared-external-input"
            or any(refused_surface.rglob("fixture.md"))
        ):
            raise RuntimeError("declared-input refusal contract failed")
        verdict = {
            "spec_id": "SMOKE", "branch": "smoke", "baseline_commit": baseline,
            "head_commit": plan["head_commit"],
            "identity_schema_version": plan["identity_schema_version"],
            "implementation_head_digest": plan["implementation_head_digest"],
            "verdict": "pass", "acs": [{"id": "AC1", "status": "pass", "evidence": "smoke"}],
            "suites": [],
            # SPEC-284: per arm, both snapshots, so the managed smoke contract
            # carries the exact shape the validator recomputes from.
            "git_footprint": {
                label: {
                    "tree_before": evidence["head_tree"],
                    "tree_after": evidence["head_tree"],
                    "porcelain_before": "",
                    "porcelain_after": "",
                }
                for label in ("baseline", "head")
            },
            # SPEC-300-002 R6: required alongside contamination in the same
            # smoke contract.
            "scope": {"checked": [], "out_of_scope": [], "amended": []},
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


def porcelain_entries(porcelain: str) -> set[str]:
    """Split a ``status --porcelain=v1`` snapshot into comparable entries.

    The unit of comparison is the whole ``XY path`` line, not the path alone: a
    path present in both snapshots under a *different* status (untracked, then
    staged) changed while the verifier held the worktree, and that is a write
    even though the path itself cancels.
    """
    return {line for line in porcelain.splitlines() if line.strip()}


def _footprint_paths(entries: Iterable[str]) -> list[str]:
    """Name paths, not raw status lines, in a footprint diagnostic."""
    return sorted(entry[3:] if len(entry) > 3 else entry.strip() for entry in entries)


def verifier_footprint_errors(before: GitFootprint, after: GitFootprint) -> list[str]:
    """Validate a verifier's worktree-local, read-only Git footprint (SPEC-284).

    The working-tree half is a set comparison of the two snapshots, never an
    emptiness test on *after*.  An entry in both was already there when the
    verifier was handed the worktree and is not attributable to it.  An entry
    only in *after* was added; an entry only in *before* was removed.  Both are
    writes -- including by a verifier that tidies up after itself, which should
    leave a symmetric snapshot rather than a shorter one.
    """
    errors: list[str] = []
    if before.tree != after.tree:
        errors.append(f"verifier mutated the repo tree: {before.tree} -> {after.tree}")
    before_entries = porcelain_entries(before.porcelain)
    after_entries = porcelain_entries(after.porcelain)
    added = _footprint_paths(after_entries - before_entries)
    removed = _footprint_paths(before_entries - after_entries)
    if added:
        errors.append("verifier added to the worktree: " + "; ".join(added))
    if removed:
        errors.append(
            "verifier removed pre-existing worktree state: " + "; ".join(removed)
        )
    return errors


def capture_verifier_footprints(worktrees: dict[str, Path]) -> dict[str, GitFootprint]:
    """Capture the footprint of every assigned arm surface (R4, SPEC-282)."""
    return {label: capture_verifier_footprint(worktree) for label, worktree in worktrees.items()}


def verifier_footprint_errors_multi(
    before: dict[str, GitFootprint], after: dict[str, GitFootprint]
) -> list[str]:
    """Validate every assigned arm surface's read-only footprint (R4, SPEC-282).

    Mutation, or a working-tree entry either arm gained or lost while the
    verifier held it, is an error; a clean baseline arm never masks a dirty head
    arm or vice versa.  Each arm is compared against its own dispatch snapshot,
    so one arm's pre-existing dirt is never charged to the other (SPEC-284).
    """
    if set(before) != set(after):
        return [f"footprint arms mismatch: before={sorted(before)} after={sorted(after)}"]
    errors: list[str] = []
    for label in sorted(before):
        for message in verifier_footprint_errors(before[label], after[label]):
            errors.append(f"{label}: {message}")
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


PREFLIGHT_DIGEST_RECORD_DIRS = (
    "canonical/metrics", ".nightshift/metrics", "metrics",
)


class PreflightDigestRefusal(ValueError):
    """The out-of-band digest record cannot be used; ``reason`` is the stable name."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def recorded_preflight_digest(
    source_repository: Path, *, spec_id: str, head_ref: str,
) -> str | None:
    """Return the digest preflight recorded out of band, or None when no record exists.

    SPEC-390-002-002: read only from the parent-private, untracked record under
    ``<metrics_dir>/_wip/preflight-digests/`` -- never from the spec, a report or
    any committed file. A record for a different head, or an unreadable one, is a
    refusal with a named reason rather than a silent fallback.
    """
    root = source_repository.resolve()
    name = f"{normalise_spec_identity(spec_id)}.json"
    record_path = next(
        (
            candidate
            for candidate in (root / rel / "_wip" / "preflight-digests" / name
                              for rel in PREFLIGHT_DIGEST_RECORD_DIRS)
            if candidate.is_file() and not candidate.is_symlink()
        ),
        None,
    )
    if record_path is None:
        return None
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        recorded_head = record["repository_head"]
        digest = record["result_sha256"]
        valid = (
            record.get("spec_id") == spec_id
            and isinstance(recorded_head, str) and GIT_OBJECT_ID_RE.fullmatch(recorded_head)
            and isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise PreflightDigestRefusal("preflight_digest_record_invalid") from None
    if not valid:
        raise PreflightDigestRefusal("preflight_digest_record_invalid")
    try:
        resolved_head = _run_git(root, "rev-parse", "--verify", f"{head_ref}^{{commit}}").strip()
    except Exception:  # noqa: BLE001 - any resolution failure is a named refusal
        raise PreflightDigestRefusal("preflight_digest_head_unresolvable") from None
    if recorded_head != resolved_head:
        raise PreflightDigestRefusal("preflight_digest_head_mismatch")
    return digest


# ---------------------------------------------------------------------------
# SPEC-NS-KIT-002-001: suite-sample wrapper and per-project throughput report.
# ---------------------------------------------------------------------------

_PYTEST_COUNT_RE = re.compile(r"(\d+) (passed|failed|skipped|errors?)\b")
_UNITTEST_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.M)
_UNITTEST_SKIP_RE = re.compile(r"skipped=(\d+)")
_XCODE_EXECUTED_RE = re.compile(
    r"Executed (\d+) tests?, with (?:(\d+) tests? skipped and )?\d+ failures? "
    r"\(\d+ unexpected\) in [0-9.]+ \(([0-9.]+)\) seconds"
)
_NS_PHASE_RE = re.compile(r"^NS-PHASE (\w+)=([0-9]+(?:\.[0-9]+)?)\s*$", re.M)
_IOS_PHASE_KEYS = ("simulator_create_s", "simulator_boot_s", "build_for_testing_s", "test_execution_s")


def parse_suite_output(output: str, *, xcode: bool = False) -> dict[str, Any]:
    """Best-effort executed/skipped counts and iOS phases; unknown stays `unavailable`."""
    result: dict[str, Any] = {"executed_tests": "unavailable", "skipped_tests": "unavailable"}
    phases: dict[str, Any] = {}
    executed = _XCODE_EXECUTED_RE.findall(output)
    if executed:
        count, skipped, wall = executed[-1]
        result["executed_tests"], result["skipped_tests"] = int(count), int(skipped or 0)
        phases["test_execution_s"] = float(wall)
    else:
        summary = [ln for ln in output.splitlines() if _PYTEST_COUNT_RE.search(ln) and " in " in ln]
        ran = _UNITTEST_RAN_RE.findall(output)
        if summary:
            counts: dict[str, int] = {}
            for number, word in _PYTEST_COUNT_RE.findall(summary[-1]):
                counts["error" if word.startswith("error") else word] = int(number)
            result["executed_tests"] = (
                counts.get("passed", 0) + counts.get("failed", 0) + counts.get("error", 0)
            )
            result["skipped_tests"] = counts.get("skipped", 0)
        elif ran:
            result["executed_tests"] = int(ran[-1])
            skipped = _UNITTEST_SKIP_RE.findall(output)
            result["skipped_tests"] = int(skipped[-1]) if skipped else 0
    for name, value in _NS_PHASE_RE.findall(output):
        phases[name] = float(value)
    if xcode:
        result["ios_phases"] = {k: v for k, v in phases.items() if k in _IOS_PHASE_KEYS}
    return result


def run_suite_sample(
    command: list[str], *, spec_id: str, arm: str, suite: str, sample: int,
    metrics_dir: Path, xcode: bool = False, output_dir: Path | None = None,
    heavy: bool = False, lease_store: Any = None, heavy_config: Mapping[str, Any] | None = None,
) -> int:
    """Run a suite command transparently and record one sample; return its exit code.

    SPEC-NS-KIT-002-007: a heavy command (config `heavy_suite.command_patterns`) first takes the
    per-host advisory lease and records its gate wait as the `coordination_gate_wait` stage; the
    sample's wall time starts after acquisition. With `output_dir` the full output is persisted
    privately before a bounded summary (path, sha256, head/tail, exit marker) is printed."""
    if heavy:
        try:
            config = dict(heavy_config) if heavy_config is not None else load_heavy_config(
                resolve_kit_root(Path.cwd()) / "config.yaml")
        except Exception:  # noqa: BLE001 - no kit root: defaults
            config = dict(HEAVY_DEFAULTS)
        if is_heavy_command(" ".join(command), config["command_patterns"]):
            store = lease_store if lease_store is not None else CoordinatorLeaseStore()
            with heavy_suite_lease(store, session=lease_session_id(), wait_limit_s=float(config["wait_limit_s"]),
                                   poll_s=float(config["poll_s"])) as lease:
                code = _run_suite_sample(command, spec_id=spec_id, arm=arm, suite=suite, sample=sample,
                                         metrics_dir=metrics_dir, xcode=xcode, output_dir=output_dir)
            _record_gate_wait(metrics_dir, spec_id, lease["gate_wait_s"])
            return code
    return _run_suite_sample(command, spec_id=spec_id, arm=arm, suite=suite, sample=sample,
                             metrics_dir=metrics_dir, xcode=xcode, output_dir=output_dir)


def _record_gate_wait(metrics_dir: Path, spec_id: str, waited_s: float) -> None:
    import record_metrics

    try:
        sidecar = record_metrics.load_timing_sidecar(record_metrics.timing_sidecar_path(metrics_dir, spec_id))
        before = sidecar["stages"].get("coordination_gate_wait")
        total = (before if _positive(before) else 0.0) + waited_s
        record_metrics.append_timing_record(metrics_dir, spec_id, "stage",
                                            {"stage": "coordination_gate_wait", "seconds": round(total, 3)})
    except (ValueError, OSError, TimeoutError) as exc:
        print(f"suite-sample: could not record gate wait: {exc}", file=sys.stderr)


def _run_suite_sample(
    command: list[str], *, spec_id: str, arm: str, suite: str, sample: int,
    metrics_dir: Path, xcode: bool, output_dir: Path | None,
) -> int:
    import time

    import record_metrics

    def load() -> Any:
        try:
            return round(os.getloadavg()[0], 2)
        except (OSError, AttributeError):  # pragma: no cover - platform without getloadavg
            return "unavailable"

    load_start, started = load(), time.monotonic()
    try:
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
        )
    except OSError as exc:
        print(f"suite-sample: cannot launch command: {exc}", file=sys.stderr)
        return 127
    captured: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        if output_dir is None:
            sys.stdout.write(line)
        captured.append(line)
    code = proc.wait()
    wall, load_end = round(time.monotonic() - started, 3), load()
    if output_dir is not None:
        # R6: the full output reaches a durable private file before anything is printed.
        text = "".join(captured)
        stem = f"{spec_id}-{arm}-{suite}-{sample}"
        record_file = persist_private(output_dir, f"{stem}.log", text)
        print(bounded_summary({**record_file, "exit_code": code, "command_exit_marker": f"NS-EXIT={code}"}, text))
    record = {
        "suite": suite, "arm": arm, "sample": sample, "wall_s": wall,
        "load_start": load_start, "load_end": load_end,
        **parse_suite_output("".join(captured), xcode=xcode),
    }
    try:
        record_metrics.append_timing_record(metrics_dir, spec_id, "sample", record)
    except (ValueError, OSError, TimeoutError) as exc:
        print(f"suite-sample: could not record sample: {exc}", file=sys.stderr)
    return code


def _distribution(values: list[float]) -> dict[str, Any] | str:
    if not values:
        return "unavailable"
    import statistics

    ordered = sorted(values)
    p90 = ordered[min(len(ordered) - 1, max(0, -(-len(ordered) * 9 // 10) - 1))]
    return {
        "n": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
        "p90": p90, "max": ordered[-1],
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _default_project_label(metrics_dir: Path) -> str:
    resolved = metrics_dir.resolve()
    if resolved.name == "metrics":
        parent = resolved.parent
        return parent.parent.name if parent.name == ".nightshift" else parent.name
    return resolved.name


def _collect_lane_events(metrics_dir: Path) -> list[dict[str, Any]]:
    """SPEC-NS-KIT-108: `lane_recorded` events from the run streams beside a metrics dir."""
    runs = metrics_dir.resolve().parent / "runs"
    if not runs.is_dir():
        return []
    try:
        from loop_events import load_events
    except ImportError:  # a copy of this module run without its sibling cannot read lanes
        return []

    found: list[dict[str, Any]] = []
    for events_file in sorted(runs.glob("*/events.jsonl")):
        found += [e for e in load_events(events_file) if e.get("event") == "lane_recorded"]
    return found


def _summarize_lanes(events: list[dict[str, Any]]) -> dict[str, Any]:
    lanes: dict[str, dict[str, Any]] = {}
    for event in events:
        lane = event.get("lane")
        if lane not in ("small", "full"):
            continue
        bucket = lanes.setdefault(lane, {"runs": 0, "values": {}, "reasons": {}})
        bucket["runs"] += 1
        for name in ("parent_tool_calls", "worker_wall_s", "verifier_wall_s", "verifier_dispatches"):
            if _is_number(event.get(name)):
                bucket["values"].setdefault(name, []).append(event[name])
        for reason in event.get("redispatch_reasons") or []:
            bucket["reasons"][reason] = bucket["reasons"].get(reason, 0) + 1
    return {
        lane: {
            "runs": b["runs"],
            **{name: _distribution(b["values"].get(name, []))
               for name in ("parent_tool_calls", "worker_wall_s", "verifier_wall_s", "verifier_dispatches")},
            "redispatch_reasons": dict(sorted(b["reasons"].items())),
        }
        for lane, b in sorted(lanes.items())
    }


def build_throughput_report(sources: list[tuple[str, Path]]) -> dict[str, Any]:
    """Aggregate per-project verification distributions from metrics rows (R5).

    Rows lacking the SPEC-NS-KIT-002-001 fields are counted but contribute
    nothing to verification statistics; a statistic with no data is
    `unavailable`, never 0.
    """
    import yaml

    gathered: dict[str, dict[str, Any]] = {}
    lane_events: dict[str, list[dict[str, Any]]] = {}
    for label, directory in sources:
        fallback = label or _default_project_label(directory)
        lane_events.setdefault(fallback, []).extend(_collect_lane_events(directory))
        for path in sorted(directory.glob("*.yaml")):
            try:
                row = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(row, dict) or "task_id" not in row:
                continue
            project = str(row.get("project") or fallback)
            bucket = gathered.setdefault(project, {
                "rows": 0, "instrumented_rows": 0, "wall": [], "share": [], "dispatches": [],
                "reasons": {}, "arms": {},
            })
            bucket["rows"] += 1
            wall = None
            try:
                start = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(row["completed_at"]).replace("Z", "+00:00"))
                if end >= start:
                    wall = (end - start).total_seconds()
                    bucket["wall"].append(wall)
            except (KeyError, ValueError, TypeError):
                pass
            block = row.get("verification")
            if not isinstance(block, dict):
                continue
            bucket["instrumented_rows"] += 1
            dispatches = [d for d in block.get("dispatches") or [] if isinstance(d, dict)]
            if dispatches:
                bucket["dispatches"].append(len(dispatches))
                if _is_number(block.get("duration_s")) and wall:
                    bucket["share"].append(block["duration_s"] / wall)
            for d in dispatches:
                reason = d.get("redispatch_reason")
                if reason:
                    bucket["reasons"][reason] = bucket["reasons"].get(reason, 0) + 1
            counts_by_pair: dict[tuple, int] = {}
            for s in block.get("suites") or []:
                if isinstance(s, dict) and s.get("arm"):
                    key = (str(s["arm"]), s.get("suite"))
                    counts_by_pair[key] = counts_by_pair.get(key, 0) + 1
            for (arm, _suite), count in counts_by_pair.items():
                bucket["arms"].setdefault(arm, []).append(count)
    projects = {}
    for project in sorted(set(lane_events) - set(gathered)):
        if lane_events[project]:
            gathered[project] = {"rows": 0, "instrumented_rows": 0, "wall": [], "share": [],
                                 "dispatches": [], "reasons": {}, "arms": {}}
    for project, b in sorted(gathered.items()):
        projects[project] = {
            "rows": b["rows"],
            "instrumented_rows": b["instrumented_rows"],
            "wall_s": _distribution(b["wall"]),
            "verification_share_of_wall": _distribution(b["share"]),
            "dispatches_per_spec": _distribution(b["dispatches"]),
            "redispatch_reasons": dict(sorted(b["reasons"].items())),
            "samples_per_arm": {arm: _distribution(v) for arm, v in sorted(b["arms"].items())},
        }
        lanes = _summarize_lanes(lane_events.get(project, []))
        if lanes:
            projects[project]["lanes"] = lanes
    return {"schema_version": 1, "projects": projects}


def _fmt_distribution(value: Any, *, share: bool = False) -> str:
    if value == "unavailable":
        return "unavailable"

    def one(x: float) -> str:
        return f"{x:.0%}" if share else f"{x:g}"

    return (f"n={value['n']} min={one(value['min'])} median={one(value['median'])} "
            f"p90={one(value['p90'])} max={one(value['max'])}")


def render_throughput_report(data: dict[str, Any]) -> str:
    lines = ["# Verification throughput report", ""]
    for project, p in data["projects"].items():
        lines += [
            f"## {project}",
            f"- metrics rows: {p['rows']} (instrumented: {p['instrumented_rows']})",
            f"- wall time per row (s): {_fmt_distribution(p['wall_s'])}",
            f"- verification share of wall: {_fmt_distribution(p['verification_share_of_wall'], share=True)}",
            f"- dispatches per spec: {_fmt_distribution(p['dispatches_per_spec'])}",
            "- re-dispatch reasons: "
            + (", ".join(f"{k}={v}" for k, v in p["redispatch_reasons"].items()) or "none recorded"),
        ]
        arms = p["samples_per_arm"]
        if arms:
            lines += [f"- samples per arm ({arm}): {_fmt_distribution(v)}" for arm, v in arms.items()]
        else:
            lines.append("- samples per arm: unavailable")
        for lane, lv in p.get("lanes", {}).items():
            lines.append(f"- lane {lane}: runs={lv['runs']}")
            lines += [f"  - {name}: {_fmt_distribution(lv[name])}" for name in
                      ("parent_tool_calls", "worker_wall_s", "verifier_wall_s", "verifier_dispatches")]
            lines.append("  - re-dispatch reasons: "
                         + (", ".join(f"{k}={v}" for k, v in lv["redispatch_reasons"].items()) or "none recorded"))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SPEC-223: parent context spend by verification lane, read from recorded telemetry.
#
# Read-only.  The method below is fixed in code (and in the spec) before any report is read, so a
# later reader cannot choose arms or thresholds after seeing the data.  Arm A = `lane: small`,
# arm B = `lane: full`, both independently verified; a run lacking a lane tag is never given an arm.
# ---------------------------------------------------------------------------

LANE_SPEND_METHOD: dict[str, Any] = {
    "arms": {"A": "lane: small", "B": "lane: full"},
    "admitted_resolution_kinds": [
        "implemented_verified_merged", "implemented_verified_remediated_merged", "verifier-dispatched",
    ],
    "min_n_per_arm": 5,
    "metric": "parent tool calls per run",
    "ratio_threshold": 0.7,
    "permutations": 10000,
    "permutation_seed": 223,
    "alpha": 0.05,
    "arm_b_comparability": "at most 4 ACs and at most one non-support scope.write path (SPEC-NS-KIT-108 rule)",
    "p_value": "two-sided permutation test on the difference of medians, (extreme + 1) / (permutations + 1)",
}
_LANE_KINDS = frozenset(LANE_SPEND_METHOD["admitted_resolution_kinds"])
_LANE_EXCLUSIONS = (
    "blocked", "reverted", "predates_lane_telemetry", "missing_lane_tag",
    "resolution_kind_not_independently_verified", "conflicting_counts", "missing_parent_tool_calls",
    "spec_not_lane_comparable",
)
_LANE_SUPPORT_PATH_RE = re.compile(
    r"^(?:canonical/|\.nightshift/)?(?:(?:tests|reports|specs|red-proofs|release-handoffs)/|CHANGELOG\.md$|release-manifest\.json$)"
)
_LANE_SPEC_ID_RE = re.compile(r"\b((?:SPEC|BUG)-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b")
_LANE_TRAILER_RE = re.compile(r"^(Nightshift-[A-Za-z-]+):\s*(.*?)\s*$")


def _lane_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0 and int(value) == value:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _lane_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def collect_lane_trailers(repo: Path, rev: str) -> list[dict[str, Any]]:
    """One record per commit at or below `rev` that carries a tool-call or resolution-kind trailer."""
    out = _lane_git(
        repo, "log", rev, "--grep=^Nightshift-Parent-Tool-Calls", "--grep=^Nightshift-Resolution-Kind",
        "--format=%H%x1f%cI%x1f%s%x1f%B%x1e",
    ).stdout
    cutoff = _lane_cutoff(repo, rev)
    reverted: set[str] = set()
    for body in _lane_git(repo, "log", rev, "--grep=This reverts commit", "--format=%B%x1e").stdout.split("\x1e"):
        reverted.update(m[:8] for m in re.findall(r"This reverts commit ([0-9a-f]{7,40})", body))
    records = []
    for chunk in out.split("\x1e"):
        if not chunk.strip():
            continue
        sha, when, subject, body = (chunk.lstrip("\n").split("\x1f", 3) + ["", "", ""])[:4]
        trailers = {}
        for line in body.splitlines():
            match = _LANE_TRAILER_RE.match(line)
            if match:
                trailers[match.group(1)] = match.group(2)
        found = _LANE_SPEC_ID_RE.search(trailers.get("Nightshift-Spec-Id", "") or subject)
        if not found:
            continue
        records.append({
            "commit": sha[:8], "time": when, "subject": subject, "spec_id": found.group(1),
            "parent_tool_calls": _lane_int(trailers.get("Nightshift-Parent-Tool-Calls")),
            "resolution_kind": trailers.get("Nightshift-Resolution-Kind") or None,
            "blocker_class": trailers.get("Nightshift-Blocker-Class") or None,
            "run_id": trailers.get("Nightshift-Run-Id") or None,
            "reverted": any(sha.startswith(r) for r in reverted),
            "predates_lane": bool(cutoff) and _lane_git(repo, "merge-base", "--is-ancestor", sha, cutoff,
                                                         check=False).returncode == 0,
            "_sha": sha,
        })
    return records


def _lane_cutoff(repo: Path, rev: str) -> str | None:
    """The earliest commit that introduced the `lane_recorded` event (SPEC-NS-KIT-108)."""
    out = _lane_git(repo, "log", rev, "-S", "lane_recorded", "--format=%H", "--", "loop_events.py",
                    "canonical/loop_events.py", check=False).stdout.split()
    return out[-1] if out else None


def _lane_spec_file(specs_dir: Path, spec_id: str) -> Path | None:
    if not specs_dir.is_dir():
        return None
    for path in sorted(specs_dir.iterdir()):
        stem = path.name.rsplit(".", 1)[0]
        if stem == spec_id or (stem.startswith(spec_id + "-") and not stem[len(spec_id) + 1:][:1].isdigit()):
            return path
    return None


def lane_spec_shape(text: str) -> dict[str, Any]:
    """AC count and the non-support `scope.write` paths of a spec."""
    section = re.search(r"^## Acceptance Criteria\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    acs = len(re.findall(r"^- \[[ xX]\] AC\d+", section.group(1), re.M)) if section else 0
    paths: list[str] = []
    lines = text.split("---", 2)[1].splitlines() if text.startswith("---") else []
    in_write = False
    for line in lines:
        if re.match(r"^\s+write:\s*$", line):
            in_write = True
        elif in_write and re.match(r"^\s*-\s+\S", line):
            paths.append(line.split("-", 1)[1].strip())
        elif in_write:
            break
    return {"ac_count": acs, "module_paths": [p for p in paths if not _LANE_SUPPORT_PATH_RE.match(p)]}


def _lane_events(runs_dir: Path | None) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    lanes: dict[str, list[dict]] = {}
    tokens: dict[str, list[dict]] = {}
    if runs_dir is None or not runs_dir.is_dir():
        return lanes, tokens
    for events_file in sorted(runs_dir.glob("*/events.jsonl")):
        try:
            lines = events_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or not event.get("spec_id"):
                continue
            item = {**event, "_run": events_file.parent.name}
            if event.get("event") == "lane_recorded":
                lanes.setdefault(str(event["spec_id"]), []).append(item)
            elif event.get("event") == "token_usage":
                tokens.setdefault(str(event["spec_id"]), []).append(item)
    return lanes, tokens


def _lane_metrics(metrics_dir: Path | None) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if metrics_dir is None or not metrics_dir.is_dir():
        return rows
    try:
        import yaml
    except ImportError:
        return rows
    for path in sorted(metrics_dir.glob("*.yaml")):
        try:
            row = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        block = row.get("verification") if isinstance(row, dict) else None
        if isinstance(block, dict) and row.get("task_id"):
            rows[str(row["task_id"])] = block
    return rows


def _lane_runs(trailers: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group commits into runs: per spec and blocked/not-blocked; mark commits are the sources when present."""
    groups: dict[tuple[str, bool], list[dict]] = {}
    for rec in sorted(trailers, key=lambda r: (r["time"], r["commit"])):
        blocked = "blocked" in rec["subject"] or (rec.get("blocker_class") not in (None, "", "none", "absent"))
        groups.setdefault((rec["spec_id"], blocked), []).append({**rec, "_blocked": blocked})
    runs = []
    for key in sorted(groups):
        members = groups[key]
        marks = [m for m in members if re.search(r"\bmark \S+ (?:done|blocked)", m["subject"])]
        runs.append(marks or members)
    return runs


def _quartile_summary(values: list[float]) -> dict[str, Any]:
    import statistics

    ordered = sorted(values)
    low, _mid, high = statistics.quantiles(ordered, n=4, method="inclusive") if len(ordered) > 1 else (
        ordered[0], ordered[0], ordered[0])
    return {"median": round(statistics.median(ordered), 3), "iqr": [round(low, 3), round(high, 3)]}


def _permutation_p(a: list[float], b: list[float]) -> float:
    import random
    import statistics

    seed, count = LANE_SPEND_METHOD["permutation_seed"], LANE_SPEND_METHOD["permutations"]
    observed = abs(statistics.median(a) - statistics.median(b))
    rng, pool, extreme = random.Random(seed), list(a) + list(b), 0
    for _ in range(count):
        rng.shuffle(pool)
        if abs(statistics.median(pool[: len(a)]) - statistics.median(pool[len(a):])) >= observed - 1e-9:
            extreme += 1
    return round((extreme + 1) / (count + 1), 3)


def build_lane_spend_report(
    *, project: str, trailers: list[dict[str, Any]], runs_dir: Path | None, metrics_dir: Path | None,
    spec_reader: Any, rev: str | None = None,
) -> dict[str, Any]:
    lane_events, token_events = _lane_events(runs_dir)
    metrics = _lane_metrics(metrics_dir)
    commit_runs = _lane_runs(trailers)
    by_spec: dict[str, list[list[dict]]] = {}
    for members in commit_runs:
        by_spec.setdefault(members[0]["spec_id"], []).append(members)
    # Pair lane events to terminal runs from the newest end: the last event belongs to the last run.
    paired: dict[int, dict] = {}
    unpaired: list[tuple[str, dict]] = []
    for spec_id in sorted(set(by_spec) | set(lane_events)):
        runs, events = by_spec.get(spec_id, []), lane_events.get(spec_id, [])
        runs = sorted(runs, key=lambda m: m[-1]["time"])
        for index in range(1, max(len(runs), len(events)) + 1):
            run = runs[-index] if index <= len(runs) else None
            event = events[-index] if index <= len(events) else None
            if run is not None and event is not None:
                paired[id(run)] = event
            elif event is not None:
                unpaired.append((spec_id, event))
    rows: list[dict[str, Any]] = []
    units = [(m[0]["spec_id"], m, paired.get(id(m))) for m in commit_runs] + [(s, None, e) for s, e in unpaired]
    for spec_id, members, event in units:
        row = _lane_row(spec_id, members, event, token_events, metrics, spec_reader)
        rows.append(row)
    rows.sort(key=lambda r: (r["spec_id"], r["commit"] or "", r["run"] or ""))
    return _lane_verdict(project, rev, rows)


def _lane_row(spec_id, members, event, token_events, metrics, spec_reader) -> dict[str, Any]:
    sources: set[str] = set()
    conflicts: list[dict[str, Any]] = []
    latest = members[-1] if members else None
    row: dict[str, Any] = {
        "spec_id": spec_id, "commit": latest["commit"] if latest else None,
        "run": event["_run"] if event else None, "lane": None, "arm": None, "exclusion_reason": None,
        "resolution_kind": None, "parent_tool_calls": None, "ac_count": None, "verifier_dispatches": None,
        "verifier_wall_s": None, "redispatch_reasons": [], "parent_tokens": None,
    }
    calls: dict[str, int] = {}
    if members:
        sources.add("trailer")
        for m in members:
            value = _lane_int(m.get("parent_tool_calls"))
            if value is not None:
                calls.setdefault("trailer", value)
                if calls["trailer"] != value:
                    conflicts.append({"field": "parent_tool_calls", "values": {"trailer": calls["trailer"],
                                                                                 "trailer:" + m["commit"]: value}})
        row["resolution_kind"] = next((m["resolution_kind"] for m in reversed(members) if m.get("resolution_kind")), None)
    if event:
        sources.add("event:lane_recorded")
        row["lane"] = event.get("lane") if event.get("lane") in ("small", "full") else None
        value = _lane_int(event.get("parent_tool_calls"))
        if value is not None:
            calls["event"] = value
        row["verifier_dispatches"] = _lane_int(event.get("verifier_dispatches"))
        wall = event.get("verifier_wall_s")
        row["verifier_wall_s"] = round(wall, 3) if _is_number(wall) else None
        row["redispatch_reasons"] = sorted(event.get("redispatch_reasons") or [])
        measured = [t for t in token_events.get(spec_id, []) if t["_run"] == event["_run"] and t.get("role") == "parent"
                    and t.get("measurement_state") == "measured"
                    and _is_number(t.get("input_tokens")) and _is_number(t.get("output_tokens"))]
        if measured:
            sources.add("token_usage")
            row["parent_tokens"] = int(sum(t["input_tokens"] + t["output_tokens"] for t in measured))
    block = metrics.get(spec_id)
    if block is not None:
        sources.add("metrics")
        dispatches = [d for d in block.get("dispatches") or [] if isinstance(d, dict)]
        if row["verifier_dispatches"] is None and dispatches:
            row["verifier_dispatches"] = len(dispatches)
        elif dispatches and row["verifier_dispatches"] != len(dispatches):
            conflicts.append({"field": "verifier_dispatches",
                              "values": {"event": row["verifier_dispatches"], "metrics": len(dispatches)}})
        if row["verifier_wall_s"] is None and _is_number(block.get("duration_s")):
            row["verifier_wall_s"] = round(block["duration_s"], 3)
    seen = {k: v for k, v in calls.items() if not k.startswith("trailer:")}
    if len(set(seen.values())) > 1:
        conflicts = [c for c in conflicts if c["field"] != "parent_tool_calls"]
        conflicts.append({"field": "parent_tool_calls", "values": dict(sorted(seen.items()))})
    row["conflicts"] = conflicts
    row["parent_tool_calls"] = None if conflicts and any(c["field"] == "parent_tool_calls" for c in conflicts) \
        else next(iter(seen.values()), None)
    row["sources"] = sorted(sources)
    text = spec_reader(spec_id, latest)
    shape = lane_spec_shape(text) if text else None
    row["ac_count"] = shape["ac_count"] if shape else None
    row["exclusion_reason"] = _lane_exclusion(row, members, shape)
    if row["exclusion_reason"] is None:
        row["arm"] = "A" if row["lane"] == "small" else "B"
    row["_historical"] = row["exclusion_reason"] == "predates_lane_telemetry"
    return row


def _lane_exclusion(row, members, shape) -> str | None:
    if members and any(m["_blocked"] for m in members):
        return "blocked"
    if members and any(m.get("reverted") for m in members):
        return "reverted"
    if row["lane"] is None:
        if members and any(m.get("predates_lane") for m in members):
            return "predates_lane_telemetry"
        return "missing_lane_tag"
    if row["resolution_kind"] not in _LANE_KINDS:
        return "resolution_kind_not_independently_verified"
    if row["conflicts"]:
        return "conflicting_counts"
    if row["parent_tool_calls"] is None:
        return "missing_parent_tool_calls"
    if row["lane"] == "full" and (shape is None or shape["ac_count"] > 4 or len(shape["module_paths"]) > 1):
        return "spec_not_lane_comparable"
    return None


def _lane_verdict(project: str, rev: str | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {"A": [], "B": []}
    for row in rows:
        if row["arm"]:
            arms[row["arm"]].append(row["parent_tool_calls"])
    historical = [r for r in rows if r.pop("_historical")]
    kinds = [r for r in historical if r["resolution_kind"] in _LANE_KINDS and r["parent_tool_calls"] is not None]
    data: dict[str, Any] = {
        "schema_version": 1, "project": project, "rev": rev, "method": LANE_SPEND_METHOD,
        "min_n_per_arm": LANE_SPEND_METHOD["min_n_per_arm"],
        "arms": {k: {"n": len(v), "values": sorted(v)} for k, v in arms.items()},
        "runs": rows,
        "exclusion_counts": {r: sum(1 for x in rows if x["exclusion_reason"] == r) for r in _LANE_EXCLUSIONS},
        "historical_full_lane": {
            "n": len(kinds), "runs": [{k: r[k] for k in ("spec_id", "commit", "parent_tool_calls", "resolution_kind")}
                                      for r in kinds],
            **(_quartile_summary([r["parent_tool_calls"] for r in kinds]) if kinds else {}),
        },
    }
    if min(len(arms["A"]), len(arms["B"])) < LANE_SPEND_METHOD["min_n_per_arm"]:
        data["verdict"] = "insufficient data"
        return data
    for name in ("A", "B"):
        data["arms"][name].update(_quartile_summary(arms[name]))
    ratio = data["arms"]["A"]["median"] / data["arms"]["B"]["median"] if data["arms"]["B"]["median"] else None
    p_value = _permutation_p(arms["A"], arms["B"])
    data["effect"] = {"ratio": round(ratio, 3) if ratio is not None else None}
    data["p_value"] = p_value
    holds = ratio is not None and ratio <= LANE_SPEND_METHOD["ratio_threshold"] and p_value < LANE_SPEND_METHOD["alpha"]
    data["verdict"] = "holds" if holds else "does not hold"
    secondary: dict[str, Any] = {}
    for name in ("A", "B"):
        group = [r for r in rows if r["arm"] == name]
        reasons: dict[str, int] = {}
        for r in group:
            for reason in r["redispatch_reasons"]:
                reasons[reason] = reasons.get(reason, 0) + 1
        secondary[name] = {
            f: [r[f] for r in group if r[f] is not None]
            for f in ("verifier_dispatches", "verifier_wall_s", "parent_tokens")
        }
        secondary[name]["redispatch_reasons"] = dict(sorted(reasons.items()))
    data["secondary"] = secondary
    return data


def render_lane_spend_report(data: dict[str, Any]) -> str:
    m = data["method"]
    lines = [
        f"# Lane spend report: {data['project']}", "",
        f"Source revision: {data['rev'] or 'not git-backed'}", "",
        "## Method (pre-declared)", "",
        f"- Arms: A = {m['arms']['A']}, B = {m['arms']['B']}; both independently verified "
        f"({', '.join(m['admitted_resolution_kinds'])}).",
        f"- Arm B comparability: {m['arm_b_comparability']}.",
        f"- Minimum N: {m['min_n_per_arm']} admitted runs per arm; otherwise `insufficient data`.",
        f"- Metric: {m['metric']}. Holds when median(A) <= {m['ratio_threshold']} x median(B) and "
        f"p < {m['alpha']} ({m['p_value']}; {m['permutations']} permutations, seed {m['permutation_seed']}).",
        "", f"## Verdict: {data['verdict']}", "", "## Arms", "",
    ]
    for name in ("A", "B"):
        arm = data["arms"][name]
        line = f"- {name}: n={arm['n']} values={arm['values']}"
        if "median" in arm:
            line += f" median={arm['median']:g} iqr={arm['iqr'][0]:g}-{arm['iqr'][1]:g}"
        lines.append(line)
    if "effect" in data:
        lines.append(f"- ratio (A/B median): {data['effect']['ratio']}; p_value: {data['p_value']}")
        for name in ("A", "B"):
            sec = data["secondary"][name]
            lines.append(f"- secondary {name}: verifier_dispatches={sec['verifier_dispatches']} "
                         f"verifier_wall_s={sec['verifier_wall_s']} parent_tokens={sec['parent_tokens']} "
                         f"redispatch_reasons={sec['redispatch_reasons']}")
    hist = data["historical_full_lane"]
    lines += ["", "## Historical full-lane trailers (before lane telemetry; not an arm)", "",
              f"- n={hist['n']}" + (f" median={hist['median']:g} iqr={hist['iqr'][0]:g}-{hist['iqr'][1]:g}"
                                    if hist["n"] else "")]
    lines += ["", "## Exclusions", ""]
    lines += [f"- {reason}: {count}" for reason, count in data["exclusion_counts"].items()]
    lines += ["", "## Runs", "", "| spec | commit | lane | kind | calls | arm / exclusion | sources |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in data["runs"]:
        lines.append(f"| {r['spec_id']} | {r['commit'] or '-'} | {r['lane'] or '-'} | {r['resolution_kind'] or '-'} | "
                     f"{r['parent_tool_calls'] if r['parent_tool_calls'] is not None else '-'} | "
                     f"{r['arm'] or r['exclusion_reason']} | {', '.join(r['sources'])} |")
    conflicts = [r for r in data["runs"] if r["conflicts"]]
    if conflicts:
        lines += ["", "## Conflicts", ""]
        lines += [f"- {r['spec_id']}: {json.dumps(c, sort_keys=True)}" for r in conflicts for c in r["conflicts"]]
    return "\n".join(lines) + "\n"


def lane_spend_main(args: argparse.Namespace) -> int:
    project = args.project or _default_project_label(args.metrics_dir)
    repo = args.git_repo
    if args.trailers_file is not None:
        try:
            trailers = [json.loads(ln) for ln in args.trailers_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, ValueError) as exc:
            print(f"lane-spend-report: cannot read trailers file: {exc}", file=sys.stderr)
            return 2
        rev = None
    elif repo is not None:
        try:
            rev = _lane_git(repo, "rev-parse", args.rev).stdout.strip()
            trailers = collect_lane_trailers(repo, rev)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"lane-spend-report: cannot read git history: {exc}", file=sys.stderr)
            return 2
    else:
        print("lane-spend-report requires --git-repo or --trailers-file", file=sys.stderr)
        return 2

    def spec_reader(spec_id: str, record: dict | None) -> str | None:
        if repo is not None and args.trailers_file is None and record and record.get("_sha"):
            for base in args.specs_dir_in_repo:
                names = _lane_git(repo, "ls-tree", "--name-only", record["_sha"], base + "/", check=False).stdout.split()
                for name in names:
                    stem = Path(name).name.rsplit(".", 1)[0]
                    if stem == spec_id or (stem.startswith(spec_id + "-") and not stem[len(spec_id) + 1:][:1].isdigit()):
                        shown = _lane_git(repo, "show", f"{record['_sha']}:{name}", check=False)
                        return shown.stdout if shown.returncode == 0 else None
            return None
        found = _lane_spec_file(args.specs_dir, spec_id) if args.specs_dir else None
        return found.read_text(encoding="utf-8") if found else None

    runs_dir = args.runs_dir if args.runs_dir is not None else args.metrics_dir.resolve().parent / "runs"
    data = build_lane_spend_report(project=project, trailers=trailers, runs_dir=runs_dir,
                                   metrics_dir=args.metrics_dir, spec_reader=spec_reader, rev=rev)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n" if args.json else render_lane_spend_report(data)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# SPEC-NS-KIT-002-002: main test-status ledger.
#
# A git-tracked, identity-bound record of the per-test status of main. It lets the protocol
# run the full suite once, re-run only what a fix could affect, excuse a known failure only
# when it is exactly the same failure, and reuse a result only when every identity input
# provably matches. Design rule (X1): anything not proven to match -- identity, digest,
# coverage, staleness -- means no reuse; callers fall back to a real run. Every function fails
# closed; none turns uncertainty into a pass. Lives in this managed module so it ships with
# the kit (a separate module would need a nightshift-sync.py release-set entry).
# ---------------------------------------------------------------------------

LEDGER_SCHEMA_VERSION = 1
LEDGER_RELATIVE_PATH = ".nightshift/test-status-ledger.json"
PROJECTED_RELATIVE_PATH = ".nightshift-ledger/baseline.json"
STATUSES = ("pass", "fail", "flaky", "unavailable")
NON_PASS = ("fail", "flaky", "unavailable")
DEFAULT_ENTRY_EXPIRY_DAYS = 30
DEFAULT_RECEIPT_TTL_DAYS = 7
LABELS = ("executed", "reused")
BUG_LINK_RE = re.compile(r"^(?:BUG|SPEC)-[A-Za-z0-9][A-Za-z0-9-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Paths whose change never alters what a test can observe: the spec corpus and
# run reports. Deliberately narrow; docs, config, resources and gate scripts all
# stay inside the identity.
_EXEMPT_RE = re.compile(r"^(?:canonical/|\.nightshift/)?(?:specs|reports)/")

# Changes that make "which tests are affected" unknowable, so a full run is
# forced (R4). Compared case-insensitively against the full relative path.
DEFAULT_FORCE_FULL_PATTERNS = (
    "*.xcodeproj/*", "*.pbxproj", "*.xcworkspace/*", "*.xcconfig", "*.plist",
    "*.entitlements", "*.xcassets/*", "package.swift", "package.resolved", "podfile*",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt", "*conftest.py",
    "*config.yaml", "makefile", "*/resources/*", "resources/*", "*helper*",
    "*lifecycle*", "*appdelegate*", "*persistence*", "*migration*",
)
_TEST_FILE_RE = re.compile(
    r"(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.py|[^/]*Tests?\.swift|[^/]*Tests?\.m)$"
)


class LedgerError(ValueError):
    """The ledger or a record could not be built or trusted."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- identity


def _ledger_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode:
        raise LedgerError(result.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return result.stdout


def compute_inputs_digest(repo: Path, ref: str, *, exempt: Iterable[str] = ()) -> str:
    """Digest every tracked path at *ref* except spec/report corpora and *exempt* paths."""
    skipped = {path.strip("/") for path in exempt}
    rows = []
    for entry in _ledger_git(repo, "ls-tree", "-r", "-z", ref).split(b"\0"):
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"\t")
        path = raw_path.decode("utf-8", "surrogateescape")
        if path in skipped or _EXEMPT_RE.match(path):
            continue
        rows.append(f"{path}\0{meta.split()[2].decode()}")
    return sha256_hex("\n".join(sorted(rows)).encode("utf-8", "surrogateescape"))


def default_toolchain() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "runtime": sys.implementation.name,
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "sdk": "unavailable",
    }


def build_identity(
    repo: Path,
    ref: str,
    *,
    command: str,
    selection: str = "full",
    flags: Iterable[str] = (),
    env: Mapping[str, str] | None = None,
    toolchain: Mapping[str, str] | None = None,
    device_policy: Mapping[str, str] | None = None,
    host: str | None = None,
    exempt: Iterable[str] = (),
) -> dict[str, Any]:
    """The full identity a result is bound to (parent spec, Design decisions)."""
    if not isinstance(command, str) or not command.strip():
        raise LedgerError("identity needs the exact test command")
    return {
        "inputs_digest": compute_inputs_digest(repo, ref, exempt=exempt),
        "command": command,
        "selection": selection,
        "flags": list(flags),
        "env": dict(sorted((env or {}).items())),
        "toolchain": dict(sorted((toolchain or default_toolchain()).items())),
        "device_policy": dict(sorted((device_policy or {"simulator": "none", "data": "fresh-per-run"}).items())),
        "host": host if host is not None else platform.node(),
    }


def identity_digest(identity: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(identity))


# --------------------------------------------------------------------------- parsing results

_NORMALISERS = (
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"/(?:private/)?(?:var|tmp)/[^\s\"']+"), "<tmp>"),
    (re.compile(r"\bline \d+"), "line <n>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b"), "<dur>"),
)


def failure_signature(kind: str, message: str) -> str:
    """Stable signature of one failure: type plus normalised first message line."""
    first = next((line.strip() for line in (message or "").splitlines() if line.strip()), "")
    for pattern, replacement in _NORMALISERS:
        first = pattern.sub(replacement, first)
    return sha256_hex(f"{kind.strip()}\0{first}".encode("utf-8"))[:16]


def parse_junit(xml_bytes: bytes) -> tuple[list[dict[str, Any]], int]:
    """Per-test results from JUnit XML, plus the total the report itself claims.

    Skipped tests are `unavailable`, never `pass`. Test IDs are
    ``file::Class::name`` when the report carries ``file``, else
    ``classname::name``.
    """
    root = ET.fromstring(xml_bytes)
    results: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        name = case.get("name", "")
        path = case.get("file")
        klass = classname.rsplit(".", 1)[-1] if classname else ""
        test_id = "::".join(part for part in (path or classname, klass if path else "", name) if part)
        item: dict[str, Any] = {"id": test_id, "duration_s": float(case.get("time") or 0.0)}
        failure = next((child for child in case if child.tag in ("failure", "error")), None)
        if failure is not None:
            item["status"] = "fail"
            item["signature"] = failure_signature(
                failure.get("type") or failure.tag, failure.get("message") or (failure.text or "")
            )
        elif any(child.tag == "skipped" for child in case):
            item["status"] = "unavailable"
        else:
            item["status"] = "pass"
        results.append(item)
    claimed = 0
    for suite in ([root] if root.tag == "testsuite" else root.iter("testsuite")):
        claimed += int(suite.get("tests") or 0)
    return results, claimed


# --------------------------------------------------------------------------- records


def _receipt_digest(record: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json({k: v for k, v in record.items() if k != "receipt_digest"}))


def build_record(
    identity: Mapping[str, Any],
    results: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    commit: str,
    native_result: Mapping[str, Any],
    evidence_digest: str,
    now: datetime,
    wrapper_output: Mapping[str, Any] | None = None,
    bug_links: Mapping[str, str] | None = None,
    previous: Mapping[str, Any] | None = None,
    reported_total: int | None = None,
    label: str = "executed",
    entry_expiry_days: int = DEFAULT_ENTRY_EXPIRY_DAYS,
    receipt_ttl_days: int = DEFAULT_RECEIPT_TTL_DAYS,
) -> dict[str, Any]:
    """Build a sealed ledger record. Every non-pass entry must link a BUG spec (R2)."""
    if label not in LABELS:
        raise LedgerError(f"unknown label {label!r}")
    links = dict(bug_links or {})
    prior_entries = (previous or {}).get("tests") if isinstance(previous, Mapping) else None
    tests: dict[str, dict[str, Any]] = {}
    for item in results:
        test_id, status = item.get("id"), item.get("status")
        if not isinstance(test_id, str) or not test_id or status not in STATUSES:
            raise LedgerError(f"invalid result entry: {item!r}")
        if test_id in tests:
            raise LedgerError(f"duplicate test id {test_id!r}")
        entry: dict[str, Any] = {
            "status": status,
            "duration_s": round(float(item.get("duration_s") or 0.0), 3),
        }
        if "signature" in item:
            entry["signature"] = str(item["signature"])
        if status in NON_PASS:
            old = prior_entries.get(test_id) if isinstance(prior_entries, Mapping) else None
            carried = (
                isinstance(old, Mapping) and old.get("status") == status
                and old.get("signature") == entry.get("signature")
            )
            bug = links.get(test_id) or (old.get("bug") if carried else None)
            if not isinstance(bug, str) or not BUG_LINK_RE.fullmatch(bug):
                raise LedgerError(f"non-pass entry {test_id!r} needs a BUG spec link")
            first_seen = old.get("first_seen") if carried else None
            first_seen = first_seen if _parse_iso(first_seen) else _iso(now)
            expires = old.get("expires_at") if carried and _parse_iso(old.get("expires_at")) else (
                _iso(_parse_iso(first_seen) + timedelta(days=entry_expiry_days))  # type: ignore[operator]
            )
            entry.update({"bug": bug, "first_seen": first_seen, "expires_at": expires})
        tests[test_id] = entry
    executed = sorted(i for i, e in tests.items() if e["status"] != "unavailable")
    counts = {status: sum(1 for e in tests.values() if e["status"] == status) for status in STATUSES}
    counts["executed"] = len(executed)
    # R7: totals never imply a pass. Coverage is full only when the run accounted for
    # exactly the tests it claims and none was skipped, timed out or not executed.
    full = (
        bool(tests)
        and counts["unavailable"] == 0
        and (reported_total is None or reported_total == len(tests))
        and identity.get("selection") == "full"
    )
    record: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "label": label,
        "created": _iso(now),
        "expires_at": _iso(now + timedelta(days=receipt_ttl_days)),
        "commit": commit,
        "identity": copy.deepcopy(dict(identity)),
        "identity_digest": identity_digest(identity),
        "coverage": "full" if full else "partial",
        "executed_ids": executed,
        "counts": counts,
        "native_result": dict(native_result),
        "wrapper_output": dict(wrapper_output or {}),
        "evidence_digest": evidence_digest,
        "originating_run": run_id,
        "tests": dict(sorted(tests.items())),
    }
    record["receipt_digest"] = _receipt_digest(record)
    return record


def verify_record(record: Any) -> list[str]:
    """Structural and integrity errors; an empty list means the receipt is trusted."""
    if not isinstance(record, dict):
        return ["record is not an object"]
    errors: list[str] = []
    if record.get("schema_version") != LEDGER_SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if record.get("label") not in LABELS:
        errors.append("label must be executed or reused")
    for key in ("identity", "tests", "native_result", "counts"):
        if not isinstance(record.get(key), dict):
            errors.append(f"{key} must be an object")
    if errors:
        return errors
    if not SHA256_RE.fullmatch(str(record.get("receipt_digest", ""))) or record["receipt_digest"] != _receipt_digest(record):
        errors.append("receipt digest does not match record content")
    if record.get("identity_digest") != identity_digest(record["identity"]):
        errors.append("identity digest does not match identity")
    if not SHA256_RE.fullmatch(str(record.get("evidence_digest", ""))):
        errors.append("evidence_digest missing or malformed")
    if not record.get("originating_run"):
        errors.append("originating_run missing")
    if _parse_iso(record.get("created")) is None or _parse_iso(record.get("expires_at")) is None:
        errors.append("created/expires_at missing or malformed")
    for test_id, entry in record["tests"].items():
        if not isinstance(entry, dict) or entry.get("status") not in STATUSES:
            errors.append(f"{test_id}: invalid status")
            continue
        if entry["status"] in NON_PASS:
            if not BUG_LINK_RE.fullmatch(str(entry.get("bug", ""))):
                errors.append(f"{test_id}: non-pass entry has no BUG link")
            if _parse_iso(entry.get("first_seen")) is None or _parse_iso(entry.get("expires_at")) is None:
                errors.append(f"{test_id}: non-pass entry needs age and expiry")
    counts = record["counts"]
    for status in STATUSES:
        if counts.get(status) != sum(1 for e in record["tests"].values() if e.get("status") == status):
            errors.append(f"counts.{status} disagrees with entries")
    if record.get("executed_ids") != sorted(
        i for i, e in record["tests"].items() if e.get("status") != "unavailable"
    ):
        errors.append("executed_ids disagrees with entries")
    if record.get("coverage") == "full" and counts.get("unavailable"):
        errors.append("full coverage cannot contain unavailable tests")
    return errors


def entry_active(entry: Mapping[str, Any], now: datetime) -> bool:
    expiry = _parse_iso(entry.get("expires_at"))
    return expiry is not None and expiry > now


# --------------------------------------------------------------------------- decisions


def reuse_decision(record: Any, identity: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """May this record stand in for a real full run of *identity*? (R5/R6.)"""
    errors = verify_record(record)
    if errors:
        return {"reuse": False, "reason": "untrusted_receipt", "detail": errors[0]}
    digest = record["receipt_digest"]
    if record["identity_digest"] != identity_digest(identity):
        return {"reuse": False, "reason": "identity_changed", "record_digest": digest}
    if record.get("coverage") != "full" or record["counts"].get("unavailable"):
        return {"reuse": False, "reason": "partial_coverage", "record_digest": digest}
    expiry = _parse_iso(record["expires_at"])
    if expiry is None or expiry <= now:
        return {"reuse": False, "reason": "stale_receipt", "record_digest": digest}
    return {
        "reuse": True, "reason": "identity_match", "label": "reused",
        "record_digest": digest, "identity_digest": record["identity_digest"],
        "originating_run": record["originating_run"], "evidence_digest": record["evidence_digest"],
    }


def _owns(test_id: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if not pattern:
            continue
        if test_id == pattern or test_id.startswith((pattern + "::", pattern + "/", pattern + ".")):
            return True
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(test_id, pattern):
            return True
    return False


def classify_failures(
    record: Any,
    current_failures: Mapping[str, str | None],
    *,
    now: datetime,
    owned: Iterable[str] = (),
    obligations: Iterable[str] = (),
) -> dict[str, Any]:
    """Excuse only the exact same test failing with the same signature (R3).

    Everything else is a regression. A test the spec changes or owns, and any
    current AC/safety/NFR obligation, is never excused.
    """
    owned, obligations = list(owned), list(obligations)
    trusted = not verify_record(record)
    tests = record["tests"] if trusted else {}
    excused: list[str] = []
    regressions: list[dict[str, str]] = []
    for test_id, signature in sorted(current_failures.items()):
        entry = tests.get(test_id)
        if not trusted:
            reason = "untrusted_ledger"
        elif _owns(test_id, owned):
            reason = "spec_owned"
        elif _owns(test_id, obligations):
            reason = "obligation"
        elif not isinstance(entry, dict) or entry.get("status") not in ("fail", "flaky"):
            reason = "new_failure"
        elif not entry_active(entry, now):
            reason = "expired"
        elif signature is None or entry.get("signature") != signature:
            reason = "signature_changed"
        else:
            excused.append(test_id)
            continue
        regressions.append({"id": test_id, "reason": reason})
    return {"proceed": not regressions, "excused": excused, "regressions": regressions}


def ledger_preflight(
    record: Any, identity: Mapping[str, Any], *, now: datetime,
    owned: Iterable[str] = (), obligations: Iterable[str] = (),
) -> dict[str, Any]:
    """Pre-flight from the ledger alone: only when its identity matches the current tree."""
    decision = reuse_decision(record, identity, now=now)
    if not decision["reuse"]:
        return {"proceed": False, "action": "run_full", **decision}
    failures = {i: e.get("signature") for i, e in record["tests"].items() if e["status"] == "fail"}
    outcome = classify_failures(record, failures, now=now, owned=owned, obligations=obligations)
    return {**decision, **outcome, "action": "reuse" if outcome["proceed"] else "run_full"}


def plan_targeted_rerun(
    *,
    failed_ids: Iterable[str],
    changed_files: Iterable[str],
    known_ids: Iterable[str] = (),
    explicit_dependents: Mapping[str, Iterable[str]] | None = None,
    force_full_patterns: Iterable[str] = DEFAULT_FORCE_FULL_PATTERNS,
) -> dict[str, Any]:
    """What to re-run after a fix (R4). A final full candidate run is always required."""
    changed = [path.strip("/") for path in changed_files]
    for path in changed:
        lowered = path.lower()
        if any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in force_full_patterns):
            return {"mode": "full", "reason": f"forced_full:{path}", "selectors": [], "final_full_run": True}
    known = sorted(set(known_ids))
    selectors = set(failed_ids)
    for path in changed:
        if _TEST_FILE_RE.search(path):
            classes = {
                "::".join(parts[:2])
                for parts in (i.split("::") for i in known if i == path or i.startswith(path + "::"))
                if len(parts) >= 3
            }
            module_level = any(
                len(i.split("::")) < 3 for i in known if i.startswith(path + "::")
            )
            if classes and not module_level:
                selectors |= classes
            else:
                selectors.add(path)  # whole file: module-level tests, or nothing known
        for dependent in (explicit_dependents or {}).get(path, ()):
            selectors.add(dependent)
    return {"mode": "targeted", "reason": "explicit_coverage", "selectors": sorted(selectors), "final_full_run": True}


# --------------------------------------------------------------------------- sampling rule
# SPEC-NS-KIT-002-003 R1/R2/R5: the ONE conditional sample-count rule. The dispatch plan, the
# verifier brief and every parent-side guard derive their counts from here; no seam hardcodes
# "3 per arm". The verdict validator embedded in guides/pinned-validator.md is a self-contained script and applies
# the same rule on a recorded verdict; tests pin that the two agree.

SAMPLES_DEFAULT = 1
SAMPLES_ESCALATED = 3
SAMPLING_ESCALATION_TRIGGERS = (
    "flaky_suspected",
    "head_failure_not_excused_by_ledger",
    "arms_disagree",
    "samples_within_arm_disagree",
    "launch_failure_without_supporting_control",
)

LAUNCH_SUSPECTED = "launch_infrastructure_suspected"
LAUNCH_SUPPORTED = "launch_infrastructure_supported"
LAUNCH_FAILURE = "launch_failure"
LAUNCH_CONTROL_ARMS = ("baseline", "alternate_device")


def required_samples_per_arm(
    *,
    flaky_suspected: bool = False,
    head_failure_unexcused: bool = False,
    arms_disagree: bool = False,
    samples_disagree: bool = False,
    unsupported_launch_failure: bool = False,
) -> int:
    """1 sample per arm; 3 only when any escalation trigger holds (R2)."""
    escalate = (
        flaky_suspected or head_failure_unexcused or arms_disagree
        or samples_disagree or unsupported_launch_failure
    )
    return SAMPLES_ESCALATED if escalate else SAMPLES_DEFAULT


def flaky_suspected_from_evidence(
    record: Any = None,
    suite_test_ids: Iterable[str] = (),
    *,
    now: datetime | None = None,
    prior_disagreeing_sample: bool = False,
) -> bool:
    """`flaky_suspected` is true only from evidence (R1), otherwise false.

    Evidence is an active (unexpired) ledger entry marked `flaky` for a test in the suite
    (all entries when ``suite_test_ids`` is empty), or a prior disagreeing sample in this run.
    An untrusted or absent ledger is never evidence.
    """
    if prior_disagreeing_sample:
        return True
    if not isinstance(record, Mapping) or verify_record(record):
        return False
    moment = now or utc_now()
    ids = list(suite_test_ids)
    for test_id, entry in record["tests"].items():
        if not isinstance(entry, Mapping) or entry.get("status") != "flaky":
            continue
        if ids and not _owns(test_id, ids) and test_id not in ids:
            continue
        if entry_active(entry, moment):
            return True
    return False


def launch_failure_unsupported(failure: Any) -> bool:
    """True when a launch failure still counts as a failure/evidence gap (a disagreement)."""
    if not isinstance(failure, Mapping) or failure.get("classification") != LAUNCH_SUPPORTED:
        return True
    probe = failure.get("control_probe")
    return not (isinstance(probe, Mapping) and str(probe.get("run", "")).strip())


def suite_required_samples(suite: Mapping[str, Any], *, head_failure_unexcused: bool = False) -> int:
    """Required samples per arm for one verdict suite entry; mirrors the pinned-validator.md validator."""
    samples = suite.get("samples") or {}
    sets = {
        arm: [set(one.get("failing") or []) for one in samples.get(arm) or []]
        for arm in ("baseline", "head")
    }
    any_ = {arm: set().union(*v) if v else set() for arm, v in sets.items()}
    all_ = {arm: set.intersection(*v) if v else set() for arm, v in sets.items()}
    return required_samples_per_arm(
        flaky_suspected=bool(suite.get("flaky_suspected")),
        head_failure_unexcused=head_failure_unexcused,
        arms_disagree=any_["baseline"] != any_["head"],
        samples_disagree=any_["baseline"] != all_["baseline"] or any_["head"] != all_["head"],
        unsupported_launch_failure=any(
            launch_failure_unsupported(f) for f in suite.get("launch_failures") or []
        ),
    )


def sampling_plan(*, flaky_suspected: bool = False) -> dict[str, Any]:
    """The `sampling` block of the dispatch plan; the brief quotes it instead of a number."""
    return {
        "default_samples_per_arm": SAMPLES_DEFAULT,
        "escalated_samples_per_arm": SAMPLES_ESCALATED,
        "flaky_suspected": bool(flaky_suspected),
        "required_samples_per_arm": required_samples_per_arm(flaky_suspected=flaky_suspected),
        "escalate_when": list(SAMPLING_ESCALATION_TRIGGERS),
    }


def classify_launch_failure(
    failed_run: str,
    control: Mapping[str, Any] | None = None,
    *,
    detail: str = "",
) -> dict[str, Any]:
    """R3/R4: record a failure at app launch before any test step; never drop or pass it.

    ``failed_run`` names the exact failed run (arm, device, attempt). ``control`` is the single
    bounded control probe, or None when none ran:
    ``{"kind": "baseline"|"alternate_device", "run": str, "device": str,
    "candidate_passed": bool, "baseline_failed_same_way": bool}``. Control evidence (the
    identical candidate passing on the control, or the baseline failing the same way) SUPPORTS an
    infrastructure hypothesis; it does not establish causality, so the original failure, the
    probe identity and the residual uncertainty are always retained. Only supported failures are
    excluded from the 3-sample disagreement trigger; without that evidence the sample stays a
    failure/evidence gap and counts as disagreement.
    """
    if not isinstance(failed_run, str) or not failed_run.strip():
        raise ValueError("launch failure must name the exact failed run")
    record: dict[str, Any] = {
        "classification": LAUNCH_SUSPECTED,
        "failed_run": failed_run,
        "detail": detail,
        "counts_as_pass": False,
        "counts_as_disagreement": True,
        "control_probe": None,
        "residual_uncertainty": "no control probe evidence: cause unestablished; remains a failure",
    }
    if control is None:
        return record
    if not isinstance(control, Mapping) or control.get("kind") not in LAUNCH_CONTROL_ARMS:
        raise ValueError("control probe kind must be one of %s" % (LAUNCH_CONTROL_ARMS,))
    if not str(control.get("run", "")).strip():
        raise ValueError("control probe must name its exact run")
    probe = {
        "kind": control["kind"],
        "run": control["run"],
        "device": control.get("device", ""),
        "candidate_passed": bool(control.get("candidate_passed")),
        "baseline_failed_same_way": bool(control.get("baseline_failed_same_way")),
    }
    record["control_probe"] = probe
    supported = (
        (control["kind"] == "alternate_device" and probe["candidate_passed"])
        or (control["kind"] == "baseline" and (probe["candidate_passed"] or probe["baseline_failed_same_way"]))
    )
    if supported:
        record["classification"] = LAUNCH_SUPPORTED
        record["counts_as_disagreement"] = False
        record["residual_uncertainty"] = (
            "control evidence supports an infrastructure hypothesis; causality is not established "
            "and the original failure may still be a candidate defect"
        )
    else:
        record["classification"] = LAUNCH_FAILURE
        record["residual_uncertainty"] = (
            "control probe did not support an infrastructure hypothesis; the failure stands"
        )
    return record


def launch_failure_errors(suite: Mapping[str, Any]) -> list[str]:
    """Guard: every recorded launch failure retains its failed run, probe and uncertainty."""
    errors: list[str] = []
    for index, item in enumerate(suite.get("launch_failures") or []):
        label = "launch_failures[%d]" % index
        if not isinstance(item, Mapping):
            errors.append("%s: not an object" % label)
            continue
        if item.get("classification") not in (LAUNCH_SUSPECTED, LAUNCH_SUPPORTED, LAUNCH_FAILURE):
            errors.append("%s: unknown classification %r" % (label, item.get("classification")))
        if not str(item.get("failed_run", "")).strip():
            errors.append("%s: original failed run dropped" % label)
        if item.get("counts_as_pass") is not False:
            errors.append("%s: a launch failure may never count as a pass" % label)
        if not str(item.get("residual_uncertainty", "")).strip():
            errors.append("%s: residual uncertainty not retained" % label)
        if item.get("classification") == LAUNCH_SUPPORTED:
            probe = item.get("control_probe")
            if not isinstance(probe, Mapping) or not str(probe.get("run", "")).strip():
                errors.append("%s: supported without a retained control probe" % label)
            if item.get("counts_as_disagreement") is not False:
                errors.append("%s: supported failure inconsistent disagreement flag" % label)
        elif item.get("counts_as_disagreement") is not True:
            errors.append("%s: unsupported launch failure must count as disagreement" % label)
    return errors


def dedup_fresh_main(
    head_record: Any, merged_identity: Mapping[str, Any], *, now: datetime, run_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """R6: reuse the verifier's head run as fresh-main only when identities are equal."""
    decision = reuse_decision(head_record, merged_identity, now=now)
    if not decision["reuse"]:
        return None, {**decision, "action": "run_full_fresh_main"}
    updated = copy.deepcopy(head_record)
    updated.update({
        "label": "reused", "created": _iso(now),
        "expires_at": _iso(now + timedelta(days=DEFAULT_RECEIPT_TTL_DAYS)),
        "reused_from": {
            "receipt_digest": head_record["receipt_digest"],
            "originating_run": head_record["originating_run"],
            "integration_run": run_id,
        },
    })
    updated["receipt_digest"] = _receipt_digest(updated)
    return updated, {**decision, "action": "reuse_head_run"}


# --------------------------------------------------------------------------- storage


def load_ledger(path: Path) -> dict[str, Any] | None:
    """Parsed ledger, or None when absent/unreadable (callers then run for real)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_ledger(path: Path, record: Mapping[str, Any]) -> None:
    errors = verify_record(dict(record))
    if errors:
        raise LedgerError("refusing to write an invalid ledger: " + errors[0])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- verdict assembly
# SPEC-NS-KIT-002-004: the kit, not the verifier, derives scope, the five classification lists,
# identity and schema shape.  The embedded pinned-validator.md validator stays the only judge: it is run,
# never reimplemented, before anything is written.

class ArmIsolationError(ValueError):
    """Arm isolation (R3) violated; ``reason`` is a controller reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


class TrustedKitError(RuntimeError):
    """The main branch's trusted copy of the kit cannot be established (R5)."""


class VerdictAssemblyError(ValueError):
    """The verifier-supplied input or a raw sample cannot yield a verdict."""


ARM_LABELS = ("baseline", "head")
TRUSTED_KIT_ENV = "NIGHTSHIFT_TRUSTED_KIT_RECORD"
SKILL_RELATIVE_PATH = "Skills/nightshift/SKILL.md"
# SPEC-NS-KIT-101 R1/R2: the pinned executable blocks live in these guides, one marker -> one guide.
# This map is the single source for the guide loader and for the trusted-kit snapshot set.
GUIDES_RELATIVE_DIR = "guides"
PINNED_BLOCK_GUIDES = {
    "# NIGHTSHIFT-VERDICT-VALIDATOR-BEGIN": "pinned-validator.md",
    "# NIGHTSHIFT-BRIEF-CHECK-BEGIN": "pinned-checks.md",
    "# NIGHTSHIFT-SCOPE-GATE-BEGIN": "pinned-checks.md",
    "<!-- NIGHTSHIFT-VERIFIER-BRIEF-BEGIN -->": "pinned-briefs.md",
    "<!-- NIGHTSHIFT-VERIFIER-BRIEF-NOSUITE-BEGIN -->": "pinned-briefs.md",
}
TEMPLATE_GUIDE = "pinned-briefs.md"
PINNED_GUIDE_NAMES = tuple(sorted({*PINNED_BLOCK_GUIDES.values(), TEMPLATE_GUIDE}))
VERDICT_TEMPLATE_SENTENCE = "This is the canonical verdict-JSON template block."


def interpreter_identity() -> str:
    return f"{platform.python_implementation()} {platform.python_version()}"


def build_arm_isolation(
    devices: Mapping[str, str] | None = None, runtimes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """R3: the plan's isolation block -- distinct per-arm devices, or sequential execution."""
    runtime = {arm: (runtimes or {}).get(arm) for arm in ARM_LABELS}
    interpreter = interpreter_identity()
    if devices:
        if set(devices) != set(ARM_LABELS) or not all(
            isinstance(v, str) and v.strip() for v in devices.values()
        ):
            raise ArmIsolationError("arm_isolation_invalid", "a device is required for each of baseline and head")
        if devices["baseline"] == devices["head"]:
            raise ArmIsolationError(
                "arm_device_overlap", f"both arms are assigned device {devices['baseline']!r}",
            )
        if not all(runtime.values()):
            raise ArmIsolationError("surface_env_gap", "a runtime is required for each arm when devices are assigned")
        mode, assigned = "devices", {arm: devices[arm] for arm in ARM_LABELS}
    else:
        mode, assigned = "sequential", None
    if None not in runtime.values() and runtime["baseline"] != runtime["head"]:
        raise ArmIsolationError(
            "surface_env_gap",
            f"arm runtimes differ: baseline {runtime['baseline']!r}, head {runtime['head']!r}",
        )
    # `interpreter` is the dispatcher's own identity, recorded for audit; the suite may run under
    # another interpreter (e.g. `uv run`), so only an explicit runtime and arm equality gate.
    return {"mode": mode, "devices": assigned, "runtime": runtime, "interpreter": interpreter}


def check_observed_arm_isolation(plan_isolation: Mapping[str, Any], observed: Any) -> None:
    """R3: reject a verdict whose arms overlapped or used a runtime unlike the plan, before any judgment."""
    if not isinstance(observed, Mapping) or not all(isinstance(observed.get(a), Mapping) for a in ARM_LABELS):
        raise ArmIsolationError(
            "arm_isolation_missing",
            'input must record arm_isolation for baseline and head: {"baseline": {"runtime": ...}, "head": {"runtime": ...}}'
        )
    runtime = plan_isolation.get("runtime") or {}
    seen_runtime = {arm: observed[arm].get("runtime") for arm in ARM_LABELS}
    if not all(isinstance(v, str) and v.strip() for v in seen_runtime.values()):
        raise ArmIsolationError("arm_isolation_missing", "each arm must record the runtime it ran on")
    if seen_runtime["baseline"] != seen_runtime["head"]:
        raise ArmIsolationError(
            "surface_env_gap",
            f"arms ran on different runtimes: baseline {seen_runtime['baseline']!r}, head {seen_runtime['head']!r}",
        )
    for arm in ARM_LABELS:
        if runtime.get(arm) is not None and seen_runtime[arm] != runtime[arm]:
            raise ArmIsolationError(
                "surface_env_gap", f"{arm} ran on runtime {seen_runtime[arm]!r}, plan assigns {runtime[arm]!r}",
            )
    devices = plan_isolation.get("devices")
    if devices:
        seen = {arm: observed[arm].get("device") for arm in ARM_LABELS}
        if seen["baseline"] == seen["head"]:
            raise ArmIsolationError("arm_device_overlap", f"both arms ran on device {seen['baseline']!r}")
        for arm in ARM_LABELS:
            if seen[arm] != devices.get(arm):
                raise ArmIsolationError(
                    "arm_device_mismatch", f"{arm} ran on {seen[arm]!r}, plan assigns {devices.get(arm)!r}",
                )
        return
    spans = {}
    for arm in ARM_LABELS:
        start, end = observed[arm].get("started_at"), observed[arm].get("ended_at")
        if start is None and end is None:
            continue
        try:
            spans[arm] = (datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end)))
        except ValueError as exc:
            raise ArmIsolationError("arm_isolation_invalid", f"{arm} window is not ISO-8601: {exc}") from exc
    if len(spans) == 2 and spans["baseline"][0] < spans["head"][1] and spans["head"][0] < spans["baseline"][1]:
        raise ArmIsolationError("arm_overlap", "sequential arms ran at overlapping times")


# ---- trusted tooling (R5)

def _plain_git(repo: Path, *args: str, check: bool = True) -> str | None:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        if check:
            raise TrustedKitError(result.stderr.strip() or f"git {args[0]} failed")
        return None
    return result.stdout


def _main_kit_entries(source: Path, main_branch: str, kit_rel: str) -> tuple[str | None, dict[str, str]]:
    commit = _plain_git(source, "rev-parse", "--verify", f"{main_branch}^{{commit}}", check=False)
    if commit is None:
        return None, {}
    commit = commit.strip()
    listing = _plain_git(source, "ls-tree", "-z", commit, "--", f"{kit_rel}/", check=False) or ""
    entries: dict[str, str] = {}
    for record in listing.split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            entries[path] = parts[2]
    skill = _plain_git(source, "rev-parse", "--verify", f"{commit}:{kit_rel}/{SKILL_RELATIVE_PATH}", check=False)
    if skill:
        entries[SKILL_RELATIVE_PATH] = skill.strip()
    pinned = {SKILL_RELATIVE_PATH}
    for guide in PINNED_GUIDE_NAMES:  # R2: the guides the verifier reads travel with SKILL.md
        rel = f"{GUIDES_RELATIVE_DIR}/{guide}"
        oid = _plain_git(source, "rev-parse", "--verify", f"{commit}:{kit_rel}/{rel}", check=False)
        if oid:
            entries[rel] = oid.strip()
            pinned.add(rel)
    return commit, {
        name.rsplit("/", 1)[-1] if name not in pinned else name: oid
        for name, oid in entries.items()
        if name in pinned or name.endswith(".py")
    }


def resolve_trusted_kit(
    source: Path, *, main_branch: str = "main", module_dir: Path | None = None,
) -> dict[str, Any]:
    """R5: compare the running kit with main's copy of it; record which copy is trusted.

    The record carries no absolute path.  ``matches`` is False when any main-tracked kit module
    (or SKILL.md, or a pinned guide) differs from the running one, i.e. the running copy is not main's.
    """
    here = (module_dir or Path(__file__).resolve().parent).resolve()
    source = Path(source).resolve()
    record: dict[str, Any] = {"main_branch": main_branch, "copy": "installed", "matches": False}
    own_top = _plain_git(here, "rev-parse", "--show-toplevel", check=False)
    source_top = _plain_git(source, "rev-parse", "--show-toplevel", check=False)
    if own_top is None or source_top is None:
        record["reason"] = "kit_not_in_git" if own_top is None else "source_not_git"
        return record
    own_top_path = Path(own_top.strip()).resolve()
    kit_rel = here.relative_to(own_top_path).as_posix() if here != own_top_path else "."
    in_candidate = own_top_path == Path(source_top.strip()).resolve()
    commit, entries = _main_kit_entries(source, main_branch, kit_rel)
    if commit is None or "verification_report.py" not in entries:
        if in_candidate:
            raise TrustedKitError(
                f"{main_branch} has no tracked kit at {kit_rel}; the candidate's own copy cannot be trusted"
            )
        record["reason"] = "main_has_no_kit"
        return record
    paths = [here / n for n in entries]
    hashed = subprocess.run(
        ["git", "hash-object", "--no-filters", "--stdin-paths"],
        input="\n".join(str(p) for p in paths if p.is_file()) + "\n",
        capture_output=True, text=True, check=False, cwd=here,
    ).stdout.split()
    local = dict(zip([n for n, p in zip(entries, paths) if p.is_file()], hashed))
    differing = sorted(n for n, oid in entries.items() if local.get(n) != oid)
    bodies = _git_batch_blobs(source, entries.values())
    record.update({
        "copy": "main", "main_commit": commit, "kit_path": kit_rel, "matches": not differing,
        "differing": differing,
        "sha256": {
            name: hashlib.sha256(bodies[entries[name]]).hexdigest()
            for name in (
                "verification_report.py", "scope_guard.py", SKILL_RELATIVE_PATH,
                *(f"{GUIDES_RELATIVE_DIR}/{g}" for g in PINNED_GUIDE_NAMES),
            )
            if name in entries
        },
    })
    record["_entries"] = entries
    return record


def materialize_trusted_kit(source: Path, record: Mapping[str, Any], destination: Path) -> Path:
    """Write main's kit modules, SKILL.md and the pinned guides from the object database into ``destination``."""
    entries = record["_entries"]
    bodies = _git_batch_blobs(Path(source).resolve(), entries.values())
    destination.mkdir(parents=True, exist_ok=True)
    for name, oid in entries.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bodies[oid])
    return destination


def public_trusted_record(record: Mapping[str, Any], *, reexecuted: bool) -> dict[str, Any]:
    return {**{k: v for k, v in record.items() if not k.startswith("_")}, "reexecuted": reexecuted}


def ensure_trusted_kit(source: Path, argv: list[str], *, main_branch: str = "main") -> tuple[dict[str, Any], int | None]:
    """R5: return (record, None) when running main's copy, else re-run the command from it.

    A candidate that modified the kit is still verified by main's copy: this process
    materializes main's modules into a private directory, re-executes the same argv there and
    returns its exit code.  The record travels to the child through the environment.
    """
    inherited = os.environ.get(TRUSTED_KIT_ENV)
    if inherited:
        record = json.loads(inherited)
        expected = (record.get("sha256") or {}).get("verification_report.py")
        if record.get("reexecuted") and expected != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            raise TrustedKitError("re-executed copy does not match the recorded main copy")
        return record, None
    record = resolve_trusted_kit(source, main_branch=main_branch)
    if record["copy"] != "main" or record["matches"]:
        return public_trusted_record(record, reexecuted=False), None
    public = public_trusted_record(record, reexecuted=True)
    with tempfile.TemporaryDirectory(prefix="ns-trusted-kit-") as scratch:
        kit = materialize_trusted_kit(source, record, Path(scratch) / "kit")
        proc = subprocess.run(
            [sys.executable, str(kit / "verification_report.py"), *argv],
            env={**os.environ, TRUSTED_KIT_ENV: json.dumps(public, sort_keys=True)}, check=False,
        )
    return public, proc.returncode


# ---- raw sample parsing

_PYTEST_FAIL_LINE_RE = re.compile(r"^(?:FAILED|ERROR) (\S+?)(?: - .*)?$", re.M)


def parse_raw_sample(text: str) -> dict[str, Any]:
    """Parse one raw per-sample output (pytest -q text or junit xml) into a verdict sample."""
    stripped = text.lstrip()
    if stripped.startswith("<"):
        return _parse_junit(stripped)
    counts: dict[str, int] = {}
    summary = [ln for ln in text.splitlines() if _PYTEST_COUNT_RE.search(ln) and " in " in ln]
    if not summary:
        raise VerdictAssemblyError("no pytest summary line (e.g. '3 passed in 0.1s') in the raw output")
    for number, word in _PYTEST_COUNT_RE.findall(summary[-1]):
        counts["error" if word.startswith("error") else word] = int(number)
    failing = sorted(set(_PYTEST_FAIL_LINE_RE.findall(text)))
    expected = counts.get("failed", 0) + counts.get("error", 0)
    if expected and not failing:
        raise VerdictAssemblyError(f"summary reports {expected} failing but no FAILED/ERROR names were found (use -rfE)")
    if expected > len(failing):
        raise VerdictAssemblyError(f"summary reports {expected} failing but only {len(failing)} names were found")
    return {
        "executed": True, "failing": failing, "failed": len(failing),
        "passed": counts.get("passed", 0), "skipped": counts.get("skipped", 0),
    }


def _parse_junit(text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise VerdictAssemblyError(f"junit xml does not parse: {exc}") from exc
    cases = list(root.iter("testcase"))
    if not cases:
        raise VerdictAssemblyError("junit xml holds no testcase elements")
    failing, skipped = set(), 0
    for case in cases:
        name = f"{case.get('classname')}::{case.get('name')}" if case.get("classname") else str(case.get("name"))
        if case.find("failure") is not None or case.find("error") is not None:
            failing.add(name)
        elif case.find("skipped") is not None:
            skipped += 1
    return {
        "executed": True, "failing": sorted(failing), "failed": len(failing),
        "passed": len(cases) - len(failing) - skipped, "skipped": skipped,
    }


def classify_sample_sets(baseline: list[set[str]], head: list[set[str]]) -> dict[str, list[str]]:
    """The five lists over sample sets; the same formulas the embedded validator recomputes."""
    b_any, b_all = set().union(*baseline), set.intersection(*baseline)
    h_any, h_all = set().union(*head), set.intersection(*head)
    return {
        "regressed": sorted(h_all - b_any),
        "newly_flaky": sorted((h_any - h_all) - b_any),
        "flaky_observed": sorted((h_any - h_all) | ((b_any - b_all) & h_any)),
        "fixed": sorted(b_all - h_any),
        "flake_resolved": sorted((b_any - b_all) - h_any),
    }


# ---- scope

def safe_canonical_protocol_files(kit_dir: Path) -> frozenset[str] | None:
    """`scope_guard._canonical_protocol_files` without executing the arm's `nightshift-sync.py`.

    The stock helper imports that file from the candidate's tree; here the literal list is read
    with `ast`, so no candidate code runs inside the trusted process.
    """
    import ast

    sync_path = Path(kit_dir).parent / "nightshift-sync.py"
    try:
        for node in ast.parse(sync_path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CANONICAL_PROTOCOL_FILES" for t in node.targets
            ):
                return frozenset(str(item) for item in ast.literal_eval(node.value))
    except (OSError, SyntaxError, ValueError):
        return None
    return None


def harden_scope_guard() -> Any:
    """Import this kit's scope_guard (into sys.modules) with candidate-code loads replaced."""
    import scope_guard

    scope_guard._canonical_protocol_files = safe_canonical_protocol_files
    return scope_guard


@contextlib.contextmanager
def hardened_scope_guard():
    """`harden_scope_guard`, undone on exit so an in-process caller's module stays stock."""
    import scope_guard

    original = scope_guard._canonical_protocol_files
    try:
        yield harden_scope_guard()
    finally:
        scope_guard._canonical_protocol_files = original


def derive_verdict_scope(
    surface: Path, spec_file: Path, *, main_root: Path | None = None, main_branch: str = "main",
) -> dict[str, list[str]]:
    """`scope` exactly as the embedded validator recomputes it (spec read from the head arm / main)."""
    with hardened_scope_guard() as scope_guard:
        return _derive_verdict_scope(
            scope_guard, surface, spec_file, main_root=main_root, main_branch=main_branch)


def _derive_verdict_scope(
    scope_guard: Any, surface: Path, spec_file: Path, *, main_root: Path | None, main_branch: str,
) -> dict[str, list[str]]:
    kit_dir = spec_file.resolve().parent.parent
    spec_text = spec_file.read_text(encoding="utf-8")
    if main_root is None and SPEC_PROJECTION_MARKER in spec_text and "<earlier-attempt-artifact-" in spec_text:
        raise VerdictAssemblyError(
            "the spec copy carries placeholdered scope entries; pass --main-root so scope is read from main"
        )
    scope = scope_guard.resolve_scope(spec_text)
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMR", "verifier-baseline", "verifier-head", "--"],
        cwd=surface, capture_output=True, text=True,
    )
    if diff.returncode:
        raise VerdictAssemblyError("cannot diff verifier-baseline..verifier-head in the surface")
    diff_paths = sorted(p for p in diff.stdout.splitlines() if p.strip())
    project_root = Path(surface)
    try:
        spec_relpath = str(spec_file.resolve().relative_to(project_root.resolve()))
    except ValueError:
        spec_relpath = str(spec_file)
    if main_root is not None:
        main_relpath = None
        for base in (main_root.resolve(), project_root.resolve()):
            try:
                rel = spec_file.resolve().relative_to(base)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in ("verifier-baseline", "verifier-head"):
                rel = Path(*rel.parts[1:])
            main_relpath = str(rel)
            break
        main_relpath = main_relpath or spec_relpath
        shown = subprocess.run(
            ["git", "show", f"{main_branch}:{main_relpath}"], cwd=main_root, capture_output=True, text=True,
        )
        if shown.returncode:
            raise VerdictAssemblyError(f"cannot read {main_branch}:{main_relpath} from the main root for scope")
        spec_text = shown.stdout
        scope = scope_guard.scope_from_main(main_root, main_relpath, main_branch)
    amend_globs: list[str] = []
    heading = re.search(r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", spec_text, re.M)
    if heading:
        for line in heading.group(1).split("\n"):
            s = line.strip()
            if not s.startswith("|") or re.match(r"^\|[\s:|-]*\|?$", s):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not any(cells) or cells[0] == "Date" or len(cells) < 5 or not cells[1]:
                continue
            amend_globs.append(cells[1])
    out_of_scope, amended = [], []
    for path in diff_paths:
        if scope_guard.classify_write(path, scope, project_root, kit_dir, spec_relpath).allowed:
            continue
        (amended if any(scope_guard._glob_match(g, path) for g in amend_globs) else out_of_scope).append(path)
    return {"checked": diff_paths, "out_of_scope": sorted(out_of_scope), "amended": sorted(amended)}


# ---- assembly

def guide_dirs(skill_path: Path) -> list[Path]:
    """Where the guides of the kit holding ``skill_path`` live (SPEC-NS-KIT-101 R1).

    The kit layout puts SKILL.md at ``<kit>/Skills/nightshift/SKILL.md`` and the guides at
    ``<kit>/guides``; a global skill install delivers them beside SKILL.md (BUG-NS-KIT-102).
    ``--skill`` therefore implies its own kit root; nothing is read from anywhere else.
    """
    skill = Path(skill_path).resolve()
    return [skill.parents[2] / GUIDES_RELATIVE_DIR, skill.parent / GUIDES_RELATIVE_DIR]


def load_guide(skill_path: Path, name: str) -> str:
    """The text of the named guide, resolved from the kit that holds ``skill_path``; fails closed."""
    for directory in guide_dirs(skill_path):
        candidate = directory / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise VerdictAssemblyError(f"guide {name} not found beside {skill_path}; pass --skill of a kit that ships it")


def _load_validator_source(skill_path: Path) -> str:
    begin, end = "# NIGHTSHIFT-VERDICT-VALIDATOR-BEGIN", "# NIGHTSHIFT-VERDICT-VALIDATOR-END"
    text = load_guide(skill_path, PINNED_BLOCK_GUIDES[begin])
    if begin not in text or end not in text:
        raise VerdictAssemblyError("pinned-validator.md carries no embedded verdict validator")
    return text[text.index(begin):text.index(end) + len(end)]


def locate_skill(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit else [
        Path(__file__).resolve().parent / SKILL_RELATIVE_PATH,
        Path.home() / ".claude" / "skills" / "nightshift" / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise VerdictAssemblyError("SKILL.md (embedded verdict validator) not found; pass --skill")


def run_embedded_validator(
    verdict_path: Path, spec_file: Path, surface: Path, main_root: Path | None, main_branch: str,
    skill_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run the embedded validator with this (trusted) kit's scope_guard pinned in sys.modules.

    The validator inserts the spec file's kit directory (the candidate's, from the head arm) at
    the front of sys.path before importing scope_guard; importing the trusted copy first makes
    the cached module win, so the candidate cannot supply the scope classifier.  Bytecode is
    not written (it would dirty the arm).
    """
    with tempfile.TemporaryDirectory(prefix="ns-validator-") as scratch:
        script = Path(scratch) / "validate_verdict.py"
        script.write_text(_load_validator_source(skill_path), encoding="utf-8")
        argv = [str(verdict_path), str(spec_file), str(surface)]
        if main_root is not None:
            argv += [str(main_root), main_branch]
        bootstrap = (
            "import runpy, sys; sys.path.insert(0, sys.argv[1]); import verification_report as v; "
            "v.harden_scope_guard(); sys.argv = sys.argv[2:]; "
            "runpy.run_path(sys.argv[0], run_name='__main__')"
        )
        return subprocess.run(
            [sys.executable, "-c", bootstrap, str(Path(__file__).resolve().parent), str(script), *argv],
            capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )


def _read_sample(entry: Any, base: Path) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise VerdictAssemblyError("a sample must be an object")
    if "path" in entry or "output" in entry:
        text = entry["output"] if "output" in entry else (base / str(entry["path"])).read_text(encoding="utf-8", errors="replace")
        return parse_raw_sample(text)
    return dict(entry)  # structured sample (reused ledger baseline, first-scaffold attempt)


def assemble_verdict(
    plan: Mapping[str, Any], supplied: Mapping[str, Any], *, input_dir: Path, spec_file: Path,
    main_root: Path | None = None, main_branch: str = "main",
) -> dict[str, Any]:
    """Build the verdict dict from the plan and the verifier's small input; no validation here."""
    check_observed_arm_isolation(plan.get("arm_isolation") or build_arm_isolation(), supplied.get("arm_isolation"))
    acs, suites_in = supplied.get("acs"), supplied.get("suites", [])
    if not isinstance(acs, list) or not all(isinstance(a, Mapping) for a in acs):
        raise VerdictAssemblyError("input.acs must be a list of {id, status, evidence} objects")
    if not isinstance(suites_in, list):
        raise VerdictAssemblyError("input.suites must be a list")
    suites: list[dict[str, Any]] = []
    commands = list(plan.get("suite_commands") or [])
    for index, item in enumerate(suites_in):
        name = item.get("name") or f"suite-{index + 1}"
        arms: dict[str, list[dict[str, Any]]] = {}
        for arm in ARM_LABELS:
            raw = (item.get("samples") or {}).get(arm)
            if not isinstance(raw, list) or not raw:
                raise VerdictAssemblyError(f"suite {name!r}: no {arm} samples supplied")
            parsed = []
            for number, entry in enumerate(raw):
                try:
                    parsed.append(_read_sample(entry, input_dir))
                except (VerdictAssemblyError, OSError) as exc:
                    raise VerdictAssemblyError(f"suite {name!r} {arm} sample {number}: {exc}") from exc
            arms[arm] = parsed
        suite: dict[str, Any] = {
            "name": name,
            "command": item.get("command") or (commands[index] if index < len(commands) else ""),
            "flaky_suspected": bool(item.get("flaky_suspected", (plan.get("sampling") or {}).get("flaky_suspected", False))),
            "samples": arms,
        }
        for key in ("launch_failures", "baseline_unavailable"):
            if key in item:
                suite[key] = item[key]
        suite["classification"] = (
            {k: [] for k in ("regressed", "newly_flaky", "flaky_observed", "fixed", "flake_resolved")}
            if "baseline_unavailable" in item
            else classify_sample_sets(
                [set(s.get("failing") or []) for s in arms["baseline"]],
                [set(s.get("failing") or []) for s in arms["head"]],
            )
        )
        suites.append(suite)
    if contamination_exposures(supplied.get("contamination")) is None:
        raise VerdictAssemblyError(
            "contamination must be null or {class, timing[, detail]} objects (R2 closed values)"
        )
    dispute = supplied.get("premise_dispute")
    derived = (
        "disputes_premise" if dispute
        else "fail" if any(a.get("status") == "fail" for a in acs) or any(s["classification"]["regressed"] for s in suites)
        else "pass"
    )
    stated = supplied.get("verdict")
    if stated is not None and stated != derived and not (stated == "fail" and derived == "pass"):
        raise VerdictAssemblyError(f"stated verdict {stated!r} contradicts the supplied evidence (derived {derived!r})")
    verdict_value = stated if stated is not None else derived
    surface = Path(plan["repository"])
    footprint = supplied.get("git_footprint")
    if footprint is None:
        before = plan.get("footprint_before")
        if not isinstance(before, Mapping):
            raise VerdictAssemblyError("no git_footprint supplied and the plan carries no footprint_before")
        after = capture_verifier_footprints({a: Path(plan["arm_working_directories"][a]) for a in ARM_LABELS})
        footprint = {
            a: {
                "tree_before": before[a]["tree"], "tree_after": after[a].tree,
                "porcelain_before": before[a]["porcelain"], "porcelain_after": after[a].porcelain,
            }
            for a in ARM_LABELS
        }
    return {
        "spec_id": plan["spec_id"],
        "branch": supplied.get("branch") or f"nightshift/{plan['spec_id']}-{plan['run_id']}",
        "baseline_commit": plan["baseline_commit"],
        "head_commit": plan["head_commit"],
        "identity_schema_version": plan["identity_schema_version"],
        "implementation_head_digest": plan["implementation_head_digest"],
        "verdict": verdict_value,
        "acs": [dict(a) for a in acs],
        "suites": suites,
        "git_footprint": footprint,
        "scope": derive_verdict_scope(surface, spec_file, main_root=main_root, main_branch=main_branch),
        "premise_dispute": dispute,
        "contamination": supplied.get("contamination"),
        "arm_isolation": supplied["arm_isolation"],
    }


def assemble_and_validate(
    plan: Mapping[str, Any], supplied: Mapping[str, Any], *, input_dir: Path, spec_file: Path,
    main_root: Path | None = None, main_branch: str = "main", skill_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """R1/R2: assemble, run the embedded validator, and return (verdict or None, validator report).

    ``None`` means refused; the report then names the exact defect.
    """
    verdict = assemble_verdict(
        plan, supplied, input_dir=input_dir, spec_file=spec_file, main_root=main_root, main_branch=main_branch,
    )
    with tempfile.TemporaryDirectory(prefix="ns-verdict-") as scratch:
        draft = Path(scratch) / "verdict.json"
        draft.write_text(json.dumps(verdict, indent=2, sort_keys=True), encoding="utf-8")
        result = run_embedded_validator(
            draft, spec_file, Path(plan["repository"]), main_root, main_branch, locate_skill(skill_path),
        )
    report = (result.stdout + result.stderr).strip()
    return (verdict if result.returncode == 0 else None), report


class MergeGateRefused(ValueError):
    """BUG-NS-KIT-107: the branch tip or an identity field is not the verified candidate."""


def check_merge_gate(
    plan: Mapping[str, Any], evidence: Mapping[str, Any], verdict: Mapping[str, Any],
    *, candidate: str, branch_head: str,
) -> str:
    """Check 7 (Head bound): the merge target is exactly the revision the verifier judged.

    Reuses `candidate_revision_digest` / `validate_dispatch_identity`; each distinct
    tamper surfaces its own detail.  Returns the bound candidate SHA.
    """
    if not isinstance(candidate, str) or not GIT_OBJECT_ID_RE.fullmatch(candidate):
        raise MergeGateRefused("candidate is not a lowercase Git object ID")
    if branch_head != candidate:
        raise MergeGateRefused(
            f"branch tip {str(branch_head)[:12]} is not the verified candidate {candidate[:12]}"
        )
    if evidence.get("candidate_revision_digest") != candidate_revision_digest(candidate):
        raise MergeGateRefused("evidence candidate_revision_digest does not match the candidate")
    if plan.get("implementation_head_digest") != evidence.get("implementation_head_digest"):
        raise MergeGateRefused("plan implementation_head_digest does not match the evidence")
    if verdict.get("implementation_head_digest") != plan.get("implementation_head_digest"):
        raise MergeGateRefused("verdict implementation_head_digest does not match the plan")
    if verdict.get("head_commit") != plan.get("head_commit"):
        raise MergeGateRefused("verdict head_commit does not match the plan")
    try:
        validate_dispatch_identity(
            dispatch_plan=dict(plan), containment_evidence=dict(evidence), verdict=dict(verdict),
            spec_id=str(plan.get("spec_id")), run_id=str(plan.get("run_id")), candidate_revision=candidate,
        )
    except ValueError as error:
        raise MergeGateRefused(f"dispatch identity does not re-derive from the candidate ({error})") from error
    return candidate


def heartbeat_declared_head(text: str) -> str | None:
    """The optional `head: <sha>` line a worker writes beside its terminal heartbeat_state."""
    for line in text.splitlines()[:40]:
        match = re.match(r"^head:[ \t]*([0-9a-f]{40}|[0-9a-f]{64})[ \t]*$", line)
        if match:
            return match.group(1)
    return None


def merge_gate_main(args: argparse.Namespace) -> int:
    def refuse(detail: str) -> int:
        print(f"MERGE-GATE: stale_head {detail}", file=sys.stderr)
        return 1

    try:
        branch_head = _run_git(args.repo, "rev-parse", "--verify", f"{args.branch}^{{commit}}").strip()
        if args.heartbeat is not None:
            declared = heartbeat_declared_head(args.heartbeat.read_text(encoding="utf-8"))
            if declared is not None and declared != branch_head:
                return refuse(f"heartbeat head {declared[:12]} is not the branch tip {branch_head[:12]}")
        if args.plan is None:
            if args.heartbeat is None:
                print("merge-gate needs --plan/--evidence/--verdict or --heartbeat", file=sys.stderr)
                return 2
            print(f"MERGE-GATE: head {branch_head}")
            return 0
        if args.evidence is None or args.verdict is None or args.candidate is None:
            print("merge-gate: --plan needs --evidence, --verdict and --candidate", file=sys.stderr)
            return 2
        bound = check_merge_gate(
            json.loads(args.plan.read_text(encoding="utf-8")),
            json.loads(args.evidence.read_text(encoding="utf-8")),
            json.loads(args.verdict.read_text(encoding="utf-8")),
            candidate=args.candidate, branch_head=branch_head,
        )
    except MergeGateRefused as refusal:
        return refuse(str(refusal))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return refuse(f"unreadable input ({type(error).__name__})")
    print(f"MERGE-GATE: bound {bound}")
    return 0


def validate_verdict_main(args: argparse.Namespace) -> int:
    """Run the embedded validator on a (hand-written) verdict with the trusted scope_guard pinned."""
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        spec_file = args.spec_file or Path(plan["arm_working_directories"]["head"]) / args.spec_path
        result = run_embedded_validator(
            args.verdict, spec_file, Path(plan["repository"]), args.main_root, args.main_branch,
            locate_skill(args.skill),
        )
    except (VerdictAssemblyError, KeyError, ValueError, OSError, TypeError) as refusal:
        print(f"validate-verdict refused: {refusal}", file=sys.stderr)
        return 1
    print((result.stdout + result.stderr).strip())
    return result.returncode


def assemble_verdict_main(args: argparse.Namespace, trusted: Mapping[str, Any]) -> int:
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        supplied = json.loads(args.input.read_text(encoding="utf-8"))
        repository = Path(plan["repository"]).resolve()
        if args.out is not None and (args.out.resolve() == repository or args.out.resolve().is_relative_to(repository)):
            raise VerdictAssemblyError("--out must be outside the verifier surface (a write there voids the verdict)")
        spec_file = args.spec_file or Path(plan["arm_working_directories"]["head"]) / args.spec_path
        if not spec_file.is_file():
            raise VerdictAssemblyError("spec file not found in the head arm; pass --spec-path or --spec-file")
        verdict, report = assemble_and_validate(
            plan, supplied, input_dir=args.input.resolve().parent, spec_file=spec_file,
            main_root=args.main_root, main_branch=args.main_branch, skill_path=args.skill,
        )
    except ArmIsolationError as refusal:
        print(f"assemble-verdict refused: {refusal}", file=sys.stderr)
        return 2
    except (VerdictAssemblyError, KeyError, ValueError, OSError, TrustedKitError) as refusal:
        print(f"assemble-verdict refused: {refusal}", file=sys.stderr)
        return 1
    if verdict is None:
        print(f"assemble-verdict refused; validator output:\n{report}", file=sys.stderr)
        return 1
    verdict["trusted_tooling"] = dict(trusted)
    body = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        print(body, end="")
        print(report, file=sys.stderr)
    else:
        args.out.write_text(body, encoding="utf-8")
        print(report)
    return 0


# --------------------------------------------------------------------------- CLI


def identity_from_extras(
    repo: Path, ref: str, extras: Mapping[str, Any], *, exempt: Iterable[str] = (),
) -> dict[str, Any]:
    """Identity at *ref* from a JSON-style mapping of command/selection/flags/env/..."""
    return build_identity(
        repo, ref, command=extras.get("command") or "",
        selection=extras.get("selection", "full"), flags=extras.get("flags", ()),
        env=extras.get("env"), toolchain=extras.get("toolchain"),
        device_policy=extras.get("device_policy"), host=extras.get("host"), exempt=exempt,
    )


def _identity_from_args(args: argparse.Namespace) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    if getattr(args, "identity_file", None):
        extras = json.loads(Path(args.identity_file).read_text(encoding="utf-8"))
    if args.command_text:
        extras["command"] = args.command_text
    ledger_rel = args.ledger_relpath
    return identity_from_extras(
        Path(args.repo), args.ref, extras, exempt=[ledger_rel] if ledger_rel else [],
    )


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--command-text", default=None, help="exact test command")
    parser.add_argument("--identity-file", default=None, help="JSON with selection/flags/env/toolchain/device_policy/host")
    parser.add_argument("--ledger-relpath", default=LEDGER_RELATIVE_PATH)


def ledger_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verification_report.py ledger", description="Main test-status ledger")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _common(sub.add_parser("identity"))
    rec = sub.add_parser("record")
    _common(rec)
    rec.add_argument("--junit", required=True)
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--exit-code", type=int, required=True)
    rec.add_argument("--out", required=True)
    rec.add_argument("--previous", default=None)
    rec.add_argument("--bug", action="append", default=[], help="TEST_ID=BUG-ID")
    rec.add_argument("--label", default="executed", choices=LABELS)
    chk = sub.add_parser("check")
    _common(chk)
    chk.add_argument("--ledger", required=True)
    chk.add_argument("--owned", action="append", default=[])
    chk.add_argument("--obligation", action="append", default=[])
    pln = sub.add_parser("plan")
    pln.add_argument("--failed", action="append", default=[])
    pln.add_argument("--changed", action="append", default=[])
    pln.add_argument("--ledger", default=None)
    args = parser.parse_args(argv)
    now = utc_now()
    try:
        if args.cmd == "identity":
            identity = _identity_from_args(args)
            print(json.dumps({"identity": identity, "identity_digest": identity_digest(identity)}, sort_keys=True))
            return 0
        if args.cmd == "record":
            xml_bytes = Path(args.junit).read_bytes()
            results, claimed = parse_junit(xml_bytes)
            previous = load_ledger(Path(args.previous)) if args.previous else None
            record = build_record(
                _identity_from_args(args), results, run_id=args.run_id,
                commit=_ledger_git(Path(args.repo), "rev-parse", args.ref).decode().strip(),
                native_result={"exit_code": args.exit_code, "junit_sha256": sha256_hex(xml_bytes)},
                evidence_digest=sha256_hex(xml_bytes), now=now,
                bug_links=dict(item.split("=", 1) for item in args.bug),
                previous=previous, reported_total=claimed, label=args.label,
            )
            write_ledger(Path(args.out), record)
            print(json.dumps({"receipt_digest": record["receipt_digest"], "coverage": record["coverage"]}, sort_keys=True))
            return 0
        if args.cmd == "check":
            outcome = ledger_preflight(
                load_ledger(Path(args.ledger)), _identity_from_args(args), now=now,
                owned=args.owned, obligations=args.obligation,
            )
            print(json.dumps(outcome, sort_keys=True))
            return 0 if outcome.get("proceed") else 1
        if args.cmd == "plan":
            known = list((load_ledger(Path(args.ledger)) or {}).get("tests", {})) if args.ledger else []
            print(json.dumps(plan_targeted_rerun(failed_ids=args.failed, changed_files=args.changed, known_ids=known), sort_keys=True))
            return 0
    except (LedgerError, OSError, ValueError, ET.ParseError) as exc:
        print(f"test-status-ledger: {exc}", file=sys.stderr)
        return 2
    return 2


# ---------------------------------------------------------------------------
# SPEC-NS-KIT-002-007: heavy-suite lease, separate budgets, cleanup observation,
# bounded diagnostics and the one-shot verifier handoff. Every external effect
# (coordinator store, clock, process table, subprocesses) is an injectable seam.
# ---------------------------------------------------------------------------

import time as _time

# R1: one reserved key per host; the coordinator store is local, so the key needs no repo
# component. The directory is the coordinator's own, never an ancestor of a working path.
HEAVY_LEASE_KEY = os.path.join(os.path.realpath(os.path.expanduser("~")), ".agent-chat-mcp", ".nightshift-heavy-suite")
HEAVY_DEFAULTS: dict[str, Any] = {"command_patterns": ("xcodebuild",), "wait_limit_s": 1800.0, "poll_s": 5.0}


class LeaseUnavailable(RuntimeError):
    """The coordinator lease could not be taken; callers fail open (SPEC-NS-KIT-001 R5)."""


def load_heavy_config(config_path: Path | None) -> dict[str, Any]:
    """`heavy_suite:` block of config.yaml (commands matching a pattern are heavy), with defaults."""
    config = dict(HEAVY_DEFAULTS)
    if config_path is None:
        return config
    try:
        import yaml

        for document in yaml.safe_load_all(config_path.read_text(encoding="utf-8")):
            block = document.get("heavy_suite") if isinstance(document, dict) else None
            if isinstance(block, dict):
                for key in HEAVY_DEFAULTS:
                    if block.get(key) is not None:
                        config[key] = block[key]
    except Exception:  # noqa: BLE001 - a malformed config keeps the defaults
        return dict(HEAVY_DEFAULTS)
    return config


def is_heavy_command(command: str, patterns: Iterable[str]) -> bool:
    return any(pattern and pattern in command for pattern in patterns)


class CoordinatorLeaseStore:
    """Real adapter. The read side mirrors hooks/main-freeze.sh (read-only sqlite, same
    liveness/expiry rule). Kit code has no coordinator write path, so a free lease cannot be
    claimed from here: a session that claimed the key through the coordinator holds the lease; a
    free key makes acquire() raise LeaseUnavailable and the caller fails open with a warning; a
    live lease held by another session is honoured (the waiter records gate wait)."""

    def __init__(self, db_path: str | None = None, key: str = HEAVY_LEASE_KEY, *, now: Any = None) -> None:
        self.db_path = db_path or os.environ.get("AGENT_CHAT_LOCAL_COORDINATOR_DB") or os.path.expanduser(
            "~/.agent-chat-mcp/local-coordinator.db")
        self.key, self._now = key, now or (lambda: datetime.now(timezone.utc))

    def holder(self) -> tuple[str | None, set[str]]:
        """(live holder session id or None, coordinator session ids that are this caller)."""
        import sqlite3
        from urllib.parse import quote

        try:
            con = sqlite3.connect(f"file:{quote(self.db_path)}?mode=ro", uri=True, timeout=0.2)
            try:
                row = con.execute(
                    "SELECT c.session_id, c.expires_at, s.status FROM local_path_claims c "
                    "LEFT JOIN local_sessions s ON s.session_id = c.session_id WHERE c.canonical_path = ?",
                    (self.key,)).fetchone()
                mine: set[str] = set()
                override = os.environ.get("NIGHTSHIFT_COORDINATOR_SESSION", "").strip()
                if override:  # same identity resolution as hooks/main-freeze.sh
                    mine.add(override)
                else:
                    for name in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID"):
                        external = os.environ.get(name, "").strip()
                        if external:
                            mine.update(r[0] for r in con.execute(
                                "SELECT session_id FROM local_sessions WHERE external_id = ? AND status != 'ended'",
                                (external,)))
                            break
            finally:
                con.close()
        except Exception as error:  # noqa: BLE001 - any read failure is an advisory outage
            raise LeaseUnavailable(f"coordinator store unreadable ({type(error).__name__})") from error
        if not row or row[2] in (None, "ended"):
            return None, mine
        try:
            expires = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
        except ValueError:
            return None, mine
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return (str(row[0]) if expires > self._now() else None), mine

    def acquire(self, session: str) -> str | None:
        holder, mine = self.holder()
        if holder is not None and (holder == session or holder in mine):
            return None  # this session claimed the key (a coordinator path claim): it holds the lease
        if holder is not None:
            return holder
        raise LeaseUnavailable("lease not claimed and kit code has no coordinator write path; "
                               "claim the key through the coordinator before a heavy suite")

    def release(self, session: str) -> None:
        return None


def lease_session_id() -> str:
    for name in ("NIGHTSHIFT_COORDINATOR_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "HERMES_SESSION_ID"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return f"pid-{os.getpid()}"


@contextlib.contextmanager
def heavy_suite_lease(
    store: Any, *, session: str, wait_limit_s: float = 1800.0, poll_s: float = 5.0,
    clock: Any = _time.monotonic, sleep: Any = _time.sleep,
):
    """Serialise heavy suites per host (R1). Yields {acquired, fail_open, gate_wait_s, warning}.

    Waiting is bounded; an outage, a wait past the limit or any store error fails open with a
    warning on stderr (advisory lease, like SPEC-NS-KIT-001)."""
    info: dict[str, Any] = {"acquired": False, "fail_open": False, "gate_wait_s": 0.0, "warning": None}
    started = clock()
    try:
        while True:
            holder = store.acquire(session)
            if holder is None:
                info["acquired"] = True
                break
            if clock() - started >= wait_limit_s:
                info.update(fail_open=True, warning=f"heavy-suite lease still held by {holder} after {wait_limit_s:g}s")
                break
            sleep(poll_s)
    except Exception as error:  # noqa: BLE001 - lease outage never blocks the suite
        info.update(fail_open=True, warning=f"heavy-suite lease unavailable ({error})")
    info["gate_wait_s"] = round(clock() - started, 3)
    if info["warning"]:
        print(f"[nightshift heavy-suite lease] WARNING: {info['warning']}; running without the lease (advisory)",
              file=sys.stderr)
    try:
        yield info
    finally:
        if info["acquired"]:
            with contextlib.suppress(Exception):
                store.release(session)


# R2/R3/R4: budgets come from recorded history (child 001 sidecars), never from one fixed run clock.
BUDGET_DEFAULTS_S = {"surface_preparation": 1800.0, "verifier_sample": 1800.0, "verifier_overhead": 300.0,
                     "integration": 3600.0}
BUDGET_MARGIN = 2.0
INTEGRATION_STAGES = ("post_verdict_gates", "post_verdict_scope", "post_verdict_terminal_integrity",
                      "post_verdict_fresh_main", "merge_cleanup", "cleanup_diagnostic")
CLEANUP_DRAIN_S = 120.0


def _sidecars(metrics_dir: Path | None) -> list[dict[str, Any]]:
    import record_metrics

    if metrics_dir is None or not Path(metrics_dir).is_dir():
        return []
    return [record_metrics.load_timing_sidecar(p) for p in sorted(Path(metrics_dir).glob("*.verification.json"))]


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def derive_budget_s(history: Iterable[float], default_s: float, *, margin: float = BUDGET_MARGIN) -> float:
    """margin x the slowest recorded value, never below the conservative default; default alone without history."""
    values = [float(v) for v in history if _positive(v)]
    return round(max(default_s, margin * max(values)), 3) if values else float(default_s)


def prepare_dispatch_timeout_s(metrics_dir: Path | None) -> float:
    history = [s["stages"].get("surface_preparation") for s in _sidecars(metrics_dir)]
    return derive_budget_s(history, BUDGET_DEFAULTS_S["surface_preparation"])


def verifier_budget_s(metrics_dir: Path | None, *, samples_per_arm: int = SAMPLES_DEFAULT, arms: int = 2,
                      suites: int = 1) -> float:
    """Suite time x sample count (+ fixed overhead). Takes no worker input: the worker cannot spend it."""
    walls = [x.get("wall_s") for s in _sidecars(metrics_dir) for x in s["samples"]]
    per_sample = derive_budget_s(walls, BUDGET_DEFAULTS_S["verifier_sample"])
    return round(per_sample * max(1, samples_per_arm) * max(1, arms) * max(1, suites)
                 + BUDGET_DEFAULTS_S["verifier_overhead"], 3)


def integration_budget_s(metrics_dir: Path | None) -> float:
    """Merge + fresh-main gates + cleanup, from recorded post-verdict stage sums, plus the owned-process drain."""
    totals = []
    for sidecar in _sidecars(metrics_dir):
        parts = [sidecar["stages"].get(name) for name in INTEGRATION_STAGES]
        parts = [p for p in parts if _positive(p)]
        if parts:
            totals.append(sum(parts))
    return round(derive_budget_s(totals, BUDGET_DEFAULTS_S["integration"]) + CLEANUP_DRAIN_S, 3)


class Budget:
    """One independent time budget; expiry of one never touches another."""

    def __init__(self, name: str, limit_s: float, *, clock: Any = _time.monotonic) -> None:
        self.name, self.limit_s, self._clock = name, float(limit_s), clock
        self._started: float | None = None

    def start(self) -> "Budget":
        self._started = self._clock()
        return self

    def elapsed_s(self) -> float:
        return round(self._clock() - self._started, 3) if self._started is not None else 0.0

    def expired(self) -> bool:
        return self._started is not None and self.elapsed_s() >= self.limit_s


def budget_expiry_record(budget: Budget, partial: Iterable[Any]) -> dict[str, Any]:
    """`budget_expiry`: partial samples are kept as evidence; it is never a verdict."""
    return {"kind": "budget_expiry", "budget": budget.name, "limit_s": round(budget.limit_s, 3),
            "elapsed_s": budget.elapsed_s(), "partial_samples": list(partial), "is_verdict": False}


def run_within_budget(budget: Budget, steps: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Run steps while the budget lasts; a step that overruns keeps its result as a partial sample."""
    budget.start()
    done: list[Any] = []
    for name, step in steps:
        if budget.expired():
            return {"completed": done, "expiry": budget_expiry_record(budget, done)}
        done.append({"step": name, "result": step()})
        if budget.expired():
            return {"completed": done, "expiry": budget_expiry_record(budget, done)}
    return {"completed": done, "expiry": None}


def integration_decision(verdict_passed: bool, integration: Budget, *, run_elapsed_s: float = 0.0,
                         whole_run_limit_s: float | None = None) -> dict[str, Any]:
    """R4: a passed independent verdict is never reverted/blocked by a whole-run clock; only the
    integration budget's own expiry is recorded (as `budget_expiry`)."""
    if not verdict_passed:
        return {"proceed": False, "reason": "no_passing_verdict", "expiry": None}
    if integration.expired():
        return {"proceed": False, "reason": "integration_budget_expired",
                "expiry": budget_expiry_record(integration, [])}
    return {"proceed": True, "reason": "integration_budget_remaining", "expiry": None,
            "whole_run_clock_ignored": whole_run_limit_s is not None and run_elapsed_s >= whole_run_limit_s}


# R6: durable private diagnostics first, bounded stdout second.
def persist_private(directory: Path, name: str, text: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / name
    data = text.encode("utf-8", errors="replace")
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def bounded_summary(record: Mapping[str, Any], text: str, *, head: int = 5, tail: int = 20, width: int = 240) -> str:
    """Path, hash and a few head/tail lines: a marker can never be lost to transport truncation."""
    lines = text.splitlines()
    clip = lambda rows: [row[:width] for row in rows]  # noqa: E731
    return json.dumps({**record, "lines": len(lines), "head": clip(lines[:head]), "tail": clip(lines[-tail:])},
                      sort_keys=True)


# R7: observation of an already-signalled, positively owned helper. This code has no signalling
# capability at all: it only reads inventories, so it can never send a second signal.
def observe_signalled_cleanup(
    owned: Iterable[Mapping[str, Any]], read_inventory: Any, *, drain_s: float = 60.0, poll_s: float = 2.0,
    clock: Any = _time.monotonic, sleep: Any = _time.sleep, out_dir: Path | None = None,
) -> dict[str, Any]:
    """`owned` rows: {pid, start, owner} captured at the single TERM. Inventories: {complete, rows}
    where rows carry pid/start/owner/argv and the observer's own row has control=True. Absence
    counts only in a complete inventory that contains the positive control; a present row with the
    same pid/start/owner (whatever its argv, e.g. an exiting label) is still draining. With
    `out_dir` each inventory is written to a private file as it is read."""
    original = copy.deepcopy([dict(o) for o in owned])
    pending = {o["pid"]: o for o in original}
    confirmed: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    inventories: list[dict[str, Any]] = []
    deadline, last_reason = clock() + drain_s, "drain_expired"
    while pending:
        try:
            inventory = read_inventory()
            if not isinstance(inventory, Mapping):
                raise ValueError("inventory is not an object")
        except Exception as error:  # noqa: BLE001 - an unreadable inventory is evidence of nothing
            inventory = {"complete": False, "rows": [], "error": type(error).__name__}
        inventories.append(copy.deepcopy(dict(inventory)))
        if out_dir is not None:  # every inventory is durable as it is read
            persist_private(out_dir, f"cleanup-inventory-{len(inventories):03d}.json",
                            json.dumps(inventory, sort_keys=True, default=str))
        rows = [r for r in inventory.get("rows") or [] if isinstance(r, Mapping)]
        proof = inventory.get("complete") is True
        control = any(r.get("control") for r in rows)
        last_reason = "drain_expired" if proof and control else ("control_missing" if proof else "incomplete_inventory")
        for pid, target in list(pending.items()):
            row = next((r for r in rows if r.get("pid") == pid and not r.get("control")), None)
            if row is None:
                if proof and control:
                    confirmed.append(target)
                    del pending[pid]
                continue
            if row.get("start") is None or row.get("owner") is None:
                gaps.append({"pid": pid, "reason": "unknown_identity"})
            elif row["start"] != target["start"]:
                gaps.append({"pid": pid, "reason": "pid_reuse_or_changed_start"})
            elif row["owner"] != target["owner"]:
                gaps.append({"pid": pid, "reason": "foreign_identity"})
            else:
                continue  # same PID/start/owner: transient label, keep observing, never a proof
            del pending[pid]
        if not pending or clock() >= deadline:
            break
        sleep(poll_s)
    gaps.extend({"pid": pid, "reason": last_reason} for pid in pending)
    return {"cleanup": "confirmed" if not gaps else "gap", "confirmed": confirmed, "gaps": gaps,
            "inventories": inventories, "signals_sent": 0, "original_owned": original}


# R8: native exit, diagnostics, transport and cleanup are separate fields.
SUCCESS_MARKER_RE = re.compile(r"(?:\*\* TEST SUCCEEDED \*\*|Test Suite .* passed|\d+ passed)")


def native_record(exit_code: Any, *, timed_out: bool = False, output: str = "") -> dict[str, Any]:
    """The native exit is whatever was captured; a success marker or later test-case rows never infer exit 0."""
    marker = bool(SUCCESS_MARKER_RE.search(output))
    if timed_out:
        return {"state": "unavailable", "reason": "native_timeout", "exit_code": None, "suite_marker_seen": marker}
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return {"state": "unavailable", "reason": "exit_capture_missing", "exit_code": None,
                "suite_marker_seen": marker}
    return {"state": "captured", "exit_code": exit_code, "suite_marker_seen": marker}


def run_native_observed(
    argv: list[str], *, out_dir: Path, inventory_fn: Any, native_timeout_s: float, inventory_timeout_s: float = 5.0,
    popen: Any = subprocess.Popen, transport: str = "ok", cleanup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a native command while a diagnostic inventory runs under its own timeout.

    A diagnostic timeout never cancels the native command. The native exit is persisted the
    moment it is available, before diagnostics are rendered. Nothing but our own direct child is
    ever signalled, and only on native timeout."""
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = out_dir / "native-output.log"
    with open(log_path, "wb") as sink:
        proc = popen(argv, stdout=sink, stderr=subprocess.STDOUT)
        diagnostic: dict[str, Any]
        try:
            diagnostic = {"state": "ok", "inventory": inventory_fn(inventory_timeout_s)}
        except (TimeoutError, subprocess.TimeoutExpired):
            diagnostic = {"state": "timeout", "inventory": None}
        except Exception as error:  # noqa: BLE001 - diagnostics are never the native outcome
            diagnostic = {"state": "unavailable", "inventory": None, "error": type(error).__name__}
        timed_out, code = False, None
        try:
            code = proc.wait(timeout=native_timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(Exception):
                proc.kill()  # our own direct child only
    output = log_path.read_text(encoding="utf-8", errors="replace")
    native = native_record(code, timed_out=timed_out, output=output)
    native_file = persist_private(out_dir, "native-exit.json", json.dumps(native, sort_keys=True))
    diag_file = persist_private(out_dir, "diagnostics.json", json.dumps(diagnostic, sort_keys=True, default=str))
    return {"native": native, "diagnostic": {"state": diagnostic["state"], **diag_file},
            "transport": {"state": transport}, "cleanup": dict(cleanup) if cleanup else {"cleanup": "unknown"},
            "native_exit_file": native_file, "output": bounded_summary(
                {"path": str(log_path)}, output)}


def command_inventory(argv: list[str], timeout_s: float) -> dict[str, Any]:
    """Real process-table reader: raises on timeout instead of waiting forever."""
    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s, check=True)
    return {"complete": True, "rows": [], "raw_lines": len(done.stdout.splitlines())}


# R5: one-shot handoff after worker-done.
HANDOFF_PLACEHOLDER_RE = re.compile(r"\{(?:spec-id|branch|baseline_commit|suite_commands|scope_summary|"
                                    r"acceptance_criteria_verbatim|verdict_path|required_samples_per_arm|"
                                    r"escalated_samples_per_arm)\}")


class HandoffRefused(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


@dataclass
class HandoffRequest:
    project_root: Path
    worktree: Path
    spec_id: str
    spec_path: str
    run_id: str
    baseline: str
    branch: str
    worker_done_head: str
    receipt_ref: str
    receipt_sha256: str
    report_path: str
    private_dir: Path
    result_path: Path
    main_branch: str = "main"
    suite_commands: list[str] = field(default_factory=list)
    metrics_dir: Path | None = None
    no_suite: bool = False
    run_kind: str = "kickoff"
    kit_root: Path | None = None
    evidence: Path | None = None


def _skill_block(skill: Path, begin: str, end: str) -> str:
    """A pinned block, read from its guide in the kit that holds ``skill`` (never from SKILL.md)."""
    guide = PINNED_BLOCK_GUIDES.get(begin)
    try:
        text = load_guide(skill, guide) if guide else ""
    except VerdictAssemblyError as error:
        raise HandoffRefused("skill_block_missing", f"{begin}: {error}") from error
    if begin not in text or end not in text:
        raise HandoffRefused("skill_block_missing", begin)
    return text[text.index(begin):text.index(end) + len(end)]


def _ac_block(spec_text: str) -> str:
    found = re.search(r"## Acceptance Criteria\n(.*?)\n## ", spec_text, re.S)
    if not found:
        raise HandoffRefused("acceptance_criteria_missing")
    return found.group(1).strip()


def compose_handoff_brief(skill: Path, spec_text: str, plan: Mapping[str, Any], verdict_path: Path) -> str:
    """Verifier brief from the SKILL template: ACs verbatim from main's spec, canonical verdict block."""
    import yaml

    suites = list(plan.get("suite_commands") or [])
    tag = "VERIFIER-BRIEF" if suites else "VERIFIER-BRIEF-NOSUITE"
    block = _skill_block(skill, f"<!-- NIGHTSHIFT-{tag}-BEGIN -->", f"<!-- NIGHTSHIFT-{tag}-END -->")
    front = yaml.safe_load(spec_text.split("---")[1]) or {}
    scope = plan.get("scope_summary") or ("scope.write = " + ", ".join((front.get("scope") or {}).get("write") or []))
    sampling = plan.get("sampling") or {}
    values = {
        "spec-id": str(plan["spec_id"]), "branch": f"{plan['head_ref']} ({plan['head_commit']})",
        "baseline_commit": str(plan["baseline_commit"]),
        "suite_commands": "; ".join(f"`{c}`" for c in suites) or "none (no-test-suite: suites must be [])",
        "scope_summary": scope, "acceptance_criteria_verbatim": _ac_block(spec_text),
        "verdict_path": str(verdict_path),
        "required_samples_per_arm": str(sampling.get("required_samples_per_arm", SAMPLES_DEFAULT)),
        "escalated_samples_per_arm": str(sampling.get("escalated_samples_per_arm", SAMPLES_ESCALATED)),
    }
    for key, value in values.items():
        block = block.replace("{" + key + "}", value)
    text = load_guide(skill, TEMPLATE_GUIDE)
    template = text[:text.index(VERDICT_TEMPLATE_SENTENCE)]
    verdict_block = template[template.rindex("```json") + len("```json"):template.rindex("```")].strip("\n")
    # The template's example scope path names a run report, which the contamination scan flags in a
    # parent-authored brief; the example value is neutral, the shape stays canonical.
    verdict_block = verdict_block.replace("nightshift-report", "example-file")
    arms = plan["arm_working_directories"]
    header = (
        "Assigned verifier surface (your ONLY working directories; never read anything else under /Users):\n"
        f"- repository: {plan['repository']}\n- baseline arm dir: {arms['baseline']}\n- head arm dir: {arms['head']}\n"
        f"Identity fields to copy into the verdict: baseline_commit={plan['baseline_commit']}, "
        f"head_commit={plan['head_commit']}, branch=\"{plan['head_ref']}\", "
        f"implementation_head_digest={plan['implementation_head_digest']}, identity_schema_version=\"1.0.0\".\n"
        f"scope.checked must equal exactly the output of `git -C {plan['repository']} diff --name-only "
        "--diff-filter=ACDMR verifier-baseline verifier-head` (rename-aware). scope.amended holds paths only.\n"
        "git_footprint: record `git -C <arm> rev-parse HEAD^{tree}` and `git -C <arm> status --porcelain` "
        "before and after your work, per arm.\n"
        "A test file that exists only at head is NOT a suite entry: cite its head result in the AC evidence strings.\n"
        f"Canonical verdict JSON template (copy shape exactly):\n```json\n{verdict_block}\n```\n\n"
    )
    out = header + block
    if HANDOFF_PLACEHOLDER_RE.search(out):
        raise HandoffRefused("brief_placeholder_unfilled", HANDOFF_PLACEHOLDER_RE.search(out).group(0))
    return out


class RealHandoffSteps:
    """Production effects for `handoff`; tests substitute a fake with the same methods."""

    def __init__(self, req: HandoffRequest, *, skill: Path | None = None) -> None:
        self.req = req
        self.skill = locate_skill(skill)
        self.kit = req.kit_root or Path(__file__).resolve().parent

    def _git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.req.project_root), *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise HandoffRefused("git_failed", " ".join(args[:2]))
        return done.stdout

    def branch_head(self) -> str:
        return self._git("rev-parse", self.req.branch).strip()

    def managed_drift(self) -> list[str]:
        names = self._git("diff", "--name-only", self.req.baseline, self.req.main_branch).splitlines()
        return [n for n in names if n and not _EXEMPT_RE.match(n)]

    def terminal_integrity(self) -> tuple[str, str]:
        import managed_payload_provenance as provenance

        result = provenance.verify_terminal_integrity(
            self.kit, spec_id=self.req.spec_id, receipt_ref=self.req.receipt_ref,
            receipt_sha256=self.req.receipt_sha256, run_id=None)
        return str(result.outcome), str(result.reason_code)

    def scope_gate(self) -> dict[str, Any]:
        import textwrap

        block = _skill_block(self.skill, "# NIGHTSHIFT-SCOPE-GATE-BEGIN", "# NIGHTSHIFT-SCOPE-GATE-END")
        with tempfile.TemporaryDirectory(prefix="ns-scope-gate-") as scratch:
            script = Path(scratch) / "scope_gate.py"
            script.write_text(textwrap.dedent("   " + block) + "\n", encoding="utf-8")
            done = subprocess.run(
                [sys.executable, str(script), str(self.req.project_root), self.req.spec_path, self.req.main_branch,
                 self.req.baseline, self.req.branch], capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        status = next((ln.split(":", 1)[1].strip() for ln in done.stdout.splitlines() if ln.startswith("SCOPE-CHECK:")),
                      "unknown")
        return {"status": status, "output": done.stdout[-2000:]}

    def report_check(self) -> list[str]:
        import validate_specs

        path = Path(self.req.worktree) / self.req.report_path
        if not path.is_file():
            return ["run report missing"]
        findings = validate_specs.validate_report_headings(path)
        if "❌" in path.read_text(encoding="utf-8"):
            findings.append("report contains a failed-check marker")
        return findings

    def prepare_dispatch(self, timeout_s: float) -> dict[str, Any]:
        req = self.req
        surface = req.private_dir / "surface"
        evidence = req.evidence or (req.project_root / ".nightshift" / "reports" / f"{req.spec_id}-verifier-surface.json")
        argv = [sys.executable, str(Path(__file__).resolve()), "prepare-dispatch", "--source", str(req.worktree),
                "--destination", str(surface), "--baseline", req.baseline, "--head", req.worker_done_head,
                "--spec-id", req.spec_id, "--run-id", req.run_id, "--report-path", req.report_path,
                "--evidence", str(evidence), "--spec-path", req.spec_path]
        for command in req.suite_commands:
            argv += ["--suite-command", command]
        if req.no_suite:
            argv.append("--no-suite")
        shutil.rmtree(surface, ignore_errors=True)
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as error:
            raise HandoffRefused("prepare_dispatch_timeout", f"{timeout_s:g}s derived budget") from error
        if done.returncode != 0:
            raise HandoffRefused("prepare_dispatch_failed", done.stderr[-300:])
        return json.loads(done.stdout)

    def build_brief(self, plan: Mapping[str, Any]) -> tuple[str, str]:
        spec_text = self._git("show", f"{self.req.main_branch}:{self.req.spec_path}")
        return compose_handoff_brief(self.skill, spec_text, plan, self.req.private_dir / "verdict.json"), spec_text

    def brief_check(self, brief_path: Path, spec_copy: Path) -> tuple[bool, str]:
        block = _skill_block(self.skill, "# NIGHTSHIFT-BRIEF-CHECK-BEGIN", "# NIGHTSHIFT-BRIEF-CHECK-END")
        done = subprocess.run(["bash", "-c", f'{block}\nbrief_check "$1" "$2"', "bash", str(brief_path), str(spec_copy)],
                              capture_output=True, text=True)
        return done.returncode == 0 and "BRIEF: clean" in done.stdout, done.stdout[-500:]

    def checkpoint(self, event: str) -> None:
        script = self.kit / "extension_checkpoint.sh"
        if not script.is_file():
            return
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([str(script), "--project-root", str(self.req.project_root), "--run-id", self.req.run_id,
                            "--spec-id", self.req.spec_id, "--run-kind", self.req.run_kind, "--event", event,
                            "--outcome", "passed" if event == "work.completed" else "unknown"],
                           capture_output=True, text=True, timeout=60)

    def record_stage(self, stage: str, seconds: float) -> None:
        import record_metrics

        if self.req.metrics_dir is not None:
            with contextlib.suppress(ValueError, OSError, TimeoutError):
                record_metrics.append_timing_record(self.req.metrics_dir, self.req.spec_id, "stage",
                                                    {"stage": stage, "seconds": round(seconds, 3)})


def run_handoff(req: HandoffRequest, steps: Any, *, clock: Any = _time.monotonic) -> dict[str, Any]:
    """Every post-worker-done step in one invocation; refuses if the worker head moved (R5)."""
    done: list[str] = []
    # A poller can tell "running" from "crashed": the record exists before any step runs.
    persist_private(req.result_path.parent, req.result_path.name,
                    json.dumps({"status": "running", "spec_id": req.spec_id}, sort_keys=True))

    def head_unmoved(label: str) -> None:
        done.append(f"head_check:{label}")
        head = steps.branch_head()
        if head != req.worker_done_head:
            # BUG-NS-KIT-107 R5: the stale_head family (formerly worker_head_moved); detail unchanged.
            raise HandoffRefused("stale_head", f"{label}: branch head differs from worker-done head")

    try:
        head_unmoved("start")
        done.append("managed_drift")
        moved = steps.managed_drift()
        if moved:
            raise HandoffRefused("managed_path_moved", ", ".join(moved[:5]))
        done.append("terminal_integrity")  # exactly once, run_id=None, before anything touches main
        outcome, reason = steps.terminal_integrity()
        if outcome != "allow":
            raise HandoffRefused("terminal_integrity", f"{outcome} {reason}")
        done.append("scope_gate")
        gate = steps.scope_gate()
        if gate["status"] not in {"clean", "amended", "not_run"}:
            raise HandoffRefused("scope_gate", gate["status"])
        done.append("report_check")
        findings = steps.report_check()
        if findings:
            raise HandoffRefused("report_check", "; ".join(findings))
        done.append("prepare_dispatch")
        timeout_s = prepare_dispatch_timeout_s(req.metrics_dir)
        started = clock()
        plan = steps.prepare_dispatch(timeout_s)
        steps.record_stage("surface_preparation", clock() - started)
        done.append("brief")
        brief, spec_text = steps.build_brief(plan)
        req.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        brief_file = persist_private(req.private_dir, "brief.md", brief)
        persist_private(req.private_dir, "plan.json", json.dumps(plan, sort_keys=True))
        spec_copy = req.private_dir.with_name(req.private_dir.name + "-spec-copy.md")
        spec_copy.write_text(spec_text, encoding="utf-8")
        done.append("brief_check")
        clean, text = steps.brief_check(Path(brief_file["path"]), spec_copy)
        if not clean:
            raise HandoffRefused("brief_contaminated", text.strip()[:300])
        head_unmoved("final")
        for event in ("work.completed", "verification.requested"):
            done.append(f"checkpoint:{event}")
            steps.checkpoint(event)
        result = {"status": "ok", "spec_id": req.spec_id, "steps": done, "brief": brief_file,
                  "private_dir": str(req.private_dir), "head": req.worker_done_head,
                  "prepare_dispatch_timeout_s": timeout_s, "scope_check": gate["status"],
                  "verifier_budget_s": verifier_budget_s(
                      req.metrics_dir, samples_per_arm=int((plan.get("sampling") or {}).get(
                          "required_samples_per_arm", SAMPLES_DEFAULT)),
                      suites=len(plan.get("suite_commands") or []) or 1),
                  "integration_budget_s": integration_budget_s(req.metrics_dir)}
    except HandoffRefused as refusal:
        result = {"status": "refused", "spec_id": req.spec_id, "reason": refusal.reason, "detail": refusal.detail,
                  "steps": done}
    persisted = persist_private(req.result_path.parent, req.result_path.name, json.dumps(result, sort_keys=True))
    return {**result, "result_file": persisted}


def handoff_main(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    req = HandoffRequest(
        project_root=root, worktree=args.worktree.resolve(), spec_id=args.spec_id, spec_path=args.spec_path,
        run_id=args.run_id, baseline=args.baseline, branch=args.branch, worker_done_head=args.worker_done_head,
        receipt_ref=args.receipt_ref, receipt_sha256=args.receipt_sha256, report_path=args.report_path,
        private_dir=args.private_dir.resolve(),
        result_path=(args.result_path or root / ".nightshift" / "reports" / args.spec_id / "handoff.json").resolve(),
        main_branch=args.main_branch, suite_commands=list(args.suite_command), metrics_dir=args.metrics_dir,
        no_suite=args.no_suite, run_kind=args.run_kind, kit_root=args.kit_root, evidence=args.evidence)
    try:
        steps = RealHandoffSteps(req, skill=args.skill)
    except VerdictAssemblyError as error:
        print(json.dumps({"status": "refused", "reason": "skill_missing", "detail": str(error)}), file=sys.stderr)
        return 2
    result = run_handoff(req, steps)
    print(json.dumps({k: result[k] for k in ("status", "reason", "steps", "result_file", "private_dir") if k in result},
                     sort_keys=True))
    return 0 if result["status"] == "ok" else 2



def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and not raw_argv[0].startswith("-") and raw_argv[0] not in {
        "prepare-dispatch",
        "prepare-surface",
        "verifier-self-test",
        "verify-preflight-proof",
        "verify-evidence-projection",
        "suite-sample",
        "throughput-report",
        "lane-spend-report",
        "ledger",
        "assemble-verdict",
        "validate-verdict",
        "trusted-kit",
        "handoff",
        "merge-gate",
    }:
        data = load_report(Path(raw_argv[0]))
        errors = validate_report_dict(data)
        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            return 1
        print(render_markdown(data))
        return 0
    if raw_argv[:1] == ["ledger"]:
        return ledger_main(raw_argv[1:])
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
    prepare.add_argument("--spec-path", default=None)
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
    # SPEC-NS-KIT-004 R1: docs/design specs: emit the no-test-suite brief and never
    # default to commands.test.
    dispatch.add_argument("--no-suite", action="store_true")
    # SPEC-288: repository-relative path of the spec under verification. Supplying
    # it is what permits that spec's predeclared external evidence to be projected;
    # omitting it leaves the dispatch exactly as it was before SPEC-288.
    dispatch.add_argument("--spec-path", default=None)
    # SPEC-NS-KIT-002-005 R1: give the verifier each arm's contractual spec projection.
    # SPEC-NS-KIT-008: default-on; --project-spec is an accepted no-op, --no-project-spec opts out.
    dispatch.add_argument("--project-spec", dest="project_spec", action="store_true", default=True)
    dispatch.add_argument("--no-project-spec", dest="project_spec", action="store_false")
    # SPEC-390-002: the coordinator's own SHA-256 of the retained preflight result a
    # `preflight-proof:` declaration names. Never taken from the spec or the report.
    prepare.add_argument("--preflight-proof-sha256", default=None)
    dispatch.add_argument("--preflight-proof-sha256", default=None)
    # SPEC-NS-KIT-002-002: optional main test-status ledger projected as a reused baseline.
    dispatch.add_argument("--ledger", type=Path, default=None)
    dispatch.add_argument("--ledger-identity-file", type=Path, default=None)
    # SPEC-NS-KIT-002-004: R3 isolation (LABEL=VALUE, baseline/head) and R5 trusted main copy.
    dispatch.add_argument("--arm-device", action="append", default=[])
    dispatch.add_argument("--arm-runtime", action="append", default=[])
    dispatch.add_argument("--main-branch", default="main")
    assemble = subparsers.add_parser("assemble-verdict")
    assemble.add_argument("--plan", required=True, type=Path)
    assemble.add_argument("--input", required=True, type=Path)
    assemble.add_argument("--spec-path", default=None)
    assemble.add_argument("--spec-file", type=Path, default=None)
    assemble.add_argument("--main-root", type=Path, default=None)
    assemble.add_argument("--main-branch", default="main")
    assemble.add_argument("--skill", type=Path, default=None)
    assemble.add_argument("--out", type=Path, default=None)
    validate = subparsers.add_parser("validate-verdict")
    validate.add_argument("--plan", required=True, type=Path)
    validate.add_argument("--verdict", required=True, type=Path)
    validate.add_argument("--spec-path", default=None)
    validate.add_argument("--spec-file", type=Path, default=None)
    validate.add_argument("--main-root", type=Path, default=None)
    validate.add_argument("--main-branch", default="main")
    validate.add_argument("--skill", type=Path, default=None)
    trusted = subparsers.add_parser("trusted-kit")
    trusted.add_argument("--source", required=True, type=Path)
    trusted.add_argument("--main-branch", default="main")
    trusted.add_argument("--materialize", type=Path, default=None)
    gate = subparsers.add_parser("merge-gate")
    gate.add_argument("--plan", type=Path, default=None)
    gate.add_argument("--evidence", type=Path, default=None)
    gate.add_argument("--verdict", type=Path, default=None)
    gate.add_argument("--branch", required=True)
    gate.add_argument("--candidate", default=None)
    gate.add_argument("--heartbeat", type=Path, default=None)
    gate.add_argument("--repo", type=Path, default=Path.cwd())
    gate.add_argument("--main-root", type=Path, default=None)
    gate.add_argument("--main-branch", default="main")
    hand = subparsers.add_parser("handoff")
    hand.add_argument("--project-root", type=Path, default=Path.cwd())
    hand.add_argument("--worktree", required=True, type=Path)
    for name in ("spec-id", "spec-path", "run-id", "baseline", "branch", "worker-done-head", "receipt-ref",
                 "receipt-sha256", "report-path"):
        hand.add_argument(f"--{name}", required=True)
    hand.add_argument("--private-dir", required=True, type=Path)
    hand.add_argument("--result-path", type=Path, default=None)
    hand.add_argument("--main-branch", default="main")
    hand.add_argument("--suite-command", action="append", default=[])
    hand.add_argument("--no-suite", action="store_true")
    hand.add_argument("--metrics-dir", type=Path, default=None)
    hand.add_argument("--run-kind", default="kickoff", choices=("run", "kickoff"))
    hand.add_argument("--kit-root", type=Path, default=None)
    hand.add_argument("--evidence", type=Path, default=None)
    hand.add_argument("--skill", type=Path, default=None)
    subparsers.add_parser("verifier-self-test")
    sample = subparsers.add_parser("suite-sample")
    sample.add_argument("--spec-id", required=True)
    sample.add_argument("--arm", required=True)
    sample.add_argument("--suite", required=True)
    sample.add_argument("--sample", type=int, default=1)
    sample.add_argument("--metrics-dir", type=Path, default=Path(".nightshift/metrics"))
    sample.add_argument("--xcode", action="store_true")
    sample.add_argument("--output-dir", type=Path, default=None,
                        help="persist full output here first and print a bounded summary (SPEC-NS-KIT-002-007 R6)")
    sample.add_argument("--no-heavy-lease", action="store_true")
    sample.add_argument("suite_command", nargs=argparse.REMAINDER)
    report = subparsers.add_parser("throughput-report")
    report.add_argument("--metrics-dir", action="append", required=True)
    report.add_argument("--json", action="store_true")
    report.add_argument("--out", type=Path, default=None)
    lane = subparsers.add_parser("lane-spend-report")
    lane.add_argument("--metrics-dir", type=Path, required=True)
    lane.add_argument("--runs-dir", type=Path, default=None)
    lane.add_argument("--git-repo", type=Path, default=None)
    lane.add_argument("--rev", default="HEAD", help="pin the git history read, so a re-run is byte-identical")
    lane.add_argument("--trailers-file", type=Path, default=None, help="offline JSONL of trailer records")
    lane.add_argument("--specs-dir", type=Path, default=None)
    lane.add_argument("--specs-dir-in-repo", action="append", default=None)
    lane.add_argument("--project", default=None)
    lane.add_argument("--json", action="store_true")
    lane.add_argument("--out", type=Path, default=None)
    evidence_check = subparsers.add_parser("verify-evidence-projection")
    evidence_check.add_argument("--surface", required=True, type=Path)
    evidence_check.add_argument("--candidate-revision-digest", required=True)
    proof_check =subparsers.add_parser("verify-preflight-proof")
    proof_check.add_argument("--surface", required=True, type=Path)
    proof_check.add_argument("--candidate-revision-digest", required=True)
    args = parser.parse_args(raw_argv)
    trusted_record: dict[str, Any] | None = None
    if args.command in {"prepare-dispatch", "assemble-verdict", "validate-verdict", "merge-gate"}:
        # SPEC-NS-KIT-002-004 R5: these commands always run from main's copy of the kit.
        trust_source = args.source if args.command == "prepare-dispatch" else (args.main_root or Path.cwd())
        try:
            trusted_record, rerun = ensure_trusted_kit(trust_source, raw_argv, main_branch=args.main_branch)
        except TrustedKitError as refusal:
            print(json.dumps({"status": "evidence_gap", "controller_reason": "trusted_kit_unavailable",
                              "detail": str(refusal)}, sort_keys=True), file=sys.stderr)
            return 2
        if rerun is not None:
            return rerun
    if args.command == "trusted-kit":
        try:
            record = resolve_trusted_kit(args.source, main_branch=args.main_branch)
            if args.materialize is not None:
                if record["copy"] != "main":
                    raise TrustedKitError(f"no main copy to materialize ({record.get('reason')})")
                materialize_trusted_kit(args.source, record, args.materialize)
        except TrustedKitError as refusal:
            print(f"trusted-kit: {refusal}", file=sys.stderr)
            return 2
        print(json.dumps(public_trusted_record(record, reexecuted=False), sort_keys=True))
        return 0
    if args.command == "handoff":
        return handoff_main(args)
    if args.command == "merge-gate":
        return merge_gate_main(args)
    if args.command == "validate-verdict":
        return validate_verdict_main(args)
    if args.command == "assemble-verdict":
        return assemble_verdict_main(args, trusted_record or {})
    if args.command == "suite-sample":
        command = list(args.suite_command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            print("suite-sample requires a command after --", file=sys.stderr)
            return 2
        return run_suite_sample(
            command, spec_id=args.spec_id, arm=args.arm, suite=args.suite,
            sample=args.sample, metrics_dir=args.metrics_dir, xcode=args.xcode,
            output_dir=args.output_dir, heavy=not args.no_heavy_lease,
        )
    if args.command == "lane-spend-report":
        args.specs_dir_in_repo = args.specs_dir_in_repo or ["canonical/specs", ".nightshift/specs", "specs"]
        return lane_spend_main(args)
    if args.command == "throughput-report":
        sources: list[tuple[str, Path]] = []
        for raw in args.metrics_dir:
            label, sep, location = raw.partition("=")
            directory = Path(location if sep else raw)
            if not directory.is_dir():
                print(f"throughput-report: not a directory: {directory.name}", file=sys.stderr)
                return 2
            sources.append((label if sep else "", directory))
        data = build_throughput_report(sources)
        text = json.dumps(data, indent=2, sort_keys=True) if args.json else render_throughput_report(data)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    if args.command == "verify-evidence-projection":
        outcome = check_projected_evidence(
            args.surface,
            expected_candidate_revision_digest=args.candidate_revision_digest,
        )
        print(json.dumps(outcome, sort_keys=True))
        return 0 if outcome["result"] == "verified" else 1
    if args.command == "verify-preflight-proof":
        outcome = check_projected_preflight_proof(
            args.surface,
            expected_candidate_revision_digest=args.candidate_revision_digest,
        )
        print(json.dumps(outcome, sort_keys=True))
        return 0 if outcome["result"] == "verified" else 1
    if args.command == "prepare-surface":
        prepare_verifier_surface(
            args.source, args.destination, baseline_ref=args.baseline,
            head_ref=args.head, report_paths=args.report_path, evidence_path=args.evidence,
            spec_id=args.spec_id, spec_path=args.spec_path,
            preflight_proof_sha256=args.preflight_proof_sha256,
        )
        return 0
    if args.command == "prepare-dispatch":
        # R2/SPEC-243-001: when the caller supplies no explicit --suite-command,
        # derive the default from the source project's own declared config
        # rather than falling back silently to the no-test-suite brief.
        suite_commands = list(args.suite_command)
        if args.no_suite and suite_commands:
            print("--no-suite conflicts with --suite-command", file=sys.stderr)
            return 2
        if not suite_commands and not args.no_suite:
            configured = configured_suite_command(args.source)
            if configured is not None:
                suite_commands = [configured]
        proof_digest = args.preflight_proof_sha256
        if proof_digest is None:
            # SPEC-390-002-002: no explicit flag -> the out-of-band record preflight
            # wrote. Consulted only when the spec declares a proof, so a spec with
            # none is untouched; an absent record leaves `no_reference_digest`.
            try:
                declared = resolve_declared_preflight_proofs(
                    args.source.resolve(), baseline_ref=args.baseline,
                    head_ref=args.head, spec_path=args.spec_path,
                )
            except (DeclaredInputRefusal, ValueError, RuntimeError):
                declared = []  # the dispatch below reports its own refusal
            if declared:
                try:
                    proof_digest = recorded_preflight_digest(
                        args.source, spec_id=args.spec_id, head_ref=args.head,
                    )
                except PreflightDigestRefusal as refusal:
                    print(json.dumps({
                        "status": "evidence_gap",
                        "controller_reason": refusal.reason,
                    }, sort_keys=True), file=sys.stderr)
                    return 2
        try:
            prepared = prepare_verifier_dispatch(
                args.source, args.destination, baseline_ref=args.baseline,
                head_ref=args.head, report_paths=args.report_path,
                evidence_path=args.evidence, suite_commands=suite_commands,
                spec_id=args.spec_id, run_id=args.run_id, spec_path=args.spec_path,
                preflight_proof_sha256=proof_digest,
                project_spec=args.project_spec,
                ledger_path=args.ledger,
                arm_isolation={
                    "devices": dict(item.split("=", 1) for item in args.arm_device) or None,
                    "runtime": dict(item.split("=", 1) for item in args.arm_runtime) or None,
                },
                trusted_tooling=trusted_record,
                ledger_identity=(
                    json.loads(args.ledger_identity_file.read_text(encoding="utf-8"))
                    if args.ledger is not None and args.ledger_identity_file is not None else None
                ),
            )
        except ArmIsolationError as refusal:
            print(json.dumps({
                "status": "evidence_gap", "controller_reason": refusal.reason,
                "detail": refusal.detail,
            }, sort_keys=True), file=sys.stderr)
            return 2
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
