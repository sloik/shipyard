#!/usr/bin/env python3
"""preflight.py — mechanize LOOP Step 1 preflight capture (SPEC-089-001).

Checks the git baseline, selected spec status, after: dependencies, and configured
baseline commands, then writes a structured JSON artifact for reports/metrics.
The command is additive: it never edits specs or stages files.

Usage:
    python3 preflight.py --spec-id SPEC-XXX [--config .nightshift/config.yaml]
        [--specs-dir .nightshift/specs] [--metrics-dir .nightshift/metrics]
        [--repo .]
Exit code is 0 when no blocking preflight failures are found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GUIDE_MAX_BYTES = 24 * 1024
RELEASE_INVENTORY_RECORD = "tests/fixtures/spec-229-006/le2-installed-allow.json"


def guide_size_problems(text: str) -> list[str]:
    size = len(text.encode("utf-8"))
    return [f"guide is {size} bytes (max {GUIDE_MAX_BYTES})"] if size > GUIDE_MAX_BYTES else []


def registry_guide_problems(skill_path: Path, guides_dir: Path) -> list[str]:
    import skill_tutorial
    problems = []
    for entry in skill_tutorial.load_registry(skill_path):
        guide = entry.get("guide")
        if guide is None:
            continue
        prefix = ".nightshift/guides/"
        if not isinstance(guide, str) or not guide.startswith(prefix):
            problems.append(f"{entry['name']}: guide must be an install path under {prefix}")
        elif not (guides_dir / guide[len(prefix):]).is_file():
            problems.append(f"{entry['name']}: guide file {guide} is not in canonical/guides/")
    return problems


def release_invariant_preflight(canonical: Path, manifest: dict, *, previous: dict | None = None,
                                profile: str = "canonical") -> dict[str, Any]:
    """Read-only canonical release checks, never installed admission or suite evidence."""
    if profile != "canonical":
        return {"applicable": False, "status": "not_applicable", "profile": profile, "reused": False}
    import stat
    import artifact_reachability
    import skill_tutorial
    import release

    canonical = canonical.resolve()
    findings = []
    inputs = {}
    def finding(rule, path, detail):
        findings.append({"rule": rule, "path": path, "detail": detail})
    def bind(path):
        relative = path.relative_to(canonical).as_posix()
        if path.is_file():
            data = path.read_bytes()
            inputs[relative] = {"sha256": hashlib.sha256(data).hexdigest(),
                                "mode": stat.S_IMODE(path.stat().st_mode)}
            return data
        inputs[relative] = None
        return None
    guides = canonical / "guides"
    for path in sorted(guides.rglob("*.md")):
        data = bind(path)
        if len(data) > GUIDE_MAX_BYTES:
            finding("guide_byte_cap", path.relative_to(canonical).as_posix(), f"{len(data)} bytes exceeds {GUIDE_MAX_BYTES}")
    skill = canonical / "Skills/nightshift/SKILL.md"
    if bind(skill) is not None:
        try:
            for problem in registry_guide_problems(skill, guides):
                finding("guide_registration", "Skills/nightshift/SKILL.md", problem)
        except (ValueError, OSError) as error:
            finding("guide_registration", "Skills/nightshift/SKILL.md", str(error))
    elif any(str(row.get("path", "")).startswith("guides/") for row in manifest.get("files", [])):
        finding("guide_registration", "Skills/nightshift/SKILL.md", "managed guides require the commands registry")
    specs, errors = _load_specs(canonical / "specs")
    for error in errors:
        finding("report_reachability", "specs", error)
    tracked = subprocess.run(["git", "-C", str(canonical), "ls-files", "-z", "--", "reports"], capture_output=True)
    tracked_paths = [p.decode("utf-8", "surrogateescape") for p in tracked.stdout.split(b"\0") if p] if tracked.returncode == 0 else None
    report_findings = artifact_reachability.sweep_reports_directory(canonical, specs, tracked_paths=tracked_paths)
    for path, problems in report_findings.items():
        for problem in problems:
            finding("report_reachability", path, problem)
    report_entries = []
    if (canonical / "reports").is_dir():
        report_entries = sorted(p.name for p in (canonical / "reports").iterdir()
                                if not p.name.startswith(".") and p.name not in artifact_reachability.REPORTS_EXCLUDED_NAMES)
        if tracked_paths is None and report_entries:
            finding("report_ownership", "reports", "Git index ownership unavailable")
    entries = release.release_entries(manifest)
    inventory = {"status": "not_present", "comparison_performed": False}
    record = canonical / RELEASE_INVENTORY_RECORD
    data = bind(record)
    if data is not None:
        try:
            saved = json.loads(data)
            if saved.get("spec") == "SPEC-229-006" and saved.get("scenario") == "LE2":
                observed = saved.get("stable", {}).get("manifest_files_checked")
                expected = len(entries)  # validate_install's authoritative installed payload inventory count
                inventory = {"status": "compatible" if type(observed) is int and observed == expected else "stale",
                             "comparison_performed": True, "observed": observed, "expected": expected,
                             "admission_proved": False}
                if inventory["status"] == "stale":
                    finding("saved_inventory", RELEASE_INVENTORY_RECORD, f"stable.manifest_files_checked={observed}; sealed inventory={expected}")
            else:
                inventory = {"status": "unrelated", "comparison_performed": False, "admission_proved": False}
        except (ValueError, AttributeError, TypeError) as error:
            finding("saved_inventory", RELEASE_INVENTORY_RECORD, f"unreadable selected record: {error}")
    identity = {"schema_version": 1, "inputs": inputs, "spec_ids": sorted(specs),
                "report_entries": report_entries, "tracked_reports": sorted(tracked_paths or []),
                "sealed_inventory": sorted((row["path"], bool(row.get("executable"))) for row in entries),
                "policy": {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                           for module in (artifact_reachability, skill_tutorial)},
                "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"applicable": True, "profile": "canonical", "ok": not findings, "findings": findings,
            "identity_digest": digest, "identity": identity, "inventory": inventory,
            "checks_executed": True, "reuse_scope": "validated unchanged success lineage; no native suite evidence",
            "reused": bool(not findings and previous and previous.get("ok") is True and previous.get("identity_digest") == digest)}

try:
    import yaml
except ImportError:  # pragma: no cover
    print("Error: PyYAML required.", file=sys.stderr)
    sys.exit(2)

try:
    from spec_frontmatter import FrontmatterError, parse_spec_file
except ImportError:  # pragma: no cover
    FrontmatterError = ValueError  # type: ignore[assignment]
    parse_spec_file = None  # type: ignore[assignment]

try:
    import validate_install
except ImportError:  # pragma: no cover
    validate_install = None  # type: ignore[assignment]

try:
    import managed_payload_provenance
except ImportError:  # pragma: no cover
    managed_payload_provenance = None  # type: ignore[assignment]

try:
    import worktree_paths
except ImportError:  # pragma: no cover
    worktree_paths = None  # type: ignore[assignment]

try:
    import lifecycle
    import validate_specs
except ImportError:  # pragma: no cover
    lifecycle = None  # type: ignore[assignment]
    validate_specs = None  # type: ignore[assignment]


RUNNABLE_STATUSES = frozenset({"ready", "in_progress", "active"})
BLOCKING_COMMANDS = frozenset({"build", "test"})
COMMAND_KEYS = ("build", "test", "lint", "type_check", "format")


def _git_path(repo: Path, name: str) -> Path | None:
    """Resolve a git path, respecting core.hooksPath when configured."""
    code, output = _run(f"git rev-parse --git-path {name}", repo)
    if code != 0 or not output.strip():
        return None
    path = Path(output.strip())
    return path if path.is_absolute() else repo / path


def _scope_applies(repo: Path, registry_path: Path) -> bool:
    """Return whether this checkout is explicitly registered as protected.

    A guard is deliberately optional in ordinary clones and linked run worktrees.
    The protected-worktrees registry is the existing explicit opt-in for the Argo
    Home primary checkout, so a missing hook is actionable only there.
    """
    if not registry_path.is_file():
        return False
    checkout = str(repo.resolve()).rstrip("/")
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if candidate and not candidate.startswith("#") and candidate.rstrip("/") == checkout:
            return True
    return False


def check_guard_liveness(repo: Path, registry_path: Path) -> list[str]:
    """Return actionable warnings for unwired guards, without changing git state.

    Guard definitions live entirely in ``hooks/guard-registry.yaml``.  The checker
    only understands the generic fields shared by every entry, so another guard is
    registered by data alone.  Registries are opt-in per protected checkout: no
    registry entry for a checkout means silence, not an attempted installation.
    """
    if not registry_path.is_file():
        return []
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [f"Git guard liveness registry is unreadable ({registry_path}): {exc}"]
    guards = raw.get("guards", []) if isinstance(raw, dict) else []
    if not isinstance(guards, list):
        return [f"Git guard liveness registry has invalid guards data: {registry_path}"]

    hooks_dir = _git_path(repo, "hooks")
    if hooks_dir is None:
        return []
    warnings: list[str] = []
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        # Activated guards are checked by their configuration-aware health
        # probe below. They must not warn in projects that did not opt in.
        if guard.get("activation") == "terminal_outcomes":
            continue
        name = str(guard.get("name", "unnamed guard"))
        scope = guard.get("scope_registry")
        if isinstance(scope, str) and scope and not _scope_applies(repo, repo / scope):
            continue
        hook_name = guard.get("hook")
        marker = guard.get("marker")
        installer = str(guard.get("installer", "the documented guard installer"))
        if not isinstance(hook_name, str) or not isinstance(marker, str):
            warnings.append(f"Git guard registry entry {name!r} is invalid; inspect {registry_path}.")
            continue
        stub = hooks_dir / hook_name
        remedy = f"Reinstall with: sh {installer}"
        if not stub.is_file():
            warnings.append(f"Git guard {name!r}: hook stub absent at {stub}. {remedy}")
            continue
        if not stub.stat().st_mode & 0o111:
            warnings.append(f"Git guard {name!r}: hook stub is not executable at {stub}. {remedy}")
            continue
        if marker not in stub.read_text(encoding="utf-8", errors="replace"):
            warnings.append(f"Git guard {name!r}: hook stub at {stub} does not wire marker {marker!r}. {remedy}")
            continue

        candidates = guard.get("target_candidates", [])
        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            warnings.append(f"Git guard registry entry {name!r} has invalid target_candidates. {remedy}")
            continue
        targets = [repo / item for item in candidates]
        existing = [target for target in targets if target.is_file()]
        mode = guard.get("target_mode", "executable")
        if not existing:
            warnings.append(f"Git guard {name!r}: target script missing ({', '.join(map(str, targets))}). {remedy}")
        elif mode == "executable" and not any(target.stat().st_mode & 0o111 for target in existing):
            warnings.append(f"Git guard {name!r}: target script is not executable ({', '.join(map(str, existing))}). {remedy}")
    return warnings


def check_terminal_outcome_guard(repo: Path, config_path: Path) -> list[str]:
    """Report a configured-but-unwired SPEC-224 boundary as installation health."""
    commands = load_commands(config_path)  # validates the shared YAML stream shape first
    del commands
    try:
        config_documents = list(yaml.safe_load_all(config_path.read_text(encoding="utf-8"))) if config_path.is_file() else []
    except yaml.YAMLError:
        return ["Terminal outcome record guard: configuration is unreadable."]
    config: dict[str, Any] = {}
    for document in config_documents:
        if isinstance(document, dict):
            config.update(document)
    outcome_config = config.get("terminal_outcomes", {})
    if not isinstance(outcome_config, dict) or not outcome_config.get("enabled", False):
        return []
    hooks_dir = _git_path(repo, "hooks")
    if hooks_dir is None:
        return ["Terminal outcome record guard: Git hooks path is unavailable."]
    hook = hooks_dir / "commit-msg"
    if not hook.is_file() or "# SPEC-224 terminal-outcome-record" not in hook.read_text(encoding="utf-8", errors="replace"):
        return ["Terminal outcome record guard: configured enforcement is not wired into commit-msg; reinstall the canonical hook."]
    if not (repo / ".nightshift" / "terminal_outcomes.py").is_file():
        return ["Terminal outcome record guard: configured enforcement helper is missing; reinstall the canonical payload."]
    return []


def load_commands(config_path: Path) -> dict[str, Any]:
    """Extract the commands block from a possibly multi-document config.yaml."""
    cfg: dict[str, Any] = {}
    if not config_path.is_file():
        return {}
    try:
        for doc in yaml.safe_load_all(config_path.read_text(encoding="utf-8")):
            if isinstance(doc, dict):
                cfg.update(doc)
    except yaml.YAMLError:
        return {}
    commands = cfg.get("commands", {})
    return commands if isinstance(commands, dict) else {}


def _run(cmd: str, cwd: Path, timeout: int | None = None) -> tuple[int, str]:
    """Run a shell command and return (exit_code, combined_output)."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout if timeout and timeout > 0 else None,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except OSError as exc:
        return 127, str(exc)


def _repository_head(repo: Path) -> str | None:
    """Return the exact commit checked out at *repo*, or None when unavailable."""
    code, output = _run("git rev-parse --verify HEAD^{commit}", repo)
    head = output.strip()
    return head if code == 0 and _GIT_OBJECT_ID_RE.fullmatch(head) else None


_GIT_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40,64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_SPEC_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_INVOCATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_ADMISSION_VALUES = frozenset({"allow", "deny", "indeterminate"})
PROJECTION_SCHEMA_VERSION = "1.0.0"


def _pattern_or_none(value: Any, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _count_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def sanitized_preflight_projection(result: Any, *, result_sha256: str) -> dict[str, Any]:
    """Project a retained preflight result onto an allowlist of parsed fields (SPEC-390-002 R1).

    The retained result holds local paths, command lines and test output, so it
    never crosses a verifier boundary. This projection is built field by field:
    every value is re-validated against a closed shape (a digest, an enum, a
    boolean, a count, an identifier) and replaced by ``None`` when it is not one.
    A field therefore cannot smuggle free text or a host path through, and a
    value the result did not carry is reported as unset rather than invented.

    ``result_sha256`` is the digest of the retained bytes the caller parsed.
    ``repository_head`` is the raw commit the run executed against; it is for the
    parent to turn into a protocol digest and must not reach a verifier as-is.
    """
    if not isinstance(result, dict):
        raise ValueError("preflight result is not a mapping")
    if not isinstance(result_sha256, str) or not _SHA256_RE.fullmatch(result_sha256):
        raise ValueError("result digest must be a lowercase SHA-256")
    checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
    admission = checks.get("install_admission")
    admission = admission if isinstance(admission, dict) else {}
    git = checks.get("git") if isinstance(checks.get("git"), dict) else {}
    commands = checks.get("commands") if isinstance(checks.get("commands"), dict) else {}
    test = commands.get("test") if isinstance(commands.get("test"), dict) else {}
    coverage = admission.get("coverage")
    coverage_projection = (
        {
            key: _count_or_none(coverage.get(key))
            for key in ("applicable", "checked", "passed", "failed")
        }
        if isinstance(coverage, dict)
        else None
    )
    failures = result.get("blocking_failures")
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "result_sha256": result_sha256,
        "spec_id": _pattern_or_none(result.get("spec_id"), _SPEC_ID_RE),
        "timestamp": _pattern_or_none(result.get("timestamp"), _TIMESTAMP_RE),
        "ok": _bool_or_none(result.get("ok")),
        "blocking_failure_count": len(failures) if isinstance(failures, list) else None,
        "git_clean": _bool_or_none(git.get("clean")),
        "install_admission": {
            "ok": _bool_or_none(admission.get("ok")),
            "admission": admission.get("admission")
            if admission.get("admission") in _ADMISSION_VALUES else None,
            "invocation_id": _pattern_or_none(
                admission.get("integrity_run_id"), _INVOCATION_ID_RE
            ),
            "artifact_sha256": _pattern_or_none(admission.get("artifact_sha256"), _SHA256_RE),
            "integrity_receipt_sha256": _pattern_or_none(
                admission.get("integrity_receipt_sha256"), _SHA256_RE
            ),
            "coverage": coverage_projection,
        },
        "declared_test": {
            "configured": bool(test) and test.get("cmd") is not None and test.get("skipped") is False,
            "exit": _count_or_none(test.get("exit")),
            "skipped": _bool_or_none(test.get("skipped")),
        },
        "repository_head": _pattern_or_none(result.get("repository_head"), _GIT_OBJECT_ID_RE),
    }


def _git_status(repo: Path) -> dict[str, Any]:
    code, out = _run("git status --porcelain --untracked-files=all", repo)
    paths = [line for line in out.splitlines() if line.strip()]
    return {
        "clean": code == 0 and not paths,
        "exit": code,
        "dirty_paths": paths,
    }


def _load_specs(specs_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    specs: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if parse_spec_file is None:
        return specs, ["spec_frontmatter.py is unavailable"]
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue  # Same corpus boundary as validate_specs; templates are not specs.
        try:
            parsed = parse_spec_file(path)
        except FrontmatterError as exc:
            errors.append(f"{path}: {exc}")
            continue
        spec_id = parsed.frontmatter.get("id")
        if isinstance(spec_id, str) and spec_id:
            specs[spec_id] = {"path": path, "frontmatter": parsed.frontmatter}
    return specs, errors


def _dependency_state(spec: dict[str, Any], specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    after = spec.get("after", [])
    if after is None:
        after = []
    if not isinstance(after, list):
        after = [after]

    required = []
    unresolved = []
    for dep_id in [str(item) for item in after]:
        dep = specs.get(dep_id)
        status = dep["frontmatter"].get("status") if dep else None
        ok = status == "done"
        item = {
            "id": dep_id,
            "status": status,
            "path": str(dep["path"]) if dep else None,
            "ok": ok,
        }
        required.append(item)
        if not ok:
            unresolved.append(item)
    return {"ok": not unresolved, "required": required, "unresolved": unresolved}


def _command_state(commands: dict[str, Any], repo: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    timeout = commands.get("test_timeout_s", 300)
    for key in COMMAND_KEYS:
        cmd = str(commands.get(key, "") or "").strip()
        blocking = key in BLOCKING_COMMANDS
        if not cmd:
            results[key] = {
                "cmd": None,
                "exit": None,
                "skipped": True,
                "blocking": blocking,
            }
            continue
        code, output = _run(cmd, repo, timeout if key == "test" else None)
        results[key] = {
            "cmd": cmd,
            "exit": code,
            "skipped": False,
            "blocking": blocking,
            "output_tail": output[-4000:],
        }
    return results


class KitRootError(RuntimeError):
    """Raised when no supported Nightshift kit-root layout resolves (R3)."""


def resolve_kit_root(repo: Path, *, own_dir: Path | None = None) -> Path:
    """Resolve this repository's Nightshift kit root layout (R1-R3).

    Prefers the canonical in-repo kit root (``own_dir`` — this script's own
    directory when it is literally named ``canonical`` and shaped like a kit)
    and falls back to an ordinary installed project's ``.nightshift/``
    directory. Fails closed — raises ``KitRootError`` — when neither layout
    resolves, when both resolve to distinct locations (ambiguous), or when a
    candidate belongs to a different Git project than ``repo``.

    Reuses ``worktree_paths.git_common_dir``, the existing Git-project
    ownership helper, rather than adding an independent path heuristic.
    """
    repo = repo.resolve()
    own = (own_dir if own_dir is not None else Path(__file__).resolve().parent).resolve()
    if worktree_paths is None:
        raise KitRootError("worktree_paths.py is unavailable; kit-root ownership cannot be verified")
    try:
        repo_common = worktree_paths.git_common_dir(repo)
    except worktree_paths.WorktreePathError as exc:
        raise KitRootError(f"repo is not a Git repository: {exc}") from exc

    def _shaped(path: Path) -> bool:
        return path.is_dir() and (path / "config.yaml").is_file()

    def _owned(path: Path) -> bool:
        try:
            return worktree_paths.git_common_dir(path) == repo_common
        except worktree_paths.WorktreePathError:
            return False

    layouts: dict[str, Path | None] = {
        "installed": repo / ".nightshift",
        "canonical": own if own.name == "canonical" else None,
    }
    valid: dict[str, Path] = {}
    foreign: dict[str, Path] = {}
    for name, candidate in layouts.items():
        if candidate is None or not _shaped(candidate):
            continue
        if _owned(candidate):
            valid[name] = candidate
        else:
            foreign[name] = candidate

    resolved = {path.resolve() for path in valid.values()}
    if len(resolved) > 1:
        detail = ", ".join(f"{name}={path}" for name, path in sorted(valid.items()))
        raise KitRootError(f"ambiguous Nightshift kit root for {repo}: {detail}")
    if resolved:
        return resolved.pop()
    if foreign:
        detail = ", ".join(f"{name}={path}" for name, path in sorted(foreign.items()))
        raise KitRootError(
            f"Nightshift kit root candidate(s) belong to a different Git project than {repo}: {detail}"
        )
    raise KitRootError(
        f"no supported Nightshift kit root found for {repo} "
        "(expected .nightshift/ or a canonical/ kit directory)"
    )


def _kit_root_denial_result(spec_id: str, repo: Path, reason: str) -> dict[str, Any]:
    """Blocking denial result when no Nightshift kit root resolves (R3/AC3).

    Matches the shape of other preflight results: no successful admission is
    ever minted, and the failure carries a controlled, deterministic reason.
    """
    return {
        "schema_version": 1,
        "spec_id": spec_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(repo),
        "checks": {
            "kit_root": {"resolved": False, "reason": reason},
            "install_admission": {"ok": False, "reason": reason, "admission": "deny"},
        },
        "blocking_failures": [reason],
        "warnings": [],
        "ok": False,
    }


def run_install_admission(
    spec_id: str | None,
    *,
    install_root: Path | None = None,
    invocation_kind: str = "preflight",
    run_id: str | None = None,
) -> dict[str, Any]:
    """SPEC-229 admission gate: the first executable action of every preflight run.

    Runs installation/integration validation before any Git status read, spec
    load, or configured command. There is no manual fallback: a missing or
    unexecutable validator, or a non-allow result, is itself a blocking
    preflight failure — it does not fall through to the checks below.
    """
    install_root = (install_root or Path(__file__).resolve().parent).resolve()
    profile = "canonical" if install_root.name == "canonical" else "installed"
    validator_path = install_root / "validate_install.py"
    if validate_install is None or not validator_path.is_file():
        return {
            "ok": False,
            "reason": "validate_install.py is unavailable; installation admission cannot run.",
            "admission": "indeterminate",
        }
    try:
        ctx, _findings, _config, config_sha = validate_install.run_validation(
            install_root, profile, invocation_kind, spec_id
        )
        artifact = validate_install.build_artifact(ctx, config_sha)
        invocation_id = str(artifact["invocation_id"])
        dest, digest, art_inv = validate_install._atomic_write_artifact(ctx.install, artifact)
        ctx.add(art_inv)
        artifact = validate_install.build_artifact(ctx, config_sha, invocation_id=invocation_id)
        admission = artifact["admission"] if dest is not None else "indeterminate"
    except Exception as exc:  # noqa: BLE001 - any internal failure denies, never crashes preflight
        return {
            "ok": False,
            "reason": f"validate_install.py raised {exc.__class__.__name__}; treated as indeterminate.",
            "admission": "indeterminate",
        }
    receipt_path = None
    receipt_sha256 = None
    if admission == "allow":
        if managed_payload_provenance is None or dest is None or digest is None:
            return {
                "ok": False,
                "reason": "Managed-payload integrity receipt could not be created; treated as indeterminate.",
                "admission": "indeterminate",
            }
        try:
            receipt_path, receipt_sha256 = managed_payload_provenance.write_integrity_receipt(
                ctx.install,
                spec_id=spec_id or "unselected",
                invocation_id=invocation_id,
                run_id=run_id,
                admitted_artifact_sha256=digest,
            )
        except Exception as exc:  # noqa: BLE001 - receipt failure denies admission
            return {
                "ok": False,
                "reason": f"Managed-payload integrity receipt failed ({exc.__class__.__name__}); treated as indeterminate.",
                "admission": "indeterminate",
            }
    return {
        "ok": admission == "allow",
        "reason": None if admission == "allow" else f"Installation admission gate result: {admission}.",
        "admission": admission,
        "artifact_path": str(dest.relative_to(install_root)) if dest else None,
        "artifact_sha256": digest,
        "integrity_receipt_path": receipt_path,
        "integrity_receipt_sha256": receipt_sha256,
        "integrity_run_id": run_id or invocation_id,
        "coverage": artifact.get("coverage"),
    }


def run_preflight(spec_id: str, repo: Path, specs_dir: Path, config_path: Path) -> dict[str, Any]:
    """Return the preflight result mapping. Writing the artifact is handled by main."""
    repo = repo.resolve()
    specs_dir = specs_dir if specs_dir.is_absolute() else repo / specs_dir
    config_path = config_path if config_path.is_absolute() else repo / config_path

    result: dict[str, Any] = {
        "schema_version": 1,
        "spec_id": spec_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(repo),
        # SPEC-390-002: the commit this run executed against, so a retained
        # result can be bound to an exact candidate instead of an author's claim.
        "repository_head": _repository_head(repo),
        "checks": {},
        "blocking_failures": [],
        "warnings": [],
    }

    install_admission = run_install_admission(spec_id, install_root=config_path.parent)
    result["checks"]["install_admission"] = install_admission
    if not install_admission["ok"]:
        result["blocking_failures"].append(
            install_admission["reason"] or "Installation admission gate denied this start."
        )
        # No manual fallback (R5): installation admission failure stops the
        # path here. Spec/dependency/baseline checks below never run, and no
        # project command is executed.
        result["ok"] = False
        return result

    git = _git_status(repo)
    result["checks"]["git"] = git
    if not git["clean"]:
        result["blocking_failures"].append("Git working tree is dirty; commit, stash, or move unrelated changes first.")

    guard_registry = Path(__file__).with_name("hooks") / "guard-registry.yaml"
    guard_warnings = check_guard_liveness(repo, guard_registry)
    terminal_guard_failures = check_terminal_outcome_guard(repo, config_path)
    guard_warnings.extend(terminal_guard_failures)
    result["checks"]["git_guards"] = {"registry": str(guard_registry), "warnings": guard_warnings}
    result["warnings"].extend(guard_warnings)
    result["blocking_failures"].extend(terminal_guard_failures)

    specs, spec_errors = _load_specs(specs_dir)
    if spec_errors:
        result["warnings"].extend(spec_errors)

    entry = specs.get(spec_id)
    if not entry:
        result["checks"]["spec"] = {"found": False, "runnable": False}
        result["checks"]["dependencies"] = {"ok": False, "required": [], "unresolved": []}
        result["blocking_failures"].append(f"Spec {spec_id} was not found in {specs_dir}.")
    else:
        frontmatter = entry["frontmatter"]
        status = frontmatter.get("status")
        runnable = status in RUNNABLE_STATUSES
        result["checks"]["spec"] = {
            "found": True,
            "path": str(entry["path"]),
            "status": status,
            "runnable": runnable,
        }
        if not runnable:
            allowed = ", ".join(sorted(RUNNABLE_STATUSES))
            result["blocking_failures"].append(
                f"Spec {spec_id} has status {status!r}; expected one of: {allowed}."
            )

        deps = _dependency_state(frontmatter, specs)
        result["checks"]["dependencies"] = deps
        if not deps["ok"]:
            unresolved = ", ".join(
                f"{item['id']} ({item['status'] or 'missing'})" for item in deps["unresolved"]
            )
            result["blocking_failures"].append(f"Unresolved after: dependencies: {unresolved}.")

        # SPEC-419: the sequential run route applies the same project spec_metadata policy
        # (version first) as promotion and parallel dispatch; an invalid policy refuses too.
        if status in {"planned", "ready", "in_progress"}:
            try:
                from spec_frontmatter import load_spec_metadata_policy, spec_metadata_problems
                metadata_problems = spec_metadata_problems(frontmatter, load_spec_metadata_policy(config_path))
            except ImportError:  # pragma: no cover - a kit without the shared policy reader
                metadata_problems = ["spec_metadata_validation_unavailable: sync the managed spec_frontmatter.py"]
            result["checks"]["spec_metadata"] = {"ok": not metadata_problems, "problems": metadata_problems}
            result["blocking_failures"].extend(metadata_problems)

        # SPEC-358 R6: route planned/ready/in_progress preflight through the
        # same '## State rationale' static rules as the CLI validator and the
        # pre-commit hook, instead of a second independent check. An unavailable
        # validator refuses admission with a repair instruction.
        if validate_specs is not None:
            try:
                spec_path = Path(entry["path"])
                body = spec_path.read_text(encoding="utf-8").split("\n---\n", 1)[-1]
                state_findings = validate_specs.validate_state_rationale_admission(
                    frontmatter, body, spec_path,
                )
            except Exception as exc:
                state_findings = [f"state_rationale_validation_unavailable: {exc}; repair the managed validator"]
            fatal = [f for f in state_findings if not f.startswith("WARNING: ")]
            result["checks"]["state_rationale"] = {"findings": state_findings}
            if fatal:
                result["blocking_failures"].extend(fatal)
            result["warnings"].extend(f for f in state_findings if f.startswith("WARNING: "))
        else:
            result["blocking_failures"].append("state_rationale_validation_unavailable: sync the managed validator")

    commands = load_commands(config_path)
    # SPEC-NS-KIT-162: canonical packaging is checked before any configured
    # command. Installed copies have their separate admission contract.
    if config_path.parent.resolve() == repo / "canonical":
        try:
            import release
            final_manifest = release.check_final_manifest(config_path.parent)
        except (ImportError, OSError, ValueError) as exc:
            final_manifest = {"ok": False, "errors": [f"final manifest check unavailable: {exc}"],
                              "affected_paths": []}
        result["checks"]["final_manifest"] = final_manifest
        if not final_manifest["ok"]:
            result["blocking_failures"].extend(final_manifest["errors"])
            result["ok"] = False
            return result

    command_results = _command_state(commands, repo)
    result["checks"]["commands"] = command_results
    if command_results["test"]["skipped"]:
        declared = commands.get("test_not_applicable")
        reason = declared.strip() if isinstance(declared, str) else ""
        if reason:
            result["warnings"].append(
                f"commands.test_not_applicable declared: {reason}; no test command run."
            )
        else:
            result["blocking_failures"].append("commands.test is not configured; baseline test gate cannot run.")
    for key, item in command_results.items():
        if item["skipped"]:
            if not item["blocking"]:
                result["warnings"].append(f"commands.{key} is not configured; skipped.")
            continue
        if item["exit"] != 0:
            message = f"commands.{key} exited {item['exit']}."
            if item["blocking"]:
                result["blocking_failures"].append(message)
            else:
                result["warnings"].append(message)

    result["ok"] = not result["blocking_failures"]
    return result


PREFLIGHT_DIGEST_DIR = Path("_wip") / "preflight-digests"


def write_preflight_digest_record(
    metrics_dir: Path, spec_id: str, repository_head: str | None, body: bytes,
) -> Path | None:
    """Record the retained result's SHA-256 out of band (SPEC-390-002-002 R1).

    The record lives under ``<metrics_dir>/_wip/`` (untracked, parent-private),
    never in the spec, a report or any committed file, so the digest stays an
    out-of-band reference. Nothing is written when the head is unknown.
    """
    if not repository_head:
        return None
    record_dir = metrics_dir / PREFLIGHT_DIGEST_DIR
    record_dir.mkdir(parents=True, exist_ok=True)
    record = record_dir / f"{spec_id}.json"
    record.write_text(
        json.dumps(
            {
                "spec_id": spec_id,
                "repository_head": repository_head,
                "result_sha256": hashlib.sha256(body).hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Nightshift Step 1 preflight checks.")
    parser.add_argument("--spec-id", required=True)
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--specs-dir", default=None, type=Path)
    parser.add_argument("--config", default=None, type=Path)
    parser.add_argument("--metrics-dir", default=None, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()

    # R1/R2: resolve the supported kit-root layout (canonical/ or .nightshift/)
    # only for whichever paths the caller did not explicitly override. An
    # explicit --specs-dir/--config/--metrics-dir always wins, unchanged from
    # prior behavior.
    kit_root: Path | None = None
    kit_root_error: str | None = None
    if args.specs_dir is None or args.config is None or args.metrics_dir is None:
        try:
            kit_root = resolve_kit_root(repo)
        except KitRootError as exc:
            kit_root_error = str(exc)

    if kit_root_error is not None:
        # R3: fail closed, no manual fallback — mints no admission result.
        result = _kit_root_denial_result(args.spec_id, repo, kit_root_error)
    else:
        specs_dir = args.specs_dir if args.specs_dir is not None else kit_root / "specs"
        config_path = args.config if args.config is not None else kit_root / "config.yaml"
        result = run_preflight(args.spec_id, repo, specs_dir, config_path)

    if args.dry_run:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    if args.metrics_dir is not None:
        metrics_dir = args.metrics_dir if args.metrics_dir.is_absolute() else repo / args.metrics_dir
    elif kit_root is not None:
        metrics_dir = kit_root / "metrics"
    else:
        metrics_dir = repo / ".nightshift" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    out = metrics_dir / f"{args.spec_id}.preflight.json"
    result["artifact_path"] = str(out)
    body = (json.dumps(result, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    out.write_bytes(body)
    write_preflight_digest_record(metrics_dir, args.spec_id, result.get("repository_head"), body)

    if result["ok"]:
        print(f"Wrote {out} (preflight ok)")
    else:
        print(f"Wrote {out} (preflight failed)", file=sys.stderr)
        for failure in result["blocking_failures"]:
            print(f"- {failure}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())


_SUITE_ENVIRONMENT_PROBE = r'''
import importlib, importlib.metadata, json, os, pathlib, tempfile, sys, hashlib
request = json.loads(sys.stdin.read())
failures, modules = [], {}
for name in request['imports']:
    try:
        module = importlib.import_module(name)
        origin = getattr(module, '__file__', None)
        try:
            version = importlib.metadata.version({'yaml': 'PyYAML', 'xdist': 'pytest-xdist'}.get(name, name))
        except importlib.metadata.PackageNotFoundError:
            version = getattr(module, '__version__', None)
        modules[name] = {'origin': origin, 'version': version,
                         'sha256': hashlib.sha256(pathlib.Path(origin).read_bytes()).hexdigest() if origin and pathlib.Path(origin).is_file() else None}
    except Exception:
        failures.append('dependency_import:' + name)
for raw in request['caches']:
    path = pathlib.Path(raw)
    try:
        if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise OSError()
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError:
        failures.append('cache_access')
try:
    with tempfile.TemporaryFile(dir=request['output']) as probe:
        probe.write(b'setup-capability'); probe.flush(); os.fsync(probe.fileno())
except OSError:
    failures.append('output_access')
print(json.dumps({'failures': failures, 'modules': modules, 'executable': sys.executable,
                  'prefix': sys.prefix, 'version': sys.version}))
sys.exit(1 if failures else 0)
'''


_SUITE_NATIVE_ENVIRONMENT_PROBE = r'''
output=$1
probe=$2
shift 2
failures=''
for cache do
    if ! test -d "$cache" || ! test -r "$cache" || ! test -w "$cache" || ! test -x "$cache"; then
        failures='"cache_access",'
    fi
done
if ! (umask 077; set -C; printf setup-capability > "$output/$probe") 2>/dev/null; then
    failures="$failures\"output_access\","
elif ! /bin/rm -- "$output/$probe"; then
    failures="$failures\"output_access\","
fi
case "$failures" in
    '') printf '{"failures":[],"runtime_kind":"native"}\n' ;;
    *) printf '{"failures":[%s],"runtime_kind":"native"}\n' "${failures%,}"; exit 1 ;;
esac
'''


def _suite_executable(value: str, root: Path, env: dict[str, str]) -> str | None:
    """Resolve with the same cwd/PATH semantics as the eventual suite launch."""
    import os
    import shutil
    if '/' in value:
        candidate = Path(os.path.abspath(root / value))
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    search = os.pathsep.join(str(root / item) if not Path(item).is_absolute() else item
                             for item in env.get('PATH', os.defpath).split(os.pathsep))
    return shutil.which(value, path=search)


def _suite_native_runtime(executable: str, selected: list[str], root: Path, env: dict[str, str]):
    """Inspect identities only; never execute a declared suite or script."""
    import os
    import shlex
    import stat
    scripts, interpreters, failures = [], [], []

    def bind_script(path):
        candidate = Path(os.path.abspath(root / path))
        try:
            if not candidate.is_file() or not os.access(candidate, os.R_OK):
                raise OSError()
            content = candidate.read_bytes()
            scripts.append({'path_sha256': hashlib.sha256(str(candidate).encode()).hexdigest(),
                            'sha256': hashlib.sha256(content).hexdigest(),
                            'mode': stat.S_IMODE(candidate.stat().st_mode)})
            return content
        except OSError:
            failures.append('script_unavailable')
            return b''

    runtime = executable
    try:
        with Path(executable).open('rb') as handle:
            header = handle.read(4096)
    except OSError:
        return None, 'native', scripts, interpreters, ['runtime_unavailable']
    if header.startswith(b'#!'):
        bind_script(executable)
        try:
            # Kernels do not apply shell quoting to the interpreter or split its one argument.
            words = header.split(b'\n', 1)[0][2:].decode().strip().split(None, 1)
        except UnicodeError:
            words = []
        interpreter = _suite_executable(words[0], root, env) if words else None
        if interpreter and Path(words[0]).name == 'env':
            interpreters.append({'path_sha256': hashlib.sha256(interpreter.encode()).hexdigest(),
                                 'sha256': hashlib.sha256(Path(interpreter).read_bytes()).hexdigest()})
            argument = words[1] if len(words) == 2 else ''
            try:
                words = shlex.split(argument[2:].lstrip()) if argument.startswith('-S') else [argument] if argument else []
            except ValueError:
                words = []
            interpreter = _suite_executable(words[0], root, env) if words and not words[0].startswith('-') else None
        runtime = interpreter
        if runtime is None:
            failures.append('runtime_unavailable')
    elif not header.startswith((b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe',
                                b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce',
                                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca')):
        failures.append('runtime_unresolved')
        runtime = None
    if Path(selected[0]).name in ('sh', 'bash'):
        operands = selected[1:]
        while operands and operands[0].startswith('-'):
            flag = operands.pop(0)
            if flag == '--': break
            if flag not in ('--noprofile', '--norc') and not (flag.startswith('-') and
                    len(flag) > 1 and set(flag[1:]) <= set('euxvfn')):
                failures.append('runtime_unresolved')
                break
        if operands and not failures:
            bind_script(operands[0])
    kind = 'python' if runtime and Path(runtime).name.startswith('python') else 'native'
    return runtime, kind, scripts, interpreters, failures


def suite_environment_public(result: dict) -> dict:
    """Only reason codes and digests cross the verifier boundary; native records stay private."""
    return {key: result[key] for key in ('schema_version', 'status', 'launch_allowed', 'is_suite_sample',
                                         'reason_codes', 'binding_sha256', 'proof_sha256', 'reused_refusal')}


def suite_environment_preflight(command: list[str], *, arm_root: Path, arm_revision: str,
                                config_identity: str, output_root: Path, timeout_s: float,
                                environment: dict[str, str] | None = None,
                                required_imports: list[str] | None = None,
                                cache_paths: list[Path] | None = None, previous: dict | None = None) -> dict:
    """Bounded setup only, under the actual launch identity; never run the suite or uv sync."""
    import os
    import shutil
    import shlex
    import stat
    import math
    env = dict(os.environ if environment is None else environment)
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError('setup requires an exact non-empty argv')
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError('setup uses the existing positive configured helper timeout')
    arm_root, output_root = Path(arm_root).resolve(), Path(output_root).resolve()
    selected = list(command)
    launcher = _suite_executable(selected[0], arm_root, env)
    reasons = []
    if os.name != 'posix':
        reasons.append('platform_capability_unavailable')
    if not isinstance(arm_revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', arm_revision):
        reasons.append('arm_revision_unavailable')
    if launcher is None:
        reasons.append('executable_unavailable')
    # A simple shell wrapper preserves its actual child argv; shell expressions are unavailable.
    if Path(selected[0]).name in ('sh', 'bash') and len(selected) == 3 and selected[1] == '-c':
        expression = selected[2]
        try:
            lexer = shlex.shlex(expression, posix=True, punctuation_chars=';&|<>()')
            lexer.whitespace_split = True
            lexer.commenters = ''
            tokens = list(lexer)
            selected = shlex.split(expression)
        except ValueError:
            selected, tokens = [], []
        if (not selected or any(token and set(token) <= set(';&|<>()') for token in tokens)
                or any(character in expression for character in ('$','`','\n'))):
            selected = []
            reasons.append('runtime_unresolved')
    executable = _suite_executable(selected[0], arm_root, env) if selected else None
    if selected and executable is None:
        reasons.append('executable_unavailable')
    caches = [Path(path).resolve() for path in (cache_paths or [])]
    runtime = executable
    runtime_kind, scripts, interpreters = 'python', [], []
    imports = list(required_imports or [])
    if selected and Path(selected[0]).name == 'uv':
        # --with can build an ephemeral environment. A read-only setup check must not invoke it.
        if env.get('UV_CACHE_DIR'):
            caches.append(Path(env['UV_CACHE_DIR']).resolve())
        uv_flags = selected[2:]
        supported_flags = {'--active', '--no-sync', '--offline', '--no-project'}
        unknown_flags = any(item.startswith('-') and item not in supported_flags for item in uv_flags[:next((i for i,v in enumerate(uv_flags) if not v.startswith('-')), len(uv_flags))])
        if (len(selected) < 2 or selected[1] != 'run' or unknown_flags or '--no-sync' not in selected or '--with' in selected or '--with-requirements' in selected
                or not env.get('VIRTUAL_ENV') or '--active' not in selected):
            reasons.append('uv_runtime_unresolved')
            runtime = None
        else:
            runtime_path = Path(env['VIRTUAL_ENV']) / 'bin/python'
            runtime = str(runtime_path) if runtime_path.is_file() else None
            if not runtime:
                reasons.append('runtime_unavailable')
        imports = imports or ['fastapi', 'httpx', 'playwright', 'pytest', 'uvicorn', 'xdist', 'yaml']
    elif runtime and not Path(runtime).name.startswith('python'):
        try:
            runtime, runtime_kind, scripts, interpreters, runtime_failures = _suite_native_runtime(executable, selected, arm_root, env)
            reasons.extend(runtime_failures)
        except OSError:
            runtime, runtime_kind = None, 'native'
            reasons.append('runtime_unavailable')
    if selected and (Path(selected[0]).name == 'pytest' or any(selected[index:index + 2] == ['-m', 'pytest'] for index in range(len(selected)))):
        imports = sorted(set(imports + ['pytest'] + (['xdist'] if any(item == '-n' or item.startswith('-n') and item[2:] in {'auto', 'logical', '2', '3', '4'} for item in selected) else [])))
    if runtime_kind == 'native':
        imports = []
    if runtime and not os.access(runtime, os.X_OK):
        reasons.append('runtime_unavailable')
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in imports):
        raise ValueError('setup imports must be explicit top-level runtime modules')
    def path_identity(path):
        try:
            info = Path(path).stat()
            return {'path_sha256': hashlib.sha256(str(path).encode()).hexdigest(), 'mode': stat.S_IMODE(info.st_mode),
                    'uid': info.st_uid, 'gid': info.st_gid, 'device': info.st_dev, 'inode': info.st_ino,
                    'read': os.access(path, os.R_OK), 'write': os.access(path, os.W_OK), 'search': os.access(path, os.X_OK)}
        except OSError:
            return {'path_sha256': hashlib.sha256(str(path).encode()).hexdigest(), 'missing': True}
    for cache in caches:
        identity = path_identity(cache)
        if (not cache.is_dir() or not all(identity.get(key) for key in ('read', 'write', 'search'))
                or not identity.get('mode', 0) & 0o444 or not identity.get('mode', 0) & 0o222 or not identity.get('mode', 0) & 0o111):
            reasons.insert(0, 'cache_access')
        if runtime_kind == 'native':
            try:
                with os.scandir(cache) as entries:
                    next(entries, None)
            except OSError:
                reasons.insert(0, 'cache_access')
    if (not output_root.is_dir() or runtime_kind == 'native' and
            (not path_identity(output_root).get('mode', 0) & 0o222 or not os.access(output_root, os.W_OK | os.X_OK))):
        reasons.append('output_access')
    runtime_sha = None
    if runtime:
        try:
            runtime_sha = hashlib.sha256(Path(runtime).read_bytes()).hexdigest()
        except OSError:
            reasons.append('runtime_unavailable')
    relevant = {key: value for key, value in env.items() if key.startswith(('UV_', 'PYTHON', 'PYTEST_')) or key in
                ('PATH', 'VIRTUAL_ENV', 'TMPDIR', 'TEMP', 'TMP', 'HOME', 'LANG', 'LC_ALL')}
    if runtime_kind == 'native':
        relevant = env
    probe = _SUITE_NATIVE_ENVIRONMENT_PROBE if runtime_kind == 'native' else _SUITE_ENVIRONMENT_PROBE
    probe_runtime = runtime
    if runtime_kind == 'native' and (not runtime or Path(runtime).name not in ('sh', 'bash')):
        probe_runtime = _suite_executable('/bin/sh', arm_root, env)
    if runtime_kind == 'native' and not probe_runtime:
        reasons.append('probe_launch_unavailable')
    def identity_sha(path, failure):
        if path is None:
            return None
        try:
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except OSError:
            reasons.append(failure)
            return None
    launcher_sha = identity_sha(launcher, 'runtime_unavailable')
    probe_runtime_sha = identity_sha(probe_runtime, 'probe_launch_unavailable')
    binding = {'arm_revision': arm_revision, 'arm_root_sha256': hashlib.sha256(str(arm_root).encode()).hexdigest(),
               'command_sha256': hashlib.sha256(json.dumps(command).encode()).hexdigest(), 'config_identity': config_identity,
               'environment_sha256': hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest(),
               'runtime_sha256': runtime_sha, 'runtime_path_sha256': hashlib.sha256(str(runtime).encode()).hexdigest(),
               'launcher_sha256': launcher_sha,
               'caches': [path_identity(path) for path in caches], 'output': path_identity(output_root),
               'imports': imports, 'probe_sha256': hashlib.sha256(probe.encode()).hexdigest(), 'timeout_s': timeout_s,
               'runtime_kind': runtime_kind, 'scripts': scripts, 'interpreters': interpreters,
               'probe_runtime_sha256': probe_runtime_sha}
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    if (isinstance(previous, dict) and previous.get('binding_sha256') == key
            and previous.get('launch_allowed') is False and previous.get('status') == 'unavailable'):
        return {**previous, 'reused_refusal': True}
    import time
    import uuid
    started = datetime.now(timezone.utc).isoformat()
    moment = time.monotonic()
    native = {'invocation_identity': uuid.uuid4().hex, 'started_at': started,
              'exit_code': None, 'timed_out': False, 'launched': False}
    observed = {}
    stdout, stderr = '', ''
    if not reasons and runtime:
        try:
            probe_env = {**env, 'PYTHONDONTWRITEBYTECODE': '1'}
            native['launched'] = True
            import signal
            probe_argv = [runtime, '-I', '-B', '-c', probe]
            if runtime_kind == 'native':
                probe_argv = [probe_runtime, '-c', probe, 'nightshift-setup', str(output_root),
                              '.nightshift-setup-' + native['invocation_identity'], *[str(path) for path in caches]]
            process = subprocess.Popen(probe_argv, cwd=arm_root, env=probe_env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            native['process_group_id'] = process.pid
            try:
                stdout, stderr = process.communicate(json.dumps({'imports': imports, 'caches': [str(path) for path in caches],
                                                    'output': str(output_root)}), timeout=timeout_s)
            except subprocess.TimeoutExpired:
                native['timed_out'] = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                reasons.append('probe_timeout')
            native['exit_code'] = process.returncode
            try:
                observed = json.loads(stdout)
                reasons.extend(observed['failures'])
                if selected and Path(selected[0]).name == 'uv' and Path(observed.get('prefix', '')).resolve() != Path(env['VIRTUAL_ENV']).resolve():
                    reasons.append('runtime_binding_mismatch')
            except (ValueError, KeyError, TypeError):
                if not native['timed_out']:
                    reasons.append('probe_result_unavailable')
            if process.returncode and not reasons:
                reasons.append('probe_failed')
        except subprocess.TimeoutExpired as error:
            native['timed_out'] = True
            stdout = error.stdout.decode(errors='replace') if isinstance(error.stdout, bytes) else error.stdout or ''
            stderr = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else error.stderr or ''
            reasons.append('probe_timeout')
        except OSError:
            reasons.append('probe_launch_unavailable')
    elif not reasons:
        reasons.append('runtime_unresolved')
    native.update(ended_at=datetime.now(timezone.utc).isoformat(), duration_s=round(time.monotonic() - moment, 6))
    native.update(stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest(), stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest())
    result = {'schema_version': 1, 'status': 'unavailable' if reasons else 'pass', 'launch_allowed': not reasons,
              'is_suite_sample': False, 'reason_codes': sorted(set(reasons)), 'binding_sha256': key,
              'binding': binding, 'native': native, 'reused_refusal': False,
              'dependency_runtime_sha256': hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest(),
              'native_stdout': stdout, 'native_stderr': stderr}
    result['proof_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result
