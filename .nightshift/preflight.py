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
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def run_install_admission(
    spec_id: str | None,
    *,
    install_root: Path | None = None,
    invocation_kind: str = "preflight",
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
        dest, digest, art_inv = validate_install._atomic_write_artifact(ctx.install, artifact)
        ctx.add(art_inv)
        artifact = validate_install.build_artifact(ctx, config_sha)
        admission = artifact["admission"] if dest is not None else "indeterminate"
    except Exception as exc:  # noqa: BLE001 - any internal failure denies, never crashes preflight
        return {
            "ok": False,
            "reason": f"validate_install.py raised {exc.__class__.__name__}; treated as indeterminate.",
            "admission": "indeterminate",
        }
    return {
        "ok": admission == "allow",
        "reason": None if admission == "allow" else f"Installation admission gate result: {admission}.",
        "admission": admission,
        "artifact_path": str(dest.relative_to(install_root)) if dest else None,
        "artifact_sha256": digest,
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

    commands = load_commands(config_path)
    command_results = _command_state(commands, repo)
    result["checks"]["commands"] = command_results
    if command_results["test"]["skipped"]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Nightshift Step 1 preflight checks.")
    parser.add_argument("--spec-id", required=True)
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--specs-dir", default=".nightshift/specs", type=Path)
    parser.add_argument("--config", default=".nightshift/config.yaml", type=Path)
    parser.add_argument("--metrics-dir", default=".nightshift/metrics", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    result = run_preflight(args.spec_id, args.repo, args.specs_dir, args.config)

    if args.dry_run:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1

    metrics_dir = args.metrics_dir if args.metrics_dir.is_absolute() else args.repo / args.metrics_dir
    metrics_dir.mkdir(parents=True, exist_ok=True)
    out = metrics_dir / f"{args.spec_id}.preflight.json"
    result["artifact_path"] = str(out)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if result["ok"]:
        print(f"Wrote {out} (preflight ok)")
    else:
        print(f"Wrote {out} (preflight failed)", file=sys.stderr)
        for failure in result["blocking_failures"]:
            print(f"- {failure}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
