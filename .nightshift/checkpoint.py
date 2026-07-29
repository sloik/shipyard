#!/usr/bin/env python3
"""
Checkpoint/resume support for Nightshift loop runs.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_MAX_CHECKPOINT_BYTES = 1024 * 1024


def _load_loop_events_module():
    module_path = Path(__file__).with_name("loop_events.py")
    spec = importlib.util.spec_from_file_location("nightshift_loop_events", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load loop_events from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


loop_events = _load_loop_events_module()


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _checkpoints_dir(nightshift_dir: Path, run_id: str) -> Path:
    return Path(nightshift_dir) / "runs" / run_id / "checkpoints"


def _checkpoint_path(nightshift_dir: Path, run_id: str, step: int) -> Path:
    return _checkpoints_dir(nightshift_dir, run_id) / f"step-{step:02d}.json"


def _latest_path(nightshift_dir: Path, run_id: str) -> Path:
    return _checkpoints_dir(nightshift_dir, run_id) / "latest.json"


def _json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _coerce_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _run_git_command(args: List[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@dataclass
class CheckpointState:
    spec_id: str = ""
    run_id: str = ""
    step: int = 0
    step_name: str = ""
    timestamp: str = ""
    git_sha: str = ""
    git_branch: str = ""
    files_modified: List[str] = field(default_factory=list)
    test_status: Dict[str, Any] = field(default_factory=dict)
    build_status: Dict[str, Any] = field(default_factory=dict)
    decisions: List[str] = field(default_factory=list)
    context_summary: str = ""
    metrics_snapshot: Dict[str, Any] = field(default_factory=dict)
    circuit_breaker_snapshot: Optional[Dict[str, Any]] = None
    knowledge_patterns_loaded: List[str] = field(default_factory=list)
    custom: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "run_id": self.run_id,
            "step": self.step,
            "step_name": self.step_name,
            "timestamp": self.timestamp,
            "git_sha": self.git_sha,
            "git_branch": self.git_branch,
            "files_modified": list(self.files_modified),
            "test_status": dict(self.test_status),
            "build_status": dict(self.build_status),
            "decisions": list(self.decisions),
            "context_summary": self.context_summary,
            "metrics_snapshot": dict(self.metrics_snapshot),
            "circuit_breaker_snapshot": (
                None
                if self.circuit_breaker_snapshot is None
                else dict(self.circuit_breaker_snapshot)
            ),
            "knowledge_patterns_loaded": list(self.knowledge_patterns_loaded),
            "custom": dict(self.custom),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointState":
        source = data if isinstance(data, dict) else {}
        circuit_breaker_snapshot = source.get("circuit_breaker_snapshot")
        if not isinstance(circuit_breaker_snapshot, dict):
            circuit_breaker_snapshot = None
        step_value = source.get("step", 0)
        try:
            step = int(step_value)
        except (TypeError, ValueError):
            step = 0
        return cls(
            spec_id=str(source.get("spec_id", "")),
            run_id=str(source.get("run_id", "")),
            step=step,
            step_name=str(source.get("step_name", "")),
            timestamp=str(source.get("timestamp", "")),
            git_sha=str(source.get("git_sha", "")),
            git_branch=str(source.get("git_branch", "")),
            files_modified=_coerce_str_list(source.get("files_modified")),
            test_status=_coerce_dict(source.get("test_status")),
            build_status=_coerce_dict(source.get("build_status")),
            decisions=_coerce_str_list(source.get("decisions")),
            context_summary=str(source.get("context_summary", "")),
            metrics_snapshot=_coerce_dict(source.get("metrics_snapshot")),
            circuit_breaker_snapshot=circuit_breaker_snapshot,
            knowledge_patterns_loaded=_coerce_str_list(
                source.get("knowledge_patterns_loaded")
            ),
            custom=_coerce_dict(source.get("custom")),
        )


def _apply_size_guard(state: CheckpointState) -> Tuple[Dict[str, Any], int, List[str]]:
    payload = state.to_dict()
    original_size = len(_json_bytes(payload))
    truncated_fields: List[str] = []

    if original_size <= _MAX_CHECKPOINT_BYTES:
        return payload, original_size, truncated_fields

    if len(payload["decisions"]) > 20:
        payload["decisions"] = payload["decisions"][-20:]
        truncated_fields.append("decisions")
        if len(_json_bytes(payload)) <= _MAX_CHECKPOINT_BYTES:
            return payload, original_size, truncated_fields

    if len(payload["context_summary"]) > 500:
        payload["context_summary"] = payload["context_summary"][:500]
        truncated_fields.append("context_summary")
        if len(_json_bytes(payload)) <= _MAX_CHECKPOINT_BYTES:
            return payload, original_size, truncated_fields

    if payload["custom"]:
        payload["custom"] = {}
        truncated_fields.append("custom")

    return payload, original_size, truncated_fields


def save_checkpoint(
    state: CheckpointState,
    nightshift_dir: Path,
    event_log=None,
) -> Path:
    payload, original_size, truncated_fields = _apply_size_guard(state)
    if truncated_fields:
        _warn(
            "checkpoint exceeds 1MB "
            f"({original_size} bytes); truncated {', '.join(truncated_fields)}"
        )

    checkpoint_file = _checkpoint_path(nightshift_dir, state.run_id, state.step)
    latest_file = _latest_path(nightshift_dir, state.run_id)
    raw = _json_bytes(payload)

    _atomic_write_bytes(checkpoint_file, raw)
    _atomic_write_bytes(latest_file, raw)

    if event_log is not None:
        event_log.emit(
            "checkpoint_saved",
            spec_id=state.spec_id,
            step=state.step,
            step_name=state.step_name,
            checkpoint_file=str(checkpoint_file),
        )

    return checkpoint_file


def _load_checkpoint_file(path: Path) -> Optional[CheckpointState]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        _warn(f"failed to load checkpoint {path}: {exc}")
        return None

    if not isinstance(data, dict):
        _warn(f"failed to load checkpoint {path}: top-level JSON must be an object")
        return None
    return CheckpointState.from_dict(data)


def load_latest_checkpoint(
    nightshift_dir: Path,
    run_id: str,
    event_log=None,
) -> Optional[CheckpointState]:
    latest = _load_checkpoint_file(_latest_path(nightshift_dir, run_id))
    if latest is not None and event_log is not None:
        event_log.emit(
            "checkpoint_restored",
            spec_id=latest.spec_id,
            step=latest.step,
            step_name=latest.step_name,
            checkpoint_file=str(_latest_path(nightshift_dir, run_id)),
        )
    return latest


def load_checkpoint(
    nightshift_dir: Path,
    run_id: str,
    step: int,
    event_log=None,
) -> Optional[CheckpointState]:
    checkpoint = _load_checkpoint_file(_checkpoint_path(nightshift_dir, run_id, step))
    if checkpoint is not None and event_log is not None:
        event_log.emit(
            "checkpoint_restored",
            spec_id=checkpoint.spec_id,
            step=checkpoint.step,
            step_name=checkpoint.step_name,
            checkpoint_file=str(_checkpoint_path(nightshift_dir, run_id, step)),
        )
    return checkpoint


def list_checkpoints(nightshift_dir: Path, run_id: str) -> List[Tuple[int, Path]]:
    checkpoints_dir = _checkpoints_dir(nightshift_dir, run_id)
    if not checkpoints_dir.exists():
        return []

    entries: List[Tuple[int, Path]] = []
    for path in checkpoints_dir.glob("step-*.json"):
        suffix = path.stem.split("step-", 1)[-1]
        try:
            step = int(suffix)
        except ValueError:
            continue
        entries.append((step, path))
    return sorted(entries, key=lambda item: item[0])


def verify_checkpoint(state: CheckpointState) -> List[str]:
    current_sha = _run_git_command(["git", "rev-parse", "HEAD"])
    current_branch = _run_git_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if current_sha is None or current_branch is None:
        return []

    messages = []
    if state.git_sha == current_sha:
        messages.append("git_sha: match")
    else:
        messages.append(
            "git_sha: MISMATCH "
            f"(checkpoint={state.git_sha}, current={current_sha})"
        )

    if state.git_branch == current_branch:
        messages.append("git_branch: match")
    else:
        messages.append(
            "git_branch: MISMATCH "
            f"(checkpoint={state.git_branch}, current={current_branch})"
        )

    for file_path in state.files_modified:
        if Path(file_path).exists():
            messages.append(f"file_exists: match ({file_path})")
        else:
            messages.append(f"file_exists: missing ({file_path})")

    return messages


def clear_checkpoints(nightshift_dir: Path, run_id: str) -> None:
    checkpoints_dir = _checkpoints_dir(nightshift_dir, run_id)
    if checkpoints_dir.exists():
        shutil.rmtree(checkpoints_dir)


def _find_last_completed_event(
    nightshift_dir: Path, spec_id: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    runs_dir = Path(nightshift_dir) / "runs"
    if not runs_dir.exists():
        return None

    best: Optional[Tuple[str, Dict[str, Any], str]] = None
    for events_file in runs_dir.glob("*/events.jsonl"):
        run_id = events_file.parent.name
        events = loop_events.load_events(events_file)
        for event in events:
            if (
                event.get("event") == "step_completed"
                and event.get("spec_id") == spec_id
                and isinstance(event.get("step"), int)
            ):
                ts_value = str(event.get("ts", ""))
                if best is None or ts_value >= best[2]:
                    best = (run_id, event, ts_value)
    if best is None:
        return None
    return best[0], best[1]


def find_resume_state(
    nightshift_dir: Path, spec_id: str
) -> Optional[Tuple[int, CheckpointState, List[str]]]:
    last_completed = _find_last_completed_event(nightshift_dir, spec_id)
    if last_completed is None:
        return None

    run_id, event = last_completed
    run_log = loop_events.RunEventLog(Path(nightshift_dir), run_id)
    resume_step = run_log.find_resume_point(spec_id)
    if resume_step is None:
        return None

    completed_step = resume_step - 1
    warnings: List[str] = []
    checkpoint = load_checkpoint(nightshift_dir, run_id, completed_step)
    if checkpoint is not None:
        return resume_step, checkpoint, warnings

    available = list_checkpoints(nightshift_dir, run_id)
    nearest = None
    for step, path in available:
        if step <= completed_step:
            nearest = (step, path)
        else:
            break

    if nearest is None:
        return None

    warning = (
        f"event log shows step {completed_step} completed but no checkpoint found "
        f"using nearest available checkpoint (step {nearest[0]})"
    )
    warnings.append(warning)
    _warn(warning)

    checkpoint = _load_checkpoint_file(nearest[1])
    if checkpoint is None:
        return None
    return resume_step, checkpoint, warnings


__all__ = [
    "CheckpointState",
    "save_checkpoint",
    "load_latest_checkpoint",
    "load_checkpoint",
    "list_checkpoints",
    "verify_checkpoint",
    "clear_checkpoints",
    "find_resume_state",
]
