#!/usr/bin/env python3
"""SPEC-051: Generate agent-readable Nightshift instruction packets.

The packet is a deterministic startup contract for a selected spec: current
state, context files, validation commands, blockers, progress, and next action.
It is intentionally small and filesystem-driven so agents do not infer required
context from prose or chat history.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CANONICAL_DIR = Path(__file__).resolve().parent
if str(CANONICAL_DIR) not in sys.path:
    sys.path.insert(0, str(CANONICAL_DIR))

try:
    from spec_frontmatter import FrontmatterError, parse_spec_file
except Exception as exc:  # pragma: no cover - import guard for deployed copies
    print(f"Error: cannot import spec_frontmatter.py: {exc}", file=sys.stderr)
    sys.exit(2)

PROTOCOL_FILES = [
    "BOOTSTRAP.md",
    "LOOP.md",
    "REVIEW.md",
    "ORCHESTRATOR.md",
    "SPEC-GUIDE.md",
]
VALIDATION_FILES = [
    "validate_specs.py",
    "scanner.py",
    "nightshift-dag.py",
    "hooks/pre-commit",
]


@dataclass(frozen=True)
class LocatedSpec:
    path: Path
    frontmatter: dict[str, Any]
    body: str


def _repo_root_hint() -> Path:
    # canonical/<script> -> Nightshift project root; .nightshift/<script> -> project root
    parent = CANONICAL_DIR.parent
    if CANONICAL_DIR.name == ".nightshift":
        return parent
    return parent


def _default_specs_dir(nightshift_dir: Path) -> Path:
    deployed = nightshift_dir / "specs"
    if deployed.exists():
        return deployed
    candidate = nightshift_dir.parent / "plans" / "specs"
    if candidate.exists():
        return candidate
    return deployed


def _path_item(path: Path, *, optional: bool = False, missing_reason: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if optional:
        item["optional"] = True
    if missing_reason:
        item["missing_reason"] = missing_reason
    return item


def _existing_or_optional(path: Path, missing_reason: str) -> dict[str, Any]:
    return _path_item(path) if path.exists() else _path_item(path, optional=True, missing_reason=missing_reason)


def _read_config(nightshift_dir: Path) -> dict[str, Any]:
    for candidate in (nightshift_dir / "config.yaml", nightshift_dir.parent / ".nightshift" / "config.yaml"):
        if candidate.exists():
            try:
                return yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                return {}
    return {}


def _load_spec(path: Path) -> LocatedSpec | None:
    try:
        parsed = parse_spec_file(path)
    except (FrontmatterError, OSError):
        return None
    return LocatedSpec(path=path, frontmatter=parsed.frontmatter, body=parsed.body)


def _spec_title(located: LocatedSpec) -> str:
    for line in located.body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return str(located.frontmatter.get("title") or located.frontmatter.get("id") or located.path.stem)


def _find_specs(specs_dir: Path) -> dict[str, LocatedSpec]:
    specs: dict[str, LocatedSpec] = {}
    if not specs_dir.exists():
        return specs
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        located = _load_spec(path)
        if not located:
            continue
        spec_id = located.frontmatter.get("id")
        if isinstance(spec_id, str) and spec_id:
            specs[spec_id] = located
    return specs


def _count_checkboxes(text: str) -> dict[str, Any]:
    tasks = []
    for idx, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*[-*]\s*\[([ xX])\]\s+(.+?)\s*$", line)
        if not match:
            continue
        tasks.append({
            "line": idx,
            "done": match.group(1).lower() == "x",
            "description": match.group(2),
        })
    total = len(tasks)
    done = sum(1 for task in tasks if task["done"])
    return {"items": tasks, "total": total, "complete": done, "remaining": total - done}


def _count_acceptance_criteria(text: str) -> dict[str, int]:
    in_ac = False
    total = 0
    complete = 0
    for line in text.splitlines():
        if line.startswith("## "):
            in_ac = line.strip().lower() == "## acceptance criteria"
            continue
        if not in_ac:
            continue
        match = re.match(r"^\s*[-*]\s*\[([ xX])\]", line)
        if match:
            total += 1
            complete += 1 if match.group(1).lower() == "x" else 0
    return {"total": total, "complete": complete, "remaining": total - complete}


def _resolve_devkb_paths(frontmatter: dict[str, Any]) -> list[dict[str, Any]]:
    names = frontmatter.get("devkb_required") or []
    if not isinstance(names, list):
        return []
    devkb_root = Path.home() / "Dropbox" / "Argo" / "DevKB"
    return [_existing_or_optional(devkb_root / str(name), "DevKB file listed by spec but not found") for name in names]


def _walk_argo_files(project_root: Path) -> list[dict[str, Any]]:
    result = []
    current = project_root.resolve()
    while True:
        argo_dir = current / ".argo"
        if argo_dir.exists():
            for name in ("README.md", "context.md"):
                path = argo_dir / name
                if path.exists():
                    result.append(_path_item(path))
        if current.parent == current:
            break
        current = current.parent
    return result


def _commands(nightshift_dir: Path, config: dict[str, Any]) -> dict[str, str | None]:
    commands = config.get("commands") if isinstance(config.get("commands"), dict) else {}
    return {
        "build": commands.get("build"),
        "test": commands.get("test"),
        "lint": commands.get("lint"),
        "type_check": commands.get("type_check"),
        "validate_specs": f"python3 {nightshift_dir / 'validate_specs.py'} {nightshift_dir / 'specs'}",
        "validate_selected_spec": f"python3 {nightshift_dir / 'nightshift-dag.py'} validate-spec <spec-file>",
        "drift": "python3 scripts/check_nightshift_drift.py",
    }


def _blocker(owner: str, risk: str, evidence: str, suggested_fix: str) -> dict[str, str]:
    return {"owner": owner, "risk": risk, "evidence": evidence, "suggested_fix": suggested_fix}


def generate_packet(spec_id: str, *, nightshift_dir: Path, specs_dir: Path, project_root: Path) -> dict[str, Any]:
    nightshift_dir = nightshift_dir.resolve()
    specs_dir = specs_dir.resolve()
    project_root = project_root.resolve()
    config = _read_config(nightshift_dir)
    specs = _find_specs(specs_dir)
    blockers: list[dict[str, str]] = []

    located = specs.get(spec_id)
    if located is None:
        return {
            "spec_id": spec_id,
            "title": spec_id,
            "status": "unknown",
            "state": "unknown",
            "project_root": str(project_root),
            "nightshift_dir": str(nightshift_dir),
            "contextFiles": {},
            "commands": _commands(nightshift_dir, config),
            "tasks": {"items": [], "total": 0, "complete": 0, "remaining": 0},
            "progress": {"tasks": {"total": 0, "complete": 0, "remaining": 0}, "acceptanceCriteria": {"total": 0, "complete": 0, "remaining": 0}},
            "blockingReasons": [_blocker("spec", "selected spec cannot be executed", f"{spec_id} not found in {specs_dir}", "Create the spec file or pass the correct --specs-dir/--spec value.")],
            "recommendedNextAction": "fix_blockers",
        }

    fm = located.frontmatter
    status = str(fm.get("status") or "draft")
    after = fm.get("after") or []
    if not isinstance(after, list):
        after = []
    required_inputs = ((fm.get("context") or {}).get("required_inputs") if isinstance(fm.get("context"), dict) else fm.get("required_inputs")) or []
    if not isinstance(required_inputs, list):
        required_inputs = []

    spec_files = [_path_item(located.path)]
    for dep in after:
        dep_spec = specs.get(str(dep))
        if dep_spec:
            spec_files.append(_path_item(dep_spec.path))
        else:
            blockers.append(_blocker("spec.after", "dependency cannot be verified", f"{spec_id} references missing dependency {dep}", f"Create {dep}, remove it from after:, or correct the dependency id."))

    knowledge_files = []
    for raw_path in required_inputs:
        p = Path(str(raw_path))
        path = p if p.is_absolute() else project_root / p
        if path.exists():
            knowledge_files.append(_path_item(path))
        else:
            knowledge_files.append(_path_item(path, optional=True, missing_reason="required input missing"))
            blockers.append(_blocker("context.required_inputs", "agent would start without required upstream artifact", str(path), "Create the required input file or update context.required_inputs."))

    protocol_files = [_existing_or_optional(nightshift_dir / name, "canonical protocol file missing") for name in PROTOCOL_FILES]
    config_files = [
        _existing_or_optional(nightshift_dir / "config.yaml", "project config missing"),
        _existing_or_optional(nightshift_dir / "config-reference.yaml", "canonical config reference missing"),
    ]
    validation_files = [_existing_or_optional(nightshift_dir / name, "validation helper missing") for name in VALIDATION_FILES]

    tasks = _count_checkboxes(located.body)
    acceptance = _count_acceptance_criteria(located.body)

    if status == "done":
        state = "all_done"
        next_action = "no_op"
    elif blockers:
        state = "blocked"
        next_action = "fix_blockers"
    elif status == "in_progress":
        state = "in_progress"
        next_action = "implement"
    elif tasks["total"] and tasks["remaining"] == 0 and acceptance["total"] and acceptance["remaining"] == 0:
        state = "all_done"
        next_action = "verify"
    else:
        state = "ready" if status == "ready" else status
        next_action = "implement" if status in {"ready", "in_progress"} else "read_context"

    return {
        "spec_id": spec_id,
        "title": _spec_title(located),
        "status": status,
        "state": state,
        "project_root": str(project_root),
        "nightshift_dir": str(nightshift_dir),
        "spec_path": str(located.path),
        "metadata": {
            "after": after,
            "provides": fm.get("provides") or [],
            "requires": fm.get("requires") or [],
            "touches": fm.get("touches") or [],
            "parent": fm.get("parent"),
        },
        "contextFiles": {
            "protocol": protocol_files,
            "config": config_files,
            "spec": spec_files,
            "project_context": _walk_argo_files(project_root),
            "knowledge": knowledge_files,
            "devkb": _resolve_devkb_paths(fm),
            "validation": validation_files,
        },
        "commands": _commands(nightshift_dir, config),
        "tasks": tasks,
        "progress": {"tasks": {k: tasks[k] for k in ("total", "complete", "remaining")}, "acceptanceCriteria": acceptance},
        "blockingReasons": blockers,
        "recommendedNextAction": next_action,
    }


def render_text(packet: dict[str, Any]) -> str:
    lines = [f'<artifact id="{packet["spec_id"]}" state="{packet["state"]}">', ""]
    lines += ["<task>", f"Work on {packet['spec_id']}: {packet.get('title', packet['spec_id'])}", "</task>", ""]
    lines += ["<context_files>"]
    for group, items in packet.get("contextFiles", {}).items():
        lines.append(f"  <group name=\"{group}\">")
        for item in items:
            suffix = ""
            if item.get("optional"):
                suffix = f" optional=\"true\" reason=\"{item.get('missing_reason', '')}\""
            lines.append(f"    <path{suffix}>{item['path']}</path>")
        lines.append("  </group>")
    lines += ["</context_files>", "", "<commands>"]
    for name, command in packet.get("commands", {}).items():
        if command:
            lines.append(f"  <command name=\"{name}\">{command}</command>")
    lines += ["</commands>", "", "<blockers>"]
    for blocker in packet.get("blockingReasons", []):
        lines.append(f"  - {blocker['owner']}: {blocker['risk']} | fix: {blocker['suggested_fix']}")
    lines += ["</blockers>", "", "<next_action>", packet.get("recommendedNextAction", "read_context"), "</next_action>", "", "</artifact>"]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Nightshift instruction packets")
    sub = parser.add_subparsers(dest="command", required=True)
    apply = sub.add_parser("apply", help="Generate apply/startup instructions for a spec")
    apply.add_argument("--spec", required=True, help="Spec id to inspect")
    apply.add_argument("--json", action="store_true", help="Emit JSON packet")
    apply.add_argument("--nightshift-dir", default=str(CANONICAL_DIR), help="Path to .nightshift or canonical dir")
    apply.add_argument("--specs-dir", default=None, help="Path to specs directory")
    apply.add_argument("--project-root", default=None, help="Project root for resolving context paths")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    nightshift_dir = Path(args.nightshift_dir)
    specs_dir = Path(args.specs_dir) if args.specs_dir else _default_specs_dir(nightshift_dir)
    project_root = Path(args.project_root) if args.project_root else _repo_root_hint()
    packet = generate_packet(args.spec, nightshift_dir=nightshift_dir, specs_dir=specs_dir, project_root=project_root)
    if args.json:
        print(json.dumps(packet, indent=2, ensure_ascii=False))
    else:
        print(render_text(packet))
    return 0 if packet.get("state") not in {"unknown"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
