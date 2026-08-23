#!/usr/bin/env python3
"""Project-configured terminal outcome record validation (SPEC-224).

The commit-msg hook invokes this module only when a project opts in with an
``terminal_outcomes`` mapping.  The mapping owns both the storage adapter and
field names, so canonical code never assumes an Argo-specific ledger.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

FLEET_FIELDS = ("spec_id", "terminal_outcome", "agent_response", "causal_confidence", "human_action_needed", "evidence_refs")


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file() or yaml is None:
        return {}
    try:
        merged: dict[str, Any] = {}
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if isinstance(document, dict):
                merged.update(document)
        value = merged.get("terminal_outcomes", {})
        return value if isinstance(value, dict) else {}
    except yaml.YAMLError:
        return {}


def configured(config: dict[str, Any]) -> bool:
    return bool(config.get("enabled", False))


def _rows(adapter: str, raw: str) -> list[dict[str, Any]]:
    if adapter == "json-array":
        value = json.loads(raw)
        if not isinstance(value, list):
            raise ValueError("json-array adapter requires a JSON array")
        return [row for row in value if isinstance(row, dict)]
    if adapter == "jsonl":
        return [value for line in raw.splitlines() if line.strip() for value in [json.loads(line)] if isinstance(value, dict)]
    raise ValueError(f"unsupported terminal outcome adapter: {adapter}")


def read_records(path: Path, adapter: str) -> list[dict[str, Any]]:
    return _rows(adapter, path.read_text(encoding="utf-8"))


def normalized(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    fields = config.get("fields", {})
    fields = fields if isinstance(fields, dict) else {}
    return {canonical: record.get(str(fields.get(canonical, canonical))) for canonical in FLEET_FIELDS}


def conforming(record: dict[str, Any], spec_id: str, terminal: str, config: dict[str, Any]) -> bool:
    row = normalized(record, config)
    required = config.get("required_fields", list(FLEET_FIELDS))
    if not isinstance(required, list):
        return False
    return (
        row["spec_id"] == spec_id
        and row["terminal_outcome"] == terminal
        and all(row.get(str(field)) not in (None, "", []) for field in required)
    )


def staged_records(repo: Path, relative_path: str, adapter: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    def show(ref: str) -> list[dict[str, Any]]:
        result = subprocess.run(["git", "-C", str(repo), "show", ref], text=True, capture_output=True, check=False)
        if result.returncode:
            return []
        return _rows(adapter, result.stdout)
    return show(f"HEAD:{relative_path}"), show(f":{relative_path}")


def changed_matching_record(repo: Path, spec_id: str, terminal: str, config: dict[str, Any]) -> tuple[bool, str]:
    path = config.get("path")
    adapter = config.get("adapter", "json-array")
    if not isinstance(path, str) or not path.strip():
        return False, "terminal_outcomes.path is required when enforcement is enabled"
    if adapter not in {"json-array", "jsonl"}:
        return False, "terminal_outcomes.adapter must be json-array or jsonl"
    try:
        before, after = staged_records(repo, path, adapter)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, f"cannot read staged terminal outcome records: {exc}"
    # A multiset difference treats both insertion and in-place replacement as a
    # changed record, while preserving legitimate duplicate records.
    before_counts = Counter(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in before)
    for row in after:
        key = json.dumps(row, sort_keys=True, separators=(",", ":"))
        if before_counts[key]:
            before_counts[key] -= 1
            continue
        if conforming(row, spec_id, terminal, config):
            return True, "matching changed terminal outcome record staged"
    return False, f"no changed conforming terminal outcome record for {spec_id} ({terminal})"


def aggregate(paths: list[Path], config: dict[str, Any]) -> list[dict[str, Any]]:
    adapter = str(config.get("adapter", "json-array"))
    return [normalized(record, config) for path in paths for record in read_records(path, adapter)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-staged", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path(".nightshift/config.yaml"))
    parser.add_argument("--spec-id")
    parser.add_argument("--terminal", choices=("done", "blocked"))
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if not configured(config):
        return 0
    if not args.check_staged or not args.spec_id or not args.terminal:
        parser.error("--check-staged, --spec-id, and --terminal are required")
    ok, detail = changed_matching_record(args.repo, args.spec_id, args.terminal, config)
    if not ok:
        print(f"[nightshift terminal-outcomes] ERROR: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
