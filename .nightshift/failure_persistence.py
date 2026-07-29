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

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is part of the Nightshift runtime
    yaml = None

try:
    from spec_frontmatter import NFR_FAMILY_STATUSES, is_nfr_family
except Exception:  # pragma: no cover - deployed copies still get a local fallback
    NFR_FAMILY_STATUSES = frozenset({"active", "retired"})

    def is_nfr_family(frontmatter: Dict[str, Any] | None) -> bool:
        if not isinstance(frontmatter, dict):
            return False
        spec_id = frontmatter.get("id")
        spec_type = frontmatter.get("type")
        return (isinstance(spec_id, str) and spec_id.startswith("NFR-")) or spec_type == "nfr"

try:
    from trace_export import TraceExportError, auto_export_from_failure
except Exception:  # pragma: no cover - deployed copies may not include SPEC-095 yet
    TraceExportError = ValueError
    auto_export_from_failure = None

try:
    from reflexion_producer import record_failure_reflexion
except Exception:  # pragma: no cover - deployed copies may not include SPEC-CTX-CORE-017 yet
    record_failure_reflexion = None


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


def _parse_frontmatter(frontmatter: str, spec_path: Path) -> Dict[str, Any]:
    if yaml is not None:
        parsed = yaml.safe_load(frontmatter) or {}
        return parsed if isinstance(parsed, dict) else {}

    parsed: Dict[str, Any] = {}
    for line in frontmatter.splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*?)\s*$", line)
        if match:
            parsed[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    if "id" not in parsed and spec_path.stem.startswith("NFR-"):
        parsed["id"] = spec_path.stem
    return parsed


def _set_frontmatter_status(frontmatter: str, status: str) -> str:
    lines = frontmatter.splitlines()
    has_status = False
    for i, line in enumerate(lines):
        if re.match(r"^\s*status\s*:", line):
            lines[i] = f"status: {status}"
            has_status = True
            break
    if not has_status:
        lines.append(f"status: {status}")
    return "\n".join(lines)


def _set_frontmatter_defaults(frontmatter: str, reason: str) -> str:
    """Add auditable blocker fields without overwriting caller-supplied evidence."""
    existing = {line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line}
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    defaults = {
        "blocker_class": "unknown_critical_failure",
        "block_reason": reason.strip(),
        "blocked_since": timestamp,
        "unblock_condition": "unknown; classification review required",
        "blocker_scope": "unknown",
        "blocker_evidence": "failure_persistence",
    }
    additions = [f"{key}: {value!r}" for key, value in defaults.items() if key not in existing]
    return frontmatter.rstrip() + ("\n" + "\n".join(additions) if additions else "")


def _nfr_run_state_entry(reason: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"### Pending/Failure Recorded {ts}\n\n"
        "Nightshift attempted to mark this NFR-family spec blocked. "
        "NFR-family specs remain `active` or `retired`; pending inputs and "
        "failed checks are recorded here instead of changing lifecycle state.\n\n"
        f"{reason.strip()}\n"
    )


def _insert_active_run_state(body: str, spec_path: Path, reason: str) -> str:
    entry = _nfr_run_state_entry(reason)
    active_state = re.search(r"(?m)^## Active Run State\s*$", body)
    if active_state:
        next_section = re.search(r"(?m)^## .*$", body[active_state.end() :])
        entry_block = "\n\n" + entry.strip() + "\n\n"
        if next_section:
            insert_at = active_state.end() + next_section.start()
            return body[:insert_at].rstrip() + entry_block + body[insert_at:].lstrip("\n")
        return body.rstrip() + entry_block

    section = f"## Active Run State\n\n{entry}\n"
    h1_match = re.search(r"(?m)^# .*$", body)
    if h1_match:
        insert_at = body.find("\n", h1_match.end())
        if insert_at == -1:
            return body.rstrip() + "\n\n" + section
        return body[: insert_at + 1] + "\n" + section + body[insert_at + 1 :]

    title = spec_path.stem.replace("_", " ").replace("-", " ")
    return f"\n# {title}\n\n{section}{body.lstrip()}"


def is_eval_fixture(frontmatter: Dict[str, Any] | None, spec_path: Path) -> bool:
    """Return True for benchmark eval fixtures, which must never be written to.

    Eval specs are the benchmark's independent variable: the runners hand the
    spec *file* to the model under test, so any text written into it becomes
    part of the next run's prompt. Membership is checked by ``type: eval``, an
    ``EVAL-`` id, or an ``EVAL-`` filename — the filename is the backstop for a
    fixture whose frontmatter was already damaged by a prior write.
    """
    spec_type = frontmatter.get("type") if isinstance(frontmatter, dict) else None
    spec_id = frontmatter.get("id") if isinstance(frontmatter, dict) else None
    return (
        spec_type == "eval"
        or (isinstance(spec_id, str) and spec_id.startswith("EVAL-"))
        or spec_path.stem.startswith("EVAL-")
    )


def mark_spec_blocked(spec_path: Path, reason: str) -> bool:
    """
    Mark a normal spec blocked and ensure ## Block Reason follows the title.

    NFR-family specs are standing constraints and dated verification trackers;
    they must never receive ``status: blocked``. For NFR-family specs this helper
    keeps/pivots the lifecycle to ``active`` or ``retired`` and records the
    pending/failure state under ``## Active Run State`` instead.

    Eval fixtures (BUG-002) are benchmark inputs rather than work items: they
    have no lifecycle to record and any write contaminates the measurement, so
    they are left byte-identical and no state is recorded on them at all. The
    failure is still durably recorded in the ledger by :func:`persist_failure`.

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
            fm = _parse_frontmatter(frontmatter, spec_path)
            if "id" not in fm and spec_path.stem.startswith("NFR-"):
                fm["id"] = spec_path.stem

            if is_eval_fixture(fm, spec_path):
                return False

            if is_nfr_family(fm):
                current_status = fm.get("status")
                target_status = (
                    current_status
                    if isinstance(current_status, str) and current_status in NFR_FAMILY_STATUSES
                    else "active"
                )
                new_frontmatter = _set_frontmatter_status(frontmatter, target_status)
                body = _insert_active_run_state(body, spec_path, reason)
                content = f"---\n{new_frontmatter}\n---\n{body}"
                if content == original:
                    return False
                _atomic_write_text(spec_path, content)
                return True

            lines = frontmatter.splitlines()
            has_status = False
            for i, line in enumerate(lines):
                if re.match(r"^\s*status\s*:", line):
                    lines[i] = "status: blocked"
                    has_status = True
                    break
            if not has_status:
                lines.append("status: blocked")

            new_frontmatter = _set_frontmatter_defaults("\n".join(lines), reason)
            body_stripped = body.lstrip()
            if "## Block Reason" not in body_stripped:
                block_section = f"## Block Reason\n\n{reason}\n\n"
                h1_match = re.search(r"(?m)^# .*$", body)
                if h1_match:
                    insert_at = body.find("\n", h1_match.end())
                    if insert_at == -1:
                        body = body.rstrip() + "\n\n" + block_section
                    else:
                        body = body[: insert_at + 1] + "\n" + block_section + body[insert_at + 1 :]
                else:
                    title = spec_path.stem.replace("_", " ").replace("-", " ")
                    body = f"\n# {title}\n\n{block_section}{body.lstrip()}"

            content = f"---\n{new_frontmatter}\n---\n{body}"
    else:
        if is_eval_fixture(None, spec_path):
            return False
        if spec_path.stem.startswith("NFR-"):
            title = spec_path.stem.replace("_", " ").replace("-", " ")
            body = f"\n# {title}\n\n{content}"
            body = _insert_active_run_state(body, spec_path, reason)
            content = f"---\nid: {spec_path.stem}\nstatus: active\n---\n{body}"
        else:
            # No frontmatter: prepend minimal blocked frontmatter and reason
            title = spec_path.stem.replace("_", " ").replace("-", " ")
            content = f"---\nstatus: blocked\n---\n# {title}\n\n## Block Reason\n\n{reason}\n\n{content}"

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

    # 2b) optional SPEC-095 regression trace export. This is intentionally
    # automatic when the failure event carries a replayable trace payload, and a
    # no-op for legacy callers that only have prose failure details.
    trace_export_path = None
    trace_export_error = None
    if auto_export_from_failure is not None:
        try:
            exported = auto_export_from_failure(
                project_root,
                source_file=source_file,
                error_type=error_type,
                description=description,
                details=details,
                status=status,
            )
            trace_export_path = str(exported) if exported is not None else None
        except TraceExportError as exc:
            trace_export_error = str(exc)

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

    reflexion_capture = None
    if record_failure_reflexion is not None:
        reflexion_capture = record_failure_reflexion(
            project_root=project_root,
            source_file=source_file,
            error_type=error_type,
            description=description,
            spec_file=spec_file,
            status=status,
        )

    return {
        "report_path": str(report_path),
        "ledger_path": str(ledger_path),
        "spec_update": spec_update,
        "trace_export_path": trace_export_path,
        "trace_export_error": trace_export_error,
        "reflexion_capture": reflexion_capture,
    }
