"""Deterministic, whole-kit release manifests and install verification (SPEC-156)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

MARKER = "release-marker.json"
PYTHON_CACHE_SUFFIXES = frozenset({".pyc", ".pyo"})

CANONICAL_SUITE = {
    "runner": "uv",
    "dependencies": [
        "pytest",
        "pyyaml",
        "fastapi",
        "uvicorn[standard]",
        "httpx",
        "playwright",
    ],
    "probe": [
        "python",
        "-c",
        "import fastapi,httpx,playwright,pytest,uvicorn,yaml",
    ],
    "command": ["python", "-m", "pytest", "-q", "tests"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_ignored_python_cache_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is disposable Python bytecode cache."""
    candidate = PurePosixPath(str(path).replace("\\", "/"))
    return (
        "__pycache__" in candidate.parts
        or candidate.suffix in PYTHON_CACHE_SUFFIXES
    )


def release_entries(manifest: dict) -> list[dict]:
    """Return payload entries after enforcing the no-cache invariant."""
    entries = list(manifest.get("files", []))
    cache = [
        entry.get("path")
        for entry in entries
        if is_ignored_python_cache_path(str(entry.get("path", "")))
    ]
    if cache:
        raise ValueError(
            "release manifest contains ignored Python cache: "
            + ", ".join(sorted(map(str, cache)))
        )
    return entries


def kit_version(canonical: Path) -> str:
    match = re.search(
        r'^kit_version:\s*"([^"]+)"',
        (canonical / "config.yaml").read_text(),
        re.MULTILINE,
    )
    if not match:
        raise ValueError("canonical config.yaml is missing kit_version")
    return match.group(1)


def manifest_files(canonical: Path, names: list[str]) -> list[dict]:
    entries = []
    for name in sorted(names):
        if is_ignored_python_cache_path(name):
            continue
        path = canonical / name
        if not path.is_file():
            raise ValueError(f"managed file missing: {name}")
        entries.append(
            {
                "path": name,
                "sha256": sha256(path),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        )
    return entries


def managed_import_gaps(canonical: Path, names: list[str]) -> list[str]:
    """Report managed Python files whose local imports are absent from the release set.

    Only imports that resolve to a sibling module in ``canonical`` are relevant:
    standard-library and third-party dependencies are supplied by the target project,
    whereas a sibling module must be copied by the kit release itself.  ``ast.walk``
    deliberately visits imports in function bodies as well as module scope.
    """
    managed = set(names)
    gaps: list[str] = []
    for name in sorted(managed):
        if not name.endswith(".py"):
            continue
        source = canonical / name
        try:
            tree = ast.parse(source.read_text(), filename=str(source))
        except SyntaxError as exc:
            gaps.append(f"managed Python file cannot be parsed: {name}: {exc.msg}")
            continue
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                else []
            )
            for module in modules:
                local = Path(*module.split(".")).with_suffix(".py")
                if (canonical / local).is_file() and str(local) not in managed:
                    gaps.append(
                        f"managed import missing from release set: {name} imports {local}"
                    )
    return sorted(set(gaps))


def _module_relative_resources(tree: ast.AST) -> set[PurePosixPath]:
    """Return literal non-Python resources read below a module directory.

    This intentionally implements a small static data-flow model instead of
    guessing from filenames.  It follows the common ``Path(__file__)`` forms,
    local aliases, helper return values, and literal ``/`` joins, then records
    paths passed to ``open``/``read_text``/``read_bytes``.
    """
    module_file = ("file", PurePosixPath("."))
    function_returns: dict[str, set[tuple[str, PurePosixPath]]] = {}

    def resolve(
        expression: ast.AST,
        bindings: dict[str, set[tuple[str, PurePosixPath]]],
    ) -> set[tuple[str, PurePosixPath]]:
        if isinstance(expression, ast.Name):
            return bindings.get(expression.id, set())
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Name)
            and expression.func.id == "Path"
            and len(expression.args) == 1
            and isinstance(expression.args[0], ast.Name)
            and expression.args[0].id == "__file__"
        ):
            return {module_file}
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Name)
            and expression.func.id in function_returns
        ):
            return function_returns[expression.func.id]
        if isinstance(expression, ast.Attribute):
            bases = resolve(expression.value, bindings)
            if expression.attr == "parent":
                return {
                    ("dir", path if kind == "file" else path.parent)
                    for kind, path in bases
                }
            return set()
        if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute):
            bases = resolve(expression.func.value, bindings)
            if expression.func.attr in {"resolve", "absolute"} and not expression.args:
                return bases
            if (
                expression.func.attr == "with_name"
                and len(expression.args) == 1
                and isinstance(expression.args[0], ast.Constant)
                and isinstance(expression.args[0].value, str)
            ):
                return {
                    ("dir", path.parent / expression.args[0].value)
                    for kind, path in bases
                    if kind == "file"
                }
            return set()
        if (
            isinstance(expression, ast.BinOp)
            and isinstance(expression.op, ast.Div)
            and isinstance(expression.right, ast.Constant)
            and isinstance(expression.right.value, str)
        ):
            return {
                ("dir", path / expression.right.value)
                for kind, path in resolve(expression.left, bindings)
                if kind == "dir"
            }
        if isinstance(expression, ast.BoolOp):
            return set().union(*(resolve(value, bindings) for value in expression.values))
        if isinstance(expression, ast.IfExp):
            return resolve(expression.body, bindings) | resolve(expression.orelse, bindings)
        return set()

    resources: set[PurePosixPath] = set()

    def scan(
        statements: list[ast.stmt],
        inherited: dict[str, set[tuple[str, PurePosixPath]]],
    ) -> None:
        bindings = dict(inherited)
        for statement in statements:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                resolved = resolve(value, bindings) if value is not None else set()
                for target in targets:
                    if isinstance(target, ast.Name) and resolved:
                        bindings[target.id] = resolved

            nodes = [
                node
                for node in ast.walk(statement)
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                or node is statement
            ]
            for node in nodes:
                opened: set[tuple[str, PurePosixPath]] = set()
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "open"
                    and node.args
                ):
                    opened = resolve(node.args[0], bindings)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"open", "read_text", "read_bytes"}
                ):
                    opened = resolve(node.func.value, bindings)
                for kind, path in opened:
                    if (
                        kind == "dir"
                        and path.suffix != ".py"
                        and path.name
                        and ".." not in path.parts
                    ):
                        resources.add(path)

            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_bindings = dict(bindings)
                positional = [*statement.args.posonlyargs, *statement.args.args]
                defaults = statement.args.defaults
                for argument, default in zip(positional[-len(defaults) :], defaults):
                    resolved = resolve(default, bindings)
                    if resolved:
                        function_bindings[argument.arg] = resolved
                returned = set().union(
                    *(
                        resolve(node.value, function_bindings)
                        for node in ast.walk(statement)
                        if isinstance(node, ast.Return) and node.value is not None
                    ),
                    set(),
                )
                if returned:
                    function_returns[statement.name] = returned
                scan(statement.body, function_bindings)

    scan(tree.body if isinstance(tree, ast.Module) else [], {})
    return resources


def managed_local_resource_gaps(canonical: Path, names: list[str]) -> list[str]:
    """Report module-relative non-Python reads absent from the managed set."""
    managed = set(names)
    gaps: list[str] = []
    for name in sorted(managed):
        if not name.endswith(".py"):
            continue
        source = canonical / name
        try:
            tree = ast.parse(source.read_text(), filename=str(source))
        except SyntaxError:
            # ``managed_import_gaps`` already reports this parse failure.
            continue
        for resource in sorted(_module_relative_resources(tree)):
            relative = str(resource)
            if relative in {"board-reads.json", "release-manifest.json"}:
                # Runtime board state is project-owned. The manifest cannot
                # contain its own digest recursively. Neither is a data source.
                continue
            if (canonical / resource).is_file() and relative not in managed:
                gaps.append(
                    f"managed local resource missing from release set: "
                    f"{name} opens {relative}"
                )
    return sorted(set(gaps))


def build_manifest(
    canonical: Path,
    names: list[str],
    *,
    smoke_checks: list[str] | None = None,
    retained_manifests: list[dict] | None = None,
    unretained_manifests: list[dict] | None = None,
) -> dict:
    payload = {
        "kit_version": kit_version(canonical),
        "schema_version": "3.0.0",
        "files": manifest_files(canonical, names),
        "smoke_checks": smoke_checks
        or [
            (
                'python3 -c "import ast,pathlib; '
                "[ast.parse(pathlib.Path(p).read_text()) for p in "
                "('board.py','release.py','reflexion_producer.py')]\""
            ),
            "python3 verification_report.py verifier-self-test",
        ],
        # The coordinator materializes this declaration as one `uv run`
        # environment for both the capability probe and suite.  Never replace
        # it with ambient `python3`: launchd and fresh shells may resolve a
        # Python that lacks the board/test dependencies.
        "canonical_suite": CANONICAL_SUITE,
        "migration_checks": ["python3 validate_specs.py specs/"],
    }
    if unretained_manifests is None:
        registry = canonical / "release-manifest-unretained.json"
        unretained_manifests = (
            json.loads(registry.read_text()) if registry.is_file() else []
        )
    return build_manifest_from_payload(
        payload,
        retained_manifests=retained_manifests or [],
        unretained_manifests=unretained_manifests,
    )


def build_manifest_from_payload(
    payload: dict,
    *,
    retained_manifests: list[dict],
    unretained_manifests: list[dict],
) -> dict:
    """Bind historical evidence into a manifest and recompute its fingerprint."""
    current = {
        key: value
        for key, value in payload.items()
        if key not in {"fingerprint", "retained_manifests", "unretained_manifests"}
    }
    current["retained_manifests"] = sorted(
        retained_manifests,
        key=lambda item: (str(item.get("kit_version", "")), str(item.get("fingerprint", ""))),
    )
    current["unretained_manifests"] = sorted(
        unretained_manifests,
        key=lambda item: str(item.get("version", "")),
    )
    normalized = json.dumps(current, sort_keys=True, separators=(",", ":")).encode()
    return {**current, "fingerprint": hashlib.sha256(normalized).hexdigest()}


def resolve_retained_manifest(
    manifest: dict, *, version: str, fingerprint: str
) -> dict | None:
    """Recover the exact current or retained release named by both identifiers."""
    if (
        manifest.get("kit_version") == version
        and manifest.get("fingerprint") == fingerprint
    ):
        return manifest
    for retained in manifest.get("retained_manifests", []):
        if not isinstance(retained, dict):
            continue
        if (
            retained.get("kit_version") == version
            and retained.get("fingerprint") == fingerprint
        ):
            return retained
    return None


def write_manifest(canonical: Path, names: list[str]) -> dict:
    previous: dict | None = None
    path = canonical / "release-manifest.json"
    if path.is_file():
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            previous = loaded
    retained = list(previous.get("retained_manifests", [])) if previous else []
    unretained = (
        list(previous["unretained_manifests"])
        if previous and "unretained_manifests" in previous
        else None
    )
    if previous and previous.get("kit_version") != kit_version(canonical):
        identity = (previous.get("kit_version"), previous.get("fingerprint"))
        if not any(
            (item.get("kit_version"), item.get("fingerprint")) == identity
            for item in retained
            if isinstance(item, dict)
        ):
            retained.append(previous)
    manifest = build_manifest(
        canonical,
        names,
        retained_manifests=retained,
        unretained_manifests=unretained,
    )
    (canonical / "release-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    return manifest


def validate_manifest(
    canonical: Path, names: list[str]
) -> tuple[bool, list[str], dict | None]:
    path = canonical / "release-manifest.json"
    if not path.exists():
        return False, ["release manifest missing"], None
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False, ["release manifest invalid JSON"], None
    expected = build_manifest(
        canonical,
        names,
        smoke_checks=manifest.get("smoke_checks"),
        retained_manifests=manifest.get("retained_manifests", []),
        unretained_manifests=manifest.get("unretained_manifests", []),
    )
    errors = []
    for key in (
        "kit_version",
        "schema_version",
        "files",
        "smoke_checks",
        "canonical_suite",
        "migration_checks",
        "retained_manifests",
        "unretained_manifests",
        "fingerprint",
    ):
        if manifest.get(key) != expected.get(key):
            errors.append(f"manifest {key} does not match canonical")
    changelog = canonical / "CHANGELOG.md"
    headings = (
        re.findall(r"^##\s+(\d+\.\d+\.\d+)\b", changelog.read_text(), re.MULTILINE)
        if changelog.is_file()
        else []
    )
    if not headings or max(
        headings, key=lambda value: tuple(map(int, value.split(".")))
    ) != kit_version(canonical):
        errors.append("manifest version does not match newest changelog release")
    if not manifest.get("smoke_checks") or not all(
        isinstance(command, str) and command.strip()
        for command in manifest["smoke_checks"]
    ):
        errors.append("manifest smoke-check metadata is invalid")
    if any(
        isinstance(entry, dict) and str(entry.get("path", "")).endswith(".nsext")
        for entry in manifest.get("files", [])
    ):
        errors.append("managed release payload cannot contain production .nsext packages")
    errors.extend(managed_import_gaps(canonical, names))
    errors.extend(managed_local_resource_gaps(canonical, names))
    return not errors, errors, manifest


def verify_install(install: Path, manifest: dict) -> tuple[bool, list[str]]:
    errors = []
    try:
        entries = release_entries(manifest)
    except ValueError as exc:
        return False, [str(exc)]
    for entry in entries:
        path = install / entry["path"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            errors.append(f"managed file mismatch: {entry['path']}")
        elif bool(path.stat().st_mode & 0o111) != entry["executable"]:
            errors.append(f"managed mode mismatch: {entry['path']}")
    marker = install / MARKER
    if not marker.exists():
        errors.append("release marker missing")
    else:
        marker_data = json.loads(marker.read_text())
        if (
            marker_data.get("fingerprint") != manifest["fingerprint"]
            or marker_data.get("kit_version") != manifest["kit_version"]
            or marker_data.get("schema_version") != manifest["schema_version"]
            or marker_data.get("release_manifest") != manifest
        ):
            errors.append("release marker is not exact")
    return not errors, errors


def apply_install(
    canonical: Path, install: Path, manifest: dict, *, dry_run: bool = False
) -> tuple[bool, list[str]]:
    """Copy whole managed set, verify it, then write marker last. No partial mode."""
    try:
        entries = release_entries(manifest)
    except ValueError as exc:
        return False, [str(exc)]
    if dry_run:
        return True, [f"would copy {len(entries)} managed files"]
    for entry in entries:
        dst = install / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((canonical / entry["path"]).read_bytes())
        os.chmod(dst, 0o755 if entry["executable"] else 0o644)
    # Verify content before the marker exists; marker is deliberately final.
    for entry in entries:
        if sha256(install / entry["path"]) != entry["sha256"]:
            return False, [f"copy verification failed: {entry['path']}"]
    (install / MARKER).write_text(
        json.dumps(
            {
                "kit_version": manifest["kit_version"],
                "fingerprint": manifest["fingerprint"],
                "schema_version": manifest["schema_version"],
                # Retain the complete, fingerprint-bound per-file evidence.  An
                # aggregate release fingerprint alone cannot prove whether one
                # later project delta is an older canonical copy.
                "release_manifest": manifest,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return verify_install(install, manifest)


def managed_drift(install: Path, manifest: dict) -> list[str]:
    """Return staged/unstaged managed paths; only git-tracked drift is a conflict."""
    result = subprocess.run(
        ["git", "-C", str(install), "status", "--porcelain", "--"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return []
    try:
        managed = {entry["path"] for entry in release_entries(manifest)} | {MARKER}
    except ValueError:
        return []
    return sorted(
        {
            line[3:]
            for line in result.stdout.splitlines()
            if len(line) > 3 and line[3:] in managed
        }
    )


def apply_fleet(
    canonical: Path, installs: list[Path], manifest: dict, *, dry_run: bool = False
) -> dict:
    """Independent repositories continue after known drift; no repository is partially applied."""
    outcome = {"verified": [], "skipped": [], "unexpected": []}
    for install in installs:
        drift = managed_drift(install, manifest)
        if drift:
            outcome["skipped"].append(
                {
                    "install": str(install),
                    "reason": "dirty managed path",
                    "paths": drift,
                }
            )
            continue
        ok, details = apply_install(canonical, install, manifest, dry_run=dry_run)
        if ok:
            outcome["verified"].append(str(install))
        else:
            outcome["unexpected"].append({"install": str(install), "details": details})
            break  # unexpected failure stops later independent repositories
    return outcome
