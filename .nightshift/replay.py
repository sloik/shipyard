#!/usr/bin/env python3
"""SPEC-055: Failed-run replay bundle writer and inspector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ALLOWED_ENV_KEYS = {"PATH", "PYTHONPATH", "VIRTUAL_ENV", "NIGHTSHIFT_RUN_ID"}
REQUIRED_FILES = {
    "manifest.json",
    "commands.jsonl",
    "context-hashes.json",
    "file-inventory-before.json",
    "file-inventory-after.json",
    "blocker.md",
}


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def redacted_env(env: dict[str, str] | None = None) -> dict[str, str]:
    src = env or os.environ
    return {key: src[key] for key in sorted(ALLOWED_ENV_KEYS) if key in src}


def file_inventory(root: Path, *, max_files: int = 500) -> list[dict[str, Any]]:
    items = []
    if not root.exists():
        return items
    for path in sorted(root.rglob("*")):
        if len(items) >= max_files:
            break
        if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.parts):
            continue
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append({"path": str(path.relative_to(root)), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return items


def context_hashes(paths: Iterable[Path]) -> dict[str, Any]:
    out = {}
    for path in paths:
        p = Path(path)
        if p.exists() and p.is_file():
            out[str(p)] = {"sha256": sha256_file(p), "size_bytes": p.stat().st_size}
        else:
            out[str(p)] = {"not_available": True}
    return out


def git_diff(project_root: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(project_root), "diff", "--stat"], capture_output=True, text=True, timeout=5)
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as exc:
        return f"git diff unavailable: {exc}\n"


def create_bundle(
    reports_root: Path,
    *,
    spec_id: str,
    project_root: Path,
    blocker: str,
    commands: list[dict[str, Any]] | None = None,
    context_files: Iterable[Path] = (),
    instruction_packet: dict[str, Any] | None = None,
    verification: dict[str, Any] | None = None,
    status: str = "failed",
    tool: str = "nightshift",
    model: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    stamp = now_stamp()
    bundle = reports_root / spec_id / "replay" / stamp
    bundle.mkdir(parents=True, exist_ok=True)
    manifest = {
        "spec_id": spec_id,
        "status": status,
        "timestamp": stamp,
        "tool": tool,
        "model": model,
        "project_root": str(project_root),
        "environment": redacted_env(env),
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "instruction-packet.json").write_text(json.dumps(instruction_packet or {"not_available": True}, indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "verification.json").write_text(json.dumps(verification or {"not_available": True}, indent=2, ensure_ascii=False), encoding="utf-8")
    with (bundle / "commands.jsonl").open("w", encoding="utf-8") as fh:
        for command in commands or []:
            fh.write(json.dumps(command, ensure_ascii=False) + "\n")
    (bundle / "context-hashes.json").write_text(json.dumps(context_hashes(context_files), indent=2, ensure_ascii=False), encoding="utf-8")
    inventory = file_inventory(project_root)
    (bundle / "file-inventory-before.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (bundle / "file-inventory-after.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (bundle / "git-diff-summary.txt").write_text(git_diff(project_root), encoding="utf-8")
    (bundle / "blocker.md").write_text(f"# Replay Blocker: {spec_id}\n\n{blocker}\n\n## Suggested Next Action\n\nInspect `commands.jsonl`, `verification.json`, and `context-hashes.json`.\n", encoding="utf-8")
    return bundle


def inspect_bundle(bundle: Path) -> tuple[int, str]:
    missing = sorted(name for name in REQUIRED_FILES if not (bundle / name).exists())
    if missing:
        return 1, "Malformed replay bundle; missing: " + ", ".join(missing)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    commands = []
    for line in (bundle / "commands.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            commands.append(json.loads(line))
    blocker = (bundle / "blocker.md").read_text(encoding="utf-8").strip().splitlines()[0]
    failing = [cmd for cmd in commands if int(cmd.get("exit_code", 0)) != 0]
    lines = [
        f"Replay bundle: {bundle}",
        f"Spec: {manifest.get('spec_id')} status={manifest.get('status')}",
        f"Tool/model: {manifest.get('tool')} / {manifest.get('model') or 'unknown'}",
        f"Commands: {len(commands)} total, {len(failing)} failing",
        f"Blocker: {blocker}",
    ]
    for cmd in failing:
        lines.append(f"- FAIL {cmd.get('exit_code')}: {cmd.get('command')} ({cmd.get('summary', '')})")
    lines.append("Recommended next steps: inspect command outputs, verify context hashes, then rerun only the failing command in a safe workspace.")
    return 0, "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Nightshift replay bundles")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("bundle")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        code, text = inspect_bundle(Path(args.bundle))
        print(text)
        return code
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
