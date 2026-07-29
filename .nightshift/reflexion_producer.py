#!/usr/bin/env python3
"""Best-effort Reflexion producer capture for Nightshift failure events."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

MAX_FIELD_CHARS = 500
MAX_TASK_CONTEXT_CHARS = 700
MAX_SESSION_ID_CHARS = 120

# SPEC-CTX-CORE-029 — producer session attribution.
#
# Run identity is carried by the NIGHTSHIFT_RUN_ID environment variable, which
# the kit already recognises as run-identifying context (replay.ALLOWED_ENV_KEYS).
# Its value is a loop_events.generate_run_id() stamp, e.g. "run-2026-07-28-210133".
#
# THE DOCUMENTED RULE: an entries.session_id beginning with "ns-run:" was written
# by an automatic Nightshift producer, never by an interactive session. Interactive
# Cortex sessions use the "S-260325-051322" shape, so the two cannot collide.
# Filter producer traffic with `WHERE session_id LIKE 'ns-run:%'`, and interactive
# traffic with `NOT LIKE 'ns-run:%'`.
NIGHTSHIFT_RUN_ID_ENV = "NIGHTSHIFT_RUN_ID"
PRODUCER_SESSION_PREFIX = "ns-run:"

_STACK_LINE = re.compile(r"^\s*(Traceback\b|File \".*\", line \d+|[A-Za-z_][\w.]*Error:|log line \d+\b)")


def _argo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_cortex_mcp_path() -> Path:
    return _argo_root() / "Cortex" / "mcp" / "cortex-mcp.py"


def _load_cortex_mcp_module(path: Path | None = None) -> ModuleType:
    mcp_path = path or _default_cortex_mcp_path()
    if not mcp_path.is_file():
        raise FileNotFoundError(f"Cortex MCP module not found: {mcp_path}")

    spec = importlib.util.spec_from_file_location(
        "nightshift_cortex_mcp_reflexion",
        mcp_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Cortex MCP module: {mcp_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bounded_text(value: Any, fallback: str, *, limit: int = MAX_FIELD_CHARS) -> str:
    if value is None:
        return fallback
    text = str(value).replace("\x00", " ").strip()
    if not text:
        return fallback

    kept_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _STACK_LINE.search(stripped):
            continue
        kept_lines.append(stripped)
        if len(" ".join(kept_lines)) >= limit:
            break

    summary = " ".join(kept_lines).strip() or fallback
    if len(summary) > limit:
        summary = summary[: limit - 1].rstrip() + "..."
    return summary


def _producer_session_id() -> str | None:
    """
    Derive this Nightshift run's producer session id, or None if there isn't one.

    Every write in one run reads the same environment value, so they share one id.
    A missing or blank run identity returns None — the write stays unattributed
    rather than failing, which is the pre-SPEC-CTX-CORE-029 behavior.
    """
    run_id = os.environ.get(NIGHTSHIFT_RUN_ID_ENV, "").replace("\x00", " ").strip()
    if not run_id:
        return None
    return f"{PRODUCER_SESSION_PREFIX}{run_id}"[:MAX_SESSION_ID_CHARS]


def _safe_task_context(
    *,
    project_root: Path,
    source_file: str,
    error_type: str,
    spec_file: str | None,
    status: str,
) -> str:
    parts = [
        f"project={project_root.name}",
        f"source={_bounded_text(source_file, 'unknown source', limit=120)}",
        f"error_type={_bounded_text(error_type, 'unknown error type', limit=120)}",
        f"status={_bounded_text(status, 'failed', limit=80)}",
    ]
    if spec_file:
        parts.append(f"spec={_bounded_text(spec_file, 'unknown spec', limit=160)}")
    return _bounded_text("; ".join(parts), "Nightshift failure", limit=MAX_TASK_CONTEXT_CHARS)


def record_failure_reflexion(
    *,
    project_root: Path,
    source_file: str,
    error_type: str,
    description: str,
    spec_file: str | None = None,
    status: str = "failed",
) -> dict[str, Any]:
    """
    Send a bounded Nightshift failure event to Cortex Reflexion.

    This is intentionally best-effort: callers must preserve their original
    failure behavior even when Cortex MCP or the producer adapter is unavailable.
    """
    project_root = Path(project_root)
    payload = {
        "producer": "nightshift-failure-persistence",
        "task_context": _safe_task_context(
            project_root=project_root,
            source_file=source_file,
            error_type=error_type,
            spec_file=spec_file,
            status=status,
        ),
        "failure_summary": _bounded_text(
            f"{_bounded_text(error_type, 'unknown error type', limit=120)}: "
            f"{_bounded_text(description, 'Nightshift persisted a failure without a structured summary')}",
            "Nightshift persisted a failure without a structured summary",
        ),
        "attempted_strategy": (
            "Persisted the Nightshift failure artifact and failure ledger; "
            "marked the spec blocked when a spec file was available."
        ),
        "session_id": _producer_session_id(),
    }

    if not (project_root / "config.yaml").is_file():
        return {
            "attempted": False,
            "captured": False,
            "payload": payload,
            "error": "Nightshift config.yaml not found; Reflexion capture skipped.",
        }

    try:
        module = _load_cortex_mcp_module()
        tool = getattr(module, "cortex_reflexion_record_producer_failure")
        result = tool(**payload)
        return {"attempted": True, "captured": True, "payload": payload, "result": result}
    except Exception as exc:
        return {
            "attempted": True,
            "captured": False,
            "payload": payload,
            "error": f"{exc.__class__.__name__}: {_bounded_text(str(exc), 'unavailable')}",
        }
