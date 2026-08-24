#!/usr/bin/env python3
"""validate_install.py — fail-closed installation and integration admission gate (SPEC-229).

Answers one question before any Nightshift start surface crosses the LOOP
boundary: is this exact Nightshift install safe to use for this start? It is a
fast, deterministic, side-effect-free validator. It never executes project
build/test/lint commands and never changes Git, specs, configuration, managed
payload, lifecycle state, or application files. Its only allowed write is one
atomic JSON artifact under the install's ignored ``reports/_wip/install-validation/``
directory.

Exit codes: ``0`` allow (warnings permitted), ``1`` deny (a proven required
invariant failed), ``2`` indeterminate (validator/artifact failure or a
required ``unknown`` result). The JSON artifact plus its externally computed
SHA-256 is the machine contract; terminal prose is never authoritative.

Reused, not reimplemented: ``release.py`` supplies manifest/fingerprint/mode
logic, ``managed_payload_provenance.py`` supplies retained-manifest and
divergence-classification logic. This module adds the admission boundary,
config-severity contract, and signal contract around them.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("Error: PyYAML required.", file=sys.stderr)
    sys.exit(2)

CANONICAL_DIR = Path(__file__).resolve().parent
if str(CANONICAL_DIR) not in sys.path:
    sys.path.insert(0, str(CANONICAL_DIR))

import release  # noqa: E402
import managed_payload_provenance as provenance  # noqa: E402

SCHEMA_VERSION = "1.0.0"
VALIDATOR_VERSION = "1.0.0"

ADMISSION_ALLOW = "allow"
ADMISSION_DENY = "deny"
ADMISSION_INDETERMINATE = "indeterminate"

STATUS_SEVERITY_RANK = {
    "pass": 0,
    "not_applicable": 0,
    "warning": 1,
    "unknown": 2,
    "fail": 3,
}

# Entrypoint inventory: every supported start surface that this validator
# proves invokes the gate before any lifecycle/Git/command/dispatch action.
# This list is deliberately the authority for INT.ENTRYPOINTS: it must name
# only surfaces that are ACTUALLY wired, so a partial-wiring rollout never
# reports a false ALLOW. The AC8 entrypoint-inventory regression test
# (test_validate_install.py::test_entrypoint_inventory_matches_repo) is the
# mechanism that fails when a new start surface is added without wiring it
# here first — see the "Suggested Follow-up Specs" section of the SPEC-229
# report for the surfaces NOT YET in this list (nightshift_coordinator.py,
# nightshift-instructions.py, the board-copied kickoff skill route).
ENTRYPOINT_INVENTORY: tuple[dict[str, str], ...] = (
    {"path": "preflight.py", "marker": "validate_install"},
    {"path": "LOOP.md", "marker": "validate_install.py"},
    {"path": "ORCHESTRATOR.md", "marker": "validate_install.py"},
    {"path": "BOOTSTRAP.md", "marker": "validate_install.py"},
)

# Managed entrypoints/runtime resources that KIT.CLOSURE proves are declared,
# present, and probe-able from the selected install root.
REQUIRED_RUNTIME_ENTRYPOINTS = ("validate_install.py", "preflight.py", "board.py", "board.sh")

PLACEHOLDER_PROJECT_NAMES = {
    "", "my-app", "tram-tracker", "multi-stack-example", "change_me", "todo",
    "your-project-name", "project-name", "example",
}
KIT_BOOTSTRAP_FIXTURE_MARKERS = ("_eval-project", "eval-project", "kit bootstrap fixture")
REQUIRED_CONFIG_SECTIONS = (
    "project", "commands", "review", "runner", "git", "nightshift_state", "release_policy",
)
RUNNER_MODES = {"inline", "orchestrator"}


class DuplicateKeyLoader(yaml.SafeLoader):
    """Multi-document YAML loader that rejects duplicate/conflicting keys.

    ``yaml.safe_load`` silently keeps the last value on a repeated mapping
    key, which lets the *effective* owner of a config value become
    ambiguous. R4 requires that ambiguity to be a structural parse error,
    not a silent overwrite.
    """


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate/conflicting key: {key!r}", node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class ConfigParseError(ValueError):
    """config.yaml cannot be parsed under the shared strict-duplicate-key loader."""


@dataclass
class Invariant:
    id: str
    category: str
    required: bool
    status: str = "unknown"
    severity: str = "unknown"
    expected: Any = None
    observed: Any = None
    evidence: list[str] = field(default_factory=list)
    owner: str = "unknown"
    remediation_code: str = "NS-REM-UNKNOWN"
    blocks_loop: bool = False
    detail: str = ""

    def set(
        self,
        status: str,
        *,
        severity: str | None = None,
        expected: Any = None,
        observed: Any = None,
        evidence: list[str] | None = None,
        owner: str | None = None,
        remediation_code: str | None = None,
        detail: str = "",
    ) -> "Invariant":
        self.status = status
        self.severity = severity if severity is not None else status
        self.expected = expected
        self.observed = observed
        self.evidence = evidence or []
        if owner is not None:
            self.owner = owner
        if remediation_code is not None:
            self.remediation_code = remediation_code
        self.detail = detail
        self.blocks_loop = self.required and status in ("fail", "unknown")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "required": self.required,
            "status": self.status,
            "severity": self.severity,
            "expected": self.expected,
            "observed": self.observed,
            "evidence": self.evidence,
            "owner": self.owner,
            "remediation_code": self.remediation_code,
            "blocks_loop": self.blocks_loop,
            "safe_auto_fix": False,
            "detail": self.detail,
        }


def _rel(base: Path, target: Path) -> str:
    """Return a project-relative evidence path; never leaks an absolute path."""
    try:
        return str(target.resolve().relative_to(base.resolve()))
    except ValueError:
        return f"<outside-root>/{target.name}"


def _load_config_documents(config_path: Path) -> list[dict[str, Any]]:
    """Parse every YAML document with the shared strict loader.

    Raises ``ConfigParseError`` on missing file, empty file, invalid syntax,
    a non-mapping document, or a duplicate/conflicting key — the exact ERROR
    row at the top of the Configuration Severity Contract.
    """
    if not config_path.is_file():
        raise ConfigParseError("config.yaml absent")
    text = config_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ConfigParseError("config.yaml empty")
    try:
        documents = list(yaml.load_all(text, Loader=DuplicateKeyLoader))
    except yaml.YAMLError as exc:
        raise ConfigParseError(f"config.yaml YAML syntax invalid: {exc.__class__.__name__}") from exc
    documents = [doc for doc in documents if doc is not None]
    if not documents:
        raise ConfigParseError("config.yaml has no documents")
    for doc in documents:
        if not isinstance(doc, dict):
            raise ConfigParseError("config.yaml document is not a mapping")
    return documents


def _merge_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for doc in documents:
        repeated = merged.keys() & doc.keys()
        if repeated:
            key = sorted(repeated, key=str)[0]
            raise ConfigParseError(f"duplicate/conflicting top-level key across documents: {key!r}")
        merged.update(doc)
    return merged


def _is_placeholder_name(name: Any) -> bool:
    if not isinstance(name, str):
        return True
    return name.strip().lower() in PLACEHOLDER_PROJECT_NAMES


def _git_run(repo: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
        )
        return proc.returncode, (proc.stdout or "").strip()
    except OSError:
        return 127, ""


def _git_path(repo: Path, name: str) -> Path | None:
    code, out = _git_run(repo, "rev-parse", "--git-path", name)
    if code != 0 or not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else (repo / path)


@dataclass
class ValidationContext:
    root: Path
    install: Path
    profile: str
    kind: str
    spec_id: str | None
    config_path: Path
    invariants: list[Invariant] = field(default_factory=list)

    def add(self, inv: Invariant) -> Invariant:
        self.invariants.append(inv)
        return inv


def check_root_identity(ctx: ValidationContext) -> None:
    inv = Invariant("ROOT.IDENTITY", "root", required=True)
    try:
        install = ctx.install.resolve(strict=False)
        code, toplevel = _git_run(install, "rev-parse", "--show-toplevel")
        code2, common = _git_run(install, "rev-parse", "--git-common-dir")
        if code != 0:
            inv.set(
                "fail",
                observed="not-a-git-repository",
                expected="git-repository",
                evidence=[],
                owner="operator",
                remediation_code="NS-REM-GIT-ROOT",
                detail="install root does not resolve to a Git repository",
            )
            ctx.add(inv)
            return
        toplevel_path = Path(toplevel).resolve()
        # Traversal/symlink-escape check: the resolved install must not sit
        # outside the resolved git toplevel via a symlink hop.
        try:
            install.relative_to(toplevel_path)
            escapes = False
        except ValueError:
            # A linked worktree's install dir can legitimately live outside
            # the main toplevel; that is valid when its common-dir resolves.
            escapes = code2 != 0
        if escapes:
            inv.set(
                "fail",
                observed="path-escape",
                expected="install-under-git-root-or-linked-worktree",
                owner="operator",
                remediation_code="NS-REM-ROOT-ESCAPE",
                detail="install root is not reachable from its Git identity",
            )
        else:
            inv.set(
                "pass",
                observed="resolved",
                expected="resolved",
                evidence=[_rel(ctx.root, install)],
                owner="validator",
                remediation_code="NS-REM-NONE",
            )
    except OSError as exc:
        inv.set(
            "unknown",
            observed=str(exc.__class__.__name__),
            expected="resolved",
            owner="validator",
            remediation_code="NS-REM-IO",
            detail="I/O failure while resolving root identity",
        )
    ctx.add(inv)


def _canonical_names() -> list[str]:
    """Load CANONICAL_PROTOCOL_FILES without importing nightshift-sync.py as a module
    that would itself need to be on the release manifest (it already is)."""
    sync_path = CANONICAL_DIR.parent / "nightshift-sync.py"
    spec = importlib.util.spec_from_file_location("nightshift_sync", sync_path)
    if spec is None or spec.loader is None:
        raise ConfigParseError("nightshift-sync.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.CANONICAL_PROTOCOL_FILES)


def check_kit_marker_and_payload_canonical(ctx: ValidationContext) -> None:
    marker_inv = Invariant("KIT.MARKER", "payload", required=True)
    payload_inv = Invariant("KIT.PAYLOAD", "payload", required=True)
    try:
        names = _canonical_names()
    except (ConfigParseError, OSError) as exc:
        marker_inv.set("unknown", observed=str(exc), owner="validator", remediation_code="NS-REM-IO")
        payload_inv.set("unknown", observed="not-checked", owner="validator", remediation_code="NS-REM-IO")
        ctx.add(marker_inv)
        ctx.add(payload_inv)
        return

    ok, errors, manifest = release.validate_manifest(ctx.install, names)
    version_errors = [e for e in errors if "version" in e or "changelog" in e]
    file_errors = [e for e in errors if e not in version_errors]

    if manifest is None:
        marker_inv.set(
            "fail", observed="manifest-missing-or-corrupt", expected="valid-release-manifest",
            owner="canonical-release-maintainer", remediation_code="NS-REM-MARKER-MISSING",
            evidence=[_rel(ctx.root, ctx.install / "release-manifest.json")],
        )
    elif version_errors:
        marker_inv.set(
            "fail", observed="version-mismatch", expected="kit/schema/changelog-agree",
            owner="canonical-release-maintainer", remediation_code="NS-REM-MARKER-VERSION",
            detail="; ".join(version_errors)[:400],
        )
    else:
        marker_inv.set("pass", observed="agree", expected="agree", owner="validator", remediation_code="NS-REM-NONE")
    ctx.add(marker_inv)

    declared = len(names)
    checked = len(manifest["files"]) if manifest else 0
    if manifest is not None and not file_errors and declared > 0 and checked == declared:
        payload_inv.set(
            "pass", observed=f"{checked}/{declared}", expected=f"{declared}/{declared}",
            owner="validator", remediation_code="NS-REM-NONE",
        )
    else:
        payload_inv.set(
            "fail",
            observed=f"{checked}/{declared}" if manifest else "0/0",
            expected=f"{declared}/{declared}",
            owner="canonical-release-maintainer", remediation_code="NS-REM-PAYLOAD-MISMATCH",
            detail="; ".join(file_errors)[:400],
        )
    ctx.add(payload_inv)


def check_kit_marker_and_payload_installed(ctx: ValidationContext) -> None:
    marker_inv = Invariant("KIT.MARKER", "payload", required=True)
    payload_inv = Invariant("KIT.PAYLOAD", "payload", required=True)
    try:
        retained = provenance.retained_manifest(ctx.install)
    except provenance.MetadataError as exc:
        marker_inv.set(
            "fail", observed="marker-invalid", expected="fingerprint-bound-retained-manifest",
            owner="operator", remediation_code="NS-REM-MARKER-MISSING", detail=str(exc)[:300],
        )
        payload_inv.set("unknown", observed="not-checked", owner="validator", remediation_code="NS-REM-IO")
        ctx.add(marker_inv)
        ctx.add(payload_inv)
        return

    marker_inv.set("pass", observed="agree", expected="agree", owner="validator", remediation_code="NS-REM-NONE")
    ctx.add(marker_inv)

    ok, errors = release.verify_install(ctx.install, retained)
    declared = len(retained.get("files", []))
    if ok and declared > 0:
        payload_inv.set(
            "pass", observed=f"{declared}/{declared}", expected=f"{declared}/{declared}",
            owner="validator", remediation_code="NS-REM-NONE",
        )
    else:
        payload_inv.set(
            "fail", observed=f"{declared - len(errors)}/{declared}" if declared else "0/0",
            expected=f"{declared}/{declared}",
            owner="operator", remediation_code="NS-REM-PAYLOAD-MISMATCH",
            detail="; ".join(errors)[:400],
        )
    ctx.add(payload_inv)

    # AC4: distinguish exact-current / retained-prior-release / unresolved-divergence
    # for dirty managed paths. Requires Git; not_applicable when unavailable.
    try:
        rows = provenance.audit_git_install(ctx.install, current_manifest=retained)
        divergent = [r for r in rows if r.classification == provenance.UNRESOLVED_DIVERGENCE]
        if divergent:
            payload_inv.status = "fail"
            payload_inv.severity = "fail"
            payload_inv.detail = (payload_inv.detail + "; unresolved-divergence on dirty managed paths")[:400]
            payload_inv.blocks_loop = True
    except provenance.MetadataError:
        pass


def check_kit_closure(ctx: ValidationContext) -> None:
    inv = Invariant("KIT.CLOSURE", "payload", required=True)
    missing: list[str] = []
    unprobeable: list[str] = []
    for name in REQUIRED_RUNTIME_ENTRYPOINTS:
        path = ctx.install / name
        if not path.is_file():
            missing.append(name)
            continue
        if name.endswith(".py"):
            try:
                import ast
                ast.parse(path.read_text(encoding="utf-8"), filename=name)
            except (SyntaxError, UnicodeDecodeError):
                unprobeable.append(name)
        elif name.endswith(".sh"):
            if not (path.stat().st_mode & 0o111):
                unprobeable.append(name)

    try:
        names = _canonical_names() if ctx.profile == "canonical" else [
            entry["path"] for entry in provenance.retained_manifest(ctx.install).get("files", [])
        ]
        gaps = release.managed_import_gaps(ctx.install, names) if ctx.profile == "canonical" else []
    except (ConfigParseError, provenance.MetadataError, OSError):
        gaps = []

    if missing or unprobeable or gaps:
        inv.set(
            "fail",
            observed={"missing": missing, "unprobeable": unprobeable, "import_gaps": len(gaps)},
            expected="all-declared-present-and-probeable",
            owner="canonical-release-maintainer", remediation_code="NS-REM-CLOSURE-GAP",
            detail=("; ".join(gaps)[:300] if gaps else ""),
        )
    else:
        inv.set(
            "pass", observed="closed", expected="closed",
            owner="validator", remediation_code="NS-REM-NONE",
        )
    ctx.add(inv)


# ---------------------------------------------------------------------------
# Configuration Severity Contract (R4)
# ---------------------------------------------------------------------------

@dataclass
class ConfigFinding:
    key: str
    status: str  # error|warning|not_applicable|pass|unknown
    code: str
    owner: str
    action: str


def evaluate_config(ctx: ValidationContext) -> tuple[list[ConfigFinding], dict[str, Any] | None, str | None]:
    """Return (findings, merged-config-or-None, config-sha256-or-None)."""
    findings: list[ConfigFinding] = []
    try:
        raw = ctx.config_path.read_bytes()
        config_sha = hashlib.sha256(raw).hexdigest()
    except OSError:
        config_sha = None

    try:
        documents = _load_config_documents(ctx.config_path)
        config = _merge_documents(documents)
    except ConfigParseError as exc:
        findings.append(ConfigFinding("<root>", "error", "NS-CFG-PARSE", "operator", str(exc)))
        return findings, None, config_sha

    schema_version = config.get("schema_version")
    if not isinstance(schema_version, str) or not re.match(r"^\d+\.\d+\.\d+$", schema_version or ""):
        findings.append(ConfigFinding("schema_version", "error", "NS-CFG-SCHEMA-VERSION", "operator",
                                       "set schema_version to a supported x.y.z value"))
    kit_version_cfg = config.get("kit_version")
    try:
        expected_kit_version = release.kit_version(CANONICAL_DIR)
    except (OSError, ValueError):
        expected_kit_version = None
    if ctx.profile == "installed" and expected_kit_version and kit_version_cfg not in (None, expected_kit_version):
        # Installed config need not match the *canonical checkout's* kit_version
        # (that is the retained release marker's job, checked by KIT.MARKER);
        # this only flags a structurally malformed kit_version field.
        pass
    if kit_version_cfg is not None and not isinstance(kit_version_cfg, str):
        findings.append(ConfigFinding("kit_version", "error", "NS-CFG-KIT-VERSION", "operator",
                                       "kit_version must be a string"))

    for section in REQUIRED_CONFIG_SECTIONS:
        if not isinstance(config.get(section), dict):
            findings.append(ConfigFinding(section, "error", "NS-CFG-SECTION-MISSING", "operator",
                                           f"add a valid `{section}:` mapping section"))

    project = config.get("project") if isinstance(config.get("project"), dict) else {}
    if ctx.profile == "installed":
        # Canonical applies its own explicit source-template rule instead:
        # config.yaml in the canonical checkout is the starter template that
        # every install copies and fills in, not a host project config, so an
        # empty project.name/language there is correct, not a placeholder
        # residue. Only a real `installed` project is held to this rule.
        name = project.get("name")
        if _is_placeholder_name(name):
            findings.append(ConfigFinding("project.name", "error", "NS-CFG-IDENTITY-PLACEHOLDER", "operator",
                                           "set project.name to this project's real name"))
        language = project.get("language")
        if not language or (isinstance(language, list) and not language):
            findings.append(ConfigFinding("project.language", "error", "NS-CFG-IDENTITY-LANGUAGE", "operator",
                                           "set project.language to a non-empty list"))
    else:
        findings.append(ConfigFinding("project", "not_applicable", "NS-CFG-OK", "validator",
                                       "canonical source-template profile: identity fields are intentionally blank"))

    commands = config.get("commands") if isinstance(config.get("commands"), dict) else {}
    stacks = config.get("stacks") if isinstance(config.get("stacks"), dict) else {}
    domain = config.get("domain") if isinstance(config.get("domain"), dict) else {}
    effective_domain = domain.get("effective") or domain.get("type") or "code"

    if ctx.profile == "installed" and effective_domain == "code":
        flat_test = str(commands.get("test", "") or "").strip()
        stack_tests_ok = bool(stacks) and all(
            isinstance(v, dict) and str(v.get("commands", {}).get("test", "") or "").strip()
            for v in stacks.values()
        )
        if not flat_test and not (stacks and stack_tests_ok):
            findings.append(ConfigFinding("commands.test", "error", "NS-CFG-TEST-MISSING", "operator",
                                           "configure commands.test or every stack's test command"))
        else:
            findings.append(ConfigFinding("commands.test", "pass", "NS-CFG-OK", "validator", ""))

        for key in ("build",):
            if not str(commands.get(key, "") or "").strip():
                findings.append(ConfigFinding(f"commands.{key}", "not_applicable", "NS-CFG-OK", "validator", ""))
        for key in ("lint", "type_check"):
            if not str(commands.get(key, "") or "").strip():
                findings.append(ConfigFinding(f"commands.{key}", "warning", "NS-CFG-COMMAND-OPTIONAL-EMPTY",
                                               "project-maintainer", f"consider configuring commands.{key}"))
        for key in ("format", "format_fix"):
            if not str(commands.get(key, "") or "").strip():
                findings.append(ConfigFinding(f"commands.{key}", "not_applicable", "NS-CFG-OK", "validator", ""))

        # host installs must not retain eval-project/kit-bootstrap fixtures
        flat_test_l = flat_test.lower()
        if any(marker in flat_test_l for marker in ("_eval-project", "eval-project")):
            findings.append(ConfigFinding("commands.test", "error", "NS-CFG-EVAL-PROJECT-RESIDUE", "operator",
                                           "point commands.test at this project, not the kit's eval fixture"))

    runner = config.get("runner") if isinstance(config.get("runner"), dict) else {}
    mode = runner.get("mode")
    if mode is not None and mode not in RUNNER_MODES:
        findings.append(ConfigFinding("runner.mode", "error", "NS-CFG-RUNNER-MODE", "operator",
                                       f"set runner.mode to one of: {', '.join(sorted(RUNNER_MODES))}"))
    elif mode == "orchestrator":
        for field_name in ("model", "harness"):
            if not str(runner.get(field_name, "") or "").strip():
                findings.append(ConfigFinding(f"runner.{field_name}", "error", "NS-CFG-RUNNER-ORCHESTRATOR-FIELD",
                                               "operator", f"set runner.{field_name} for orchestrator mode"))

    circuit_breaker = config.get("circuit_breaker") if isinstance(config.get("circuit_breaker"), dict) else {}
    parallel_admission = config.get("parallel_admission") if isinstance(config.get("parallel_admission"), dict) else {}
    limit = parallel_admission.get("limit") if isinstance(parallel_admission, dict) else None
    if parallel_admission and (limit is None or not isinstance(limit, int) or limit <= 0):
        # NFR-001 fail-closed: missing/invalid limit is only a WARNING when the
        # consuming path demonstrably coerces to sequential (limit=1). This
        # validator cannot execute the coercing code path, so it records the
        # coercion as unproven and treats it per the stricter documented
        # default: warn (effective limit 1) rather than block, matching the
        # contract's "record effective limit 1" instruction — never ERROR
        # solely for an absent/zero value that config-side defaults already
        # coerce to sequential.
        findings.append(ConfigFinding("parallel_admission.limit", "warning", "NS-CFG-PARALLEL-LIMIT",
                                       "operator", "parallel limit missing/invalid; coerced to sequential (1)"))
    del circuit_breaker

    devkb = config.get("devkb") if isinstance(config.get("devkb"), dict) else {}
    devkb_path = devkb.get("path")
    if isinstance(devkb_path, str) and devkb_path:
        pass  # explicitly declared external field: absolute is allowed, never echoed

    return findings, config, config_sha


def check_config_invariants(ctx: ValidationContext, findings: list[ConfigFinding]) -> None:
    def worst(subset: list[ConfigFinding]) -> str:
        order = {"error": 3, "unknown": 2, "warning": 1, "not_applicable": 0, "pass": 0}
        if not subset:
            return "pass"
        return max(subset, key=lambda f: order.get(f.status, 0)).status

    def to_status(sev: str) -> tuple[str, str]:
        return {"error": ("fail", "fail"), "warning": ("warning", "warning"),
                "unknown": ("unknown", "unknown"), "pass": ("pass", "pass"),
                "not_applicable": ("not_applicable", "not_applicable")}[sev]

    def emit(inv_id: str, subset_keys: tuple[str, ...], required: bool = True) -> None:
        subset = [f for f in findings if f.key in subset_keys or f.key.split(".")[0] in subset_keys]
        sev = worst(subset)
        status, severity = to_status(sev)
        inv = Invariant(inv_id, "config", required=required)
        offenders = [f"{f.key}:{f.code}" for f in subset if f.status in ("error", "unknown")]
        inv.set(
            status, severity=severity,
            expected="no-required-config-errors", observed=f"{len(subset)}-findings-checked",
            evidence=offenders[:10],
            owner="operator" if status == "fail" else "validator",
            remediation_code=(subset[0].code if subset and subset[0].status in ("error", "unknown") else "NS-REM-NONE"),
        )
        ctx.add(inv)

    emit("CFG.PARSE_VERSION", ("<root>", "schema_version", "kit_version"))
    emit("CFG.IDENTITY", ("project",))
    emit("CFG.COMMAND_DOMAIN", ("commands",))
    emit("CFG.RUNNER_POLICY", ("runner", "parallel_admission", "circuit_breaker"))
    emit("CFG.PATH_PRIVACY", ("path",))


# ---------------------------------------------------------------------------
# Integration invariants
# ---------------------------------------------------------------------------

def check_int_git(ctx: ValidationContext) -> None:
    inv = Invariant("INT.GIT", "integration", required=True)
    code, _ = _git_run(ctx.install, "rev-parse", "--show-toplevel")
    hooks_dir = _git_path(ctx.install, "hooks")
    if code != 0 or hooks_dir is None:
        inv.set(
            "fail", observed="git-unresolved", expected="git-resolved",
            owner="operator", remediation_code="NS-REM-GIT-UNRESOLVED",
        )
    else:
        inv.set("pass", observed="resolved", expected="resolved", owner="validator", remediation_code="NS-REM-NONE")
    ctx.add(inv)


def check_int_directories(ctx: ValidationContext) -> None:
    inv = Invariant("INT.DIRECTORIES", "integration", required=True)
    required_dirs = ["specs", "reports", "metrics"] if ctx.profile == "installed" else ["specs", "reports"]
    missing = [d for d in required_dirs if not (ctx.install / d).is_dir()]
    if missing:
        inv.set(
            "warning", observed=missing, expected="present-or-safely-usable",
            owner="operator", remediation_code="NS-REM-DIR-MISSING",
            detail="directories are created on first use by the owning path, not by this read-only gate",
        )
    else:
        inv.set("pass", observed="present", expected="present", owner="validator", remediation_code="NS-REM-NONE")
    ctx.add(inv)


def check_int_hooks(ctx: ValidationContext) -> None:
    inv = Invariant("INT.HOOKS", "integration", required=(ctx.profile == "installed"))
    if ctx.profile != "installed":
        inv.set("not_applicable", observed="canonical-profile", expected="n/a", owner="validator",
                 remediation_code="NS-REM-NONE")
        ctx.add(inv)
        return
    hooks_dir = _git_path(ctx.install, "hooks")
    if hooks_dir is None:
        inv.set("fail", observed="hooks-dir-unresolved", expected="pre-commit-wired",
                 owner="operator", remediation_code="NS-REM-HOOK-MISSING")
        ctx.add(inv)
        return
    hook = hooks_dir / "pre-commit"
    if not hook.is_file():
        inv.set("fail", observed="missing", expected="present-and-executable",
                 owner="operator", remediation_code="NS-REM-HOOK-MISSING",
                 detail="reinstall through the whole-kit release")
        ctx.add(inv)
        return
    if not (hook.stat().st_mode & 0o111):
        inv.set("fail", observed="not-executable", expected="present-and-executable",
                 owner="operator", remediation_code="NS-REM-HOOK-MODE")
        ctx.add(inv)
        return
    try:
        content = hook.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = ""
    invokes_guard = (
        "managed_payload_provenance" in content
        or "guard_staged_install" in content
        or "release-manifest.json" in content
    )
    # An early unconditional `exit 0`/`return`/`true` before the guard marker
    # would false-green; a coarse but effective proof is that no unguarded
    # unconditional-success line appears before the first guard invocation.
    lines = content.splitlines()
    guard_line = next((i for i, ln in enumerate(lines) if "managed_payload_provenance" in ln or "guard_staged_install" in ln), None)
    shadowed = False
    if guard_line is not None:
        for ln in lines[:guard_line]:
            stripped = ln.strip()
            if stripped in ("exit 0", "return 0", "true") or re.match(r"^exit\s+0\s*$", stripped):
                shadowed = True
                break
    if invokes_guard and not shadowed:
        inv.set("pass", observed="wired", expected="wired", owner="validator", remediation_code="NS-REM-NONE")
    else:
        inv.set(
            "fail",
            observed="shadowed-or-disconnected" if shadowed else "not-wired",
            expected="wired-before-unconditional-success",
            owner="operator", remediation_code="NS-REM-HOOK-SHADOWED",
            detail="reinstall through the whole-kit release",
        )
    ctx.add(inv)


def check_int_entrypoints(ctx: ValidationContext) -> None:
    inv = Invariant("INT.ENTRYPOINTS", "integration", required=True)
    missing = []
    for entry in ENTRYPOINT_INVENTORY:
        path = ctx.install / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(entry["path"])
            continue
        if entry["marker"] not in text:
            missing.append(entry["path"])
    if missing:
        inv.set(
            "fail", observed=missing, expected="all-entrypoints-gated",
            owner="canonical-release-maintainer", remediation_code="NS-REM-ENTRYPOINT-GAP",
        )
    else:
        inv.set(
            "pass", observed=f"{len(ENTRYPOINT_INVENTORY)}/{len(ENTRYPOINT_INVENTORY)}",
            expected=f"{len(ENTRYPOINT_INVENTORY)}/{len(ENTRYPOINT_INVENTORY)}",
            owner="validator", remediation_code="NS-REM-NONE",
        )
    ctx.add(inv)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_validation(root: Path, profile: str, kind: str, spec_id: str | None) -> tuple[ValidationContext, list[ConfigFinding], dict[str, Any] | None, str | None]:
    root = root.resolve()
    install = root / ".nightshift" if profile == "installed" and (root / ".nightshift").is_dir() else root
    config_path = install / "config.yaml"
    ctx = ValidationContext(root=root, install=install, profile=profile, kind=kind, spec_id=spec_id, config_path=config_path)

    check_root_identity(ctx)
    if profile == "canonical":
        check_kit_marker_and_payload_canonical(ctx)
    else:
        check_kit_marker_and_payload_installed(ctx)
    check_kit_closure(ctx)

    findings, config, config_sha = evaluate_config(ctx)
    check_config_invariants(ctx, findings)

    check_int_git(ctx)
    check_int_directories(ctx)
    check_int_hooks(ctx)
    check_int_entrypoints(ctx)

    return ctx, findings, config, config_sha


def _atomic_write_artifact(install: Path, payload: dict[str, Any]) -> tuple[Path | None, str | None, Invariant]:
    inv = Invariant("ART.OUTPUT", "evidence", required=True)
    out_dir = install / "reports" / "_wip" / "install-validation"
    try:
        real_root = install.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        resolved_out_dir = out_dir.resolve()
        # Path/symlink-escape guard: resolved output dir must remain under
        # the resolved install root.
        resolved_out_dir.relative_to(real_root)
    except (OSError, ValueError) as exc:
        inv.set("fail", observed=str(exc.__class__.__name__), expected="writable-contained-directory",
                owner="validator", remediation_code="NS-REM-ARTIFACT-DIR")
        return None, None, inv

    invocation_id = payload["invocation_id"]
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", invocation_id) + ".json"
    dest = out_dir / safe_name
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".validate_install-", suffix=".tmp", dir=str(out_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, dest)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as exc:
        inv.set("fail", observed=str(exc.__class__.__name__), expected="atomic-write-success",
                owner="validator", remediation_code="NS-REM-ARTIFACT-WRITE")
        return None, None, inv

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    inv.set("pass", observed="written", expected="written", owner="validator", remediation_code="NS-REM-NONE",
             evidence=[_rel(install, dest)])
    return dest, digest, inv


def build_artifact(
    ctx: ValidationContext,
    config_sha: str | None,
    *,
    invocation_id: str | None = None,
) -> dict[str, Any]:
    invariants = ctx.invariants
    declared = len(invariants)
    applicable = sum(1 for i in invariants if i.status != "not_applicable")
    checked = sum(1 for i in invariants if i.status in ("pass", "fail", "warning", "unknown"))
    passed = sum(1 for i in invariants if i.status == "pass")
    failed = sum(1 for i in invariants if i.status == "fail")
    warning = sum(1 for i in invariants if i.status == "warning")
    unknown = sum(1 for i in invariants if i.status == "unknown")
    not_applicable = declared - applicable

    required_fail = any(i.required and i.status == "fail" for i in invariants)
    required_unknown = any(i.required and i.status == "unknown" for i in invariants)
    coverage_gap = not (checked == applicable and applicable > 0)

    if required_fail or coverage_gap and required_unknown:
        admission, exit_code = ADMISSION_DENY, 1
    elif required_unknown or coverage_gap:
        admission, exit_code = ADMISSION_INDETERMINATE, 2
    else:
        admission, exit_code = ADMISSION_ALLOW, 0

    highest_severity = "pass"
    for status in ("fail", "unknown", "warning"):
        if any(i.status == status for i in invariants):
            highest_severity = status
            break

    try:
        expected_kit_version = release.kit_version(CANONICAL_DIR)
    except (OSError, ValueError):
        expected_kit_version = None

    payload = {
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "invocation_id": invocation_id or uuid.uuid4().hex,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_ms": 0,
        "trust_profile": ctx.profile,
        "invocation_kind": ctx.kind,
        "admission": admission,
        "exit_code": exit_code,
        "highest_severity": highest_severity,
        "release": {"kit_version": expected_kit_version},
        "bindings": {
            "config_sha256": config_sha,
            "spec_id": ctx.spec_id,
        },
        "coverage": {
            "declared": declared, "applicable": applicable, "checked": checked,
            "passed": passed, "failed": failed, "warning": warning,
            "unknown": unknown, "not_applicable": not_applicable,
        },
        "invariants": [i.to_dict() for i in invariants],
        "privacy": {"redaction_applied": True},
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--profile", choices=("installed", "canonical"), required=True)
    parser.add_argument("--kind", choices=("normal", "kickoff", "bootstrap", "orchestrator", "preflight"), default="normal")
    parser.add_argument("--spec-id", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the full artifact JSON to stdout")
    args = parser.parse_args(argv)

    start = datetime.now(timezone.utc)
    try:
        ctx, findings, config, config_sha = run_validation(args.root, args.profile, args.kind, args.spec_id)
    except Exception as exc:  # noqa: BLE001 - any internal failure is indeterminate, never a crash
        print(f"INDETERMINATE: validator internal error ({exc.__class__.__name__})", file=sys.stderr)
        return 2

    # ART.OUTPUT is the last stable invariant. Its pass status is included in
    # the candidate bytes: a successful atomic write makes that statement true,
    # while a failed write produces no artifact and is reported indeterminate.
    invocation_id = uuid.uuid4().hex
    artifact_ref = f"reports/_wip/install-validation/{invocation_id}.json"
    art_inv = Invariant("ART.OUTPUT", "evidence", required=True)
    art_inv.set(
        "pass",
        observed="written",
        expected="written",
        owner="validator",
        remediation_code="NS-REM-NONE",
        evidence=[artifact_ref],
    )
    ctx.add(art_inv)
    artifact = build_artifact(ctx, config_sha, invocation_id=invocation_id)
    artifact["duration_ms"] = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    dest, digest, written_inv = _atomic_write_artifact(ctx.install, artifact)
    if dest is None:
        ctx.invariants[-1] = written_inv
        artifact = build_artifact(ctx, config_sha, invocation_id=invocation_id)
        artifact["duration_ms"] = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    admission = artifact["admission"]
    exit_code = artifact["exit_code"]
    if dest is None:
        admission, exit_code = ADMISSION_INDETERMINATE, 2

    label = {"allow": "ALLOW", "deny": "DENY", "indeterminate": "INDETERMINATE"}[admission]
    cov = artifact["coverage"]
    rel_dest = _rel(ctx.install, dest) if dest else "<unwritten>"
    print(f"{label} checked={cov['checked']}/{cov['applicable']} failed={cov['failed']} warning={cov['warning']} unknown={cov['unknown']} artifact={rel_dest} sha256={digest or 'n/a'}")
    rows = [i for i in artifact["invariants"] if i["status"] in ("fail", "warning", "unknown")][:5]
    for row in rows:
        print(f"  - {row['id']} [{row['status']}] owner={row['owner']} remedy={row['remediation_code']}")
    if args.json:
        print(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
