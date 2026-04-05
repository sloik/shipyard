#!/usr/bin/env python3
"""
Durable failure persistence helpers for Nightshift.

Guarantees:
- Failure artifacts are written atomically (temp file + replace).
- A tracked failure ledger is updated atomically.
- Spec frontmatter can be marked blocked with a Block Reason section.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically to destination path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def _read_json_or_default(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def normalize_status(status: Any) -> tuple[str, Optional[str]]:
    """Normalize status aliases. Returns (normalized, raw_status_or_none)."""
    if not isinstance(status, str):
        return "failed", None
    if status == "fail":
        return "failed", "fail"
    return status, None


def mark_spec_blocked(spec_path: Path, reason: str) -> bool:
    """
    Mark spec frontmatter status as blocked and ensure # Block Reason exists first.
    Returns True if spec was updated.
    """
    if not spec_path.exists():
        return False

    original = spec_path.read_text(encoding="utf-8")
    content = original

    # Parse frontmatter if present
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            frontmatter = content[4:end]
            body = content[end + 5 :]

            lines = frontmatter.splitlines()
            has_status = False
            for i, line in enumerate(lines):
                if re.match(r"^\s*status\s*:", line):
                    lines[i] = "status: blocked"
                    has_status = True
                    break
            if not has_status:
                lines.append("status: blocked")

            new_frontmatter = "\n".join(lines)
            body_stripped = body.lstrip()
            if not body_stripped.startswith("# Block Reason"):
                block_section = f"# Block Reason\n\n{reason}\n\n"
                body = block_section + body

            content = f"---\n{new_frontmatter}\n---\n{body}"
    else:
        # No frontmatter: prepend minimal blocked frontmatter and reason
        content = f"---\nstatus: blocked\n---\n# Block Reason\n\n{reason}\n\n{content}"

    if content == original:
        return False
    _atomic_write_text(spec_path, content)
    return True


def persist_failure(
    project_root: Path,
    source_file: str,
    error_type: str,
    description: str,
    details: Optional[Dict[str, Any]] = None,
    spec_file: Optional[str] = None,
    status: str = "failed",
    raw_status: Optional[str] = None,
) -> Dict[str, str]:
    """
    Persist a failure event transactionally:
    1) write per-event artifact to reports/failures/*.json
    2) update metrics/failure-ledger.json atomically
    3) optionally mark spec as blocked with a Block Reason
    """
    project_root = Path(project_root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_stem = Path(source_file).stem

    event = {
        "timestamp": ts,
        "status": status,
        "raw_status": raw_status,
        "source_file": source_file,
        "error_type": error_type,
        "description": description,
        "details": details or {},
        "spec_file": spec_file,
    }

    # 1) durable per-event artifact
    report_path = project_root / "reports" / "failures" / f"{ts}-{source_stem}.json"
    _atomic_write_json(report_path, event)

    # 2) durable ledger
    ledger_path = project_root / "metrics" / "failure-ledger.json"
    ledger = _read_json_or_default(ledger_path, [])
    if not isinstance(ledger, list):
        ledger = []
    ledger.append(event)
    _atomic_write_json(ledger_path, ledger)

    # 3) best-effort spec block update
    spec_update = "skipped"
    if spec_file:
        spec_path = (project_root / spec_file).resolve()
        if spec_path.exists():
            reason = (
                "Automatically blocked due to persisted failure.\n\n"
                f"- Error type: `{error_type}`\n"
                f"- Source: `{source_file}`\n"
                f"- Description: {description}\n"
            )
            updated = mark_spec_blocked(spec_path, reason)
            spec_update = "updated" if updated else "unchanged"
        else:
            spec_update = "not_found"

    return {
        "report_path": str(report_path),
        "ledger_path": str(ledger_path),
        "spec_update": spec_update,
    }

