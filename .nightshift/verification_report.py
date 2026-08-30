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
from pathlib import Path, PurePosixPath
from typing import Any

try:  # pragma: no cover - deployed install may be incomplete
    from preflight import KitRootError, load_commands, resolve_kit_root
except Exception:  # pragma: no cover - deployed install may be incomplete
    KitRootError = None  # type: ignore[assignment,misc]
    load_commands = None  # type: ignore[assignment]
    resolve_kit_root = None  # type: ignore[assignment]

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
    "acs", "suites", "git_footprint", "contamination",
})
VERIFIER_IDENTITY_SCHEMA_VERSION = "1.0.0"
CONTAINMENT_EVIDENCE_SCHEMA_VERSION = "1.6.0"
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
        surface_repositories = self.evidence["surface_repositories"]
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
            # SPEC-282 (R1/R2/AC3): each arm is already materialized as its own
            # runnable, read-only working directory under the same standalone
            # surface -- the verifier never checks out or materializes a ref
            # itself, it only names the already-assigned directory per arm.
            "arm_working_directories": dict(surface_repositories),
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


def _materialize_ref(
    source_repository: Path,
    destination: Path,
    ref: str,
    *,
    report_paths: Iterable[str],
    retained_report_paths: Iterable[str] = (),
    same_spec_metrics_paths: Iterable[str] = (),
) -> tuple[list[str], list[dict[str, str]]]:
    """Materialize one tracked snapshot without sharing the source object DB.

    Returns the withheld paths and the per-entry record of every tracked symlink
    materialized as something other than a symlink (SPEC-285). The two lists are
    kept apart deliberately: a withheld path must be *unreachable* from the
    surface, while a transformed entry is still present and committed.
    """
    _clear_snapshot(destination)
    surface_root = destination.resolve()
    excluded: list[str] = []
    transformed: list[dict[str, str]] = []
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
            record = _materialize_symlink(
                body.decode("utf-8", "surrogateescape"),
                target=target, destination=surface_root, path=path,
            )
            if record is not None:
                transformed.append(record)
        else:
            target.write_bytes(body)
            target.chmod(0o755 if mode == "100755" else 0o644)
    return sorted(excluded), sorted(transformed, key=lambda record: record["path"])


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
    except DeclaredInputRefusal as refusal:
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
        raise
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
    projected_paths: list[str] = []
    excluded_by_ref: dict[str, list[str]] = {}
    transformed_by_ref: dict[str, list[dict[str, str]]] = {}
    fixed_env = _git_environment(
        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2000-01-01T00:00:00Z",
    )
    for label, ref in refs:
        excluded_by_ref[label], transformed_by_ref[label] = _materialize_ref(
            source_repository,
            destination,
            ref,
            report_paths=report_paths,
            retained_report_paths=retained_reports,
            same_spec_metrics_paths=same_spec_metrics,
        )
        projected_paths = _project_external_inputs(
            destination, resolved_inputs, input_records
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
        projected_paths,
    )

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
            spec_path=spec_path,
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
        ready = (
            projection_ready
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
    # SPEC-288: repository-relative path of the spec under verification. Supplying
    # it is what permits that spec's predeclared external evidence to be projected;
    # omitting it leaves the dispatch exactly as it was before SPEC-288.
    dispatch.add_argument("--spec-path", default=None)
    subparsers.add_parser("verifier-self-test")
    args = parser.parse_args(raw_argv)
    if args.command == "prepare-surface":
        prepare_verifier_surface(
            args.source, args.destination, baseline_ref=args.baseline,
            head_ref=args.head, report_paths=args.report_path, evidence_path=args.evidence,
            spec_id=args.spec_id, spec_path=args.spec_path,
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
                spec_id=args.spec_id, run_id=args.run_id, spec_path=args.spec_path,
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
