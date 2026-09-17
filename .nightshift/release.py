"""Deterministic, whole-kit release manifests and install verification (SPEC-156)."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional

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


def resolve_sync_selection(
    declaration: Optional[Mapping], managed_names: list[str]
) -> set[str]:
    """Resolve which of ``managed_names`` a per-install sync should deliver
    (SPEC-356 R2).

    Pure and total: ``declaration`` is whatever sits at an install's
    ``release_policy`` key. ``None`` and ``{}`` both mean "this install
    declares no release_policy" and resolve to the full ``managed_names`` set.
    This function never reads YAML and never distinguishes an absent
    ``release_policy`` from a malformed one — a caller that requires a valid
    ``committed_kit`` (``allow``/``opt_out``) must reject the malformed case
    before calling this resolver.

    Resolution: when ``sync_files.include`` is a non-empty list, the candidate
    set is the members of ``managed_names`` matching any ``include`` glob
    (``include`` can never admit a name outside ``managed_names``); otherwise
    the candidate set is all of ``managed_names`` unless ``committed_kit`` is
    ``"opt_out"``, in which case it starts empty. ``sync_files.exclude``
    globs are then subtracted from the candidate set — exclude only narrows,
    it never widens, so excluding from an already-empty (opt_out, no include)
    set stays empty.
    """
    managed = list(managed_names)
    if not declaration:
        return set(managed)

    committed_kit = declaration.get("committed_kit") if isinstance(declaration, Mapping) else None
    sync_files = declaration.get("sync_files") if isinstance(declaration, Mapping) else None

    include: list[str] = []
    exclude: list[str] = []
    if isinstance(sync_files, Mapping):
        raw_include = sync_files.get("include")
        if isinstance(raw_include, list):
            include = [glob for glob in raw_include if isinstance(glob, str)]
        raw_exclude = sync_files.get("exclude")
        if isinstance(raw_exclude, list):
            exclude = [glob for glob in raw_exclude if isinstance(glob, str)]

    if include:
        candidate = {name for name in managed if any(fnmatch.fnmatch(name, glob) for glob in include)}
    elif committed_kit == "opt_out":
        candidate = set()
    else:
        candidate = set(managed)

    if exclude:
        candidate = {name for name in candidate if not any(fnmatch.fnmatch(name, glob) for glob in exclude)}

    return candidate


def is_kit_install(nightshift_dir: Path) -> bool:
    """Return whether a ``.nightshift`` directory is a kit install at all.

    BUG-323: every discovery path (``nightshift-sync.find_nightshift_dirs``,
    ``doctor.find_projects``, ``nsm.discover_projects``,
    ``nightshift-master._discover_projects``) used to treat the directory name
    alone as proof of an install. A stray ``.nightshift/red-proofs/`` then
    became an "install" with no configuration, the coordinator raised a
    migration request it could never satisfy, and the whole repository -- real
    installs included -- was skipped from the release.

    A real install always has ``config.yaml`` (written by bootstrap) or
    ``release-marker.json`` (written by every release); a bootstrapped but
    never-released project has only the former, so either one suffices. This
    single definition ships in managed payload so canonical and installs agree
    by construction rather than by hand.
    """
    directory = Path(nightshift_dir)
    return (directory / "config.yaml").is_file() or (directory / MARKER).is_file()


def kit_version(canonical: Path) -> str:
    match = re.search(
        r'^kit_version:\s*"([^"]+)"',
        (canonical / "config.yaml").read_text(),
        re.MULTILINE,
    )
    if not match:
        raise ValueError("canonical config.yaml is missing kit_version")
    return match.group(1)


def schema_version(canonical: Path) -> str:
    """Return the canonical config schema version (SPEC-269).

    Falls back to ``"3.0.0"`` when ``config.yaml`` has no ``schema_version``
    field, matching this module's historical hard-coded manifest value so
    fixtures that omit the field keep their prior behavior unchanged.
    """
    match = re.search(
        r'^schema_version:\s*"([^"]+)"',
        (canonical / "config.yaml").read_text(),
        re.MULTILINE,
    )
    return match.group(1) if match else "3.0.0"


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
        "schema_version": schema_version(canonical),
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


HISTORY_KEYS = frozenset({"retained_manifests", "unretained_manifests"})


def flatten_retained(entry: dict) -> dict:
    """Empty a retained manifest's own history before it is retained again.

    A retained entry that carries its own ``retained_manifests`` duplicates
    manifests that already sit beside it in the same list, so each release
    doubles the file (measured: 12KB at 3.8.4 to 29MB at 3.11.0 across eleven
    releases). ``resolve_retained_manifest`` scans the list without recursing,
    so the nested copies were never reachable evidence in the first place.
    The keys are emptied rather than dropped so a retained entry keeps the
    shape of the manifest it came from.
    """
    if not isinstance(entry, dict):
        return entry
    if not any(entry.get(key) for key in HISTORY_KEYS):
        return entry
    return {**entry, **{key: [] for key in HISTORY_KEYS}}


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
        if key not in {"fingerprint"} | HISTORY_KEYS
    }
    current["retained_manifests"] = sorted(
        (flatten_retained(item) for item in retained_manifests),
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


class SameVersionResealError(RuntimeError):
    """A same-version reseal would orphan completed handoffs (BUG-331)."""


def completed_records_on_fingerprint(canonical: Path, fingerprint: str) -> list[str]:
    """Names of completed ``release-handoffs/*.json`` records sealed against
    ``fingerprint``.

    Per the BUG-331 gap protocol, a completed record whose own fingerprint
    cannot be read is treated as referencing ``fingerprint`` -- the stricter
    path -- since an unreadable record can never be positively cleared.
    """
    directory = canonical / "release-handoffs"
    if not directory.is_dir():
        return []
    names: list[str] = []
    for record_path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(record_path.read_text())
        except json.JSONDecodeError:
            names.append(record_path.name)
            continue
        if not isinstance(record, dict) or record.get("status") != "completed":
            continue
        sealed = record.get("manifest_fingerprint")
        if not isinstance(sealed, str) or not sealed or sealed == fingerprint:
            names.append(record_path.name)
    return names


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
    elif previous:
        # Same-version reseal (BUG-331/SPEC-257): the on-disk fingerprint is
        # about to be replaced without being retained. That is only safe when
        # nothing sealed a completion against it yet -- check before writing.
        on_disk_fingerprint = previous.get("fingerprint")
        if isinstance(on_disk_fingerprint, str) and on_disk_fingerprint:
            offending = completed_records_on_fingerprint(canonical, on_disk_fingerprint)
            if offending:
                raise SameVersionResealError(
                    "same-version reseal would orphan completed handoff record(s) "
                    f"sealed against the on-disk fingerprint {on_disk_fingerprint}: "
                    f"{', '.join(offending)}. Either bump kit_version (the previous "
                    "manifest is then retained), or reset these records to status "
                    "'pending' first so the next rollout completes them again."
                )
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


# ---------------------------------------------------------------------------
# SPEC-324: static payload gate
#
# The 3.17.0 rollout needed four apply attempts because canonical shipped
# payload that its own installs' gates rejected -- and each rejection was only
# discoverable after a full canonical-suite preflight and a real repository
# commit. Everything below is a pure function of the canonical checkout, runs
# in seconds inside validate_manifest (which already closes --apply on any
# error), and asks the one question the shape checks never asked: will the
# payload be ACCEPTED by the installs that receive it?
# ---------------------------------------------------------------------------

SKILL_PATH = "Skills/nightshift/SKILL.md"
GUARD_PATH = "scope_guard.py"
SHELLCHECK_INSTALL_HINT = "brew install shellcheck"


def _manifest_paths(manifest: dict) -> list[str]:
    return [str(entry.get("path", "")) for entry in manifest.get("files", [])]


def payload_shell_lint_errors(canonical: Path, manifest: dict) -> list[str]:
    """R1: every ``.sh`` payload entry passes ``shellcheck`` (BUG-322 class)."""
    scripts = [path for path in _manifest_paths(manifest) if path.endswith(".sh")]
    if not scripts:
        return []
    if shutil.which("shellcheck") is None:
        return [
            f"shellcheck is required to validate {len(scripts)} shell payload file(s) "
            f"and is not on PATH ({SHELLCHECK_INSTALL_HINT})"
        ]
    result = subprocess.run(
        ["shellcheck", "--format=gcc", *scripts],
        cwd=canonical,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    findings = [line for line in result.stdout.splitlines() if line.strip()]
    return [f"payload shell lint: {line}" for line in findings] or [
        "payload shell lint: shellcheck failed: " + result.stderr.strip()[-400:]
    ]


def _load_module_from(path: Path, name: str):
    import importlib.util

    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Python 3.14 resolves dataclass annotations through sys.modules at class
    # creation; an unregistered module raises inside @dataclass (the BUG-020
    # mechanism). Register before executing, exactly as validate_install does.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def payload_scope_classification_errors(canonical: Path, manifest: dict) -> list[str]:
    """R2: the guard that ships accepts every path that ships (BUG-321 class).

    Runs the candidate payload's own ``scope_guard.classify_write`` over every
    manifest path in two simulated layouts -- an install and a canonical
    checkout -- with no active spec, against a scratch ``release-marker.json``
    embedding the candidate manifest. Only when ``scope_guard.py`` is itself a
    manifest member: fixtures that ship a single module have no guard to ask.
    """
    paths = _manifest_paths(manifest)
    if GUARD_PATH not in paths:
        return []
    try:
        guard = _load_module_from(canonical / GUARD_PATH, "_release_gate_scope_guard")
    except Exception as exc:  # noqa: BLE001 - the gate must report, never crash
        return [f"payload scope classification: cannot load {GUARD_PATH}: {exc}"]
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="nightshift-payload-gate-") as scratch:
        root = Path(scratch)
        for layout in (".nightshift", "canonical"):
            kit = root / layout
            (kit / "specs").mkdir(parents=True)
            (kit / MARKER).write_text(
                json.dumps({"kit_version": manifest.get("kit_version"),
                            "fingerprint": manifest.get("fingerprint"),
                            "release_manifest": manifest})
            )
            for path in paths:
                try:
                    decision = guard.classify_write(
                        f"{layout}/{path}", None, root, kit, None,
                        known_specs_dirs={kit / "specs"},
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"payload scope classification: {layout}/{path}: classify_write raised {exc!r}"
                    )
                    continue
                if not decision.allowed:
                    errors.append(
                        f"payload scope classification: {layout}/{path} would be denied "
                        f"by the shipped guard ({decision.reason})"
                    )
    return errors


def skill_version_errors(canonical: Path, manifest: dict) -> list[str]:
    """R3: ``SKILL.md``'s own ``version:`` equals ``kit_version``."""
    if SKILL_PATH not in _manifest_paths(manifest):
        return []
    text = (canonical / SKILL_PATH).read_text()
    match = re.search(r"^version:\s*([^\s#]+)", text, re.MULTILINE)
    declared = match.group(1).strip("\"'") if match else None
    expected = manifest.get("kit_version")
    if declared != expected:
        return [f"{SKILL_PATH} declares version {declared!r}; manifest kit_version is {expected!r}"]
    return []


def handoff_membership_errors(canonical: Path, manifest: dict) -> list[str]:
    """R4: every pending handoff names only paths its target manifest manages.

    Delegates to ``release_handoff.validate_artifact`` -- the one place that
    knows how a record's target version resolves (current, retained, or
    explicitly unretained) and which non-payload artifacts a record may name --
    and surfaces only the membership failures. A record that can never re-pin
    (SPEC-254/255 named ``canonical_copies.py``, never managed) is a release
    error here, where the release cannot proceed past it, instead of one line
    among a hundred authoring-time findings.
    """
    directory = canonical / "release-handoffs"
    if not directory.is_dir():
        return []
    try:
        handoff = _load_module_from(canonical / "release_handoff.py", "_release_gate_release_handoff")
    except Exception as exc:  # noqa: BLE001
        return [f"release handoff membership: cannot load release_handoff.py: {exc}"]
    errors: list[str] = []
    for record_path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(record_path.read_text())
        except json.JSONDecodeError:
            errors.append(f"release handoff {record_path.name} is not valid JSON")
            continue
        if record.get("status") != "pending":
            continue
        for problem in handoff.validate_artifact(
            record, spec_id=str(record.get("spec_id", "")), manifest=manifest
        ):
            if "unmanaged paths" in problem:
                errors.append(f"release handoff {record_path.name}: {problem}")
    return errors


def completed_handoff_orphan_errors(canonical: Path, manifest: dict) -> list[str]:
    """R4 (BUG-331): flag a completed record whose fingerprint is orphaned.

    A completed record is only trustworthy provenance while its sealed
    fingerprint resolves to something -- the current manifest, a retained
    historical one, or an explicitly unretained release. When none of those
    match, the fingerprint was silently dropped by a same-version reseal (or
    equivalent) and the record is now unverifiable; that must be visible at
    the next preflight, not tolerated quietly.
    """
    directory = canonical / "release-handoffs"
    if not directory.is_dir():
        return []
    try:
        handoff = _load_module_from(canonical / "release_handoff.py", "_release_gate_release_handoff")
    except Exception as exc:  # noqa: BLE001 - the gate must report, never crash
        return [f"release handoff provenance: cannot load release_handoff.py: {exc}"]
    errors: list[str] = []
    for record_path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(record_path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("status") != "completed":
            continue
        outcome = handoff.resolve_manifest_membership(record, manifest)
        if outcome.get("outcome") == "missing":
            errors.append(
                f"release handoff {record_path.name}: completed against fingerprint "
                f"{record.get('manifest_fingerprint')!r}, which is neither current, "
                "retained, nor explicitly unretained (BUG-331 orphaned fingerprint)"
            )
    return errors


def finding_family_regression_errors(canonical: Path, manifest: dict) -> list[str]:
    """SPEC-337 R2: deny a validate_specs.py finding family that is new or
    grew relative to the stored floor, so a regression is visible instead of
    drowned among ~700 pre-existing findings (SPEC-319 Open Questions item 3
    / SPEC-QUESTIONS-007 Q3 option B).

    A family that only shrank, or disappeared entirely, is never an error --
    that is progress. Only ``added`` families and ``changed`` families whose
    count increased are denied (SPEC-270 R3's ``diff_finding_family_summaries``
    already distinguishes these).

    To accept a genuine new/grown family into the floor after reviewing that
    it is intentional (R3), regenerate the baseline from the repo root:

        python3 canonical/validate_specs.py canonical/specs --format json \\
            --ownership-summary \\
          | python3 -c "import json, sys; data = json.load(sys.stdin); \\
              json.dump(data['finding_family_summary'], sys.stdout, indent=2); \\
              print()" \\
          > canonical/metrics/validation-error-floor-baseline.json
    """
    specs_dir = canonical / "specs"
    if not specs_dir.is_dir():
        return []
    baseline_path = canonical / "metrics" / "validation-error-floor-baseline.json"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"validation error floor: cannot read baseline {baseline_path}: {exc}"]
    try:
        validate_specs = _load_module_from(
            canonical / "validate_specs.py", "_release_gate_validate_specs"
        )
    except Exception as exc:  # noqa: BLE001 - the gate must report, never crash
        return [f"validation error floor: cannot load validate_specs.py: {exc}"]
    try:
        results = validate_specs.validate_directory(specs_dir)
    except ValueError as exc:
        return [f"validation error floor: cannot validate {specs_dir}: {exc}"]
    frontmatters = validate_specs._collect_frontmatters_for_paths([str(specs_dir)])
    current = validate_specs.finding_family_summary(results, frontmatters)
    diff = validate_specs.diff_finding_family_summaries(baseline, current)
    errors: list[str] = []
    for change in diff["changes"]:
        if change["change"] == "added":
            errors.append(
                f"validation error floor: new finding family {change['family']!r} "
                f"(count={change['count']}) not present in baseline"
            )
        elif change["change"] == "changed" and change["after"]["count"] > change["before"]["count"]:
            errors.append(
                f"validation error floor: finding family {change['family']!r} grew "
                f"{change['before']['count']} -> {change['after']['count']}"
            )
    return errors


def payload_gate_errors(canonical: Path, manifest: dict) -> list[str]:
    """All SPEC-324 checks, in the order a reader would want to fix them.

    SPEC-333 wires in BUG-331 R4 (``completed_handoff_orphan_errors``): the 19
    real historical completed-handoff records that were orphaned by past
    same-version reseals have been dispositioned (folded -- reset to the
    pending sentinel so the next real rollout completes them again, same
    pattern as the BUG-016.json precedent), so this check is clean on the
    real checkout.

    SPEC-337's finding-family baseline diff is deliberately NOT a member
    (BUG-334). Every check here is a cheap comparison scoped to whatever
    directory it is handed, and ``validate_install.py`` hands this function an
    *install* directory. The finding-family diff is neither: it is
    canonical-only (an install has its own unrelated ``specs/`` corpus and
    never receives ``metrics/validation-error-floor-baseline.json``) and it
    costs a whole-corpus ``validate_directory`` walk. It runs from
    ``release_coordinator.coordinate_release`` instead, alongside
    ``check_canonical_suite_headroom``.
    """
    return (
        skill_version_errors(canonical, manifest)
        + handoff_membership_errors(canonical, manifest)
        + completed_handoff_orphan_errors(canonical, manifest)
        + payload_shell_lint_errors(canonical, manifest)
        + payload_scope_classification_errors(canonical, manifest)
    )


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
    errors.extend(payload_gate_errors(canonical, manifest))
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
