#!/usr/bin/env python3
"""run_validation.py — mechanize Step 9 validation capture (SPEC-092).

Runs the configured build/test/lint/type_check commands and writes a structured
`metrics/<spec-id>.validation.json` that `record_metrics.py --mark-commit` reads for
AUTHORITATIVE test/lint/type/build numbers (instead of best-effort report-parsing).
Additive: if the file is absent the metrics hook falls back to its old behaviour.

Null/empty commands are skipped and recorded as skipped (Null Command Policy), never
silently dropped. Test-count parsing is best-effort (pytest `N passed/failed`; exit-code
fallback otherwise) — a present-but-coarse count beats none.

Usage:
    python3 run_validation.py --spec-id SPEC-XXX [--config .nightshift/config.yaml]
        [--metrics-dir .nightshift/metrics] [--repo .] [--dry-run]
Exit code mirrors overall validation: 0 if every run command passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("Error: PyYAML required.", file=sys.stderr)
    sys.exit(2)

_PYTEST_PASSED = re.compile(r"(\d+)\s+passed")
_PYTEST_FAILED = re.compile(r"(\d+)\s+failed")
_PYTEST_ERROR = re.compile(r"(\d+)\s+error")


def load_commands(config_path: Path) -> dict:
    """Extract the `commands` block from a (possibly multi-document) config.yaml."""
    cfg = {}
    if config_path.is_file():
        try:
            for doc in yaml.safe_load_all(config_path.read_text()):
                if isinstance(doc, dict):
                    cfg.update(doc)
        except yaml.YAMLError:
            pass
    return cfg.get("commands", {}) or {}


def _run(cmd: str, cwd: Path, timeout: int | None) -> tuple[int, str]:
    """Run a shell command, return (exit_code, combined_output). 124 on timeout."""
    try:
        p = subprocess.run(
            cmd, shell=True, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout if timeout and timeout > 0 else None,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except OSError as e:
        return 127, str(e)


def parse_tests(output: str, exit_code: int) -> tuple[int, int, int]:
    """Best-effort (total, passed, failed) from test output; exit-code fallback."""
    passed = int(m.group(1)) if (m := _PYTEST_PASSED.search(output)) else None
    failed = int(m.group(1)) if (m := _PYTEST_FAILED.search(output)) else 0
    errors = int(m.group(1)) if (m := _PYTEST_ERROR.search(output)) else 0
    failed += errors
    if passed is None:
        # unparseable: fall back to exit code only (0 passed/0 failed is honest "unknown")
        return (0, 0, 0 if exit_code == 0 else 0)
    return (passed + failed, passed, failed)


def run_validation(spec_id: str, commands: dict, repo: Path) -> dict:
    """Run each configured command; return the validation result mapping."""
    result: dict = {
        "spec_id": spec_id,
        "build_pass": True,
        "tests_total": 0, "tests_passed": 0, "tests_failed": 0,
        "lint_errors": 0, "type_errors": 0,
        "commands": {},
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    test_timeout = commands.get("test_timeout_s", 300)

    for key in ("build", "test", "lint", "type_check"):
        cmd = str(commands.get(key, "") or "").strip()
        if not cmd:
            result["commands"][key] = {"cmd": None, "exit": None, "skipped": True}
            continue
        timeout = test_timeout if key == "test" else None
        code, out = _run(cmd, repo, timeout)
        result["commands"][key] = {"cmd": cmd, "exit": code}
        if key == "build" and code != 0:
            result["build_pass"] = False
        elif key == "test":
            total, passed, failed = parse_tests(out, code)
            result["tests_total"], result["tests_passed"], result["tests_failed"] = total, passed, failed
            if code != 0 and failed == 0:
                result["tests_failed"] = max(1, failed)  # nonzero exit, unparseable → at least 1
        elif key == "lint" and code != 0:
            result["lint_errors"] = 1
        elif key == "type_check" and code != 0:
            result["type_errors"] = 1
    return result


def overall_ok(result: dict) -> bool:
    return (result["build_pass"] and result["tests_failed"] == 0
            and result["lint_errors"] == 0 and result["type_errors"] == 0)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run configured validation commands; write validation.json.")
    p.add_argument("--spec-id", required=True)
    p.add_argument("--config", default=".nightshift/config.yaml", type=Path)
    p.add_argument("--metrics-dir", default=".nightshift/metrics", type=Path)
    p.add_argument("--repo", default=".", type=Path)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    commands = load_commands(args.config)
    result = run_validation(args.spec_id, commands, args.repo)

    if args.dry_run:
        print(json.dumps(result, indent=2))
        return 0 if overall_ok(result) else 1

    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    out = args.metrics_dir / f"{args.spec_id}.validation.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote {out} (build_pass={result['build_pass']} "
          f"tests={result['tests_passed']}/{result['tests_total']} "
          f"lint_errors={result['lint_errors']} type_errors={result['type_errors']})")
    return 0 if overall_ok(result) else 1


if __name__ == "__main__":
    sys.exit(main())
