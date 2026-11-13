#!/usr/bin/env python3
"""Guarded, repository-scoped coordinator for whole-kit Nightshift releases.

The coordinator deliberately owns git integration while ``release.py`` remains
the mechanical copy/verify primitive.  It never pushes and never stages paths
outside the computed release allowlist.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import config_migrations
import release
import release_handoff
import spec_id
from observability_enroll import classify_path as observability_classify
from observability_enroll import release_disposition


@dataclass(frozen=True)
class MigrationRequest:
    install: str
    worker_id: str
    old_schema: str
    required_schema: str
    allowed_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    manifest_fingerprint: str
    isolation: str = "worktree"
    may_commit: bool = False
    may_push: bool = False
    may_merge: bool = False
    may_change_lifecycle: bool = False
    config_source_sha256: str | None = None
    required_kit_version: str | None = None


@dataclass
class MigrationResult:
    worker_id: str
    changes: dict[str, str]
    validation_passed: bool
    isolation: str = "worktree"
    committed: bool = False
    pushed: bool = False
    merged: bool = False
    lifecycle_changed: bool = False
    details: list[str] = field(default_factory=list)


@dataclass
class RepositoryPlan:
    root: Path
    installs: list[Path]
    allowed_paths: set[str]
    committed_kit_policy: str | None
    policy_sources: tuple[str, ...]
    hook_policies: tuple[tuple[str, str], ...]
    # BUG-NS-KIT-117: repo-relative registry copies this release untracks.
    untrack_paths: set[str] = field(default_factory=set)


MigrationRunner = Callable[[MigrationRequest], MigrationResult]
SuiteRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
# Bounds one canonical-suite step so a hung release cannot wait forever. The
# value is meant to clear the suite's measured healthy runtime with roughly
# as much room again to spare, which is the relation
# check_canonical_suite_headroom() checks against a durable, per-run
# measurement recorded by _record_canonical_suite_duration() -- not a
# hand-edited literal (SPEC-336; that failure mode was BUG-320). 600 was set
# against a 305.25s suite; by 3.17.0 a green suite measured 996.10s, so the
# guard meant to catch a hang was refusing every healthy release (BUG-320).
# 2100 was set against that 996.10s measurement; by kit 3.23.0 a green suite
# measured 1065.135s, leaving only 1034.865s headroom -- just under the
# required 2x margin -- so the guard tripped again for the same organic-growth
# reason. Bumped once more with real margin. 2400 was set against that
# 1065.135s measurement; by kit 3.24.0 a real fleet-release preflight
# recorded a healthy suite run of 1701.715s -- 2400 - 1701.715 = 698.285,
# far short of the required 2x margin -- tripping the same organic-growth
# guard again (SPEC-377). Bumped to 4800 with real margin to spare.
# SPEC-NS-KIT-116 (2026-10-07): suite measured 2441-2731s, so 4800 < 2x; bumped to 6000.
CANONICAL_SUITE_TIMEOUT_S = 7200
SKILL_MANAGED_PATH = "Skills/nightshift/SKILL.md"
# BUG-NS-KIT-102: manifest guides are delivered beside the global SKILL.md.
SKILL_GUIDES_SOURCE_PREFIX = "guides/"
SKILL_GUIDES_TARGET_DIR = "Skills/nightshift/guides/"
# SPEC-336: durable per-run canonical-suite duration measurements are written
# as sibling artifacts to write_metrics()'s own reports/_wip/release-*.json
# convention, using this glob to find the most recent one.
CANONICAL_SUITE_DURATION_GLOB = "canonical-suite-duration-*.json"
# SPEC-394 R3: the per-test durations of the same run are written as a JUnit XML
# sibling of that record. The suite child writes to a unique pending path (via
# PYTEST_ADDOPTS, so the pinned CANONICAL_SUITE.command argv is untouched) and
# the recorder moves it beside the matching duration record. The name does not
# match CANONICAL_SUITE_DURATION_GLOB.
CANONICAL_SUITE_JUNIT_PENDING_PREFIX = "canonical-suite-junit-pending-"
CANONICAL_SUITE_JUNIT_TEMPLATE = "canonical-suite-test-durations-{stamp}Z.junit.xml"
# BUG-NS-KIT-130 R2: a committable summary of the same JUnit file (totals and summed
# duration per test file; no test ids, parameters, messages or captured output).
CANONICAL_SUITE_SUMMARY_TEMPLATE = "canonical-suite-test-summary-{stamp}Z.json"
_JUNIT_MODULE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
# SPEC-NS-KIT-126: a recent green suite record may stand in for the --apply
# preflight's full run when the cut changed only release-mechanical paths
# (relative to canonical/). "dir/**" entries are prefixes.
SUITE_REUSE_MAX_AGE_S = 24 * 3600
RELEASE_MECHANICAL_PATHS = (
    "config.yaml",  # kit version source
    "config-reference.yaml",
    "LOOP.md",
    "Skills/nightshift/SKILL.md",
    "CHANGELOG.md",
    "release-manifest.json",
    "release-handoffs/**",
    "tests/fixtures/spec-229-006/**",
    "spec-id-legacy/**",  # legacy spec-id lists the cut re-freezes
)
# Files that carry the version string among other content: reuse only when
# every changed line in them holds a version number.
RELEASE_VERSION_LINE_PATHS = (
    "config.yaml",
    "config-reference.yaml",
    "LOOP.md",
    "Skills/nightshift/SKILL.md",
)
# Tests that read the mechanical paths (manifest, CHANGELOG, version strings,
# fixtures, legacy lists, handoffs); run instead of the full suite on reuse.
RELEASE_MECHANICAL_TESTS = (
    "tests/test_release.py",
    "tests/test_release_handoff.py",
    "tests/test_spec_229_006_live_e2e.py",
    "tests/test_spec_417_005_slim_skill.py",
    "tests/test_spec_id_validation.py",
    "tests/test_spec_id_docs.py",
    "tests/test_managed_payload_provenance.py",
    "tests/test_managed_payload_acceptance.py",
)
SUITE_GROWTH_WARNING_RATIO_X10 = 16  # 1.6x, integer-compared
_VERSION_TOKEN = re.compile(r"\d+\.\d+\.\d+")
# The line hooks/pre-commit identifies itself by; the write-scope installer
# recognises the same string (BUG-329).
KIT_HOOK_HEADER = "# Nightshift Kit \u2014 Pre-commit hook"
# SPEC-NS-KIT-143: the line hooks/commit-msg identifies itself by, and the replay window.
COMMIT_MSG_HOOK_HEADER = "Nightshift Kit \u2014 Commit message hook"
COMMIT_MSG_REPLAY_DAYS = 30
COMMIT_MSG_REPLAY_CAP = 500
COMMIT_MSG_REPLAY_WALK = 5000
COMMIT_MSG_REFRESH_MODES = ("auto", "force", "never")


def _run(
    command: list[str],
    *,
    cwd: Path,
    check: bool = False,
    timeout: int | None = None,
    binary: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=not binary,
        capture_output=True,
        check=check,
        timeout=timeout,
    )


def _run_canonical_suite_step(
    runner: SuiteRunner,
    argv: list[str],
    canonical: Path,
) -> subprocess.CompletedProcess[str]:
    """Run one canonical-suite command without allowing release to hang forever."""
    try:
        return runner(argv, canonical)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        detail = f"canonical suite command exceeded {CANONICAL_SUITE_TIMEOUT_S}s: {' '.join(argv)}"
        return subprocess.CompletedProcess(
            argv, 124, stdout, f"{stderr}\n{detail}".strip()
        )


def _canonical_suite_junit_pending_path(canonical: Path) -> Path:
    """Return a unique, not-yet-existing JUnit XML path for one suite run."""
    return (
        canonical
        / "reports"
        / "_wip"
        / f"{CANONICAL_SUITE_JUNIT_PENDING_PREFIX}{uuid.uuid4().hex}.xml"
    )


def _repair_environment_digest() -> str:
    """Bind the caller environment, excluding control-only invocation metadata."""
    excluded = {"NIGHTSHIFT_ESCALATION_SIGNOFF", "NIGHTSHIFT_ACTIVE_SPEC",
                "NIGHTSHIFT_COORDINATOR_SESSION", "NIGHTSHIFT_RUN_ID", "PYTEST_CURRENT_TEST"}
    return hashlib.sha256(json.dumps({key: value for key, value in os.environ.items()
                                     if key not in excluded}, sort_keys=True).encode()).hexdigest()


def _repair_observer_source() -> str:
    # Reuse the existing serial/xdist collection and complete phase observer.
    from verification_report import _EXPECTED_FIX_PYTEST_OBSERVER
    return _EXPECTED_FIX_PYTEST_OBSERVER + r'''
import sys, hashlib, importlib.metadata
_original_finish = pytest_sessionfinish
@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _active:
        options = session.config.option
        _binding["repair_complete_selection"] = not any(
            getattr(options, key, None) for key in
            ("keyword", "markexpr", "deselect", "ignore", "ignore_glob", "collectonly", "maxfail", "lf", "stepwise")) and not _binding.get("repair_deselected")
        try:
            paths = {Path(sys.executable).resolve()}
            for distribution in importlib.metadata.distributions():
                directory = getattr(distribution, "_path", None)
                if directory is None:
                    raise RuntimeError("unknown dependency identity")
                identified = False
                for name in ("METADATA", "RECORD", "PKG-INFO"):
                    candidate = Path(directory) / name
                    if candidate.is_file():
                        paths.add(candidate.resolve())
                        identified = True
                if not identified:
                    raise RuntimeError("unknown dependency metadata")
            _binding["repair_runtime"] = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                          for path in sorted(paths)]
        except Exception:
            _binding["repair_runtime_unavailable"] = True
    _original_finish(session, exitstatus)
def pytest_deselected(items):
    if _active:
        _binding["repair_deselected"] = _binding.get("repair_deselected", 0) + len(items)
'''


def compose_inventory_repair(canonical: Path, *, original_record: dict,
                             closure_record: dict, review: dict, approval: dict) -> dict:
    """Author a distinct receipt after exact explicit owner approval; never edit runs."""
    receipt = {"schema_version": 1, "outcome": "repair-composed",
               "manifest_fingerprint": json.loads((canonical / "release-manifest.json").read_text())["fingerprint"],
               "original_record": original_record,
               "closure_record": closure_record, "review": review, "approval": approval}
    try:
        receipt["coverage"] = release_handoff.record_repair_coverage(canonical, receipt)
    except Exception as exc:
        raise ValueError("record-only repair composition refused") from exc
    path = canonical / "reports/_wip" / ("canonical-suite-repair-composition-" + uuid.uuid4().hex + ".json")
    write_metrics(receipt, path)
    return receipt


def record_inventory_repair_closure(canonical: Path) -> Path:
    """Run the complete approved reader in normal mode; this is never a FULL record."""
    if os.environ.get("SPEC_229_006_RECORD"):
        raise ValueError("repair closure requires record mode unset")
    manifest = json.loads((canonical / "release-manifest.json").read_text())
    command = manifest["canonical_suite"]["command"]
    if not command or command[-1] != "tests":
        raise ValueError("unknown full command/reader closure")
    commit, clean = _canonical_tree_state(canonical)
    junit = canonical / "reports/_wip" / ("canonical-record-repair-closure-" + uuid.uuid4().hex + ".xml")
    junit.parent.mkdir(parents=True, exist_ok=True)
    result = _run_canonical_suite(command[:-1] + [release_handoff.REPAIR_READER], canonical, junit_xml=junit)
    end_commit, end_clean = _canonical_tree_state(canonical)
    record = {"suite_passed": result.returncode == 0, "canonical_commit": commit,
              "tree_clean_start": clean, "tree_clean_end": end_clean and commit == end_commit,
              "recorded_at": datetime.now(UTC).isoformat(), "phase": "repair_reader_closure",
              "test_durations_artifact": junit.name}
    native = junit.with_suffix(".native.json")
    if native.is_file():
        record["native_proof"] = json.loads(native.read_text())
    path = junit.with_suffix(".json")
    write_metrics(record, path)
    return path


def _suite_environment(junit_xml: Path | None) -> dict[str, str]:
    """Build the suite child's environment (SPEC-394 R3).

    ``NIGHTSHIFT_ESCALATION_SIGNOFF`` is dropped, and when ``junit_xml`` is
    given ``--junitxml=<path>`` is appended to any existing ``PYTEST_ADDOPTS``
    so pytest records per-test durations without changing the command argv.
    """
    from verification_report import _strip_owned_pytest_junit
    environment = os.environ.copy()
    _strip_owned_pytest_junit(environment)
    for flag in ("NIGHTSHIFT_ESCALATION_SIGNOFF", "NIGHTSHIFT_ACTIVE_SPEC", "NIGHTSHIFT_COORDINATOR_SESSION", "NIGHTSHIFT_RUN_ID"):
        environment.pop(flag, None)
    if junit_xml is not None:
        junit_option = shlex.quote(f"--junitxml={junit_xml}")
        existing = environment.get("PYTEST_ADDOPTS", "").strip()
        environment["PYTEST_ADDOPTS"] = (
            f"{existing} {junit_option}" if existing else junit_option
        )
    return environment


RELEASE_PREPARATION_FORMAL = (
    "tests/test_formal_audit_trace_mutations.py",
    "tests/test_formal_current_trace_capture.py",
)
RELEASE_PREPARATION_SENTINELS = (
    "tests/test_board_search_benchmark.py::test_production_guard_has_no_functional_window_override_and_caps_arm",
    "tests/test_board_search_benchmark.py::test_execution_phase_collection_orders_reuses_and_retains_first_abort",
)


def _release_preparation(canonical: Path, manifest: dict, runner: SuiteRunner) -> tuple[dict, list[str]]:
    """Run the bounded release-environment checks before the full suite."""
    started = time.monotonic()
    managed = {str(entry.get("path")) for entry in manifest.get("files", [])}
    if "release_coordinator.py" not in managed:
        return {"status": "not_applicable", "reason": "release coordinator is not in this payload"}, []
    reference_path = canonical / "tests/search_reference.py"
    try:
        module_spec = importlib.util.spec_from_file_location("release_search_reference", reference_path)
        if module_spec is None or module_spec.loader is None:
            raise ValueError("search reference module unavailable")
        reference = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(reference)
        search_compatibility = reference.compatibility_preflight(canonical / "board.py")
    except (OSError, ValueError, ImportError) as exc:
        return {"status": "failed", "search_compatibility": {"error": str(exc)}}, [
            f"functional search compatibility failed: {exc}"
        ]
    try:
        command = _suite_argv(manifest["canonical_suite"], "command")
    except (KeyError, ValueError) as exc:
        return {"status": "unavailable", "error": str(exc)}, [f"release preparation unavailable: {exc}"]
    selected = {
        "formal_collection": [*command[:-1], "--collect-only", *RELEASE_PREPARATION_FORMAL],
        "harness_sentinels": [*command[:-1], *RELEASE_PREPARATION_SENTINELS],
    }
    source_paths = (*RELEASE_PREPARATION_FORMAL, "tests/test_board_search_benchmark.py")
    missing_sources = [path for path in source_paths if not (canonical / path).is_file()]
    evidence = {"status": "passed", "interpreter": str(Path(sys.executable).resolve()),
                "environment_sha256": _repair_environment_digest(),
                "search_compatibility": search_compatibility,
                "sources": {path: hashlib.sha256((canonical / path).read_bytes()).hexdigest() for path in source_paths},
                "steps": {}}
    errors = [f"release preparation source missing: {path}" for path in missing_sources]
    if missing_sources:
        evidence["sources"] = {}
        evidence["status"] = "failed"
        evidence["elapsed_s"] = round(time.monotonic() - started, 3)
        return evidence, errors
    for name, argv in selected.items():
        result = _run_canonical_suite_step(runner, argv, canonical)
        evidence["steps"][name] = {"argv": argv, "returncode": result.returncode,
                                   "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}
        if result.returncode:
            errors.append(f"release preparation {name} failed: {(result.stderr or result.stdout).strip()[-500:]}")
        if name == "formal_collection" and result.stdout and any(path not in result.stdout for path in RELEASE_PREPARATION_FORMAL):
            errors.append("release preparation formal_collection omitted selected node IDs")
        if name == "harness_sentinels" and "skipped" in (result.stdout + result.stderr).lower():
            errors.append("release preparation harness_sentinels reported skips")
    evidence["elapsed_s"] = round(time.monotonic() - started, 3)
    if errors:
        evidence["status"] = "failed"
    return evidence, errors


def _run_canonical_suite(
    argv: list[str], cwd: Path, *, junit_xml: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run release preflight without leaking an operator commit authorization.

    ``NIGHTSHIFT_ESCALATION_SIGNOFF`` is intentionally consumed by a managed
    install's commit gate.  It must not change canonical test behavior, or the
    same release can pass or fail based on an operator decision unrelated to
    the kit under test.
    """
    environment = _suite_environment(None)
    if junit_xml is None:
        return subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False,
                              timeout=CANONICAL_SUITE_TIMEOUT_S, env=environment)
    import tempfile
    junit_xml.parent.mkdir(parents=True, exist_ok=True)
    observation = junit_xml.with_suffix(".observation.json")
    with tempfile.TemporaryDirectory(prefix="nightshift-release-observer-") as scratch:
        module = "_nightshift_release_observer_" + uuid.uuid4().hex
        (Path(scratch) / (module + ".py")).write_text(_repair_observer_source())
        from verification_report import _pytest_observer_environment
        environment = _pytest_observer_environment(environment, module=module,
            observer_dir=Path(scratch), binding={"command": argv},
            observation=observation, junit_xml=junit_xml)
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False,
                                timeout=CANONICAL_SUITE_TIMEOUT_S, env=environment)
    if observation.is_file() and junit_xml.is_file():
        try:
            data = json.loads(observation.read_text())
            manifest = json.loads((cwd / "release-manifest.json").read_text())
            native = {"schema_version": 1, "command": argv,
                      "base_command": manifest["canonical_suite"]["command"],
                      "environment_sha256": _repair_environment_digest(),
                      "runtime": data["binding"]["repair_runtime"],
                      "record_mode": bool(os.environ.get("SPEC_229_006_RECORD")),
                      "complete_selection": data["binding"].get("repair_complete_selection") is True,
                      "native_exit_code": result.returncode, "observation": data,
                      "junit_sha256": hashlib.sha256(junit_xml.read_bytes()).hexdigest()}
            write_metrics(native, junit_xml.with_suffix(".native.json"))
        except (OSError, ValueError, KeyError):
            pass  # Missing complete native proof always falls back to the full gate.
    return result


def _junit_test_file(classname: str) -> str:
    """Map a pytest JUnit ``classname`` to its test file path, or a fixed placeholder.

    Only the module part (up to the ``test_*`` component) is kept, so a class name or
    anything unexpected in the attribute never reaches the summary.
    """
    if not _JUNIT_MODULE_RE.match(classname):
        return "<unattributed>"
    parts = classname.split(".")
    for index, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[: index + 1]) + ".py"
    return "<unattributed>"


def summarize_junit(junit_xml: Path) -> dict | None:
    """Return totals and summed duration per test file for a JUnit file (BUG-NS-KIT-130 R2).

    The result holds no test ids, parameters, failure messages or captured output, so it
    can be committed where the raw XML (intentional fixture secrets and PII) cannot.
    ``None`` when the file does not parse.
    """
    import xml.etree.ElementTree as ElementTree

    try:
        root = ElementTree.parse(junit_xml).getroot()
    except (ElementTree.ParseError, OSError):
        return None
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    per_file: dict[str, float] = {}
    total_s = 0.0
    for case in root.iter("testcase"):
        try:
            seconds = float(case.get("time", "0") or 0)
        except ValueError:
            seconds = 0.0
        totals["tests"] += 1
        totals["failures"] += 1 if case.find("failure") is not None else 0
        totals["errors"] += 1 if case.find("error") is not None else 0
        totals["skipped"] += 1 if case.find("skipped") is not None else 0
        path = _junit_test_file(case.get("classname", ""))
        per_file[path] = per_file.get(path, 0.0) + seconds
        total_s += seconds
    return {
        "schema_version": 1,
        **totals,
        "duration_s": round(total_s, 3),
        "files": {path: round(per_file[path], 3) for path in sorted(per_file)},
    }


def _record_canonical_suite_duration(
    canonical: Path,
    duration_s: float,
    *,
    suite_passed: bool,
    junit_xml: Path | None = None,
    commit: str | None = None,
    tree_clean_start: bool = False,
    tree_clean_end: bool = False,
    phase: str = "release_apply",
) -> Path:
    """Persist a durable, timestamped measurement of one canonical-suite run.

    Follows write_metrics()'s existing reports/_wip timestamped-JSON
    convention (the same one result["duration_s"] uses for whole-release
    duration) rather than the Nightshift loop's per-spec preflight schema,
    which has no timing field (SPEC-336 R6). ``suite_passed`` is recorded so
    the headroom check (which cares about *healthy* runtime) can ignore a
    duration produced by a failed or timed-out run, e.g. a run that hit
    CANONICAL_SUITE_TIMEOUT_S itself would otherwise poison every later
    headroom check with its own timeout as the "measured" runtime.

    SPEC-394 R3: when ``junit_xml`` names a file the suite child actually wrote
    (a timed-out or killed run writes none), it is moved beside this record as
    ``canonical-suite-test-durations-<stamp>Z.junit.xml`` and the record gains
    ``test_durations_artifact`` (its file name). Nothing is added otherwise.
    BUG-NS-KIT-130 R2: beside it, ``canonical-suite-test-summary-<stamp>Z.json`` holds
    the committable summary (``test_summary_artifact``); release evidence cites that
    file, never the raw XML.
    """
    recorded_at = datetime.now(UTC)
    stamp = recorded_at.strftime("%Y%m%dT%H%M%S%f")
    record = {
        "duration_s": round(duration_s, 3),
        "recorded_at": recorded_at.isoformat(),
        "canonical_suite_timeout_s": CANONICAL_SUITE_TIMEOUT_S,
        "suite_passed": suite_passed,
        # SPEC-NS-KIT-126 R1: bind the record to the exact commit and tree state.
        "canonical_commit": commit,
        "tree_clean_start": tree_clean_start,
        "tree_clean_end": tree_clean_end,
        "phase": phase,
    }
    output = canonical / "reports" / "_wip" / f"canonical-suite-duration-{stamp}Z.json"
    if junit_xml is not None and junit_xml.is_file():
        durations = output.with_name(CANONICAL_SUITE_JUNIT_TEMPLATE.format(stamp=stamp))
        native = junit_xml.with_suffix(".native.json")
        if native.is_file():
            try:
                record["native_proof"] = json.loads(native.read_text())
            except (OSError, ValueError):
                pass
        os.replace(junit_xml, durations)
        record["test_durations_artifact"] = durations.name
        summary = summarize_junit(durations)
        if summary is not None:
            summary_path = output.with_name(CANONICAL_SUITE_SUMMARY_TEMPLATE.format(stamp=stamp))
            write_metrics(summary, summary_path)
            record["test_summary_artifact"] = summary_path.name
    write_metrics(record, output)
    return output


def latest_canonical_suite_duration(canonical: Path) -> dict | None:
    """Return the most recently recorded *healthy* canonical-suite duration.

    A record whose ``suite_passed`` is false (failed or timed-out run) is
    skipped: the headroom invariant is about healthy runtime, and a timed-out
    run's duration is CANONICAL_SUITE_TIMEOUT_S itself, which would otherwise
    make the headroom check fail permanently for the wrong reason. Returns
    ``None`` on a fresh checkout with no prior recorded healthy measurement
    (SPEC-336 R4).
    """
    directory = canonical / "reports" / "_wip"
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob(CANONICAL_SUITE_DURATION_GLOB), reverse=True):
        try:
            record = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if record.get("suite_passed"):
            return record
    return None


def _canonical_tree_state(canonical: Path) -> tuple[str | None, bool]:
    """Return (HEAD commit, tree clean) for canonical/ (SPEC-NS-KIT-126).

    Clean means ``git status --porcelain`` is empty for canonical/ (tracked
    changes and untracked, non-ignored files); outside a git work tree the
    commit is ``None`` and the tree is never clean.
    """
    head = _run(["git", "rev-parse", "HEAD"], cwd=canonical)
    if head.returncode:
        return None, False
    status = _run(["git", "status", "--porcelain", "--", "."], cwd=canonical)
    return head.stdout.strip(), status.returncode == 0 and not status.stdout.strip()


def _mechanical_path(path: str) -> bool:
    return any(
        path.startswith(rule[:-2]) if rule.endswith("/**") else path == rule
        for rule in RELEASE_MECHANICAL_PATHS
    )


def _version_lines_only(canonical: Path, commit: str, path: str) -> bool:
    diff = _run(
        ["git", "diff", "-U0", "--no-renames", "--relative", commit, "HEAD", "--", path],
        cwd=canonical,
    )
    if diff.returncode:
        return False
    lines = [
        line
        for line in diff.stdout.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    return bool(lines) and all(_VERSION_TOKEN.search(line) for line in lines)


def _newest_suite_record(canonical: Path) -> tuple[str, dict] | None:
    directory = canonical / "reports" / "_wip"
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob(CANONICAL_SUITE_DURATION_GLOB), reverse=True):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            return path.name, record
    return None


def evaluate_suite_reuse(canonical: Path, *, now: datetime | None = None) -> dict:
    """Decide whether the newest suite record can stand in for the full run.

    SPEC-NS-KIT-126 R2: reuse only when the newest record passed, is at most
    24 hours old, was clean at both ends, the current tree is clean, and every
    path changed since its commit is release-mechanical. Any doubt means the
    full suite runs. Returns ``reusable`` plus ``reason`` (and, when reusable,
    ``record``, ``commit`` and ``changed_paths``).
    """
    def refuse(reason: str) -> dict:
        return {"reusable": False, "reason": reason}

    for path in sorted((canonical / "reports/_wip").glob("canonical-suite-repair-composition-*.json"), reverse=True):
        try:
            receipt = json.loads(path.read_text())
            if not release_handoff.validate_record_repair_composition(canonical, receipt):
                return {"reusable": True, "reason": "approved inventory-only repair composition",
                        "outcome": "repair-composed", "composition": receipt,
                        "record": receipt["original_record"]["path"],
                        "commit": json.loads((canonical / receipt["closure_record"]["path"]).read_text())["canonical_commit"],
                        "changed_paths": [release_handoff.REPAIR_RECORD]}
        except (OSError, ValueError, KeyError):
            continue
    found = _newest_suite_record(canonical)
    if found is None:
        return refuse("no canonical-suite record")
    name, record = found
    commit = record.get("canonical_commit")
    if not record.get("suite_passed") or not commit:
        return refuse(f"newest record {name} did not pass or has no commit")
    try:
        recorded = datetime.fromisoformat(record["recorded_at"])
        age = ((now or datetime.now(UTC)) - recorded).total_seconds()
    except (KeyError, TypeError, ValueError):
        return refuse(f"record {name} has no usable recorded_at")
    if not 0 <= age <= SUITE_REUSE_MAX_AGE_S:
        return refuse(f"record {name} is outside the 24 hour window")
    if record.get("tree_clean_start") is not True or record.get("tree_clean_end") is not True:
        return refuse(f"record {name} tree was not clean at both ends")
    head, clean = _canonical_tree_state(canonical)
    if head is None or not clean:
        return refuse("current canonical tree is not clean")
    diff = _run(
        ["git", "diff", "--name-only", "--no-renames", "--relative", commit, "HEAD", "--", "."],
        cwd=canonical,
    )
    if diff.returncode:
        return refuse(f"cannot diff record commit {commit} against HEAD")
    changed = sorted(line for line in diff.stdout.splitlines() if line)
    outside = [path for path in changed if not _mechanical_path(path)]
    if outside:
        return refuse("non-mechanical paths changed: " + ", ".join(outside[:5]))
    for path in changed:
        if path in RELEASE_VERSION_LINE_PATHS and not _version_lines_only(
            canonical, commit, path
        ):
            return refuse(f"{path} changed beyond version lines")
    return {
        "reusable": True,
        "reason": "release-mechanical changes only",
        "record": name,
        "commit": commit,
        "changed_paths": changed,
    }


def canonical_suite_growth_warning(canonical: Path) -> str | None:
    """SPEC-NS-KIT-126 R4: warn when the suite grew 1.6x past the apply baseline.

    Compares the newest healthy record of any phase with the newest healthy
    ``release_apply`` record (records without a phase predate the field and are
    apply records). Never blocks.
    """
    directory = canonical / "reports" / "_wip"
    if not directory.is_dir():
        return None
    latest: float | None = None
    baseline: float | None = None
    for path in sorted(directory.glob(CANONICAL_SUITE_DURATION_GLOB), reverse=True):
        try:
            record = json.loads(path.read_text())
            duration = float(record["duration_s"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if not record.get("suite_passed"):
            continue
        if latest is None:
            latest = duration
        if record.get("phase", "release_apply") == "release_apply":
            baseline = duration
            break
    if latest is None or baseline is None or latest * 10 < baseline * SUITE_GROWTH_WARNING_RATIO_X10:
        return None
    return (
        f"WARNING: latest healthy canonical-suite duration {round(latest, 3)}s is at least "
        f"1.6x the newest healthy release_apply record {round(baseline, 3)}s "
        f"(CANONICAL_SUITE_TIMEOUT_S={CANONICAL_SUITE_TIMEOUT_S}s)"
    )


def record_suite_run(canonical: Path, duration_s: float, *, passed: bool) -> dict:
    """SPEC-NS-KIT-126 R4: write a ``merge``-phase record; touches no install."""
    commit, clean = _canonical_tree_state(canonical)
    path = _record_canonical_suite_duration(
        canonical,
        duration_s,
        suite_passed=passed,
        commit=commit,
        tree_clean_start=clean,
        tree_clean_end=clean,
        phase="merge",
    )
    return {
        "record": str(path),
        "phase": "merge",
        "suite_passed": passed,
        "canonical_commit": commit,
        "tree_clean": clean,
        "warning": canonical_suite_growth_warning(canonical),
    }


def check_canonical_suite_headroom(canonical: Path) -> tuple[bool, str]:
    """Check that CANONICAL_SUITE_TIMEOUT_S still clears the last real run.

    Reads the durable measurement written by _record_canonical_suite_duration
    (SPEC-336 R3) instead of a hand-maintained literal, so the tripwire that
    BUG-320's predecessor could never fire is real again. The relation
    checked is the same one the removed hand-edited-literal test asserted:
    the cap must clear the measured runtime with roughly as much room again
    to spare.

    With no durable measurement yet (fresh checkout, first run) this degrades
    safely and reports healthy rather than hard-failing preflight purely for
    lacking history (SPEC-336 R4).
    """
    record = latest_canonical_suite_duration(canonical)
    if record is None:
        return True, (
            "no durable canonical-suite duration measurement recorded yet; "
            "degrading safely (SPEC-336 R4)"
        )
    measured = record["duration_s"]
    headroom = CANONICAL_SUITE_TIMEOUT_S - measured
    if headroom >= measured:
        return True, (
            f"CANONICAL_SUITE_TIMEOUT_S={CANONICAL_SUITE_TIMEOUT_S}s clears the last "
            f"measured canonical-suite runtime {measured}s (recorded "
            f"{record['recorded_at']}) with {round(headroom, 3)}s to spare"
        )
    return False, (
        f"CANONICAL_SUITE_TIMEOUT_S={CANONICAL_SUITE_TIMEOUT_S}s no longer clears the "
        f"last measured canonical-suite runtime {measured}s (recorded "
        f"{record['recorded_at']}) with roughly as much room again to spare"
    )


def _git_root(path: Path) -> Path | None:
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def _relative(repo: Path, path: Path) -> str:
    return path.resolve().relative_to(repo).as_posix()


def _schema_version(install: Path) -> str:
    config = install / "config.yaml"
    if not config.is_file():
        return "missing"
    return config_migrations._current_schema_version(config.read_text()) or "missing"


def _committed_kit_policy(install: Path) -> tuple[str | None, str]:
    config = install / "config.yaml"
    source = str(config)
    if not config.is_file():
        return None, source
    section = re.search(
        r"(?ms)^release_policy:\s*(?:#.*)?\n(?P<body>(?:^[ \t]+.*(?:\n|$))*)",
        config.read_text(),
    )
    if section is None:
        return None, source
    value = re.search(
        r'(?m)^[ \t]+committed_kit:\s*["\']?([^"\'\s#]+)',
        section.group("body"),
    )
    return (value.group(1) if value else "invalid:missing"), source


def _commit_hook_policies(repo: Path) -> tuple[tuple[str, str], ...]:
    hooks_result = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=repo)
    if hooks_result.returncode:
        return ()
    hooks = Path(hooks_result.stdout.strip())
    if not hooks.is_absolute():
        hooks = repo / hooks
    policies: list[tuple[str, str]] = []
    for name in ("pre-commit", "prepare-commit-msg", "commit-msg"):
        hook = hooks / name
        if not hook.is_file() or not hook.stat().st_mode & 0o111:
            continue
        marker = re.search(
            r"(?m)^\s*#\s*nightshift-release-policy:\s*"
            r"committed-kit=(allow|opt_out)\s*$",
            hook.read_text(errors="replace"),
        )
        if marker:
            policies.append((marker.group(1), str(hook.resolve())))
    return tuple(policies)


def _release_policy_errors(plan: RepositoryPlan) -> list[str]:
    errors: list[str] = []
    if plan.committed_kit_policy and plan.committed_kit_policy.startswith("invalid:"):
        errors.append(
            "invalid committed-kit release policy in " + ", ".join(plan.policy_sources)
        )
    hook_values = {value for value, _source in plan.hook_policies}
    hook_sources = [source for _value, source in plan.hook_policies]
    if len(hook_values) > 1:
        errors.append("conflicting commit-hook policies: " + ", ".join(hook_sources))
    elif hook_values:
        hook_policy = next(iter(hook_values))
        if plan.committed_kit_policy is None:
            errors.append(
                f"commit-hook policy {hook_policy} requires a project declaration; "
                f"hook source: {hook_sources[0]}; policy sources: "
                + ", ".join(plan.policy_sources)
            )
        elif plan.committed_kit_policy != hook_policy:
            errors.append(
                f"committed-kit policy {plan.committed_kit_policy} conflicts with "
                f"commit-hook policy {hook_policy}; policy sources: "
                + ", ".join(plan.policy_sources)
                + f"; hook source: {hook_sources[0]}"
            )
    return errors


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def _migration_needed(install: Path, required: str) -> bool:
    current = _schema_version(install)
    return not _version_tuple(current) or _version_tuple(current) < _version_tuple(
        required
    )



def _is_coordinator_kit_version_write(repo: Path, relative: str, manifest: dict) -> bool:
    """BUG-330: is the working-tree config.yaml exactly HEAD's plus this
    release's kit_version reconciliation? Unreadable HEAD -> False (stricter)."""
    head = _run(["git", "show", f"HEAD:{relative}"], cwd=repo)
    if head.returncode:
        return False
    try:
        current = (repo / relative).read_text()
    except OSError:
        return False
    try:
        return current == config_migrations.set_kit_version(head.stdout, manifest["kit_version"])
    except ValueError:
        return False


def _install_allowlist(repo: Path, install: Path, manifest: dict) -> set[str]:
    paths = {_relative(repo, install / entry["path"]) for entry in manifest["files"]}
    paths.add(_relative(repo, install / release.MARKER))
    # BUG-326: config.yaml is always a release-owned change now -- the
    # coordinator reconciles the project-owned kit_version on every delivery,
    # not only when a schema migration runs. A config.yaml that is already
    # dirty before the release still skips the repository (project-owned work
    # in progress is never written into).
    paths.add(_relative(repo, install / "config.yaml"))
    return paths


REGISTRY_FILENAME = "projects-registry.json"


def _tracked_registry_paths(repo: Path, installs: Iterable[Path]) -> set[str]:
    """BUG-NS-KIT-117: registry copies the repo still tracks (exact paths)."""
    tracked: set[str] = set()
    for install in installs:
        relative = _relative(repo, install / REGISTRY_FILENAME)
        probe = _run(["git", "ls-files", "--error-unmatch", "--", relative], cwd=repo)
        if probe.returncode == 0:
            tracked.add(relative)
    return tracked


def _suite_argv(metadata: dict, phase: str) -> list[str]:
    """Build the declared dependency-capable suite command without a shell."""
    if metadata.get("runner") != "uv":
        raise ValueError("canonical suite runner must be uv")
    dependencies = metadata.get("dependencies")
    command = metadata.get(phase)
    if (
        not isinstance(dependencies, list)
        or not dependencies
        or not all(isinstance(item, str) and item.strip() for item in dependencies)
    ):
        raise ValueError("canonical suite dependencies must be non-empty strings")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item.strip() for item in command)
    ):
        raise ValueError(f"canonical suite {phase} must be a non-empty argv list")
    argv = ["uv", "run"]
    for dependency in dependencies:
        argv.extend(("--with", dependency))
    return argv + command


def _project_owned_managed_path(path: str) -> bool:
    """Keep generated project evidence private while admitting the schema.

    ``specs/_TEMPLATE.md`` (SPEC-300-001) is the one managed-kit exception
    under ``specs/`` — a template, not project-generated spec content, so it
    joins ``metrics/_SCHEMA.md`` as the other named exemption from the
    project-owned ``specs``/``metrics``/``knowledge`` boundary.
    """
    parts = Path(path).parts
    if path in {"metrics/_SCHEMA.md", "specs/_TEMPLATE.md"}:
        return False
    return bool({"specs", "metrics", "knowledge"}.intersection(parts))


def _managed_relative(plan: RepositoryPlan, repo_path: str) -> str:
    """Strip the most-specific install prefix for repositories with nesting."""
    prefixes = sorted(
        (_relative(plan.root, install).rstrip("/") for install in plan.installs),
        key=len,
        reverse=True,
    )
    for prefix in prefixes:
        if repo_path.startswith(prefix + "/"):
            return repo_path.removeprefix(prefix + "/")
    return repo_path


def validate_release_ownership(
    plans: Iterable[RepositoryPlan], manifest: dict
) -> list[str]:
    """Prove copy/stage/commit ownership for every repo before first write."""
    errors: list[str] = []
    managed = {entry["path"] for entry in manifest["files"]}
    conflicts = sorted(path for path in managed if _project_owned_managed_path(path))
    if conflicts:
        errors.append(
            "manifest-managed paths are project-owned: " + ", ".join(conflicts)
        )
    for plan in plans:
        copy_paths = {
            _relative(plan.root, install / entry["path"])
            for install in plan.installs
            for entry in manifest["files"]
        }
        marker_paths = {
            _relative(plan.root, install / release.MARKER) for install in plan.installs
        }
        # BUG-326: config.yaml is release-owned on every delivery (kit_version
        # reconciliation), not only when a schema migration runs. This is the
        # independent recomputation that _install_allowlist must agree with.
        config_paths = {
            _relative(plan.root, install / "config.yaml") for install in plan.installs
        }
        expected = copy_paths | marker_paths | config_paths
        if plan.allowed_paths != expected:
            errors.append(f"release allowlist mismatch for repository: {plan.root}")
        for repo_path in sorted(copy_paths):
            relative = _managed_relative(plan, repo_path)
            if _project_owned_managed_path(relative):
                errors.append(
                    f"project-owned path entered release allowlist: {repo_path}"
                )
    return sorted(set(errors))


def plan_repositories(
    installs: Iterable[Path], manifest: dict
) -> tuple[list[RepositoryPlan], list[dict]]:
    grouped: dict[Path, list[Path]] = {}
    skipped: list[dict] = []
    for install in sorted({path.resolve() for path in installs}):
        # BUG-323: a directory that is not a kit install is reported as such
        # and never grouped with the repository's real installs, so it cannot
        # raise the unsatisfiable migration request that used to skip them all.
        if not release.is_kit_install(install):
            skipped.append(
                {
                    "install": str(install),
                    "classification": "phantom_install",
                    "reason": (
                        "directory is not a kit install: no config.yaml and "
                        f"no {release.MARKER}"
                    ),
                }
            )
            continue
        repo = _git_root(install)
        if repo is None:
            skipped.append(
                {
                    "install": str(install),
                    "classification": "known_project_local",
                    "reason": "install is not inside a git repository",
                }
            )
            continue
        grouped.setdefault(repo, []).append(install)

    plans = []
    for repo, repo_installs in sorted(grouped.items(), key=lambda item: str(item[0])):
        allowed: set[str] = set()
        declarations = [_committed_kit_policy(install) for install in repo_installs]
        declared_values = {
            value for value, _source in declarations if value is not None
        }
        if len(declared_values) > 1:
            policy = "invalid:conflicting"
        else:
            policy = next(iter(declared_values), None)
        for install in repo_installs:
            allowed.update(_install_allowlist(repo, install, manifest))
        plans.append(
            RepositoryPlan(
                repo,
                repo_installs,
                allowed,
                policy,
                tuple(source for _value, source in declarations),
                _commit_hook_policies(repo),
                _tracked_registry_paths(repo, repo_installs),
            )
        )
    return plans, skipped


@dataclass
class _RepositoryStatus:
    staged: set[str]
    dirty: set[str]
    # Each destination's associated source participates in safety, not staging.
    associations: dict[str, set[str]]

    @property
    def safety_paths(self) -> set[str]:
        return self.dirty | {p for paths in self.associations.values() for p in paths}


def _porcelain_status(repo: Path) -> _RepositoryStatus:
    result = _run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo, binary=True,
    )
    if result.returncode:
        raise RuntimeError(os.fsdecode(result.stderr).strip() or "git status failed")
    # fsdecode preserves undecodable pathname bytes. Binary capture also avoids
    # universal-newline translation of literal CR and LF inside filenames.
    raw = os.fsdecode(result.stdout)
    staged: set[str] = set()
    dirty: set[str] = set()
    associations: dict[str, set[str]] = {}
    if not raw:
        return _RepositoryStatus(staged, dirty, associations)
    if not raw.endswith("\0"):
        raise RuntimeError("malformed git status: missing NUL terminator")
    records = iter(raw[:-1].split("\0"))

    def identity(path: str) -> str:
        if not path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
            raise RuntimeError("malformed git status: invalid repository-relative path")
        return path

    for record in records:
        if len(record) < 4 or record[2] != " ":
            raise RuntimeError("malformed git status: invalid record")
        xy = record[:2]
        if (xy != "??" and (any(c not in " MADRCUTU" for c in xy) or xy == "  ")) or ("R" in xy and "C" in xy):
            raise RuntimeError("malformed git status: invalid status code")
        path = identity(record[3:])
        paths = {path}
        if "R" in xy or "C" in xy:
            try:
                source = identity(next(records))
            except StopIteration as exc:
                raise RuntimeError("malformed git status: missing associated source") from exc
            if source == path:
                raise RuntimeError("malformed git status: identical association")
            associations.setdefault(path, set()).add(source)
            if "R" in xy:
                paths.add(source)
                associations.setdefault(source, set()).add(path)
        dirty.update(paths)
        if xy[0] not in {" ", "?"}:
            staged.update(paths)
    return _RepositoryStatus(staged, dirty, associations)


def _porcelain_paths(repo: Path) -> tuple[set[str], set[str]]:
    status = _porcelain_status(repo)
    return status.staged, status.dirty


def _checkpoint_exclusion_reason(plan: RepositoryPlan, path: str) -> str | None:
    """Use the same literal identity exclusions for planning and associations."""
    import scope_guard

    for install in plan.installs:
        prefix = _relative(plan.root, install).rstrip("/") + "/"
        config = install / "config.yaml"
        if (path.startswith(prefix) and config.is_file()
                and "sink: private-dropbox" in config.read_text(errors="replace")
                and observability_classify(".nightshift/" + path[len(prefix):]) == "private_artifact"):
            return "private_artifact"
    if path.rsplit("/", 1)[-1] == "projects-registry.json":
        return "generated_registry"
    specs_dirs = {install / "specs" for install in plan.installs}
    if (plan.root / "canonical" / "specs").is_dir():
        specs_dirs.add(plan.root / "canonical" / "specs")
    if (scope_guard._SPEC_HOME_RE.match(path.rsplit("/", 1)[-1])
            and scope_guard._is_spec_home_violation(path, plan.root, specs_dirs, plan.installs[0])[0]):
        return "spec_wrong_home"
    return None


def preflight_repository(
    plan: RepositoryPlan,
    manifest: dict,
) -> list[str]:
    status = _porcelain_status(plan.root)
    staged, dirty = status.staged, status.safety_paths
    errors = []
    protected_associations = sorted({
        path for destination, sources in status.associations.items()
        for path in {destination, *sources}
        if _checkpoint_exclusion_reason(plan, path) is not None
        or _project_owned_managed_path(_managed_relative(plan, path))
    })
    if protected_associations:
        errors.append("protected associated paths: " + ", ".join(protected_associations))
    unrelated_staged = sorted(staged - plan.allowed_paths)
    if unrelated_staged:
        errors.append("unrelated pre-staged paths: " + ", ".join(unrelated_staged))
    # Manifest payload is canonical-owned and is replaced deterministically on
    # every release.  Only configuration/migration paths are project-owned.
    payload_paths = {
        _relative(plan.root, install / entry["path"])
        for install in plan.installs
        for entry in manifest["files"]
    } | {_relative(plan.root, install / release.MARKER) for install in plan.installs}
    # Project-owned configuration is never canonical payload, even when its
    # schema already needs no migration and therefore is absent from the
    # commit allowlist.  A pre-existing edit must skip this repository before
    # payload copy: its local hook may inspect the whole worktree.
    project_owned_config = {
        _relative(plan.root, install / "config.yaml") for install in plan.installs
    }
    # BUG-330: a config.yaml whose only difference from HEAD is this release's
    # own kit_version reconciliation is the coordinator's leftover from a
    # refused commit (BUG-326 writes it before the commit), not project work.
    # Anything else dirty in it still skips the repository.
    own_reconciliation = {
        path
        for path in (dirty & project_owned_config)
        if _is_coordinator_kit_version_write(plan.root, path, manifest)
    }
    dirty_project_owned = sorted(
        ((dirty & plan.allowed_paths) - payload_paths - own_reconciliation)
        | ((dirty & project_owned_config) - own_reconciliation)
    )
    if dirty_project_owned:
        errors.append(
            "project-owned release paths require separate configuration migration: "
            + ", ".join(dirty_project_owned)
        )
    return errors



def _instruction_path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or '..' in Path(value).parts:
        raise ValueError('instruction path must be repository-relative')
    path = root / value
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise ValueError('instruction paths cannot traverse symlinks')
    path.resolve().relative_to(root)
    return path


def _instruction_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def audit_instruction_versions(root: Path, declaration: Path | None, installs: Iterable[Path]) -> dict:
    """Read only explicitly declared line fields; never infer pins from project prose."""
    from config_migrations import load_config_documents, merge_config_documents

    root = root.resolve()
    if _git_root(root) != root:
        raise ValueError('instruction repository must be a Git toplevel')
    known = sorted(str(p.resolve()) for p in installs)
    result = {'schema_version': 1, 'repository': str(root), 'installs': known,
              'coverage': 'undeclared', 'references': [], 'blocking': False,
              'payload_delivery': 'not_evaluated', 'opt_out': False}
    if declaration is None:
        return result
    declaration = _instruction_path(root, declaration.absolute().relative_to(root).as_posix())
    raw = declaration.read_bytes()
    declaration_documents = load_config_documents(raw.decode())
    if len(declaration_documents) != 1:
        raise ValueError('invalid instruction declaration')
    data = declaration_documents[0]
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('references'), list):
        raise ValueError('invalid instruction declaration')
    if type(data.get('opt_out', False)) is not bool:
        raise ValueError('invalid instruction opt_out')
    result.update(coverage='declared', declaration=str(declaration),
                  declaration_sha256=hashlib.sha256(raw).hexdigest(), opt_out=data.get('opt_out', False))
    result['head'] = _run(['git', 'rev-parse', 'HEAD'], cwd=root).stdout.strip()
    result['index_sha256'] = hashlib.sha256(
        _run(['git', 'ls-files', '--stage', '-z'], cwd=root).stdout.encode()).hexdigest()
    seen = set()
    for ref in data['references']:
        if not isinstance(ref, dict) or type(ref.get('required', False)) is not bool:
            raise ValueError('invalid instruction reference')
        row = {k: ref.get(k) for k in ('path', 'prefix', 'install')}
        row.update(required=ref.get('required', False), ownership='project', status='unknown',
                   remediation='Fix the explicit declaration or installed identity; audit never edits.')
        try:
            path = _instruction_path(root, ref.get('path'))
            prefix = ref.get('prefix')
            if not isinstance(prefix, str) or not prefix or '\n' in prefix or '\r' in prefix:
                raise ValueError('a single literal line prefix is required')
            key = (str(path), prefix)
            if key in seen:
                raise ValueError('duplicate instruction field')
            seen.add(key)
            blob = path.read_bytes()
            row['file_sha256'] = hashlib.sha256(blob).hexdigest()
            classification = ref.get('classification', 'active')
            if classification == 'historical':
                row.update(status='historical', remediation='Historical example; no correction.')
            elif classification != 'active':
                raise ValueError('unknown reference classification')
            elif result['opt_out']:
                row.update(status='opt_out', remediation='Project opted out; no correction.')
            else:
                lines = [line for line in blob.decode().splitlines() if line.startswith(prefix)]
                if len(lines) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', lines[0][len(prefix):]):
                    raise ValueError('active field must be unique and contain only a version')
                install = _instruction_path(root, ref.get('install'))
                if str(install.resolve()) not in known:
                    raise ValueError('owning install must be explicitly bound to a discovered install')
                marker_raw = (install / release.MARKER).read_bytes()
                config_raw = (install / 'config.yaml').read_bytes()
                row['authority_sha256'] = hashlib.sha256(marker_raw + b'\0' + config_raw).hexdigest()
                marker = json.loads(marker_raw)
                config = merge_config_documents(load_config_documents(config_raw.decode()))
                version = marker['kit_version']
                if not isinstance(config, dict) or config.get('kit_version') != version:
                    raise ValueError('installed marker/config versions disagree')
                valid, errors = release.verify_install(install, marker['release_manifest'])
                if not valid or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', version):
                    raise ValueError('invalid installed marker/payload identity: ' + '; '.join(errors))
                policy, _ = _committed_kit_policy(install)
                row.update(old=lines[0][len(prefix):], new=version,
                           status='current' if lines[0][len(prefix):] == version else 'drift',
                           install_policy=policy,
                           remediation='Owner may approve an exact declared-reference commit.')
        except (ValueError, KeyError, OSError, TypeError, UnicodeError) as exc:
            row.update(status='unknown', reason=str(exc))
        result['references'].append(row)
    result['blocking'] = any(row['required'] and row['status'] in ('drift', 'unknown') for row in result['references'])
    result['audit_sha256'] = _instruction_digest(result)
    return result


def reconcile_instruction_versions(root: Path, declaration: Path, installs: Iterable[Path],
                                   audit: dict, approval: dict | None) -> dict:
    """Commit only approved exact fields with normal hooks, preserving the other index entries."""
    installs = tuple(installs)
    current = audit_instruction_versions(root, declaration, installs)
    if (not isinstance(approval, dict) or not isinstance(approval.get('approved_by'), str)
            or not approval['approved_by'].strip() or approval.get('audit_sha256') != audit.get('audit_sha256')
            or current != audit):
        raise ValueError('missing exact approval or concurrent instruction/identity/index change')
    if current['opt_out'] or any(row['status'] == 'unknown' for row in current['references']):
        raise ValueError('opt-out or unknown instruction authority refuses correction')
    rows = [row for row in current['references'] if row['status'] == 'drift']
    if any(row.get('install_policy') == 'opt_out' for row in rows):
        raise ValueError('owning install opted out')
    if not rows:
        return {'status': 'unchanged', 'changes': [], 'audit_sha256': current['audit_sha256']}
    root = root.resolve()
    paths = sorted({row['path'] for row in rows})
    status = _porcelain_status(root)
    if set(paths) & status.safety_paths:
        raise ValueError('declared instruction files must be clean before correction')
    originals = {name: _instruction_path(root, name).read_bytes() for name in paths}
    updated = dict(originals)
    for row in rows:
        old = (row['prefix'] + row['old']).encode()
        new = (row['prefix'] + row['new']).encode()
        updated[row['path']] = b''.join(
            new + line[len(old):] if line.rstrip(b'\r\n') == old else line
            for line in updated[row['path']].splitlines(keepends=True))
    # Final compare before any write; the approval also binds the full index and authority.
    if audit_instruction_versions(root, declaration, installs) != current:
        raise ValueError('concurrent instruction change')
    for name, blob in updated.items():
        _instruction_path(root, name).write_bytes(blob)
    receipt = {'status': 'commit_refused', 'audit_sha256': current['audit_sha256'],
               'approved_by': approval['approved_by'], 'changes': [
                   {**row, 'new_file_sha256': hashlib.sha256(updated[row['path']]).hexdigest()}
                   for row in rows]}
    commit = _run(['git', '--literal-pathspecs', 'commit', '--only', '-m',
                   'chore: reconcile approved project instruction versions', '--', *paths], cwd=root)
    if commit.returncode:
        receipt['reason'] = commit.stderr.strip() or commit.stdout.strip()
    else:
        receipt.update(status='committed', commit=_run(['git', 'rev-parse', 'HEAD'], cwd=root).stdout.strip())
    return receipt


def reconcile_kit_version(install: Path, manifest: dict, *, dry_run: bool) -> dict | None:
    """BUG-326: bring the install's project-owned ``kit_version`` to the release.

    Returns ``{"install", "from", "to"}`` when the line differs (and writes it
    unless ``dry_run``), ``None`` when nothing would change. Touches no other
    byte of ``config.yaml``; a config without the line is left alone.
    """
    config_path = install / "config.yaml"
    if not config_path.is_file():
        return None
    current = config_path.read_text()
    updated = config_migrations.set_kit_version(current, manifest["kit_version"])
    if updated == current:
        return None
    node = config_migrations._version_node(current, "kit_version")
    if not dry_run:
        config_path.write_text(updated)
    return {
        "install": str(install),
        "from": node.value if node is not None else None,
        "to": manifest["kit_version"],
    }


def wire_pre_commit_hook(install: Path, *, dry_run: bool) -> dict | None:
    """BUG-326: install the kit's own ``hooks/pre-commit`` when the repository
    has none, exactly as BOOTSTRAP.md documents (copy + chmod +x).

    ``INT.HOOKS``' remedy for a missing hook is "reinstall through the
    whole-kit release", so the release does it. An existing hook is never
    overwritten -- merging a foreign hook is a human's call (GIT.md) -- it is
    only reported. ``.git/hooks`` lies outside the worktree, so nothing here is
    staged or committed.

    Kit-owned hooks are refreshed here AND, for committed repositories, again
    by ``_refresh_recognized_nightshift_precommit_hooks`` at commit time (the
    pre-existing SPEC-156 step). The two are idempotent; this one also covers
    installs that are delivered without a coordinator commit (opt-out and
    non-git installs), which the commit-time step never reaches.
    """
    source = install / "hooks" / "pre-commit"
    if not source.is_file():
        return None
    hooks = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=install)
    if hooks.returncode:
        return None
    hooks_dir = (install / hooks.stdout.strip()).resolve() if not os.path.isabs(hooks.stdout.strip()) else Path(hooks.stdout.strip())
    target = hooks_dir / "pre-commit"
    if target.exists():
        # BUG-329: a hook carrying the kit's own identifying header is
        # kit-owned and is refreshed to the shipped payload when it differs --
        # otherwise a fixed hook never reaches a repository that already has
        # the broken one. (A write-scope snippet chained into it is redundant:
        # the managed hook calls protect-write-scope.sh directly.) A hook
        # without the header is foreign and is only reported.
        try:
            existing = target.read_bytes()
        except OSError:
            existing = b""
        if KIT_HOOK_HEADER.encode() not in existing:
            return {"install": str(install), "hook": str(target), "action": "kept-existing"}
        if existing == source.read_bytes():
            return {"install": str(install), "hook": str(target), "action": "up-to-date"}
        if not dry_run:
            shutil.copy2(source, target)
            target.chmod(target.stat().st_mode | 0o111)
        return {"install": str(install), "hook": str(target), "action": "refreshed"}
    if not dry_run:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | 0o111)
    return {"install": str(install), "hook": str(target), "action": "installed"}


def build_migration_request(
    install: Path,
    manifest: dict,
    sequence: int,
) -> MigrationRequest:
    source = (install / "config.yaml").read_bytes()
    return MigrationRequest(
        install=str(install),
        worker_id=f"release-migration-{sequence:03d}",
        old_schema=config_migrations._current_schema_version(source.decode("utf-8")) or "missing",
        required_schema=manifest["schema_version"],
        allowed_paths=("config.yaml", ".migrations/"),
        validation_commands=tuple(
            manifest.get("migration_checks", ["python3 validate_specs.py specs/"])
        ),
        manifest_fingerprint=manifest["fingerprint"],
        config_source_sha256=hashlib.sha256(source).hexdigest(),
        required_kit_version=manifest["kit_version"],
    )


def default_migration_runner(request: MigrationRequest) -> MigrationResult:
    """Reference implementation of "the registered deterministic migration".

    ``Skills/nightshift/SKILL.md`` Step 3 dispatches one fresh, worktree-isolated
    subagent per install and gives it only the old/required schema and the
    registered migration to follow — it does not call this function directly.
    This is the testable, canonical implementation that dispatch instructs each
    worker to reproduce exactly (``config_migrations.migrate``), and it is also a
    valid ``migration_runner`` for a caller that wants that exact deterministic
    behavior without spawning a subagent (e.g. a smoke test or a project with no
    per-install customization to reconcile).
    """
    config_path = Path(request.install) / "config.yaml"
    source = config_path.read_bytes()
    if not request.config_source_sha256 or hashlib.sha256(source).hexdigest() != request.config_source_sha256:
        raise ValueError("migration source configuration changed after review")
    current_text = source.decode("utf-8")
    migrated_text = config_migrations.migrate(
        current_text, target=request.required_schema
    )
    return MigrationResult(
        worker_id=request.worker_id,
        changes={"config.yaml": migrated_text},
        validation_passed=True,
        isolation=request.isolation,
    )


def validate_migration_result(request: MigrationRequest, result: MigrationResult) -> list[str]:
    errors = []
    if result.worker_id != request.worker_id:
        errors.append("migration worker identity mismatch")
    if result.isolation != "worktree":
        errors.append("migration worker was not isolated in a worktree")
    if result.committed or result.pushed or result.merged or result.lifecycle_changed:
        errors.append("migration worker exceeded its coordinator-only authority")
    if not isinstance(result.changes, dict):
        return errors + ["migration worker changes must be a mapping"]
    for path, text in result.changes.items():
        if (not isinstance(path, str) or Path(path).is_absolute() or '..' in Path(path).parts
                or (path != "config.yaml" and not path.startswith(".migrations/"))):
            errors.append(f"migration worker changed non-allowlisted path: {path}")
        if not isinstance(text, str):
            errors.append("migration worker output must contain text")
    if result.validation_passed is not True:
        errors.append("migration worker validation failed")
    candidate = result.changes.get("config.yaml")
    if not isinstance(candidate, str):
        return errors + ["migration worker required config.yaml candidate is missing"]
    try:
        if not request.config_source_sha256 or not request.required_kit_version:
            raise ValueError("migration request is missing its source/target binding")
        source = (Path(request.install) / "config.yaml").read_bytes()
        if hashlib.sha256(source).hexdigest() != request.config_source_sha256:
            raise ValueError("migration source configuration changed after review")
        expected = config_migrations.migrate(source.decode('utf-8'), target=request.required_schema)
        if candidate != expected:
            errors.append("migration config.yaml differs from the registered transformation")
        config_migrations.validate_config_structure(candidate)
        projected = config_migrations.set_kit_version(candidate, request.required_kit_version)
        config = config_migrations.validate_config_structure(projected)
        if config.get('schema_version') != request.required_schema:
            errors.append("migration candidate does not contain the required schema target")
        if config.get('kit_version') != request.required_kit_version:
            errors.append("migration candidate cannot reconcile the required kit target")
    except (ValueError, OSError) as exc:
        errors.append(str(exc))
    return errors


def _apply_migration_result(install: Path, result: MigrationResult) -> None:
    for relative, text in result.changes.items():
        destination = install / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)


def _run_declared_checks(
    install: Path,
    commands: Iterable[str],
    *,
    timeout_s: int,
) -> list[str]:
    errors = []
    for command in commands:
        result = subprocess.run(
            shlex.split(command),
            cwd=install,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
        if result.returncode:
            tail = (result.stdout + "\n" + result.stderr).strip()[-1000:]
            errors.append(f"smoke check failed ({command}): {tail}")
    return errors


def _verify_staged(plan: RepositoryPlan, manifest: dict) -> tuple[set[str], list[str]]:
    staged_result = _run(["git", "diff", "--cached", "--name-only"], cwd=plan.root)
    staged = set(staged_result.stdout.splitlines())
    errors = []
    outside = sorted(staged - plan.allowed_paths - plan.untrack_paths)
    if outside:
        errors.append("staged path outside release allowlist: " + ", ".join(outside))
    # BUG-NS-KIT-117: the registry may appear in a release commit only as the
    # planned removal of a tracked copy, never as added or modified content.
    deleted = set(
        _run(
            ["git", "diff", "--cached", "--diff-filter=D", "--name-only"], cwd=plan.root
        ).stdout.splitlines()
    )
    if any(
        path.endswith(REGISTRY_FILENAME)
        and not (path in plan.untrack_paths and path in deleted)
        for path in staged
    ):
        errors.append("generated registry entered release commit")
    for path in staged:
        relative = _managed_relative(plan, path)
        if _project_owned_managed_path(relative):
            errors.append(f"project-owned path entered release commit: {path}")

    for install in plan.installs:
        ok, details = release.verify_install(install, manifest)
        if not ok:
            errors.extend(f"{install}: {detail}" for detail in details)
    return staged, errors


def _refresh_recognized_nightshift_precommit_hooks(plan: RepositoryPlan) -> list[str]:
    """Refresh only installed hooks that identify themselves as Nightshift.

    A release commit invokes the repository's Git hook, not the just-copied
    managed `.nightshift/hooks/pre-commit` payload.  Refreshing an explicitly
    identified Nightshift hook closes that bootstrap gap without touching a
    project-owned hook.
    """
    errors: list[str] = []
    for install in plan.installs:
        source = install / "hooks" / "pre-commit"
        hooks = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=plan.root)
        if hooks.returncode or not source.is_file():
            continue
        directory = Path(hooks.stdout.strip())
        if not directory.is_absolute():
            directory = plan.root / directory
        target = directory / "pre-commit"
        if (
            not target.is_file()
            or "Nightshift Kit — Pre-commit hook"
            not in target.read_text(errors="replace")[:300]
        ):
            continue
        try:
            shutil.copy2(source, target)
            # BUG-329: a hook must be executable whatever mode the payload
            # copy carries; copy2 alone inherits the source's mode.
            target.chmod(target.stat().st_mode | 0o111)
        except OSError as exc:
            errors.append(
                f"could not refresh recognized Nightshift pre-commit hook: {exc}"
            )
    return errors


def _commit_msg_hook_target(root: Path) -> Path | None:
    hooks = _run(["git", "rev-parse", "--git-path", "hooks"], cwd=root)
    if hooks.returncode:
        return None
    directory = Path(hooks.stdout.strip())
    if not directory.is_absolute():
        directory = root / directory
    return directory / "commit-msg"


def _hook_verdict(hook: Path, message_file: Path, scratch: Path, *, identity: dict | None = None) -> tuple[bool, str]:
    """Run one hook on one message file from an empty directory (SPEC-NS-KIT-143 R2).

    The working directory holds no ``.nightshift`` tree and is not a git
    repository, so the hook's SPEC-183 path and terminal-outcome check are inert
    and nothing in any project can be written. The environment is minimal.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(scratch), "LC_ALL": "C", **(identity or {})}
    try:
        proc = subprocess.run(
            ["bash", str(hook), str(message_file)],
            cwd=scratch, env=env, text=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"hook did not run: {exc}"
    if proc.returncode == 0:
        return True, ""
    output = proc.stdout + proc.stderr
    reason = next((ln.strip() for ln in output.splitlines() if "ERROR" in ln), output.strip())
    return False, re.sub(r"^\[nightshift commit-msg\] ERROR:\s*", "", reason)[:200]


def _commit_msg_probe_identity(root: Path, install: Path, scratch: Path) -> dict:
    """Snapshot only local identity/membership; no config, scanner or project cwd.

    Put the snapshot outside the hook cwd so no project-side hook feature is
    enabled. Expand the registry identity before HOME is isolated for execution.
    """
    context = scratch / "id-context"
    context.mkdir()
    shutil.copyfile(Path(spec_id.__file__), context / "spec_id.py")
    code, ids, _warning = spec_id.commit_project_legacy_ids(install, root)
    rows = [{"path": str(root.resolve()), "code": code}] if code else []
    (context / "projects-registry.json").write_text(json.dumps({"projects": rows}))
    if code:
        (context / "spec-id-legacy").mkdir()
        # Keep unreadable membership grammar-only; do not fabricate membership.
        if _warning is None:
            (context / "spec-id-legacy" / f"{code}.json").write_text(json.dumps({"project_code": code, "ids": sorted(ids)}))
    return {"NIGHTSHIFT_COMMIT_PROJECT_ROOT": str(root.resolve()), "NIGHTSHIFT_COMMIT_ID_INSTALL": str(context)}


def _replay_commit_msg_history(root: Path, new_hook: Path, old_hook: Path, *, install: Path | None = None) -> dict:
    """SPEC-NS-KIT-143 R2: replay recent commit messages through the new and current hooks.

    Window: reachable from HEAD, authored in the last 30 days, merges excluded, at most 500.
    Reads git history only; messages go to files in a private temp directory.
    """
    cutoff = time.time() - COMMIT_MSG_REPLAY_DAYS * 86400
    # No --since: git stops walking at the first commit older than the bound, which
    # truncates a history with out-of-order dates. Filter on the author date here;
    # the walk itself is bounded so a very large history stays cheap.
    log = _run(
        ["git", "log", "--no-merges", f"-n{COMMIT_MSG_REPLAY_WALK}", "--format=%H %at"],
        cwd=root,
    )
    shas = []
    for line in log.stdout.splitlines() if not log.returncode else []:
        sha, _, authored = line.partition(" ")
        if authored.isdigit() and int(authored) >= cutoff:
            shas.append(sha)
        if len(shas) >= COMMIT_MSG_REPLAY_CAP:
            break
    would_reject = already_rejected = 0
    reasons: dict[str, int] = {}
    examples: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ns-commit-msg-replay-") as tmp:
        scratch = Path(tmp)
        identity = _commit_msg_probe_identity(root, install or root / ".nightshift", scratch)
        message_file = scratch / "COMMIT_EDITMSG"
        for sha in shas:
            body = _run(["git", "log", "-1", "--format=%B", sha], cwd=root).stdout
            message_file.write_text(body)
            new_ok, reason = _hook_verdict(new_hook, message_file, scratch, identity=identity)
            if new_ok:
                continue
            old_ok, _old_reason = _hook_verdict(old_hook, message_file, scratch, identity=identity)
            if not old_ok:
                already_rejected += 1
                continue
            would_reject += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            if len(examples) < 5:
                examples.append(body.splitlines()[0] if body.strip() else "")
    return {
        "replayed": len(shas),
        "would_reject": would_reject,
        "already_rejected": already_rejected,
        "reasons": [f"{text} (x{count})" if count > 1 else text for text, count in reasons.items()],
        "examples": examples,
    }


def project_owned_commit_msg(root: Path, source: Path, install: Path) -> dict | None:
    """Report a fork's compatibility without writing the active hook or its mode."""
    if not source.is_file():
        return None
    target = _commit_msg_hook_target(root)
    if target is None or not target.is_file():
        return None
    try:
        if COMMIT_MSG_HOOK_HEADER in target.read_bytes()[:300].decode("utf-8", errors="replace"):
            return None
    except OSError:
        return None
    code, legacy, warning = spec_id.commit_project_legacy_ids(install, root)
    probe_code = code or "DEMO"
    ids = [f"{kind}-{probe_code}-001" for kind in spec_id.ID_KINDS] + sorted(legacy)[:3]
    probes = []
    with tempfile.TemporaryDirectory(prefix="ns-commit-msg-probes-") as tmp:
        scratch = Path(tmp)
        identity = _commit_msg_probe_identity(root, install, scratch)
        message = scratch / "COMMIT_EDITMSG"
        for token in ids:
            subject = f"[{token}] docs: compatibility probe"
            message.write_text(subject + "\n")
            kit_ok, kit_reason = _hook_verdict(source, message, scratch, identity=identity)
            fork_ok, fork_reason = _hook_verdict(target, message, scratch, identity=identity)
            probes.append({"subject": subject, "kit_accepts": kit_ok, "fork_accepts": fork_ok,
                           "kit_reason": kit_reason, "fork_reason": fork_reason})
    rejected = [p["subject"] for p in probes if not p["fork_accepts"]]
    remediation = (f"Back up {target} to {target.with_name('commit-msg.nightshift-prev')}; "
                   f"replace the fork with {install / 'hooks' / 'commit-msg'} and make it executable, "
                   "then let the next whole-kit release refresh it. No automatic replacement by doctor --fix.")
    summary = "project_owned_commit_msg; fork rejects: " + ("; ".join(rejected) or "none of the probes")
    return {"finding": "project_owned_commit_msg", "summary": summary,
            "probes": probes, "rejected_probes": rejected, "remediation": remediation,
            "legacy_warning": warning}


def plan_commit_msg_refresh(
    plan: RepositoryPlan, source: Path, *, mode: str, dry_run: bool
) -> dict | None:
    """SPEC-NS-KIT-143: refresh a recognised kit ``commit-msg`` hook, but only after the replay.

    Never creates a hook (D1). Defers when the replay finds commits the new hook
    would reject (D2) unless ``mode == "force"`` (D3). ``dry_run`` writes nothing.
    """
    if not source.is_file():
        return None
    record: dict = {"repository": str(plan.root)}
    target = _commit_msg_hook_target(plan.root)
    if target is None or not target.is_file():
        return {**record, "commit_msg_hook": "absent", "summary": "absent"}
    try:
        existing = target.read_bytes()
    except OSError:
        return {**record, "commit_msg_hook": "absent", "summary": "absent"}
    if COMMIT_MSG_HOOK_HEADER not in existing[:300].decode("utf-8", errors="replace"):
        finding = project_owned_commit_msg(plan.root, source, plan.installs[0])
        return {**record, "commit_msg_hook": "project_owned", **(finding or {"summary": "project_owned"})}
    if mode == "never":
        return None
    if existing == source.read_bytes():
        return {**record, "commit_msg_hook": "unchanged", "summary": "unchanged"}
    replay = _replay_commit_msg_history(plan.root, source, target, install=plan.installs[0])
    record.update(replay)
    rejects = replay["would_reject"]
    if rejects and mode != "force":
        detail = f"{rejects} would be rejected: {'; '.join(replay['reasons'])}"
        record["commit_msg_hook"] = "would_defer" if dry_run else "deferred"
        record["summary"] = f"would defer ({detail})"
        return record
    forced = bool(rejects)
    if dry_run:
        record["commit_msg_hook"] = "would_refresh_forced" if forced else "would_refresh"
        record["summary"] = "would refresh (forced)" if forced else "would refresh"
        return record
    try:
        shutil.copy2(target, target.with_name("commit-msg.nightshift-prev"))
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | 0o111)
    except OSError as exc:
        record["commit_msg_hook"] = "failed"
        record["summary"] = f"failed ({exc})"
        return record
    record["commit_msg_hook"] = "refreshed_forced" if forced else "refreshed"
    record["summary"] = record["commit_msg_hook"]
    return record


def commit_msg_hook_table(entries: list[dict]) -> str:
    """Operator-facing per-repository commit-msg hook table (text twin of the JSON field)."""
    if not entries:
        return "commit-msg hook: no recognised repositories"
    lines = ["commit-msg hook refresh", "repository  ->  outcome"]
    for entry in entries:
        lines.append(f"{entry['repository']}  ->  {entry['summary']}")
        if entry.get("remediation"):
            lines.append(f"    {entry['remediation']}")
        for example in entry.get("examples", []):
            lines.append(f"    e.g. {example}")
    return "\n".join(lines)


def _commit_repository(
    plan: RepositoryPlan, manifest: dict
) -> tuple[str | None, list[str]]:
    # Managed kit directories are historically gitignored in some projects.
    # Force-add is safe because every path comes from the release allowlist and
    # the staged set is mechanically rechecked before commit.
    add_result = _run(
        ["git", "add", "-f", "--", *sorted(plan.allowed_paths)], cwd=plan.root
    )
    if add_result.returncode:
        return None, [add_result.stderr.strip() or "git add failed"]
    # BUG-NS-KIT-117: untrack (index only; the file stays on disk) the exact
    # registry paths planned for this repository, inside the same commit.
    if plan.untrack_paths:
        untrack = _run(
            ["git", "rm", "--cached", "-q", "--", *sorted(plan.untrack_paths)],
            cwd=plan.root,
        )
        if untrack.returncode:
            return None, [untrack.stderr.strip() or "git rm --cached failed"]
    staged, errors = _verify_staged(plan, manifest)
    if errors:
        return None, errors
    if not staged:
        return None, []

    if hook_errors := _refresh_recognized_nightshift_precommit_hooks(plan):
        return None, hook_errors

    message = (
        f"[SPEC-156] chore: release kit {manifest['kit_version']}\n\n"
        f"Nightshift-Release-Version: {manifest['kit_version']}\n"
        f"Nightshift-Release-Fingerprint: {manifest['fingerprint']}\n"
        f"Nightshift-Verified-Installs: {len(plan.installs)}"
    )
    # BUG-NS-KIT-117: a pathspec commit snapshots the working tree, which would
    # re-add the kept-on-disk registry. With an untrack in the set, commit the
    # index instead; _verify_staged just proved it holds exactly the release set.
    commit_args = (
        ["git", "commit", "-m", message]
        if plan.untrack_paths & staged
        else ["git", "commit", "-m", message, "--", *sorted(staged)]
    )
    commit = _run(commit_args, cwd=plan.root)
    if commit.returncode:
        return None, [
            commit.stderr.strip() or commit.stdout.strip() or "git commit failed"
        ]
    sha = _run(["git", "rev-parse", "HEAD"], cwd=plan.root).stdout.strip()
    committed = set(
        _run(
            ["git", "show", "--pretty=format:", "--name-only", sha], cwd=plan.root
        ).stdout.splitlines()
    )
    if committed != staged or not committed.issubset(
        plan.allowed_paths | plan.untrack_paths
    ):
        return sha, ["post-commit path-set verification failed"]
    return sha, []


def _skill_manifest_entry(manifest: dict) -> dict | None:
    return next(
        (
            entry
            for entry in manifest.get("files", [])
            if entry.get("path") == SKILL_MANAGED_PATH
        ),
        None,
    )


def _skill_delivery_entries(manifest: dict) -> list[tuple[str, str, dict]]:
    """(canonical source, release-root target, manifest entry): skill, guides, assets.

    BUG-NS-KIT-102: the slim skill's command bodies live in ``guides/``; the global
    skill is only usable with those guides beside it, so they travel with SKILL.md.
    """
    skill = _skill_manifest_entry(manifest)
    if skill is None:
        return []
    guides = sorted(
        (
            entry
            for entry in manifest.get("files", [])
            if str(entry.get("path", "")).startswith(SKILL_GUIDES_SOURCE_PREFIX)
        ),
        key=lambda entry: entry["path"],
    )
    return [(SKILL_MANAGED_PATH, SKILL_MANAGED_PATH, skill)] + [
        (
            entry["path"],
            SKILL_GUIDES_TARGET_DIR
            + entry["path"][len(SKILL_GUIDES_SOURCE_PREFIX):],
            entry,
        )
        for entry in guides
    ] + [
        (entry["path"], entry["path"], entry)
        for entry in sorted(manifest.get("files", []), key=lambda entry: entry["path"])
        if entry["path"] in release_handoff.SKILL_ASSET_PATHS
    ]


def _skill_delivery_preflight(
    canonical: Path, release_root: Path | None, manifest: dict
) -> tuple[dict | None, list[str]]:
    """Resolve and preflight the separately installed active skill payload."""
    entries = _skill_delivery_entries(manifest)
    if not entries:
        return None, []
    if release_root is None:
        return None, ["managed canonical skill requires an explicit release root"]
    root = release_root.resolve()
    repo = _git_root(root)
    if repo is None or repo != root:
        return None, ["release root must be the owning git repository root"]
    status = _porcelain_status(repo)
    staged, dirty = status.staged, status.safety_paths
    errors: list[str] = []
    files: list[dict] = []
    for source_relative, target_relative_expected, entry in entries:
        source = canonical / source_relative
        target = root / target_relative_expected
        label = "skill" if source_relative == SKILL_MANAGED_PATH else "skill guide"
        if not source.is_file() or source.is_symlink():
            return None, [f"canonical {label} source is missing or unsafe: {source_relative}"]
        target_relative = _relative(repo, target)
        if target_relative != target_relative_expected:
            return None, [f"canonical {label} target path is not exact: {source_relative}"]
        if target_relative in dirty:
            errors.append(f"canonical {label} target is dirty or pre-staged: {target_relative}")
        expected_mode = 0o755 if entry.get("executable") else 0o644
        if stat.S_IMODE(source.stat().st_mode) != expected_mode:
            errors.append(f"canonical {label} source mode does not match manifest: {source_relative}")
        if release.sha256(source) != entry.get("sha256"):
            errors.append(f"canonical {label} source hash does not match manifest: {source_relative}")
        files.append(
            {
                "source": source,
                "target": target,
                "target_relative": target_relative,
                "sha256": entry.get("sha256"),
                "mode": expected_mode,
            }
        )
    head = files[0]
    return {
        "repo": repo,
        "source": head["source"],
        "target": head["target"],
        "target_relative": head["target_relative"],
        "sha256": head["sha256"],
        "mode": head["mode"],
        "files": files,
        "preexisting_staged": staged,
    }, errors


def _atomic_copy_skill(source: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nightshift-skill-", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_evidence(
    repo: Path,
    files: list[dict],
    preexisting_staged: set[str],
) -> tuple[dict | None, list[str]]:
    targets = {item["target_relative"] for item in files}
    staged = set(
        _run(["git", "diff", "--cached", "--name-only"], cwd=repo).stdout.splitlines()
    )
    staged_targets = staged & targets
    created_exact_commit = bool(staged_targets)
    if staged - targets != preexisting_staged:
        return None, ["canonical skill staging changed unrelated paths"]
    if created_exact_commit:
        commit = _run(
            [
                "git",
                "commit",
                "-m",
                "[SPEC-230] chore: deliver managed Nightshift skill",
                "--",
                *sorted(staged_targets),
            ],
            cwd=repo,
        )
        if commit.returncode:
            return None, [
                commit.stderr.strip() or commit.stdout.strip() or "skill commit failed"
            ]
        remaining = set(
            _run(
                ["git", "diff", "--cached", "--name-only"], cwd=repo
            ).stdout.splitlines()
        )
        if remaining != preexisting_staged:
            return None, ["canonical skill commit consumed unrelated staging"]
    sha = _run(
        ["git", "log", "-1", "--format=%H", "--", *sorted(targets)], cwd=repo
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None, ["canonical skill has no owning commit"]
    committed_paths = set(
        _run(
            ["git", "show", "--pretty=format:", "--name-only", sha], cwd=repo
        ).stdout.splitlines()
    )
    if created_exact_commit and committed_paths != staged_targets:
        return None, ["canonical skill commit evidence verification failed"]
    for item in files:
        relative = item["target_relative"]
        blob = _run(["git", "show", f"HEAD:{relative}"], cwd=repo)
        tree = _run(["git", "ls-tree", "HEAD", "--", relative], cwd=repo)
        expected_git_mode = "100755" if item["mode"] == 0o755 else "100644"
        if (
            blob.returncode
            or hashlib.sha256(blob.stdout.encode()).hexdigest() != item["sha256"]
            or tree.returncode
            or not tree.stdout.startswith(expected_git_mode + " ")
        ):
            return None, ["canonical skill commit evidence verification failed"]
    return {
        "sha": sha,
        "paths": sorted(committed_paths),
        "verified": True,
        "unrelated_staging_preserved": True,
        "mode": "100755" if files[0]["mode"] == 0o755 else "100644",
    }, []


def _deliver_skill(plan: dict) -> tuple[dict | None, list[str]]:
    repo = plan["repo"]
    files = plan["files"]
    verification = {"bytes": True, "sha256": True, "mode": True}
    for item in files:
        _atomic_copy_skill(item["source"], item["target"], item["mode"])
        verification["bytes"] &= item["target"].read_bytes() == item["source"].read_bytes()
        verification["sha256"] &= release.sha256(item["target"]) == item["sha256"]
        verification["mode"] &= (
            stat.S_IMODE(item["target"].stat().st_mode) == item["mode"]
        )
    if not all(verification.values()):
        return None, ["canonical skill target verification failed"]
    add = _run(
        ["git", "add", "-f", "--", *(item["target_relative"] for item in files)],
        cwd=repo,
    )
    if add.returncode:
        return None, [add.stderr.strip() or "canonical skill git add failed"]
    commit, errors = _commit_evidence(repo, files, plan["preexisting_staged"])
    if errors:
        return None, errors
    return {
        "status": "verified",
        "source_relative_path": SKILL_MANAGED_PATH,
        "target_relative_path": plan["target_relative"],
        "sha256": plan["sha256"],
        "mode": f"{plan['mode']:04o}",
        "allowlist": [item["target_relative"] for item in files],
        "verification": verification,
        "commit_evidence": commit,
    }, []


# SPEC-NS-KIT-123: installed-profile validation of the fleet, in process.
# The invariants a release itself rewrites (marker, payload bytes, and the
# project-owned kit_version) fail on every pre-sync install by construction, so
# they are classed apart from failures the release cannot clear.
FIXED_BY_RELEASE_INVARIANTS = frozenset({"KIT.MARKER", "KIT.PAYLOAD", "CFG.PARSE_VERSION"})


def _validate_install_entry(install: Path) -> dict:
    """Validate one install with the in-process validator; never write into it.

    ``validate_install.main`` also writes an artifact and receipt into the
    install, so only ``run_validation`` + ``build_artifact`` are used. Any
    failure, including a failed import, is recorded as INDETERMINATE.
    """
    started = time.monotonic()
    entry: dict = {"install": str(install), "verdict": "INDETERMINATE"}
    try:
        import validate_install

        ctx, _findings, _config, config_sha = validate_install.run_validation(
            install.parent, "installed", "coordinator", None
        )
        artifact = validate_install.build_artifact(ctx, config_sha)
        entry["verdict"] = str(artifact["admission"]).upper()
        entry["config_findings"] = [{"key": finding.key, "status": finding.status, "code": finding.code,
            "owner": finding.owner,
            "action": "Correct project-owned YAML parse error and revalidate." if finding.code == "NS-CFG-PARSE" else finding.action}
            for finding in (_findings or []) if isinstance(finding, validate_install.ConfigFinding)
            and finding.status in {"error", "unknown", "warning"}]
        entry["failed_invariants"] = [
            {
                "id": item["id"],
                "classification": (
                    "fixed_by_release"
                    if item["id"] in FIXED_BY_RELEASE_INVARIANTS
                    else "pre_existing"
                ),
                "status": item["status"],
                "remediation_code": item["remediation_code"],
                "codes": list(item.get("evidence") or []),
            }
            for item in artifact["invariants"]
            if item["status"] in ("fail", "unknown")
        ]
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - R4: record, keep going
        entry["exception"] = exc.__class__.__name__
        entry["failed_invariants"] = []
    entry["duration_s"] = round(time.monotonic() - started, 3)
    return entry


def _fleet_suite_setup_entry(install: Path, manifest: dict) -> dict:
    """Observe the declared launch prerequisite before copies; never run a suite.

    Delivery and installed admission retain their existing outcome semantics.
    This observation uses the target canonical checker against current project
    command/config/script bytes, so it is not a post-upgrade suite prediction.
    """
    import preflight
    entry = {'install': str(install), 'observation_phase': 'pre_apply',
             'checker_fingerprint': manifest['fingerprint'], 'schema_version': 1,
             'is_suite_sample': False, 'launch_allowed': False,
             'status': 'unavailable', 'reason_codes': [],
             'binding_sha256': None, 'proof_sha256': None}
    try:
        raw = (install / 'config.yaml').read_bytes()
        config = config_migrations.merge_config_documents(
            config_migrations.load_config_documents(raw.decode()))
        commands = config.get('commands', {})
        if not isinstance(commands, dict):
            raise ValueError('commands must be a mapping')
        command = commands.get('test')
        if not isinstance(command, str) or not command.strip():
            exemption = commands.get('test_not_applicable')
            if isinstance(exemption, str) and exemption.strip():
                entry.update(status='not_applicable', reason_codes=['test_not_applicable'])
            else:
                entry['reason_codes'] = ['test_command_unavailable']
            return entry
        revision = _run(['git', 'rev-parse', 'HEAD'], cwd=install.parent)
        arm_revision = revision.stdout.strip() if revision.returncode == 0 else 'unavailable'
        with tempfile.TemporaryDirectory(prefix='nightshift-release-setup-') as output:
            record = preflight.suite_environment_preflight(shlex.split(command),
                arm_root=install.parent, arm_revision=arm_revision,
                config_identity=hashlib.sha256(raw).hexdigest(), output_root=Path(output), timeout_s=5)
        entry.update(preflight.suite_environment_public(record))
    except (Exception, SystemExit):
        entry.update(status='unavailable', launch_allowed=False,
                     reason_codes=['setup_observation_unavailable'])
    return entry


def fleet_validation_table(entries: list[dict]) -> str:
    """Render fleet validation entries as the operator-facing table."""
    if not entries:
        return "fleet validation: no installs"
    lines = ["fleet validation (installed profile)", "verdict         seconds  install"]
    for entry in entries:
        lines.append(
            f"{entry['verdict']:<15} {entry['duration_s']:>7.3f}  {entry['install']}"
        )
        if entry.get("exception"):
            lines.append(f"    validator error: {entry['exception']}")
        for item in entry["failed_invariants"]:
            codes = ",".join(item.get("codes") or []) or item.get("remediation_code", "")
            lines.append(f"    {item['id']}  {item['classification']}  {codes}")
    return "\n".join(lines)


def _record_cheap_preflight(result: dict, canonical: Path, manifest: dict) -> list[str]:
    """SPEC-NS-KIT-124: the seconds-long floor and last-run headroom checks.

    Records both outcomes in ``result`` and returns the failure messages. The
    floor skip (no baseline declared) is BUG-334 R3's; the headroom reads the
    last recorded healthy suite run, so it can run before the suite.
    """
    failures = release.source_cut_errors(canonical, manifest, require_finalized=not result.get('dry_run', False))
    result['source_cut'] = release.source_cut_metadata(canonical)
    if failures:
        result['remaining_cheap_checks'] = 'not_run_after_source_cut_refusal'
        return failures
    from preflight import release_invariant_preflight
    invariants = release_invariant_preflight(canonical, manifest, previous=result.get("release_invariants"))
    result["release_invariants"] = invariants
    failures.extend(f"{item['rule']}: {item['path']}: {item['detail']}" for item in invariants["findings"])
    if failures:
        result["remaining_cheap_checks"] = "not_run_after_release_invariant_refusal"
        return failures
    family_errors, skipped = release.finding_floor_check(canonical, manifest)
    result["finding_family_regression_healthy"] = not family_errors
    if skipped:
        result["finding_family_regression_skipped"] = skipped
    if family_errors:
        result["finding_family_regression_errors"] = family_errors
        failures.extend(family_errors)
    healthy, reason = check_canonical_suite_headroom(canonical)
    result["canonical_suite_headroom_healthy"] = healthy
    result["canonical_suite_headroom_reason"] = reason
    if not healthy:
        failures.append(reason)
    warning = canonical_suite_growth_warning(canonical)
    if warning:
        result["canonical_suite_growth_warning"] = warning
        print(warning, file=sys.stderr)
    return failures


def _uncommitted_handoff_files(canonical: Path, spec_ids: list[str]) -> list[str]:
    """BUG-NS-KIT-127 R4: handoff files this run changed that git does not show clean."""
    names = sorted({f"{release_handoff.HANDOFF_DIR}/{spec_id}.json" for spec_id in spec_ids})
    if not names:
        return []
    try:
        done = subprocess.run(
            ["git", "-C", str(canonical), "status", "--porcelain", "--", *names],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return names
    if done.returncode != 0:
        return names
    dirty = {line[3:].strip().strip('"') for line in done.stdout.splitlines() if len(line) > 3}
    return [name for name in names if any(item.endswith(name) for item in dirty)]


def _repository_refusal(
    plan: RepositoryPlan, manifest: dict, *, include_opt_out: bool = False
) -> tuple[dict, bool] | None:
    """The skip entry the dry-run gives ``plan`` before any migration, or None.

    Shared by ``coordinate_release`` and the SPEC-NS-KIT-128 checkpoint plan so
    the two cannot disagree. The bool is True when the entry is also a conflict.
    """
    base = {
        "repository": str(plan.root),
        "installs": [str(item) for item in plan.installs],
    }
    policy_errors = _release_policy_errors(plan)
    if policy_errors:
        return {
            **base,
            "classification": "release_policy_conflict",
            "reason": "; ".join(policy_errors),
        }, True
    if plan.committed_kit_policy == "opt_out" and not include_opt_out:
        return {
            **base,
            "classification": "committed_kit_opt_out",
            "reason": "project release policy opts out of committed managed-kit payloads",
            "policy_sources": list(plan.policy_sources),
        }, False
    migration_skips = [
        disposition
        for install in plan.installs
        if (disposition := release_disposition(install)) is not None
    ]
    if migration_skips:
        return {
            **base,
            "classification": "tracked_private_artifacts_unresolved",
            "reason": migration_skips[0]["reason"],
            "migration_reference": migration_skips[0]["migration_reference"],
        }, False
    preflight_errors = preflight_repository(plan, manifest)
    if preflight_errors:
        return {
            **base,
            "classification": "known_project_local",
            "reason": "; ".join(preflight_errors),
        }, True
    return None


def checkpoint_plan(
    installs: Iterable[Path], manifest: dict, *, include_opt_out: bool = False
) -> dict:
    """SPEC-NS-KIT-128: read-only pre-release checkpoint plan per repository.

    Lists the dirty paths a checkpoint commit may take and the excluded ones
    with a reason, plus the classification the dry-run gives the repository.
    Writes nothing: git runs with optional locks off and no file is created.
    """
    previous = os.environ.get("GIT_OPTIONAL_LOCKS")
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        plans, initial_skips = plan_repositories(installs, manifest)
        repositories = []
        for plan in plans:
            status = _porcelain_status(plan.root)
            dirty = status.dirty
            commit: list[str] = []
            excluded: list[dict] = []
            for path in sorted(dirty):
                reason = next((reason for identity in [path, *sorted(status.associations.get(path, set()))]
                               if (reason := _checkpoint_exclusion_reason(plan, identity)) is not None), None)
                if reason is None:
                    commit.append(path)
                else:
                    excluded.append({"path": path, "reason": reason})
            refusal = _repository_refusal(
                plan, manifest, include_opt_out=include_opt_out
            )
            repositories.append(
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                    "dirty_path_count": len(dirty),
                    "commit_paths": commit,
                    "excluded_paths": excluded,
                    "dry_run_classification": (
                        "eligible" if refusal is None else refusal[0]["classification"]
                    ),
                    "dry_run_reason": None if refusal is None else refusal[0]["reason"],
                }
            )
    finally:
        if previous is None:
            os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        else:
            os.environ["GIT_OPTIONAL_LOCKS"] = previous
    return {
        "mode": "checkpoint-plan",
        "release_version": manifest["kit_version"],
        "repositories": repositories,
        "skipped_installs": initial_skips,
    }



def _readiness_installs(entry: dict) -> list[str]:
    values = entry.get('installs', [])
    return ([entry['install']] if isinstance(entry.get('install'), str) else []) + [
        value for value in values if isinstance(value, str)]


def _readiness_codes(observation: dict) -> set[str]:
    return ({str(code) for item in observation.get('failed_invariants', []) for code in item.get('codes', [])}
            | {str(item['remediation_code']) for item in observation.get('failed_invariants', []) if item.get('remediation_code')}
            | {str(item['code']) for item in observation.get('config_findings', []) if item.get('code')})


def _readiness_failure_identity(observation: dict) -> set[tuple]:
    # Shared codes alone cannot establish that the same invariant or finding failed.
    return ({('invariant', item.get('id'), item.get('status'), item.get('remediation_code'), tuple(sorted(item.get('codes', []))))
             for item in observation.get('failed_invariants', [])}
            | {('finding', item.get('key'), item.get('status'), item.get('code'))
               for item in observation.get('config_findings', [])})


def build_readiness_summary(result: dict) -> dict:
    """Pure evidence projection: no discovery, validation, mutation or recovery execution."""
    seed = result.get('readiness_summary') or {}
    associations = {row['install']: row.get('repository') for row in seed.get('rows', [])}
    for group in ('skipped', 'untouched', 'fleet_validation', 'post_sync_validation'):
        for entry in result.get(group, []):
            for install in _readiness_installs(entry):
                associations.setdefault(install, entry.get('repository'))
    for install in result.get('verified_installs', []):
        associations.setdefault(install, None)
    version, fingerprint = result.get('release_version'), result.get('release_fingerprint')
    exact = (isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)
             and isinstance(fingerprint, str) and re.fullmatch(r'[0-9a-f]{64}', fingerprint))
    target = {'kit_version': version, 'fingerprint': fingerprint, 'identity_status': 'recorded' if exact else 'unknown'}
    skipped = {install: entry for entry in result.get('skipped', []) for install in _readiness_installs(entry)}
    untouched = {install for entry in result.get('untouched', []) for install in _readiness_installs(entry)}
    verified = set(result.get('verified_installs', []))
    pre = {entry['install']: entry for entry in result.get('fleet_validation', [])}
    post = {entry['install']: entry for entry in result.get('post_sync_validation', [])}
    dry = result.get('dry_run') is True
    rows = []
    for install, repository in sorted(associations.items()):
        disposition = skipped.get(install)
        delivery = ('skipped' if disposition else 'untouched' if dry or install in untouched
                    else 'delivered' if install in verified else 'interrupted_unknown')
        observation = (pre if dry else post).get(install)
        phase = ('pre_apply' if dry else 'post_apply') if observation is not None else 'not_observed'
        admission = 'not_observed' if observation is None else str(observation.get('verdict', 'INDETERMINATE')).lower()
        if admission not in {'allow', 'deny', 'indeterminate', 'not_observed'}:
            admission = 'indeterminate'
        invariants = copy.deepcopy((observation or {}).get('failed_invariants') or [])
        findings = copy.deepcopy((observation or {}).get('config_findings') or [])
        codes = sorted(_readiness_codes(observation or {}))
        if disposition and disposition.get('classification'):
            codes.append(str(disposition['classification']))
        failures = _readiness_failure_identity(observation or {})
        prior_failures = _readiness_failure_identity(pre.get(install, {}))
        origin = ('not_observed' if admission == 'not_observed' else 'no_failure_observed' if admission == 'allow'
                  else 'pre_apply_observed' if dry else 'pre_existing_observed' if admission == 'deny' and failures and failures <= prior_failures
                  else 'post_apply_cause_unknown')
        repair = 'requires_finding_review' if any(item.get('id') == 'CFG.PARSE_VERSION' for item in invariants) else 'no_readiness_prediction'
        condition = (disposition or {}).get('reason') or ', '.join(codes) or (observation or {}).get('exception') or (
            'admission was not observed' if admission == 'not_observed' else 'admission ' + admission)
        if not exact:
            action = 'inspect'
        elif delivery == 'skipped':
            reason = str(condition).lower()
            action = ('resolve_repository_then_retry_exact_release' if any(word in reason for word in ('dirty', 'pre-staged', 'unresolved git', 'project-owned release paths require separate configuration migration'))
                      else 'correct_project_config_then_revalidate' if any(word in reason for word in ('config', 'schema', 'migration'))
                      else 'inspect_release_policy_or_skip_condition')
        elif dry:
            action = 'review_pre_apply_observation'
        elif delivery in {'untouched', 'interrupted_unknown'}:
            action = 'inspect_then_retry_exact_release'
        elif admission == 'deny' and (findings or any(item.get('id', '').startswith('CFG.') for item in invariants)):
            action = 'correct_project_config_then_revalidate'
        elif admission != 'allow':
            action = 'inspect_admission_evidence'
        else:
            action = 'none'
        rows.append({'install': install, 'repository': repository, 'delivery': delivery, 'admission': admission,
            'observation_phase': phase, 'reason_codes': codes, 'failed_invariants': invariants, 'config_findings': findings,
            'validator_exception': (observation or {}).get('exception'), 'failure_origin': origin,
            'release_repair_expectation': repair, 'delivery_reason': (disposition or {}).get('reason'),
            'recovery': {'target': target, 'unmet_condition': str(condition)[:1200] if action != 'none' else None,
                'next_action': action, 'authorizes_mutation': False,
                'retry_boundary': 'Inspect repository state and confirm canonical version/fingerprint match the recorded target before using the existing coordinator apply path.' if 'retry' in action else None}})
    by_phase = {phase: {verdict: sum(row['observation_phase'] == phase and row['admission'] == verdict for row in rows)
                       for verdict in ('allow', 'deny', 'indeterminate')} for phase in ('pre_apply', 'post_apply')}
    counts = {state: sum(row['delivery'] == state for row in rows) for state in ('delivered', 'skipped', 'untouched', 'interrupted_unknown')}
    counts.update(discovered=len(rows), admitted_after_apply=by_phase['post_apply']['allow'],
                  not_observed=sum(row['admission'] == 'not_observed' for row in rows))
    repositories = {row['repository'] for row in rows if row['repository'] is not None}
    grouped = {repo: [row for row in rows if row['repository'] == repo] for repo in repositories}
    repository_counts = {'scope': 'distinct_known_repository_paths', 'discovered': len(repositories),
        'delivered': sum(any(row['delivery'] == 'delivered' for row in group) for group in grouped.values()),
        'fully_delivered': sum(all(row['delivery'] == 'delivered' for row in group) for group in grouped.values()),
        'admitted_after_apply': sum(all(row['observation_phase'] == 'post_apply' and row['admission'] == 'allow' for row in group) for group in grouped.values()),
        'unknown_repository_installs': sum(row['repository'] is None for row in rows)}
    return {'schema_version': '1.0.0', 'discovery_complete': seed.get('discovery_complete', False),
        'count_scope': 'unique_discovered_installs' if seed.get('discovery_complete') else 'reported_installs_discovery_unknown',
        'target': target, 'rows': rows, 'counts': counts, 'admission_by_phase': by_phase,
        'repository_counts': repository_counts, 'informational_only': True}


def readiness_table(summary: dict) -> str:
    counts = summary['counts']
    lines = ['delivery/readiness summary (informational only)',
        f"install scope={summary['count_scope']}: discovered={counts['discovered']} delivered={counts['delivered']} skipped={counts['skipped']} untouched={counts['untouched']} interrupted_unknown={counts['interrupted_unknown']}"]
    for phase in ('pre_apply', 'post_apply'):
        item = summary['admission_by_phase'][phase]
        lines.append(f"admission {phase}: allow={item['allow']} deny={item['deny']} indeterminate={item['indeterminate']}")
    lines.append(f"admitted_after_apply={counts['admitted_after_apply']} not_observed={counts['not_observed']}; pre_apply is not a prediction of post-upgrade readiness")
    repos = summary['repository_counts']
    lines.append(f"repository scope={repos['scope']}: discovered={repos['discovered']} delivered={repos['delivered']} fully_delivered={repos['fully_delivered']} admitted_after_apply={repos['admitted_after_apply']} unknown_repository_installs={repos['unknown_repository_installs']}")
    for row in summary['rows']:
        lines.append(f"  {row['install']}: delivery={row['delivery']} admission={row['admission']} phase={row['observation_phase']} origin={row['failure_origin']}; next={row['recovery']['next_action']}")
        if row['release_repair_expectation'] == 'requires_finding_review':
            lines.append('    CFG.PARSE_VERSION is an aggregate classification; review findings, not an automatic repair guarantee.')
        for finding in row['config_findings']:
            lines.append(f"    {finding.get('key')}: {finding.get('code')} — {finding.get('action', '')}")
    return '\n'.join(lines)

def _set_outcome(result: dict) -> None:
    """BUG-NS-KIT-131: one exit mapping. 0 completed, 3 skips only, 1 failed (2 is main's invalid manifest)."""
    if result["failure_class"] or result["unexpected_failure"]:
        result["outcome"], result["exit_code"] = "failed", 1
    elif result["skipped"]:
        result["outcome"], result["exit_code"] = "completed_with_skips", 3
    else:
        result["outcome"], result["exit_code"] = "completed", 0
    if "readiness_summary" in result:
        result["readiness_summary"] = build_readiness_summary(result)


def coordinate_release(
    canonical: Path,
    installs: Iterable[Path],
    manifest: dict,
    *,
    dry_run: bool,
    migration_runner: MigrationRunner | None = None,
    canonical_suite_runner: SuiteRunner | None = None,
    inject_unexpected_after_commits: int | None = None,
    smoke_timeout_s: int = 60,
    include_opt_out: bool = False,
    release_root: Path | None = None,
    refresh_commit_msg_hooks: str = "auto",
) -> dict:
    """Coordinate one exact release with known-failure isolation and stop semantics."""
    started = time.monotonic()
    plans, initial_skips = plan_repositories(installs, manifest)
    skill_plan, skill_preflight_errors = _skill_delivery_preflight(
        canonical, release_root, manifest
    )
    result = {
        "release_version": manifest["kit_version"],
        "release_fingerprint": manifest["fingerprint"],
        "dry_run": dry_run,
        "managed_payload_mode": "canonical_replace",
        "file_level_patch_attempted": False,
        "include_opt_out": include_opt_out,
        "planned_installs": sum(len(plan.installs) for plan in plans),
        "planned_repositories": len(plans),
        "eligible_installs": [],
        "verified_installs": [],
        "release_policies": {
            str(plan.root): {
                "committed_kit": plan.committed_kit_policy or "undeclared",
                "policy_sources": list(plan.policy_sources),
                "hook_policies": [
                    {"committed_kit": policy, "source": source}
                    for policy, source in plan.hook_policies
                ],
            }
            for plan in plans
        },
        "skipped": initial_skips,
        "untouched": [],
        "repository_commits": [],
        "migrations": [],
        "conflicts": [],
        "failure_class": None,
        "unexpected_failure": None,
        "rollback_attempted": False,
        "push_attempted": False,
        "canonical_suite_runs": 0,
        "canonical_suite_probe": "not_run",
        "canonical_suite_result": "not_run",
        "canonical_suite_duration_s": None,
        "canonical_suite_duration_record": None,
        "canonical_suite_reuse_decision": None,
        "smoke_checks_run": 0,
        "producer_session_evidence": {},
        "old_fingerprints": {},
        "post_commit_rebuild_time_s": None,
        "release_handoffs_repinned": [],
        "release_handoffs_completed": [],
        "release_handoffs_not_completed": [],
        "release_handoffs_uncommitted": [],
        "config_kit_version_updates": [],
        "hooks_wired": [],
        "commit_msg_refresh_mode": refresh_commit_msg_hooks,
        "commit_msg_hooks": [],
        "registry_untracks": [],
        "fleet_validation": [],
        "post_sync_validation": [],
        "skill_delivery": (
            {
                "status": "planned" if skill_plan else "not_required",
                "source_relative_path": SKILL_MANAGED_PATH,
                "target_relative_path": SKILL_MANAGED_PATH,
                "sha256": skill_plan["sha256"] if skill_plan else None,
                "mode": f"{skill_plan['mode']:04o}" if skill_plan else None,
                "allowlist": (
                    [item["target_relative"] for item in skill_plan["files"]]
                    if skill_plan
                    else []
                ),
                "verification": {"bytes": False, "sha256": False, "mode": False},
                "commit_evidence": None,
            }
        ),
        "rerun_command": (
            f"python3 {canonical / 'release_coordinator.py'}"
            f" --root {canonical.parents[2]} --apply"
        ),
    }

    # Report forks even when policy, dirty state or preflight later prevents a
    # rollout. These are read-only observations, independent of refresh mode.
    fork_repositories = set()
    for plan in plans:
        finding = project_owned_commit_msg(plan.root, canonical / "hooks" / "commit-msg", plan.installs[0])
        if finding:
            result["commit_msg_hooks"].append({"repository": str(plan.root), "commit_msg_hook": "project_owned", **finding})
            fork_repositories.add(plan.root)

    result["readiness_summary"] = {"discovery_complete": True, "rows": [
        {"install": str(install), "repository": str(plan.root)} for plan in plans for install in plan.installs
    ] + [{"install": entry["install"], "repository": entry.get("repository")} for entry in initial_skips]}

    for plan in plans:
        for install in plan.installs:
            marker = install / release.MARKER
            try:
                old = json.loads(marker.read_text()).get("fingerprint")
            except (FileNotFoundError, json.JSONDecodeError):
                old = None
            result["old_fingerprints"][str(install)] = old

    # BUG-NS-KIT-212: setup observations cover every discovered target before copies.
    targets = dict.fromkeys(row['install'] for row in result['readiness_summary']['rows'])
    result['suite_environment_setup'] = [_fleet_suite_setup_entry(Path(name), manifest) for name in targets]

    if dry_run:
        # SPEC-NS-KIT-123 R1/R2: every discovered install, read-only,
        # reported even when a later preflight stops the run.
        result["fleet_validation"] = [
            _validate_install_entry(install)
            for plan in plans
            for install in plan.installs
        ]

    # R1: reported, never a stop, in the dry-run; R2 enforces it in the apply.
    cheap_failures = _record_cheap_preflight(result, canonical, manifest)

    ownership_errors = validate_release_ownership(plans, manifest)
    ownership_errors.extend(skill_preflight_errors)
    if ownership_errors:
        result["failure_class"] = "canonical_preflight"
        result["unexpected_failure"] = "; ".join(ownership_errors)
        result["untouched"] = [
            {
                "repository": str(plan.root),
                "installs": [str(item) for item in plan.installs],
            }
            for plan in plans
        ]
        result["duration_s"] = round(time.monotonic() - started, 3)
        result["completed_at"] = datetime.now(UTC).isoformat()
        _set_outcome(result)
        return result

    if not dry_run:
        if cheap_failures:
            result["failure_class"] = "canonical_preflight"
            result["unexpected_failure"] = "; ".join(cheap_failures)
            result["untouched"] = [
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                }
                for plan in plans
            ]
            result["duration_s"] = round(time.monotonic() - started, 3)
            result["completed_at"] = datetime.now(UTC).isoformat()
            _set_outcome(result)
            return result
        preparation_runner = canonical_suite_runner or (
            lambda argv, cwd: _run_canonical_suite(argv, cwd)
        )
        preparation, preparation_errors = _release_preparation(
            canonical, manifest, preparation_runner
        )
        result["release_preparation"] = preparation
        if preparation_errors:
            result["failure_class"] = "canonical_preflight"
            result["unexpected_failure"] = "; ".join(preparation_errors)
            result["untouched"] = [
                {"repository": str(plan.root), "installs": [str(item) for item in plan.installs]}
                for plan in plans
            ]
            result["duration_s"] = round(time.monotonic() - started, 3)
            result["completed_at"] = datetime.now(UTC).isoformat()
            _set_outcome(result)
            return result
        try:
            probe_argv = _suite_argv(manifest["canonical_suite"], "probe")
            suite_argv = _suite_argv(manifest["canonical_suite"], "command")
        except (KeyError, ValueError) as exc:
            probe_result = subprocess.CompletedProcess([], 2, "", str(exc))
            suite_argv = []
        else:
            suite_junit_xml = _canonical_suite_junit_pending_path(canonical)
            runner = canonical_suite_runner or (
                lambda argv, cwd: _run_canonical_suite(
                    argv, cwd, junit_xml=suite_junit_xml
                )
            )
            probe_result = _run_canonical_suite_step(runner, probe_argv, canonical)
        result["canonical_suite_probe"] = (
            "passed" if probe_result.returncode == 0 else "failed"
        )
        if probe_result.returncode:
            result["failure_class"] = "canonical_preflight"
            result["unexpected_failure"] = (
                probe_result.stdout + "\n" + probe_result.stderr
            ).strip()[-2000:]
            result["untouched"] = [
                {
                    "repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                }
                for plan in plans
            ]
            result["duration_s"] = round(time.monotonic() - started, 3)
            result["completed_at"] = datetime.now(UTC).isoformat()
            _set_outcome(result)
            return result
        reuse = evaluate_suite_reuse(canonical)
        result["canonical_suite_reuse_decision"] = reuse["reason"]
        if reuse["reusable"] and reuse.get("outcome") == "repair-composed":
            result["canonical_suite_result"] = "repair-composed"
            result["canonical_suite_composition"] = reuse["composition"]
        elif reuse["reusable"]:
            subset_argv = _suite_argv(
                {
                    **manifest["canonical_suite"],
                    "subset": [
                        *manifest["canonical_suite"]["command"][:-1],
                        *RELEASE_MECHANICAL_TESTS,
                    ],
                },
                "subset",
            )
            subset_runner = canonical_suite_runner or (
                lambda argv, cwd: _run_canonical_suite(argv, cwd)
            )
            subset_result = _run_canonical_suite_step(subset_runner, subset_argv, canonical)
            subset_passed = subset_result.returncode == 0
            result["canonical_suite_reused_from"] = {
                "record": reuse["record"],
                "commit": reuse["commit"],
            }
            result["canonical_suite_reused_changed_paths"] = reuse["changed_paths"]
            result["canonical_suite_subset_result"] = "passed" if subset_passed else "failed"
            result["canonical_suite_result"] = "reused" if subset_passed else "failed"
            if not subset_passed:
                result["failure_class"] = "canonical_preflight"
                result["unexpected_failure"] = (
                    subset_result.stdout + "\n" + subset_result.stderr
                ).strip()[-2000:]
                result["untouched"] = [
                    {
                        "repository": str(plan.root),
                        "installs": [str(item) for item in plan.installs],
                    }
                    for plan in plans
                ]
                result["duration_s"] = round(time.monotonic() - started, 3)
                result["completed_at"] = datetime.now(UTC).isoformat()
                _set_outcome(result)
                return result
        else:
            start_commit, start_clean = _canonical_tree_state(canonical)
            suite_started = time.monotonic()
            suite_result = _run_canonical_suite_step(runner, suite_argv, canonical)
            suite_duration_s = time.monotonic() - suite_started
            suite_passed = suite_result.returncode == 0
            end_commit, end_clean = _canonical_tree_state(canonical)
            result["canonical_suite_duration_s"] = round(suite_duration_s, 3)
            result["canonical_suite_duration_record"] = str(
                _record_canonical_suite_duration(
                    canonical,
                    suite_duration_s,
                    suite_passed=suite_passed,
                    junit_xml=suite_junit_xml,
                    commit=start_commit,
                    tree_clean_start=start_clean,
                    tree_clean_end=end_clean and end_commit == start_commit,
                    phase="release_apply",
                )
            )
            result["canonical_suite_runs"] = 1
            result["canonical_suite_result"] = "passed" if suite_passed else "failed"
            if suite_result.returncode:
                result["failure_class"] = "canonical_preflight"
                result["unexpected_failure"] = (
                    suite_result.stdout + "\n" + suite_result.stderr
                ).strip()[-2000:]
                result["untouched"] = [
                    {
                        "repository": str(plan.root),
                        "installs": [str(item) for item in plan.installs],
                    }
                    for plan in plans
                ]
                result["duration_s"] = round(time.monotonic() - started, 3)
                result["completed_at"] = datetime.now(UTC).isoformat()
                _set_outcome(result)
                return result

            headroom_healthy, headroom_reason = check_canonical_suite_headroom(canonical)
            result["canonical_suite_headroom_healthy"] = headroom_healthy
            result["canonical_suite_headroom_reason"] = headroom_reason
            if not headroom_healthy:
                result["failure_class"] = "canonical_preflight"
                result["unexpected_failure"] = headroom_reason
                result["untouched"] = [
                    {
                        "repository": str(plan.root),
                        "installs": [str(item) for item in plan.installs],
                    }
                    for plan in plans
                ]
                result["duration_s"] = round(time.monotonic() - started, 3)
                result["completed_at"] = datetime.now(UTC).isoformat()
                _set_outcome(result)
                return result

    committed_repositories = 0
    for plan_index, plan in enumerate(plans):
        if (
            inject_unexpected_after_commits is not None
            and committed_repositories >= inject_unexpected_after_commits
        ):
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "injected unexpected coordinator failure"
            for later in plans[plan_index:]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break

        refusal = _repository_refusal(
            plan, manifest, include_opt_out=include_opt_out
        )
        if refusal is not None:
            entry, is_conflict = refusal
            result["skipped"].append(entry)
            if is_conflict:
                result["conflicts"].append(entry)
            continue

        migrations: list[tuple[Path, MigrationRequest, MigrationResult]] = []
        migration_failed = False
        for sequence, install in enumerate(plan.installs, start=1):
            request = None
            try:
                source_text = (install / "config.yaml").read_text()
                config_migrations.validate_config_structure(source_text)
                config_migrations.set_kit_version(source_text, manifest["kit_version"])
                if not _migration_needed(install, manifest["schema_version"]):
                    continue
                request = build_migration_request(install, manifest, sequence)
                if migration_runner is None:
                    errors = ["registered config migration requires a fresh migration worker"]
                else:
                    worker_result = migration_runner(request)
                    errors = validate_migration_result(request, worker_result)
                    if not errors:
                        migrations.append((install, request, worker_result))
            except (ValueError, OSError) as exc:
                errors = [f"migration configuration refused: {exc}"]
            result["migrations"].append(
                {
                    "request": asdict(request) if request is not None else {"install": str(install)},
                    "verified": not errors,
                    "errors": errors,
                }
            )
            if errors:
                result["skipped"].append(
                    {
                        "repository": str(plan.root),
                        "installs": [str(item) for item in plan.installs],
                        "classification": "known_project_local",
                        "reason": "; ".join(errors),
                    }
                )
                migration_failed = True
                break
        if migration_failed:
            continue

        # Workers for later installs may outlive an earlier candidate's source snapshot.
        # Revalidate the entire batch at the repository's first-write boundary.
        for install, request, worker_result in migrations:
            errors = validate_migration_result(request, worker_result)
            if errors:
                result["migrations"].append({"request": asdict(request), "verified": False,
                    "errors": errors, "phase": "pre_apply_validation"})
                result["skipped"].append({"repository": str(plan.root),
                    "installs": [str(item) for item in plan.installs],
                    "classification": "known_project_local", "reason": "; ".join(errors)})
                migration_failed = True
                break
        if migration_failed:
            continue

        result["registry_untracks"].extend(
            {"repository": str(plan.root), "path": path}
            for path in sorted(plan.untrack_paths)
        )
        if dry_run:
            result["eligible_installs"].extend(str(item) for item in plan.installs)
            for install in plan.installs:
                planned = reconcile_kit_version(install, manifest, dry_run=True)
                if planned:
                    result["config_kit_version_updates"].append(planned)
                hook = wire_pre_commit_hook(install, dry_run=True)
                if hook:
                    result["hooks_wired"].append(hook)
            refreshed = None if plan.root in fork_repositories else plan_commit_msg_refresh(
                plan,
                canonical / "hooks" / "commit-msg",
                mode=refresh_commit_msg_hooks,
                dry_run=True,
            )
            if refreshed:
                result["commit_msg_hooks"].append(refreshed)
            continue

        repository_errors = []
        for install in plan.installs:
            ok, details = release.apply_install(canonical, install, manifest)
            if not ok:
                repository_errors.extend(f"{install}: {detail}" for detail in details)
                break
            for migrated_install, request, worker_result in migrations:
                if migrated_install == install:
                    _apply_migration_result(install, worker_result)
            # BUG-326: the project-owned kit_version and the documented
            # pre-commit wiring are part of "on this release", not extras.
            updated = reconcile_kit_version(install, manifest, dry_run=False)
            if updated:
                result["config_kit_version_updates"].append(updated)
            hook = wire_pre_commit_hook(install, dry_run=False)
            if hook:
                result["hooks_wired"].append(hook)
            smoke_errors = _run_declared_checks(
                install,
                manifest["smoke_checks"],
                timeout_s=smoke_timeout_s,
            )
            result["smoke_checks_run"] += len(manifest["smoke_checks"])
            repository_errors.extend(smoke_errors)
            if smoke_errors:
                break
        if repository_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(repository_errors)
            for later in plans[plan_index + 1 :]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break

        # SPEC-NS-KIT-143: refresh the wired commit-msg hook (replay-gated) so the
        # release commit below runs the new grammar; first install is the shared source.
        refreshed = None if plan.root in fork_repositories else plan_commit_msg_refresh(
            plan,
            next(
                (i / "hooks" / "commit-msg" for i in plan.installs if (i / "hooks" / "commit-msg").is_file()),
                plan.installs[0] / "hooks" / "commit-msg",
            ),
            mode=refresh_commit_msg_hooks,
            dry_run=False,
        )
        if refreshed:
            result["commit_msg_hooks"].append(refreshed)

        sha, commit_errors = _commit_repository(plan, manifest)
        if commit_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(commit_errors)
            for later in plans[plan_index + 1 :]:
                result["untouched"].append(
                    {
                        "repository": str(later.root),
                        "installs": [str(item) for item in later.installs],
                    }
                )
            break
        result["verified_installs"].extend(str(item) for item in plan.installs)
        # SPEC-NS-KIT-123 R3: recorded, never a stop or exit-code input.
        result["post_sync_validation"].extend(
            _validate_install_entry(install) for install in plan.installs
        )
        if sha:
            result["repository_commits"].append(
                {
                    "repository": str(plan.root),
                    "commit": sha,
                    "verified_installs": len(plan.installs),
                }
            )
            committed_repositories += 1

    producer = canonical / "reflexion_producer.py"
    if producer.is_file():
        result["producer_session_evidence"] = {
            "sha256": release.sha256(producer),
            "contains_producer_session_id": "_producer_session_id"
            in producer.read_text(),
            "verified_install_shas": {
                str(install): release.sha256(Path(install) / "reflexion_producer.py")
                for install in result["verified_installs"]
                if (Path(install) / "reflexion_producer.py").is_file()
            },
        }
    if not dry_run and result["unexpected_failure"] is None and skill_plan is not None:
        # Recheck after managed-install commits so a concurrent edit/stage race
        # cannot be overwritten by the external exact-path delivery.
        refreshed_plan, refreshed_errors = _skill_delivery_preflight(
            canonical, release_root, manifest
        )
        if refreshed_errors or refreshed_plan is None:
            skill_errors = refreshed_errors or ["canonical skill plan disappeared"]
            skill_delivery = None
        else:
            skill_delivery, skill_errors = _deliver_skill(refreshed_plan)
        if skill_errors:
            result["failure_class"] = "unexpected_mid_rollout"
            result["unexpected_failure"] = "; ".join(skill_errors)
            result["skill_delivery"] = {
                **result["skill_delivery"],
                "status": "failed",
            }
        else:
            result["skill_delivery"] = skill_delivery
    # A handoff scoped to eligible installs is complete after every eligible
    # repository verifies. Known local skips remain observable and keep the
    # coordinator exit non-zero, but do not invalidate deliveries already made.
    if (
        not dry_run
        and result["canonical_suite_probe"] == "passed"
        and (
            (
                result["canonical_suite_runs"] == 1
                and result["canonical_suite_result"] == "passed"
            )
            or (
                result["canonical_suite_runs"] == 0
                and result["canonical_suite_result"] == "reused"
                and result.get("canonical_suite_subset_result") == "passed"
            )
            or (
                result["canonical_suite_runs"] == 0
                and result["canonical_suite_result"] == "repair-composed"
                and not release_handoff.validate_record_repair_composition(canonical, result.get("canonical_suite_composition"))
            )
        )
        and result["managed_payload_mode"] == "canonical_replace"
        and result["file_level_patch_attempted"] is False
        and len(result["verified_installs"]) >= 1
        and result["unexpected_failure"] is None
        and result["rollback_attempted"] is False
        and result["push_attempted"] is False
    ):
        result["release_handoffs_repinned"] = release_handoff.repin_pending_handoffs(
            canonical, manifest
        )
        result["release_handoffs_repinned"].extend(
            release_handoff.repin_folded_handoffs(canonical, manifest)
        )
        result["release_handoffs_completed"] = (
            release_handoff.complete_pending_handoffs(canonical, manifest, result)
        )
        result["release_handoffs_not_completed"] = (
            release_handoff.pending_handoffs_not_completed(canonical, manifest, result)
        )
        result["release_handoffs_uncommitted"] = _uncommitted_handoff_files(
            canonical,
            [*result["release_handoffs_repinned"], *result["release_handoffs_completed"]],
        )
        # SPEC-334 R5: records skipped because their source spec is not
        # status: done -- observable in the same serialized result dict
        # write_metrics() persists, not just in-process return values.
        result["release_handoffs_blocked_by_spec_status"] = (
            release_handoff.pending_handoffs_blocked_by_spec_status(canonical, manifest)
        )
    result["duration_s"] = round(time.monotonic() - started, 3)
    result["completed_at"] = datetime.now(UTC).isoformat()
    _set_outcome(result)
    return result


def write_metrics(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def discover_installs(
    sync, root: Path, canonical: Path, *, isolated: bool
) -> tuple[list[Path], list[str]]:
    """BUG-NS-KIT-133: installs plus the roots scanned; ``isolated`` scans ``root`` alone.

    ``find_nightshift_dirs`` always appends ``EXTRA_SCAN_ROOTS`` (the real fleet), so
    ``--root`` alone never isolates a rehearsal. Isolation empties that list only for
    the duration of the scan.
    """
    extras = list(getattr(sync, "EXTRA_SCAN_ROOTS", []))
    if isolated:
        roots = [root]
        sync.EXTRA_SCAN_ROOTS = []
    else:
        roots = [root] + [r for r in extras if r.exists() and r != root]
    try:
        found = sync.find_nightshift_dirs(root)
    finally:
        if isolated:
            sync.EXTRA_SCAN_ROOTS = extras
    installs = [path for path in found if path.resolve() != canonical.resolve()]
    return installs, [str(r) for r in roots]


def rehearse_candidate(
    canonical: Path, manifest: dict, installs: Iterable[Path], *, release_root: Path,
    canonical_suite_runner: SuiteRunner, protected_inputs: Iterable[Path] = (),
    controlled_writer: Callable[[], None] | None = None,
) -> dict:
    """Apply one controlled candidate rehearsal only to installs below ``release_root``."""
    root = release_root.resolve()
    selected = [Path(install).resolve() for install in installs]
    outside = [str(install) for install in selected if not install.is_relative_to(root)]
    if outside:
        return {"status": "refused", "reason": "install outside rehearsal root", "outside": outside,
                "qualified": False}
    protected = [Path(path).resolve() for path in protected_inputs]
    outside_inputs = [str(path) for path in protected if not path.is_relative_to(root)]
    if outside_inputs:
        return {"status": "refused", "reason": "protected input outside rehearsal root",
                "outside": outside_inputs, "qualified": False}
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    if controlled_writer is not None:
        controlled_writer()
    changed = [path for path in protected if not path.is_file() or
               hashlib.sha256(path.read_bytes()).hexdigest() != before[str(path)]]
    if changed:
        return {"status": "refused", "reason": "rehearsal protected input changed after planning",
                "changed": [str(path) for path in changed], "qualified": False,
                "controlled_writer": controlled_writer is not None}
    result = coordinate_release(
        canonical, selected, manifest, dry_run=False, release_root=root,
        canonical_suite_runner=canonical_suite_runner,
    )
    return {"status": "passed" if result.get("failure_class") is None else "failed",
            "qualified": False, "controlled_suite_runner": True,
            "root": str(root), "installs": [str(path) for path in selected],
            "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Argo/discovery root")
    parser.add_argument(
        "--isolated-root",
        action="store_true",
        help="BUG-NS-KIT-133: discover installs under --root only, never the extra fleet scan roots (rehearsals, tests)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument(
        "--checkpoint-plan",
        action="store_true",
        help="SPEC-NS-KIT-128: read-only per-repository checkpoint commit list and dry-run classification",
    )
    mode.add_argument(
        "--record-suite-run",
        action="store_true",
        help="SPEC-NS-KIT-126: record a merge-phase suite duration; touches no install",
    )
    parser.add_argument("--duration-s", type=float, help="with --record-suite-run")
    outcome = parser.add_mutually_exclusive_group()
    outcome.add_argument("--passed", action="store_true", help="with --record-suite-run")
    outcome.add_argument("--failed", action="store_true", help="with --record-suite-run")
    parser.add_argument("--metrics-out", type=Path)
    parser.add_argument(
        "--migration-runner",
        choices=("worker", "reference"),
        default="worker",
        help=(
            "BUG-326: 'reference' applies release_coordinator.default_migration_runner "
            "-- the deterministic implementation every dispatched worker must reproduce "
            "byte-for-byte -- so a schema-behind install with no per-install "
            "customization is migrated in this guarded run. Default 'worker' keeps "
            "today's behaviour: a fresh migration worker is required."
        ),
    )
    parser.add_argument(
        "--include-opt-out",
        action="store_true",
        help="operator-authorized one-release override of committed_kit: opt_out",
    )
    parser.add_argument(
        "--refresh-commit-msg-hooks",
        choices=COMMIT_MSG_REFRESH_MODES,
        default="auto",
        help=(
            "SPEC-NS-KIT-143: auto (default) refreshes a recognised kit commit-msg hook unless "
            "a 30-day history replay finds commits the new hook would reject (then defers); "
            "force refreshes anyway; never skips the step"
        ),
    )
    mode.add_argument('--audit-instructions', action='store_true')
    mode.add_argument('--reconcile-instructions', action='store_true')
    parser.add_argument('--instruction-declaration', type=Path)
    parser.add_argument('--instruction-install', type=Path, action='append', default=[])
    parser.add_argument('--instruction-audit', type=Path)
    parser.add_argument('--instruction-approval', type=Path)
    args = parser.parse_args()
    if args.audit_instructions or args.reconcile_instructions:
        if args.root is None:
            parser.error('instruction audit needs --root <project>')
        try:
            if args.reconcile_instructions:
                if not all((args.instruction_declaration, args.instruction_audit, args.instruction_approval)):
                    parser.error('correction needs declaration, audit and exact approval JSON')
                result = reconcile_instruction_versions(
                    args.root, args.instruction_declaration, args.instruction_install,
                    json.loads(args.instruction_audit.read_text()), json.loads(args.instruction_approval.read_text()))
            else:
                result = audit_instruction_versions(args.root, args.instruction_declaration, args.instruction_install)
            if args.metrics_out:
                write_metrics(result, args.metrics_out)
            print(json.dumps(result, indent=2))
            return 2 if result.get('blocking') or result.get('status') == 'commit_refused' else 0
        except (ValueError, OSError) as exc:
            print(json.dumps({'status': 'refused', 'reason': str(exc)}))
            return 2


    if any((args.instruction_declaration, args.instruction_install, args.instruction_audit, args.instruction_approval)):
        parser.error('instruction options require --audit-instructions or --reconcile-instructions')
    canonical = Path(__file__).resolve().parent
    if args.record_suite_run:
        if args.duration_s is None or args.duration_s < 0 or not (args.passed or args.failed):
            parser.error("--record-suite-run needs --duration-s <seconds> and --passed or --failed")
        recorded = record_suite_run(canonical, args.duration_s, passed=args.passed)
        if recorded["warning"]:
            print(recorded["warning"], file=sys.stderr)
        print(json.dumps(recorded, indent=2))
        return 0
    if args.root is None or not (args.dry_run or args.apply or args.checkpoint_plan):
        parser.error("--root and one of --dry-run/--apply/--checkpoint-plan are required")
    sys.path.insert(0, str(canonical.parent))
    import importlib.util

    sync_path = canonical.parent / "nightshift-sync.py"
    spec = importlib.util.spec_from_file_location("nightshift_sync", sync_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load nightshift-sync.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)

    valid, errors, manifest = release.validate_manifest(
        canonical, sync.CANONICAL_PROTOCOL_FILES, require_finalized=args.apply
    )
    if not valid or manifest is None:
        print(json.dumps({"preflight": "failed", "errors": errors}, indent=2))
        return 2

    installs, scanned_roots = discover_installs(
        sync, args.root.resolve(), canonical, isolated=args.isolated_root
    )
    discovery = {"isolated": args.isolated_root, "roots": scanned_roots}
    if args.checkpoint_plan:
        plan = checkpoint_plan(
            installs, manifest, include_opt_out=args.include_opt_out
        )
        plan["discovery"] = discovery
        if args.metrics_out:
            write_metrics(plan, args.metrics_out)
        print(json.dumps(plan, indent=2))
        return 0
    result = coordinate_release(
        canonical,
        installs,
        manifest,
        dry_run=args.dry_run,
        migration_runner=(
            default_migration_runner if args.migration_runner == "reference" else None
        ),
        include_opt_out=args.include_opt_out,
        release_root=args.root.resolve(),
        refresh_commit_msg_hooks=args.refresh_commit_msg_hooks,
    )
    result["discovery"] = discovery
    result["rerun_command"] = (
        f"python3 {canonical / 'release_coordinator.py'}"
        f" --root {args.root.resolve()} --apply"
        + (" --isolated-root" if args.isolated_root else "")
        + (" --include-opt-out" if args.include_opt_out else "")
        + (" --migration-runner reference" if args.migration_runner == "reference" else "")
        + (
            f" --refresh-commit-msg-hooks {args.refresh_commit_msg_hooks}"
            if args.refresh_commit_msg_hooks != "auto"
            else ""
        )
    )
    output = args.metrics_out or canonical / "reports" / "_wip" / (
        f"release-{manifest['kit_version']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_metrics(result, output)
    if result["fleet_validation"]:
        # stderr keeps stdout a single JSON document for existing consumers.
        print(fleet_validation_table(result["fleet_validation"]), file=sys.stderr)
    print(readiness_table(result["readiness_summary"]), file=sys.stderr)
    if result["commit_msg_hooks"]:
        print(commit_msg_hook_table(result["commit_msg_hooks"]), file=sys.stderr)
    print(json.dumps({**result, "metrics_path": str(output)}, indent=2))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
