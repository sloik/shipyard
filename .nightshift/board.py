#!/usr/bin/env python3
"""
SPEC-050 — Local Web Kanban Board for Nightshift specs.

Single-file FastAPI server. Entire HTML/CSS/JS is embedded as a Python string.
Launch: python .nightshift/board.py [--port 7842] [--open] [--specs <path>]

Requirements: fastapi uvicorn[standard] pyyaml
"""

from __future__ import annotations

# Dependency check before anything else
try:
    import fastapi
    import uvicorn
    import yaml
except ImportError as e:
    import sys
    print(f"✗ Missing dependency: {e}")
    print("  Install: pip install fastapi uvicorn[standard] pyyaml")
    sys.exit(1)

import errno
import json
import logging
import os
import re
import resource
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

try:
    from status_store import StatusStore
except Exception:
    StatusStore = None  # type: ignore[assignment]

try:
    from loop_observability import compute_from_db as compute_loop_observability
except Exception:
    compute_loop_observability = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def _registry_field_help() -> dict[str, str]:
    """Return board help directly from the canonical vocabulary registry."""
    try:
        from vocabulary import load_registry
        concepts = load_registry().get("concepts", [])
    except (ImportError, KeyError, OSError, TypeError, ValueError):
        return {}
    wanted = {
        "status", "layer", "priority", "readiness", "run_state",
        "blocker_class", "blocker_scope", "block_reason", "unblock_condition",
    }
    return {
        str(concept["key"]): str(concept.get("short_help") or concept.get("definition") or "")
        for concept in concepts
        if isinstance(concept, dict) and concept.get("key") in wanted
    }


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------

_FRONTMATTER_RECONCILE_STATUSES = frozenset({
    "planned", "draft", "ready", "in_progress", "blocked",
    "active", "done", "superseded", "retired",
})


def _checkpoint_epoch(state: dict) -> float | None:
    """Return checkpoint timestamp seconds, or None when unavailable."""
    raw = state.get("created_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _should_reconcile_frontmatter_status(
    frontmatter_status: str,
    durable_state: dict,
    file_mtime: float,
    spec_path: Path | None = None,
) -> bool:
    """Whether a newer spec-file status should repair a stale durable row."""
    durable_status = str(durable_state.get("status", ""))
    if durable_status == frontmatter_status:
        return False
    if frontmatter_status not in _FRONTMATTER_RECONCILE_STATUSES:
        return False
    payload = durable_state.get("payload")
    if spec_path is not None and isinstance(payload, dict):
        checkpoint_path = payload.get("spec_path")
        if checkpoint_path and Path(str(checkpoint_path)) != spec_path:
            return False
    checkpoint_mtime = _checkpoint_epoch(durable_state)
    if checkpoint_mtime is None:
        return True
    return file_mtime >= checkpoint_mtime


@dataclass
class CacheEntry:
    path: Path
    mtime: float
    frontmatter: dict
    body_md: Optional[str] = None  # None = not yet loaded (Tier 2)


class SpecCache:
    """mtime-keyed two-tier cache.

    Tier 1 — frontmatter dicts, always in memory.
    Tier 2 — body markdown, lazy (loaded on first access per spec).
    """

    def __init__(self, specs_dir: Path, status_store=None) -> None:
        self._specs_dir = specs_dir
        self._status_store = status_store
        self._dir_mtime: float = 0.0
        self._entries: dict[str, CacheEntry] = {}  # keyed by spec id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warm(self) -> None:
        """Load all Tier 1 frontmatter at startup."""
        self._dir_mtime = os.stat(self._specs_dir).st_mtime
        with os.scandir(self._specs_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(".md"):
                    continue
                self._load_entry(Path(entry.path), entry.stat().st_mtime)

    def get_all_frontmatter(self) -> list[dict]:
        """Return all frontmatter dicts, checking mtime for staleness."""
        dir_m = os.stat(self._specs_dir).st_mtime
        if dir_m != self._dir_mtime:
            self._reconcile(dir_m)

        with os.scandir(self._specs_dir) as entries:
            for de in entries:
                if not de.name.endswith(".md"):
                    continue
                path = Path(de.path)
                mtime = de.stat().st_mtime
                # Find existing entry by path
                entry = self._entry_by_path(path)
                if entry is None:
                    # New file appeared between reconcile and scandir
                    self._load_entry(path, mtime)
                elif entry.mtime != mtime:
                    # File changed — re-parse
                    self._reload_entry(entry, mtime)

        # Return copies with internal keys stripped, plus observable readiness
        # and admission evidence. Stored lifecycle status remains untouched.
        public = [self._public_fm(e.frontmatter, e.mtime) for e in self._entries.values()]
        by_id = {str(item.get("id")): item for item in public if item.get("id")}
        help_text = _registry_field_help()
        try:
            from lifecycle import derive_admission
        except ImportError:
            derive_admission = None
        if derive_admission is not None:
            for item in public:
                if item.get("status") in {"done", "superseded", "active", "retired"}:
                    continue
                body = self.get_body(str(item.get("id"))) or ""
                admission = derive_admission(item, body, by_id)
                item["readiness"] = admission.readiness.level.value
                item["readiness_evidence"] = list(admission.readiness.findings)
                item["readiness_dimensions"] = [
                    {
                        "name": dimension.name,
                        "result": dimension.level.value,
                        "evidence": list(dimension.evidence),
                    }
                    for dimension in admission.readiness.dimensions
                ]
                item["run_state"] = admission.state
                item["run_state_reason"] = admission.reason
                item["_help"] = dict(help_text)
        return public

    def get_body(self, spec_id: str) -> Optional[str]:
        """Return body markdown for a spec, loading lazily."""
        entry = self._entries.get(spec_id)
        if entry is None:
            return None
        mtime = os.stat(entry.path).st_mtime
        if entry.mtime != mtime:
            self._reload_entry(entry, mtime)
        if entry.body_md is None:
            entry.body_md = self._read_body(entry.path)
        return entry.body_md

    def get_path(self, spec_id: str) -> Optional[Path]:
        """Return the source file path for a spec."""
        self.get_all_frontmatter()
        entry = self._entries.get(spec_id)
        return entry.path if entry else None

    def search(self, q: str) -> list[dict]:
        """In-memory case-insensitive search over frontmatter fields + body."""
        self.get_all_frontmatter()  # ensure Tier 1 is fresh

        # Warm all bodies for changed/new files
        with os.scandir(self._specs_dir) as entries:
            for de in entries:
                if not de.name.endswith(".md"):
                    continue
                path = Path(de.path)
                mtime = de.stat().st_mtime
                entry = self._entry_by_path(path)
                if entry is not None and entry.body_md is None:
                    entry.body_md = self._read_body(path)
                elif entry is not None and entry.mtime != mtime:
                    self._reload_entry(entry, mtime)
                    if entry.body_md is None:
                        entry.body_md = self._read_body(path)

        ql = q.lower()
        results = []
        for entry in self._entries.values():
            spec_id = entry.frontmatter.get("id", "")
            title = entry.frontmatter.get("_title", "")
            body = entry.body_md or ""
            haystack = (spec_id + " " + title + " " + body).lower()
            idx = haystack.find(ql)
            if idx == -1:
                continue
            start = max(0, idx - 60)
            end = min(len(haystack), idx + len(ql) + 60)
            excerpt = "..." + haystack[start:end] + "..."
            results.append({
                "id": spec_id,
                "title": title or spec_id,
                "status": self._effective_status(entry.frontmatter),
                "excerpt": excerpt,
            })
        return results

    def update_status(self, spec_id: str, status: str) -> None:
        """Write new status to spec frontmatter and the durable checkpoint store."""
        entry = self._entries.get(spec_id)
        if entry is None:
            raise KeyError(f"spec not found: {spec_id}")
        if status not in _VALID_SPEC_STATUSES:
            raise ValueError(f"invalid status: {status}")
        allowed_statuses = _allowed_statuses_for_spec(entry.frontmatter)
        if status not in allowed_statuses:
            raise ValueError(_status_error_for_spec(entry.frontmatter, status) or f"invalid status: {status}")

        self._update_status_file(entry, status)

        if self._status_store is not None:
            self._status_store.update_state(
                spec_id,
                status,
                source="board",
                payload={"spec_path": str(entry.path)},
            )
            return

    def _update_status_file(self, entry: CacheEntry, status: str) -> None:
        """Legacy file-backed status write used when no durable store is configured."""
        text = entry.path.read_text(encoding="utf-8")

        # Split on --- delimiters
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"malformed frontmatter in {entry.path}")

        # parts[0] = "" (before first ---), parts[1] = fm text, parts[2] = body
        fm_block = parts[1]
        body_block = parts[2]

        new_fm = re.sub(
            r"^status:.*$",
            f"status: {status}",
            fm_block,
            flags=re.MULTILINE,
        )
        new_content = "---" + new_fm + "---" + body_block

        tmp = entry.path.with_suffix(".md.tmp")
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(tmp, entry.path)

        # Sync mtime into cache — no re-read needed
        entry.mtime = os.stat(entry.path).st_mtime
        entry.frontmatter["status"] = status
        # Invalidate body so next get_body re-reads (body unchanged but mtime changed)
        # Actually body is unchanged; we just keep it to avoid unnecessary disk I/O.
        # But our mtime comparison would re-read on next call — preserve body.
        # We already updated mtime above, so body is still valid.

    def force_refresh(self) -> None:
        """Wipe cache and re-warm all frontmatter from disk."""
        self._entries.clear()
        self._dir_mtime = 0.0
        self.warm()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reconcile(self, dir_m: float) -> None:
        """Add new files and remove deleted ones when dir mtime changed."""
        self._dir_mtime = dir_m
        on_disk: set[Path] = set()
        with os.scandir(self._specs_dir) as entries:
            for de in entries:
                if de.name.endswith(".md"):
                    on_disk.add(Path(de.path))

        # Remove entries whose files were deleted
        to_remove = [sid for sid, e in self._entries.items() if e.path not in on_disk]
        for sid in to_remove:
            del self._entries[sid]

        # New files will be picked up by the scandir loop in get_all_frontmatter

    def _entry_by_path(self, path: Path) -> Optional[CacheEntry]:
        for e in self._entries.values():
            if e.path == path:
                return e
        return None

    def _load_entry(self, path: Path, mtime: float) -> None:
        """Parse a spec file and store it in cache."""
        fm, body = _parse_spec_file(path)
        spec_id = fm.get("id")
        if not spec_id:
            return  # Skip files without an id field
        entry = CacheEntry(path=path, mtime=mtime, frontmatter=fm, body_md=None)
        # We don't store body in Tier 1 — only load it on demand
        self._entries[spec_id] = entry

    def _reload_entry(self, entry: CacheEntry, mtime: float) -> None:
        """Re-parse a changed file in-place."""
        fm, body = _parse_spec_file(entry.path)
        new_id = fm.get("id")
        old_id = entry.frontmatter.get("id")
        entry.mtime = mtime
        entry.frontmatter = fm
        entry.body_md = None  # Invalidate Tier 2 on file change
        if new_id and new_id != old_id:
            # ID changed — re-key
            if old_id in self._entries:
                del self._entries[old_id]
            if new_id:
                self._entries[new_id] = entry

    def _read_body(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            return ""
        return parts[2].lstrip("\n")

    def _public_fm(self, fm: dict, mtime: float = 0.0) -> dict:
        """Return frontmatter dict without internal _body key, plus _mtime."""
        out = {k: v for k, v in fm.items() if k != "_body"}
        out["status"] = self._effective_status(fm, mtime)
        if mtime:
            out["_mtime"] = mtime
        return out

    def _effective_status(self, fm: dict, file_mtime: float = 0.0) -> str:
        spec_id = fm.get("id")
        file_status = str(fm.get("status", "draft"))
        if self._status_store is not None and spec_id:
            state = self._status_store.get_state(spec_id)
            if state and state.get("status"):
                if _should_reconcile_frontmatter_status(file_status, state, file_mtime, self._entries[spec_id].path):
                    self._status_store.update_state(
                        spec_id,
                        file_status,
                        source="frontmatter-reconcile",
                        note="terminal spec frontmatter was newer than durable transient status",
                        payload={"file_mtime": file_mtime},
                    )
                    return file_status
                return str(state["status"])
        return file_status


def _parse_spec_file(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter and body from a spec file.

    Returns (frontmatter_dict, body_str). frontmatter_dict contains _title
    extracted from the first H1 in body. Does NOT store _body in the dict.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    fm_text = parts[1]
    body = parts[2].lstrip("\n")

    try:
        _loaded = yaml.safe_load(fm_text)
        fm = _loaded if isinstance(_loaded, dict) else {}
    except yaml.YAMLError:
        fm = {}

    # Extract title from first H1 in body
    for line in body.splitlines():
        if line.startswith("# "):
            fm["_title"] = line[2:].strip()
            break

    # Extract first H2 section matching common "what is this about" headings.
    # Used by the board's hover tooltip to give context without opening the spec.
    section_re = re.compile(
        r"^##\s+(Problem|Issue|Why|Background|Context|Description|Summary|Overview)\b",
        re.IGNORECASE,
    )
    in_section = False
    section_lines: list[str] = []
    for line in body.splitlines():
        if section_re.match(line):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            section_lines.append(line)
    snippet = "\n".join(section_lines).strip()
    if snippet:
        # Strip leading bullet/quote/heading markup for cleaner tooltip text
        snippet = re.sub(r"(?m)^\s*[#*\->`]+\s*", "", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if snippet:
            fm["_problem"] = snippet[:280]

    return fm, body


def _graph_display_title(spec_id: str, title: str) -> str:
    """Title for graph labels.

    Bug specs often use H1s like `BUG-001 — Short title`. Graph labels already
    render the spec ID on the first line, so strip that leading duplicate.
    """
    cleaned = (title or spec_id).strip()
    if not spec_id:
        return cleaned
    pattern = rf"^{re.escape(spec_id)}\s*(?:[-–—:]\s*)?"
    cleaned = re.sub(pattern, "", cleaned, count=1).strip()
    return cleaned or spec_id


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Nightshift Board")

# --- Observability (SPEC-122) -------------------------------------------------
# Dedicated logger with its own stderr handler + propagate=False. This emits
# regardless of uvicorn's log_level="warning" and without touching the uvicorn
# config. stderr is already captured by board.restart.log; no new file/rotation
# (right altitude for a local single-user board).
log = logging.getLogger("nightshift.board")
if not log.handlers:  # idempotent: module may be re-imported (export path, tests)
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False


@app.exception_handler(Exception)
async def _log_unhandled(request: Request, exc: Exception) -> PlainTextResponse:
    """Log any unhandled endpoint exception with traceback + path + a stable code.

    Returns a PLAIN-TEXT 500 (not JSON) on purpose: the frontend pollSpecs loop
    has no response.ok check and relies on response.json() THROWING on this body
    to keep the board on its previous state. A JSON 500 body would parse and blank
    the board — the exact SPEC-121 failure. Do not change this to JSONResponse.
    """
    error_code = uuid4().hex[:8]
    log.error(
        "unhandled error_code=%s method=%s path=%s",
        error_code, request.method, request.url.path,
        exc_info=True,
    )
    return PlainTextResponse("Internal Server Error", status_code=500)


cache: SpecCache  # initialized in __main__
project_name: str = "PROJECT"  # set in __main__
reports_dir: Optional[Path] = None  # set in __main__
history_db_dir: Optional[Path] = None  # set in __main__
reads_file: Optional[Path] = None   # set in __main__
status_store = None

# Canonical spec lifecycle statuses come from spec_frontmatter.
try:
    from spec_frontmatter import (
        VALID_SPEC_STATUSES as _VALID_SPEC_STATUSES,
        NFR_FAMILY_STATUSES as _NFR_FAMILY_STATUSES,
        STATUS_SEMANTICS as _STATUS_SEMANTICS,
        VALID_COLUMN_STATES as _VALID_COLUMN_STATES,
        allowed_statuses_for_spec as _allowed_statuses_for_spec,
        status_error_for_spec as _status_error_for_spec,
        check_column_override as _check_column_override,
    )
except Exception:
    _VALID_SPEC_STATUSES = frozenset({
        "planned", "draft", "ready", "in_progress", "blocked",
        "active", "done", "superseded", "retired",
    })
    _NFR_FAMILY_STATUSES = frozenset({"active", "retired"})
    _STATUS_SEMANTICS = {
        "planned": "Validated future work, intentionally outside the current queue.",
        "draft": "Spec exists but acceptance criteria or approach are still being refined.",
        "ready": "Spec is implementation-ready with clear ACs and no unresolved blockers.",
        "in_progress": "Work is actively being implemented against this spec.",
        "blocked": "Execution cannot proceed until an external dependency or decision is resolved.",
        "done": "Acceptance criteria are satisfied and the spec outcome is complete.",
        "superseded": "Spec is replaced by a newer spec and should no longer be executed.",
        "active": "NFR spec is currently enforced as an active project constraint.",
        "retired": "NFR spec no longer applies and is kept for historical traceability.",
    }

    def _is_nfr_family(frontmatter: dict | None) -> bool:
        if not isinstance(frontmatter, dict):
            return False
        spec_id = frontmatter.get("id")
        spec_type = frontmatter.get("type")
        return (isinstance(spec_id, str) and spec_id.startswith("NFR-")) or spec_type == "nfr"

    def _allowed_statuses_for_spec(frontmatter: dict | None) -> frozenset:
        return _NFR_FAMILY_STATUSES if _is_nfr_family(frontmatter) else _VALID_SPEC_STATUSES

    def _status_error_for_spec(frontmatter: dict | None, status: str) -> str | None:
        if _is_nfr_family(frontmatter) and status not in _NFR_FAMILY_STATUSES:
            return (
                "NFR-family specs (id starts with NFR- or type is nfr) must use "
                f"status active or retired; got {status}"
            )
        if status not in _VALID_SPEC_STATUSES:
            return f"invalid status: {status}"
        return None

    _VALID_COLUMN_STATES = frozenset({"expanded", "collapsed", "hidden"})

    def _check_column_override(override: object) -> list:  # type: ignore[misc]
        """Fallback when spec_frontmatter is unavailable."""
        problems: list = []
        if not isinstance(override, dict):
            problems.append("board_column_defaults must be a mapping")
            return problems
        raw_states = override.get("default_state")
        if raw_states is not None:
            if not isinstance(raw_states, dict):
                problems.append("board_column_defaults.default_state must be a mapping")
            else:
                for col_id, state in raw_states.items():
                    if col_id not in _VALID_SPEC_STATUSES:
                        problems.append(
                            f"board_column_defaults.default_state has unknown status {col_id!r}"
                        )
                    elif state not in _VALID_COLUMN_STATES:
                        problems.append(
                            f"board_column_defaults.default_state[{col_id!r}] has invalid value"
                            f" {state!r} — must be one of: expanded, collapsed, hidden"
                        )
        raw_order = override.get("order")
        if raw_order is not None:
            if not isinstance(raw_order, list):
                problems.append("board_column_defaults.order must be a list")
            elif set(raw_order) != set(_VALID_SPEC_STATUSES) or len(raw_order) != len(_VALID_SPEC_STATUSES):
                missing = sorted(set(_VALID_SPEC_STATUSES) - set(raw_order))
                extra = sorted(set(raw_order) - set(_VALID_SPEC_STATUSES))
                problems.append(
                    f"board_column_defaults.order must be a full permutation"
                    f" (missing={missing}, extra={extra})"
                )
        return problems

STATUS_COLUMNS_ORDER = [
    "active", "planned", "draft", "blocked",
    "ready", "in_progress", "done", "superseded", "retired",
]

# Per-column default display state for a fresh board.
# "expanded" = full column, "collapsed" = narrow strip, "hidden" = not rendered.
_STATUS_DEFAULT_STATE = {
    "active":      "collapsed",
    "planned":     "collapsed",
    "draft":       "expanded",
    "blocked":     "collapsed",
    "ready":       "expanded",
    "in_progress": "expanded",
    "done":        "expanded",
    "superseded":  "hidden",
    "retired":     "hidden",
}

# Guard against drift: board columns must stay aligned with canonical statuses.
if set(STATUS_COLUMNS_ORDER) != set(_VALID_SPEC_STATUSES):
    missing = sorted(set(_VALID_SPEC_STATUSES) - set(STATUS_COLUMNS_ORDER))
    extra = sorted(set(STATUS_COLUMNS_ORDER) - set(_VALID_SPEC_STATUSES))
    raise RuntimeError(
        "STATUS_COLUMNS_ORDER out of sync with canonical statuses. "
        f"missing={missing} extra={extra}"
    )
if set(_STATUS_SEMANTICS.keys()) != set(_VALID_SPEC_STATUSES):
    missing = sorted(set(_VALID_SPEC_STATUSES) - set(_STATUS_SEMANTICS.keys()))
    extra = sorted(set(_STATUS_SEMANTICS.keys()) - set(_VALID_SPEC_STATUSES))
    raise RuntimeError(
        "STATUS_SEMANTICS out of sync with canonical statuses. "
        f"missing={missing} extra={extra}"
    )

def _build_status_columns(order: list, default_state_map: dict) -> list:
    """Build the STATUS_COLUMNS list from an order + default_state mapping."""
    return [
        {
            "id": s,
            "label": s.upper(),
            "meaning": _STATUS_SEMANTICS.get(s, ""),
            "default_state": default_state_map[s],
        }
        for s in order
    ]


STATUS_COLUMNS = _build_status_columns(STATUS_COLUMNS_ORDER, _STATUS_DEFAULT_STATE)
status_columns_json = json.dumps(STATUS_COLUMNS, ensure_ascii=False)


BOARD_BRANCH_FALLBACKS = ("main", "develop", "master")


class BoardBranchError(RuntimeError):
    """Raised when a board is launched from the wrong git branch."""


def _project_root_for_specs_dir(specs_dir: Path) -> Path:
    """Return the project root for a Nightshift specs directory."""
    return specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent


def _read_config_documents(config_path: Path) -> list[dict]:
    """Read dict documents from config.yaml, tolerating multi-document configs."""
    if not config_path.exists():
        return []
    try:
        docs = yaml.safe_load_all(config_path.read_text(encoding="utf-8"))
        return [doc for doc in docs if isinstance(doc, dict)]
    except Exception as exc:
        print(f"[board] WARNING: could not read {config_path}: {exc}", file=sys.stderr)
        return []


def _read_configured_main_branch(config_path: Path) -> "str | None":
    """Read git.main_branch from config.yaml, returning None when absent."""
    for cfg in _read_config_documents(config_path):
        git_cfg = cfg.get("git")
        if not isinstance(git_cfg, dict):
            continue
        branch = git_cfg.get("main_branch")
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
    return None


def _git_branch_exists(project_root: Path, branch: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    return result.returncode == 0


def _git_current_branch(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project_root), "branch", "--show-current"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    if result.returncode != 0:
        raise BoardBranchError(
            f"could not determine current git branch for {project_root}: {result.stderr.strip() or 'git failed'}"
        )
    branch = result.stdout.strip()
    if not branch:
        raise BoardBranchError(f"board must run from a named branch, but {project_root} is detached")
    return branch


def _expected_board_branch(project_root: Path, config_path: Path) -> str:
    configured = _read_configured_main_branch(config_path)
    if configured:
        if not _git_branch_exists(project_root, configured):
            raise BoardBranchError(
                f"configured git.main_branch '{configured}' does not exist in {project_root}"
            )
        return configured

    for branch in BOARD_BRANCH_FALLBACKS:
        if _git_branch_exists(project_root, branch):
            return branch

    choices = ", ".join(BOARD_BRANCH_FALLBACKS)
    raise BoardBranchError(
        f"unknown default branch for {project_root}: config.yaml has no git.main_branch "
        f"and none of the fallback branches exist ({choices})"
    )


def _validate_board_branch(project_root: Path, config_path: Path) -> str:
    """Ensure the board is serving the configured default branch checkout."""
    expected = _expected_board_branch(project_root, config_path)
    current = _git_current_branch(project_root)
    if current != expected:
        raise BoardBranchError(
            f"board must run from default branch '{expected}', but current branch is '{current}'"
        )
    return expected


def _apply_column_override(config_path: Path) -> "str | None":
    """Read per-project column override from config.yaml and reassign globals.

    If the override section is absent, malformed, or invalid, the canonical
    defaults (SPEC-074) are preserved unchanged.  Never raises — all errors
    are logged as warnings so a bad config.yaml never prevents board startup.

    Returns a one-line startup note (SPEC-079) when a valid, non-trivial
    override is applied, or None when the canonical defaults are in effect.

    Called from __main__ after specs_dir is resolved.  Also available to
    tests, which must save/restore the affected globals around each call.
    """
    global STATUS_COLUMNS, status_columns_json  # noqa: PLW0603

    if not config_path.exists():
        return None  # no project config — canonical defaults apply

    override = None
    for cfg in _read_config_documents(config_path):
        override = cfg.get("board_column_defaults")
        if override is not None:
            break
    if override is None:
        return None  # absent section — no change, SPEC-074 behaviour

    # --- Validate override via shared checker (SPEC-080 single source of truth) ---
    problems = _check_column_override(override)
    if problems:
        print(
            f"[board] WARNING: board_column_defaults in {config_path} is invalid"
            f" — {problems[0]} — override ignored",
            file=sys.stderr,
        )
        return None

    # Override is valid; merge state and order.
    raw_states = override.get("default_state") or {}
    merged_state = dict(_STATUS_DEFAULT_STATE)  # start from canonical
    for col_id, state in raw_states.items():
        merged_state[col_id] = state

    raw_order = override.get("order")
    if raw_order is not None:
        merged_order = raw_order
    else:
        merged_order = STATUS_COLUMNS_ORDER  # canonical order unchanged

    STATUS_COLUMNS = _build_status_columns(merged_order, merged_state)
    status_columns_json = json.dumps(STATUS_COLUMNS, ensure_ascii=False)

    # SPEC-079: build a startup note summarising what actually changed vs canonical.
    # Iterate in canonical column order for deterministic output.
    state_changes = [
        f"{col}={merged_state[col]}"
        for col in STATUS_COLUMNS_ORDER
        if merged_state[col] != _STATUS_DEFAULT_STATE[col]
    ]
    order_changed = merged_order != STATUS_COLUMNS_ORDER

    if not state_changes and not order_changed:
        return None  # override present but identical to canonical — no noise

    parts = state_changes[:]
    if order_changed:
        parts.append("order customized")
    return "▸ Column override loaded: " + ", ".join(parts)


def _load_read_set() -> set[str]:
    if reads_file is None or not reads_file.exists():
        return set()
    try:
        data = json.loads(reads_file.read_text(encoding="utf-8"))
        return set(data.get("read", []))
    except Exception:
        return set()


def _save_read_set(read_set: set[str]) -> None:
    if reads_file is None:
        return
    tmp = reads_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"read": sorted(read_set)}, indent=2), encoding="utf-8")
    os.replace(tmp, reads_file)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = HTML_TEMPLATE
    html = html.replace("__PROJECT__", project_name)
    html = html.replace("__STATUS_COLUMNS_JSON__", status_columns_json)
    html = html.replace("__PROJECT_KEY__", project_name)
    return HTMLResponse(html)


def _count_open_fds() -> Optional[int]:
    """Open FD count for THIS process. None if the platform exposes neither dir.

    /proc/self/fd on Linux, /dev/fd on macOS/BSD. listdir transiently uses one fd
    that is closed before return, so the count may read +1 high — fine for an
    "is it near the ceiling" signal. May raise OSError(EMFILE) when FDs are
    already exhausted; that failure is itself the definitive 'unhealthy' verdict
    and is handled by the caller.
    """
    for d in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(d):
            return len(os.listdir(d))
    return None


def _db_reachable(db_path: Optional[Path]) -> bool:
    """Best-effort durable-store liveness. The exists() guard prevents a plain
    connect() from recreating a deleted DB as empty and reporting healthy.
    closing() guarantees the probe itself never leaks an FD (the SPEC-121 class).
    """
    if db_path is None or not db_path.exists():
        return False
    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@app.get("/api/health")
async def health() -> dict:
    """Operational health — never returns 5xx itself; verdict is in the body.

    Surfaces the FD-exhaustion bug-class (SPEC-121) BEFORE it causes a 500:
    reports the board's own open-FD count vs its own RLIMIT_NOFILE soft limit.
    """
    try:
        return _health_payload()
    except Exception as exc:  # a health check that 500s when sick is useless
        log.error("health endpoint failure", exc_info=True)
        return {"status": "error", "detail": str(exc)}


def _health_payload() -> dict:
    soft = resource.getrlimit(resource.RLIMIT_NOFILE)[0]

    # FD probe first — before the db probe opens anything.
    open_fds: Optional[int] = None
    fd_exhausted = False
    try:
        open_fds = _count_open_fds()
    except OSError as exc:
        if exc.errno == errno.EMFILE:  # 24: the definitive exhaustion signal
            fd_exhausted = True

    if open_fds is not None and soft > 0:
        fd_pct: Optional[float] = round(open_fds / soft, 4)
        fd_headroom: Optional[int] = soft - open_fds
    else:
        fd_pct = None
        fd_headroom = None

    db_path = getattr(status_store, "db_path", None)
    db_ok = _db_reachable(db_path)

    try:
        spec_count: Optional[int] = len(cache._entries)  # cheap: no rescan, no db
    except Exception:
        spec_count = None

    # Overall = worst-of(fd, db). Unknown FD headroom is treated as unhealthy.
    if fd_exhausted or fd_pct is None or fd_pct >= 0.90:
        status = "unhealthy"
    elif fd_pct >= 0.70:
        status = "degraded"
    else:
        status = "ok"
    if not db_ok and status == "ok":
        status = "degraded"

    return {
        "status": status,
        "open_fds": open_fds,
        "fd_limit_soft": soft,
        "fd_pct": fd_pct,
        "fd_headroom": fd_headroom,
        "db_reachable": db_ok,
        "spec_count": spec_count,
    }


@app.get("/api/specs")
async def get_specs() -> list[dict]:
    return cache.get_all_frontmatter()


@app.get("/api/statuses")
async def get_statuses() -> list[dict]:
    """Canonical board status columns sourced from Nightshift definitions."""
    return STATUS_COLUMNS


@app.get("/api/vocabulary")
async def get_vocabulary() -> dict:
    """Versioned registry export for board/CLI/documentation consumers."""
    try:
        from vocabulary import load_registry
        registry = load_registry()
        return {"registry_version": registry["version"], "concepts": registry["concepts"]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"vocabulary unavailable: {exc}")


@app.get("/api/loop-observability")
async def get_loop_observability() -> dict:
    """Operational loop-health metrics from recorded run history."""
    if compute_loop_observability is None:
        raise HTTPException(status_code=503, detail="loop observability unavailable")
    return compute_loop_observability(history_db_dir)


@app.get("/api/spec/{spec_id}")
async def get_spec(spec_id: str) -> dict:
    all_fm = cache.get_all_frontmatter()
    fm = next((f for f in all_fm if f.get("id") == spec_id), None)
    if not fm:
        raise HTTPException(status_code=404, detail=f"spec not found: {spec_id}")
    body = cache.get_body(spec_id)
    return {
        "frontmatter": fm,
        "body_md": body,
        "title": fm.get("_title", spec_id),
    }


@app.put("/api/spec/{spec_id}/status")
async def update_status(spec_id: str, payload: dict) -> dict:
    status = payload.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status required")
    try:
        cache.update_status(spec_id, status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"spec not found: {spec_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.get("/api/spec/{spec_id}/status/history")
async def get_status_history(spec_id: str) -> dict:
    if not any(f.get("id") == spec_id for f in cache.get_all_frontmatter()):
        raise HTTPException(status_code=404, detail=f"spec not found: {spec_id}")
    store = getattr(cache, "_status_store", None)
    if store is None:
        return {"spec_id": spec_id, "history": []}
    return {"spec_id": spec_id, "history": store.get_state_history(spec_id)}


@app.get("/api/search")
async def search(q: str = "") -> list[dict]:
    if not q:
        return []
    return cache.search(q)


@app.get("/api/graph")
async def graph() -> dict:
    specs = cache.get_all_frontmatter()
    nodes = []
    for s in specs:
        sid = s.get("id")
        if not sid:
            continue
        title = s.get("_title", sid)
        graph_title = _graph_display_title(sid, title)
        short_title = graph_title[:20] if len(graph_title) > 20 else graph_title
        nodes.append({
            "id": sid,
            "label": f"{sid}\n{short_title}",
            "status": s.get("status", "draft"),
            "group": s.get("status", "draft"),
            "provides": s.get("provides") or [],
            "requires": s.get("requires") or [],
            "touches": s.get("touches") or [],
            "parent": s.get("parent"),
            # `type` rides server-side so the client can shape grouping/non-runnable
            # nodes (type in {main, nfr} — the nightshift-dag executable predicate)
            # without joining against the separately-fetched /api/specs list.
            "type": s.get("type"),
            "unlocks": [],
        })
    edges = []
    unlocks: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for s in specs:
        sid = s.get("id")
        if not sid:
            continue
        # Arrow direction follows execution order: prerequisite → dependent.
        # If sid has `after: [dep]`, then `dep` unblocks `sid` — draw `dep → sid`.
        for dep in (s.get("after") or []):
            edges.append({"from": dep, "to": sid, "arrows": "to"})
            unlocks.setdefault(dep, []).append(sid)
    for node in nodes:
        node["unlocks"] = sorted(unlocks.get(node["id"], []))
    # Parent (grouping-membership) edges — a SEPARATE list from `after:` edges so
    # dependency-graph semantics stay clean. Emitted parent → child, and only when
    # the parent resolves to an existing node (dangling parents are omitted;
    # nightshift-dag already flags them). Rendered dashed/no-arrow on the client.
    node_ids = {node["id"] for node in nodes}
    parent_edges = []
    for s in specs:
        sid = s.get("id")
        pid = s.get("parent")
        if sid and pid and pid in node_ids:
            parent_edges.append({"from": pid, "to": sid, "kind": "parent", "dashes": True})
    return {"nodes": nodes, "edges": edges, "parent_edges": parent_edges}


@app.post("/api/refresh")
async def refresh() -> dict:
    cache.force_refresh()
    return {"count": len(cache.get_all_frontmatter())}


# ──────────────────────────────────────────────────────────────────────
# SPEC-064: Cross-project dependency registry + external-spec proxy
# ──────────────────────────────────────────────────────────────────────


@app.get("/api/projects-registry")
def projects_registry() -> dict:
    """Return the cross-project registry written by nightshift-sync.py.

    If the file is missing (older project, never synced), return an empty
    shape so the client can degrade gracefully.
    """
    # `specs_dir` is assigned only in the __main__ block, so it is NOT a module
    # global under import-based launch (tests, `uvicorn board:app`). Use the
    # cache's specs dir — the same source the worktree endpoint relies on.
    f = cache._specs_dir.parent / "projects-registry.json"
    if not f.is_file():
        return {"generated_at": None, "projects": []}
    try:
        return json.loads(f.read_text())
    except Exception:
        return {"generated_at": None, "projects": [], "_error": "registry parse failed"}


@app.get("/api/external-spec/{port}/{spec_id}")
def external_spec(port: int, spec_id: str) -> dict:
    """Server-side proxy to another local board's /api/spec endpoint.

    Avoids cross-origin restrictions in the browser. Port is whitelisted to
    the board hash range (7800-7999) for SSRF protection. Timeout: 500ms.
    Returns {status: None, _unreachable: True} when the target isn't running.
    """
    if not (7800 <= port <= 7999):
        raise HTTPException(status_code=400, detail="port out of allowed board range (7800-7999)")
    # spec_id is path-restricted by FastAPI but we validate anyway to keep the
    # proxy from being a free URL passthrough.
    if not re.match(r"^[A-Z0-9_\-.]+$", spec_id):
        raise HTTPException(status_code=400, detail="invalid spec_id")
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/spec/{spec_id}", timeout=0.5
        ) as r:
            data = json.loads(r.read())
            # Surface just the status to keep the proxy payload tight.
            fm = (data or {}).get("frontmatter") or {}
            return {"status": fm.get("status"), "id": spec_id}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return {"status": None, "_unreachable": True, "id": spec_id}


_REPORTS_EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    "build", "dist", "DerivedData", ".claude", ".cortex",
    ".cache", ".next", "target", "Pods",
}


def _project_root_for_reports() -> Optional[Path]:
    """Project root used as the base for recursive `reports/` discovery."""
    if reports_dir is None:
        return None
    # reports_dir is `<project>/.nightshift/reports`; its grandparent is the project root.
    root = reports_dir.parent.parent if reports_dir.parent.name == ".nightshift" else reports_dir.parent
    return root if root and root.exists() else None


def _iter_report_files(root: Path):
    """Yield every *.md file inside any directory named 'reports' under root."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _REPORTS_EXCLUDE_DIRS]
        if Path(dirpath).name != "reports":
            continue
        for fname in filenames:
            if fname.endswith(".md"):
                yield Path(dirpath) / fname


def _resolve_report_path(filename: str) -> tuple[Path, Path]:
    root = _project_root_for_reports()
    if root is None:
        raise HTTPException(status_code=503, detail="reports not configured")
    if ".." in Path(filename).parts or filename.startswith("/") or filename.startswith("\\"):
        raise HTTPException(status_code=400, detail="invalid path")
    # SPEC-071 R7: realpath-normalize BOTH sides before the containment check so
    # a firmlink/symlink (e.g. macOS Dropbox) on one side can't defeat it.
    root = Path(os.path.realpath(str(root)))
    candidate = Path(os.path.realpath(str(root / filename)))
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="path escapes project root")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    return root, candidate


def _open_in_vscode(path: Path) -> dict:
    target = str(path.resolve())
    # SPEC-071 R8: a path that still carries an unresolved path token must never
    # reach the shell — refuse rather than open a garbage path. Path tokens are
    # resolved at egress; a residual '{{' here means a resolution bug upstream.
    if "{{" in target:
        raise HTTPException(
            status_code=400,
            detail="unresolved path token in target — refusing to open",
        )
    code_bin = shutil.which("code")
    if code_bin:
        cmd = [code_bin, "-n", target]
    elif sys.platform == "darwin":
        cmd = ["open", "-n", "-a", "Visual Studio Code", target]
    else:
        raise HTTPException(status_code=503, detail="VS Code CLI not found")
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to open VS Code: {e}")
    return {"ok": True, "path": target}


@app.get("/api/reports")
async def get_reports() -> list[dict]:
    """List every Markdown file inside any `reports/` directory in the project,
    not just `.nightshift/reports/`. Agents tend to drop reports next to the
    artifact they reviewed (e.g. `App/<Package>/reports/...`)."""
    root = _project_root_for_reports()
    if root is None:
        return []
    read_set = _load_read_set()
    result = []
    for path in _iter_report_files(root):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        rel_str = str(rel)
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append({
            "filename": rel_str,        # unique identifier (path under project root)
            "name": path.name,           # short display name
            "mtime": stat.st_mtime,
            "is_read": rel_str in read_set,
        })
    # Newest first by mtime
    result.sort(key=lambda r: r["mtime"], reverse=True)
    return result


@app.get("/api/report/{filename:path}")
async def get_report(filename: str) -> dict:
    """Read a single report by its project-relative path (slashes allowed)."""
    _, candidate = _resolve_report_path(filename)
    return {"filename": filename, "content": candidate.read_text(encoding="utf-8")}


@app.post("/api/open/spec/{spec_id}")
async def open_spec_in_vscode(spec_id: str) -> dict:
    path = cache.get_path(spec_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"spec not found: {spec_id}")
    return _open_in_vscode(path)


@app.post("/api/open/report/{filename:path}")
async def open_report_in_vscode(filename: str) -> dict:
    _, candidate = _resolve_report_path(filename)
    return _open_in_vscode(candidate)


@app.get("/api/worktree-status")
async def get_worktree_status() -> dict:
    """For each spec, report any worktree (other than the board's working tree)
    where the spec has a different `status:` than what the board sees on main.

    Returns: { spec_id: [{ "branch": str, "status": str, "path": str }, ...] }
    Only specs with at least one differing worktree are included.
    """
    # Use the cache's current specs directory. In tests/imported usage there is
    # no module-level `specs_dir` global from __main__.
    cur_specs_dir = cache._specs_dir
    project_root = (cur_specs_dir.parent.parent if cur_specs_dir.name == "specs" else cur_specs_dir.parent)
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return {}
    if result.returncode != 0:
        return {}

    # Parse `git worktree list --porcelain` output. Records separated by blank lines.
    worktrees: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current.get("worktree"):
                worktrees.append(current)
            current = {}
            continue
        key, _, val = line.partition(" ")
        if key in ("worktree", "branch", "HEAD"):
            current[key] = val
    if current.get("worktree"):
        worktrees.append(current)

    # Build {spec_id: status} for the board's main view (uses cache)
    main_statuses = {f.get("id"): f.get("status") for f in cache.get_all_frontmatter() if f.get("id")}
    main_path = str(project_root.resolve())

    out: dict[str, list[dict]] = {}
    rel_specs = cur_specs_dir.relative_to(project_root)  # e.g. ".nightshift/specs"
    rel_specs_str = str(rel_specs) + "/"
    for wt in worktrees:
        wt_path = wt.get("worktree", "")
        if not wt_path or os.path.realpath(wt_path) == os.path.realpath(main_path):
            continue
        wt_specs_dir = Path(wt_path) / rel_specs
        if not wt_specs_dir.exists():
            continue
        branch = (wt.get("branch") or "").replace("refs/heads/", "") or "(detached)"
        wt_head = wt.get("HEAD", "")

        # Only surface specs actually modified in this worktree branch — not all
        # specs whose status merely differs because main moved forward since the
        # worktree was created.  Compute the set of spec filenames changed between
        # the merge-base and the worktree HEAD, plus any uncommitted working-tree
        # changes. If the git calls succeed we use this as a filter; on failure we
        # fall back to the original behaviour (scan all specs).
        use_git_filter = False
        modified_spec_names: set[str] = set()
        try:
            mb = subprocess.run(
                ["git", "-C", str(project_root), "merge-base", "HEAD", wt_head],
                capture_output=True, text=True, timeout=2,
            )
            if mb.returncode == 0 and mb.stdout.strip():
                dd = subprocess.run(
                    ["git", "-C", str(project_root), "diff", "--name-only",
                     mb.stdout.strip(), wt_head, "--", rel_specs_str],
                    capture_output=True, text=True, timeout=2,
                )
                for f in dd.stdout.splitlines():
                    if f.endswith(".md"):
                        modified_spec_names.add(Path(f).name)
            # Include uncommitted working-directory changes inside the worktree
            ud = subprocess.run(
                ["git", "-C", wt_path, "diff", "--name-only", "HEAD", "--", rel_specs_str],
                capture_output=True, text=True, timeout=2,
            )
            for f in ud.stdout.splitlines():
                if f.endswith(".md"):
                    modified_spec_names.add(Path(f).name)
            use_git_filter = True
        except Exception:
            pass

        with os.scandir(wt_specs_dir) as entries:
            for entry in entries:
                if not entry.name.endswith(".md"):
                    continue
                if use_git_filter and entry.name not in modified_spec_names:
                    continue
                try:
                    fm, _ = _parse_spec_file(Path(entry.path))
                except Exception:
                    continue
                spec_id = fm.get("id")
                wt_status = fm.get("status")
                if not spec_id or not wt_status:
                    continue
                if main_statuses.get(spec_id) == wt_status:
                    continue  # same as main, don't surface
                out.setdefault(spec_id, []).append({
                    "branch": branch,
                    "status": wt_status,
                    "path": wt_path,
                })
    return out


@app.post("/api/reports/read")
async def mark_report_read(payload: dict) -> dict:
    filename = payload.get("filename", "")
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    read_set = _load_read_set()
    read_set.add(filename)
    _save_read_set(read_set)
    return {"ok": True}


@app.post("/api/reports/read-all")
async def mark_all_reports_read() -> dict:
    root = _project_root_for_reports()
    if root is None:
        raise HTTPException(status_code=503, detail="reports not configured")
    read_set = _load_read_set()
    count = 0
    for path in _iter_report_files(root):
        rel = str(path.relative_to(root))
        if rel not in read_set:
            read_set.add(rel)
            count += 1
    _save_read_set(read_set)
    return {"ok": True, "count": count}


# ---------------------------------------------------------------------------
# Embedded frontend
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NIGHTSHIFT · __PROJECT__</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #12141a;
  --surface: #1a1d24;
  --surface-hi: #22262f;
  --border: #2e3340;
  --text: #d4d4d4;
  --text-muted: #606474;
  --font: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
  --c-planned: #c084fc;
  --c-draft: #9b72cf;
  --c-ready: #4fc3f7;
  --c-in-progress: #ffb347;
  --c-blocked: #ff4444;
  --c-active: #f59e0b;
  --c-retired: #6b7280;
  --c-done: #39ff14;
  --c-superseded: #555;
  --header-h: 96px;
  --c-theme: #74c0fc;
}

html.light {
  --bg: #d8dce5;
  --surface: #e4e8f0;
  --surface-hi: #cdd2dc;
  --border: #b0b6c4;
  --text: #1e2128;
  --text-muted: #6b7280;
  --c-planned: #a855f7;
  --c-draft: #7c3aed;
  --c-ready: #0284c7;
  --c-in-progress: #d97706;
  --c-blocked: #dc2626;
  --c-active: #b45309;
  --c-retired: #9ca3af;
  --c-done: #16a34a;
  --c-superseded: #9ca3af;
}

/* hover tint auto-derives from theme color — no override needed per-theme */
:root, html.light {
  --hover: color-mix(in srgb, var(--c-theme) 18%, var(--surface));
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Header ── */
#header {
  position: sticky;
  top: 0;
  z-index: 200;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  border-top: 3px solid var(--c-theme);
  padding: 10px 16px 8px;
  flex-shrink: 0;
}

.header-row1 {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.logo {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.05em;
  color: var(--c-theme);
  white-space: nowrap;
}
.logo-project {
  opacity: 0.7;
  font-size: 12px;
  font-weight: 400;
}

.header-row1 .spacer { flex: 1; }

.btn {
  background: var(--surface-hi);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: var(--font);
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
  border-radius: 2px;
  white-space: nowrap;
  transition: background 0.1s, color 0.1s;
}
.btn:hover { background: var(--hover); }
.btn.active {
  background: var(--c-in-progress);
  color: #000;
  border-color: var(--c-in-progress);
}

.header-row2 {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.loop-metrics {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 10px;
}
.loop-metric {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  color: var(--text-muted);
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--c-theme) 8%, var(--surface));
  border-radius: 2px;
  padding: 3px 6px;
}
.loop-metric strong {
  color: var(--text);
  font-weight: 600;
}

#search {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: var(--font);
  font-size: 12px;
  padding: 5px 10px;
  width: 320px;
  border-radius: 2px;
  outline: none;
}
#search:focus { border-color: var(--c-theme); }
#search::placeholder { color: var(--text-muted); }

#btn-clear-search {
  display: none;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font);
  font-size: 11px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 2px;
  line-height: 1;
}
#btn-clear-search:hover { color: var(--text); border-color: var(--text-muted); }
#btn-clear-search.visible { display: block; }

/* ── Main area ── */
#main {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Board tab ── */
#board-view {
  flex: 1;
  overflow-x: auto;
  overflow-y: hidden;
  display: flex;
  padding: 12px;
  gap: 10px;
}

/* ── Search results ── */
#search-results {
  display: none;
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

#search-results.visible { display: block; }

.search-empty {
  color: var(--text-muted);
  text-align: center;
  margin-top: 60px;
  font-size: 13px;
}

.search-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 700px;
}

/* ── Column ── */
.column {
  flex: 1;
  min-width: 140px;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  position: relative;
}

/* Attention state: blocked column contains one or more specs. */
.column.column--blocked-hot {
  border-color: color-mix(in srgb, var(--c-blocked) 70%, var(--border));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--c-blocked) 45%, transparent);
}
.column--collapsed.column--blocked-hot {
  background: color-mix(in srgb, var(--c-blocked) 12%, var(--surface));
  border-color: color-mix(in srgb, var(--c-blocked) 70%, var(--border));
}

.column--collapsed {
  flex: none !important;
  width: 32px !important;
  min-width: 32px !important;
  overflow: hidden;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.15s;
}
.column--collapsed:hover { opacity: 1; }
.col-collapsed-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 0;
  gap: 8px;
  height: 100%;
}
.col-collapsed-name {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  white-space: nowrap;
}
.col-collapsed-count {
  font-size: 9px;
  color: var(--text-muted);
}

.col-header {
  position: sticky;
  top: 0;
  background: color-mix(in srgb, var(--c-theme) 8%, var(--surface));
  border-bottom: 2px solid color-mix(in srgb, var(--c-theme) 30%, var(--border));
  padding: 8px 10px 6px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  display: flex;
  justify-content: space-between;
  align-items: center;
  z-index: 10;
}

.col-name { color: var(--text); }
.col-name-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.col-meaning {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid color-mix(in srgb, var(--c-theme) 45%, var(--border));
  color: var(--text-muted);
  font-size: 9px;
  cursor: help;
}

.col-count {
  background: color-mix(in srgb, var(--c-theme) 22%, var(--border));
  color: var(--text);
  border-radius: 9px;
  padding: 1px 6px;
  font-size: 10px;
}

.card-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
  min-height: 80px;
}

/* ── Card ── */
.card {
  background: var(--surface-hi);
  border: 1px solid var(--border);
  border-left-width: 4px;
  border-left-color: var(--text-muted);
  border-radius: 3px;
  padding: 8px 8px 6px;
  margin-bottom: 6px;
  cursor: pointer;
  position: relative;
  transition: background 0.1s;
}
.card[data-status="planned"]     { border-left-color: var(--c-planned); }
.card[data-status="draft"]       { border-left-color: var(--c-draft); }
.card[data-status="ready"]       { border-left-color: var(--c-ready); }
.card[data-status="in_progress"] { border-left-color: var(--c-in-progress); }
.card[data-status="blocked"]     { border-left-color: var(--c-blocked); }
.card[data-status="active"]      { border-left-color: var(--c-active); }
.card[data-status="done"]        { border-left-color: var(--c-done); }
.card[data-status="superseded"]  { border-left-color: var(--c-superseded); }
.card[data-status="retired"]     { border-left-color: var(--c-retired); }

.card:hover { background: var(--hover); color: var(--text); cursor: grab; }
.card.sortable-drag { opacity: 0.6; transform: rotate(1.5deg); }
.card.sortable-ghost { opacity: 0.3; }
.card.card--active {
  background: var(--hover);
  outline: 2px solid var(--c-theme);
  outline-offset: -1px;
  box-shadow: 0 0 0 1px var(--c-theme), 0 0 18px rgba(116,192,252,0.22);
}
/* Transient highlight applied while hovering a chip in the RECENT bar.
   No layout/scroll/zoom change — just an outline so you can spot the card.
   Distinct from .card--active (open panel) so they can co-exist. */
.card.card--peek {
  outline: 2px dashed var(--c-theme);
  outline-offset: -2px;
}

/* ── Column resize handle ── */
.col-resize {
  position: absolute;
  right: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 20;
  background: transparent;
  transition: background 0.15s;
}
.col-resize:hover, .col-resize.dragging { background: var(--c-theme); opacity: 0.5; }

/* ── Column visibility dropdown ── */
#col-vis-wrap { position: relative; }
#col-vis-dropdown {
  display: none;
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 6px 0;
  z-index: 500;
  min-width: 170px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
#col-vis-dropdown.open { display: block; }
#type-filter-wrap { position: relative; }
#type-filter-dropdown {
  display: none;
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 6px 0;
  z-index: 500;
  min-width: 150px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.5);
}
#type-filter-dropdown.open { display: block; }
.type-filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
  color: var(--text);
  user-select: none;
}
.type-filter-item:hover { background: var(--surface-hi); }
.type-filter-item input[type=checkbox] { accent-color: var(--c-theme); cursor: pointer; }
.col-vis-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
  color: var(--text);
  user-select: none;
}
.col-vis-item:hover { background: var(--surface-hi); }
.col-vis-item input[type=checkbox] { accent-color: var(--c-theme); cursor: pointer; }
.col-vis-left { display: flex; align-items: center; gap: 8px; flex: 1; }
.col-drag-handle {
  color: var(--text-muted);
  cursor: grab;
  font-size: 14px;
  line-height: 1;
  user-select: none;
  padding: 0 4px 0 0;
}
.col-drag-handle:hover { color: var(--text); }
.col-collapse-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font);
  font-size: 10px;
  padding: 1px 5px;
  cursor: pointer;
  border-radius: 2px;
}
.col-collapse-btn:hover { color: var(--text); border-color: var(--text-muted); }

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 3px;
}

.card-id {
  font-size: 10px;
  font-weight: 600;
  color: var(--c-ready);
}

.card-dots {
  font-size: 10px;
  color: var(--text-muted);
  letter-spacing: 1px;
}

.card-title {
  font-size: 11px;
  color: var(--text);
  line-height: 1.4;
  margin-bottom: 4px;
  word-break: break-word;
}

.card-meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.badge {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid var(--border);
  color: var(--text-muted);
  background: var(--bg);
}

.dep-badge {
  font-size: 9px;
  color: var(--text-muted);
  margin-left: auto;
  white-space: nowrap;
}

/* Worktree-state badge — shows when a sibling git worktree has the spec
   in a different status than the board's main view. */
.wt-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--c-theme) 15%, var(--surface));
  border: 1px solid color-mix(in srgb, var(--c-theme) 50%, var(--border));
  color: var(--c-theme);
  margin-top: 3px;
  white-space: nowrap;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Detail panel ── */
#panel {
  --pw: 40%;
  position: fixed;
  right: calc(-1 * var(--pw));
  top: var(--header-h, 0px);
  width: var(--pw);
  min-width: 280px;
  height: calc(100vh - var(--header-h, 0px));
  background: var(--surface);
  border-left: 1px solid var(--border);
  z-index: 500;
  display: flex;
  flex-direction: column;
  transition: right 0.25s ease;
  overflow: hidden;
}

#panel.open { right: 0; }

#panel-resize {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  transition: background 0.15s;
}
#panel-resize:hover, #panel-resize.dragging { background: var(--c-theme); opacity: 0.5; }

#panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

#panel-id {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-theme);
}

#panel-close {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
  padding: 0 4px;
}
#panel-close:hover { color: var(--text); }
#btn-copy-id {
  background: var(--surface-hi);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  line-height: 1;
  opacity: 1;
  flex-shrink: 0;
  transition: background 0.1s, border-color 0.1s, color 0.1s;
}
#btn-copy-id:hover, #btn-copy-id:focus {
  background: var(--hover);
  border-color: var(--c-theme);
  color: var(--c-theme);
  outline: none;
}

#panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

#panel-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}

.meta-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
  margin-bottom: 12px;
}
.meta-table td {
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}
.meta-table td:first-child {
  color: var(--text-muted);
  width: 80px;
}
/* Status dropdown in the detail panel */
#panel-status-select {
  background: var(--surface-hi);
  color: var(--text);
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-muted);
  border-radius: 3px;
  font-size: 11px;
  font-family: monospace;
  padding: 2px 6px;
  cursor: pointer;
  width: 100%;
}
#panel-status-select:focus { outline: none; border-color: var(--c-theme); }
#panel-status-select[data-status="planned"]     { border-left-color: var(--c-planned); }
#panel-status-select[data-status="draft"]       { border-left-color: var(--c-draft); }
#panel-status-select[data-status="ready"]       { border-left-color: var(--c-ready); }
#panel-status-select[data-status="in_progress"] { border-left-color: var(--c-in-progress); }
#panel-status-select[data-status="blocked"]     { border-left-color: var(--c-blocked); }
#panel-status-select[data-status="active"]      { border-left-color: var(--c-active); }
#panel-status-select[data-status="done"]        { border-left-color: var(--c-done); }
#panel-status-select[data-status="superseded"]  { border-left-color: var(--c-superseded); }
#panel-status-select[data-status="retired"]     { border-left-color: var(--c-retired); }

.chips-row {
  margin-bottom: 8px;
  font-size: 11px;
}
.chips-label {
  color: var(--text-muted);
  display: inline-block;
  width: 60px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--surface-hi);
  border: 1px solid var(--border);
  color: var(--c-ready);
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 2px;
  margin: 2px 3px 2px 0;
  cursor: pointer;
  text-decoration: none;
}
.chip:hover { background: var(--border); }
.chip[data-status="planned"]     { color: var(--c-planned); border-color: color-mix(in srgb, var(--c-planned) 60%, var(--border)); }
.chip[data-status="draft"]       { color: var(--c-draft); border-color: color-mix(in srgb, var(--c-draft) 60%, var(--border)); }
.chip[data-status="ready"]       { color: var(--c-ready); border-color: color-mix(in srgb, var(--c-ready) 60%, var(--border)); }
.chip[data-status="in_progress"] { color: var(--c-in-progress); border-color: color-mix(in srgb, var(--c-in-progress) 60%, var(--border)); }
.chip[data-status="blocked"]     { color: var(--c-blocked); border-color: var(--c-blocked); background: color-mix(in srgb, var(--c-blocked) 12%, var(--surface-hi)); }
.chip[data-status="active"]      { color: var(--c-active); border-color: color-mix(in srgb, var(--c-active) 60%, var(--border)); }
.chip[data-status="done"]        { color: var(--c-done); border-color: var(--c-done); background: color-mix(in srgb, var(--c-done) 10%, var(--surface-hi)); }
.chip[data-status="superseded"]  { color: var(--c-superseded); border-color: color-mix(in srgb, var(--c-superseded) 60%, var(--border)); }
.chip[data-status="retired"]     { color: var(--c-retired); border-color: color-mix(in srgb, var(--c-retired) 60%, var(--border)); }
.chip-status {
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: inherit;
  opacity: 0.9;
}
/* SPEC-064: cross-project external dep */
.chip[data-external="1"] {
  border-style: dashed;
  background: color-mix(in srgb, var(--c-theme) 8%, var(--surface-hi));
}
.chip-ext-icon {
  font-size: 9px;
  opacity: 0.7;
  margin-right: 2px;
}
.chip[data-external="1"][data-unreachable="1"] {
  opacity: 0.6;
}
.spec-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 0 5px;
  text-decoration: none;
  white-space: nowrap;
  transition: background 0.1s, border-color 0.1s, color 0.1s;
}
.spec-link:hover { background: var(--hover); }
.spec-link-status {
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.05em;
}
.spec-link[data-status="planned"]     { color: var(--c-planned); border-color: color-mix(in srgb, var(--c-planned) 55%, var(--border)); }
.spec-link[data-status="draft"]       { color: var(--c-draft); border-color: color-mix(in srgb, var(--c-draft) 55%, var(--border)); }
.spec-link[data-status="ready"]       { color: var(--c-ready); border-color: color-mix(in srgb, var(--c-ready) 55%, var(--border)); }
.spec-link[data-status="in_progress"] { color: var(--c-in-progress); border-color: color-mix(in srgb, var(--c-in-progress) 55%, var(--border)); }
.spec-link[data-status="blocked"]     { color: var(--c-blocked); border-color: var(--c-blocked); background: color-mix(in srgb, var(--c-blocked) 10%, transparent); }
.spec-link[data-status="active"]      { color: var(--c-active); border-color: color-mix(in srgb, var(--c-active) 55%, var(--border)); }
.spec-link[data-status="done"]        { color: var(--c-done); border-color: var(--c-done); background: color-mix(in srgb, var(--c-done) 8%, transparent); }
.spec-link[data-status="superseded"]  { color: var(--c-superseded); border-color: color-mix(in srgb, var(--c-superseded) 55%, var(--border)); }
.spec-link[data-status="retired"]     { color: var(--c-retired); border-color: color-mix(in srgb, var(--c-retired) 55%, var(--border)); }

.panel-divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 12px 0;
}

/* Markdown styles (shared by spec body + report body) */
.panel-md h1, .panel-md h2, .panel-md h3 {
  color: var(--text);
  margin: 12px 0 6px;
  font-size: 13px;
}
.panel-md p { font-size: 11px; line-height: 1.6; margin-bottom: 8px; }
.panel-md code {
  background: var(--surface-hi);
  border: 1px solid var(--border);
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 10px;
}
.panel-md pre {
  background: var(--surface-hi);
  border: 1px solid var(--border);
  padding: 10px;
  border-radius: 3px;
  overflow-x: auto;
  margin-bottom: 8px;
}
.panel-md pre code { background: none; border: none; padding: 0; }
.panel-md a { color: var(--c-theme); }
.panel-md ul, .panel-md ol {
  font-size: 11px;
  padding-left: 18px;
  margin-bottom: 8px;
}
.panel-md li { margin-bottom: 3px; }

/* ── Reports panel ── */
.panel-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
#panel-back-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font);
  font-size: 10px;
  padding: 2px 7px;
  cursor: pointer;
  border-radius: 2px;
  white-space: nowrap;
  flex-shrink: 0;
}
#panel-back-btn:hover { color: var(--text); border-color: var(--text-muted); }
#panel-reports-btn-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 8px;
}

.reports-filter-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}
#reports-filter {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: var(--font);
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 2px;
  outline: none;
}
#reports-filter:focus { border-color: var(--c-theme); }
#reports-filter::placeholder { color: var(--text-muted); }
#btn-reports-filter-clear {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font);
  font-size: 11px;
  padding: 0 8px;
  cursor: pointer;
  border-radius: 2px;
  white-space: nowrap;
}
#btn-reports-filter-clear:hover { color: var(--text); border-color: var(--text-muted); }
.reports-meta-line { font-size: 10px; color: var(--text-muted); margin-bottom: 8px; }
.report-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 6px 8px 9px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  border-radius: 2px;
  border-left: 3px solid transparent;
  transition: background 0.1s, opacity 0.12s, border-color 0.12s;
}
.report-item:hover { background: var(--hover); }
/* UNREAD: bold left-rail accent in the theme color, full text contrast,
   slight background tint so they pop on a long list. */
.report-item:not(.read) {
  border-left-color: var(--c-theme);
  background: color-mix(in srgb, var(--c-theme) 6%, var(--surface));
}
.report-item:not(.read):hover {
  background: color-mix(in srgb, var(--c-theme) 14%, var(--surface));
}
.report-item:not(.read) .report-name {
  color: var(--text);
  font-weight: 600;
}
/* READ: muted, faded, no accent — clearly "already done". */
.report-item.read { opacity: 0.55; }
.report-item.read:hover { opacity: 0.85; }
.report-item.read .report-name { color: var(--text-muted); font-weight: 400; }
.report-dot { font-size: 11px; margin-top: 1px; flex-shrink: 0; line-height: 1; }
.report-dot.unread { color: var(--c-theme); }
.report-dot.read   { color: var(--text-muted); }
.report-info { flex: 1; min-width: 0; }
.report-name {
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.report-meta-line { font-size: 10px; color: var(--text-muted); margin-top: 2px; }
.reports-heading {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 10px;
}
.reports-empty { color: var(--text-muted); font-size: 12px; margin-top: 24px; text-align: center; }
.reports-actions-bar {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}
.reports-actions-bar .btn {
  font-size: 10px;
  padding: 3px 8px;
}
#panel-report-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
#panel-report-filename {
  font-size: 10px;
  color: var(--text-muted);
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Graph tab ── */
#graph-view {
  display: none;
  flex: 1;
  position: relative;
}
#graph-view.active { display: flex; flex-direction: column; }

#graph-container {
  flex: 1;
  background: var(--bg);
  position: relative;
  overflow: hidden;
  min-height: 0;
}
#graph-container > div {
  width: 100% !important;
  height: 100% !important;
}
#graph-container canvas {
  display: block !important;
  width: 100% !important;
  height: 100% !important;
}

#graph-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 10;
  display: flex;
  gap: 6px;
}
/* vis.js navigation buttons — replace PNG sprites with theme-aware Unicode glyphs */
div.vis-network div.vis-navigation div.vis-button {
  background-image: none !important;
  background-color: var(--surface-hi);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text);
  font-family: var(--font);
  font-size: 14px;
  font-weight: 600;
  text-align: center;
  line-height: 30px;
  width: 32px !important;
  height: 32px !important;
  cursor: pointer;
  transition: background-color 0.1s, border-color 0.1s, color 0.1s;
}
div.vis-network div.vis-navigation div.vis-button:hover {
  background-color: var(--hover);
  border-color: var(--c-theme);
  color: var(--c-theme);
}
div.vis-button.vis-up::before          { content: "↑"; }
div.vis-button.vis-down::before        { content: "↓"; }
div.vis-button.vis-left::before        { content: "←"; }
div.vis-button.vis-right::before       { content: "→"; }
div.vis-button.vis-zoomIn::before      { content: "+"; }
div.vis-button.vis-zoomOut::before     { content: "−"; }
div.vis-button.vis-zoomExtends::before { content: "⊡"; font-size: 16px; }

#graph-info {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 11px;
  color: var(--text);
  background: var(--surface-hi);
  padding: 6px 10px;
  border-radius: 3px;
  border: 1px solid var(--border);
  display: none;
  z-index: 12;
  max-width: 60%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

#graph-legend {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 10px;
  color: var(--text);
  background: var(--surface-hi);
  padding: 8px 12px;
  border-radius: 3px;
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
  z-index: 12;
  box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  padding: 1px 3px;
  border-radius: 2px;
  transition: opacity 0.12s, color 0.12s;
}
.legend-item:hover { color: var(--c-theme); }
.legend-item.legend-hidden { opacity: 0.32; }
.legend-item.legend-hidden:hover { opacity: 0.6; }

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

/* ── Recent bar ── */
#recent-bar {
  flex-shrink: 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 4px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 30px;
  overflow: hidden;
}
.recent-label {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  white-space: nowrap;
}
#recent-chips {
  display: flex;
  gap: 5px;
  overflow-x: auto;
  flex: 1;
  scrollbar-width: none;
}
#recent-chips::-webkit-scrollbar { display: none; }
.recent-chip {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 2px;
  font-size: 10px;
  cursor: pointer;
  white-space: nowrap;
  color: var(--text-muted);
  flex-shrink: 0;
  transition: color 0.1s, border-color 0.1s;
}
.recent-chip:hover { color: var(--text); border-color: var(--text-muted); }
.recent-chip.active { border-color: var(--c-theme); color: var(--c-theme); }

/* ── Spec hover tooltip (used by recent bar, board cards, and graph nodes) ── */
#spec-tooltip {
  position: fixed;
  background: var(--surface-hi);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 8px 12px;
  z-index: 9000;
  pointer-events: none;
  display: none;
  max-width: 360px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.45);
}
.tt-id {
  font-size: 10px;
  font-weight: 600;
  color: var(--c-theme);
  margin-bottom: 4px;
}
.tt-title {
  font-size: 11px;
  color: var(--text);
  line-height: 1.4;
  margin-bottom: 5px;
  word-break: break-word;
}
.tt-status {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.07em;
  margin-bottom: 6px;
}
.tt-problem {
  font-size: 10px;
  color: var(--text);
  line-height: 1.45;
  border-top: 1px solid var(--border);
  padding-top: 6px;
  white-space: normal;
}

/* ── Toast ── */
#toast {
  position: fixed;
  top: 16px;
  right: 16px;
  background: #2a1a00;
  border: 1px solid var(--c-in-progress);
  color: var(--c-in-progress);
  font-size: 11px;
  padding: 8px 14px;
  border-radius: 3px;
  z-index: 9999;
  display: none;
  font-family: var(--font);
}
</style>
</head>
<body>

<div id="header">
  <div class="header-row1">
    <span class="logo">▸ NIGHTSHIFT BOARD <span class="logo-project">/ __PROJECT__</span></span>
    <div class="spacer"></div>
    <button class="btn" id="btn-refresh" onclick="doRefresh()">⟳ REFRESH</button>
    <button class="btn" id="btn-deps" onclick="toggleDeps()">⌥ DEPS</button>
    <button class="btn" id="btn-graph" onclick="showGraph()">▣ GRAPH</button>
    <button class="btn" id="btn-all-reports" onclick="openReportsViewFromHeader()" title="Browse all human-review reports across the project">📋 REPORTS</button>
    <button class="btn" id="btn-archived" onclick="toggleArchived()">🗄 ARCHIVED</button>
    <button class="btn" id="btn-fit-cols" onclick="fitColumns()" title="Distribute visible expanded columns to fill board width — resets manual resize gaps">⇔ FIT</button>
    <button class="btn" id="btn-reset-cols" onclick="resetColumnLayout()" title="Reset column layout to canonical defaults (collapsed/hidden/order) — preserves card order, widths, and other preferences">↺ RESET COLS</button>
    <div id="col-vis-wrap">
      <button class="btn" id="btn-cols" onclick="toggleColVisDropdown()">⊞ COLS</button>
      <div id="col-vis-dropdown"></div>
    </div>
    <div id="type-filter-wrap">
      <button class="btn" id="btn-type-filter" onclick="toggleTypeFilterDropdown()" title="Filter board and graph by spec type">⊟ TYPE</button>
      <div id="type-filter-dropdown"></div>
    </div>
    <button class="btn" id="btn-theme-mode" onclick="toggleDarkMode()">☀</button>
    <button class="btn" id="btn-theme-color" onclick="cycleThemeColor()" title="Theme color">◉</button>
  </div>
  <div class="header-row2">
    <input type="text" id="search" placeholder="░ search specs..." autocomplete="off">
    <button id="btn-clear-search" onclick="clearSearch()">✕ clear</button>
  </div>
  <div id="pending-work" class="loop-metrics" aria-label="Pending Nightshift work"></div>
  <div id="loop-metrics" class="loop-metrics" aria-label="Loop observability metrics"></div>
</div>

<div id="main">
  <div id="board-view"></div>
  <div id="search-results"></div>
  <div id="graph-view">
    <div id="graph-toolbar">
      <button class="btn" onclick="showBoard()">← BOARD</button>
      <button class="btn" onclick="resetGraphLayout()" title="Clear saved node positions and re-run column layout">⟲ RESET</button>
      <button class="btn" id="btn-graph-topo" onclick="applyDepsOrderLayout()" title="Arrange left→right by dependency depth: sources (no prereqs) on left, most-blocked on right. Clusters stacked vertically.">↦ TOPO</button>
      <button class="btn" id="btn-graph-auto" onclick="autoArrangeGraph()" title="Toggle force-directed auto-arrange; click again or drag a node to stop">⚙ AUTO</button>
      <button class="btn" id="btn-graph-snap" onclick="toggleGraphSnap()" title="Snap dragged nodes to a grid">⚏ SNAP</button>
    </div>
    <div id="graph-container"></div>
    <div id="graph-info"></div>
    <div id="graph-legend"></div>
  </div>
</div>

<div id="recent-bar">
  <span class="recent-label">RECENT</span>
  <div id="recent-chips"></div>
</div>

<!-- Detail panel -->
<div id="panel">
  <div id="panel-resize" onmousedown="startPanelResize(event)"></div>
  <div id="panel-header">
    <div class="panel-header-left">
      <button id="panel-back-btn" onclick="panelGoBack()" style="display:none">← BACK</button>
      <span id="panel-id"></span>
      <button id="btn-copy-id" onclick="copySpecId()" title="Copy spec ID" style="display:none">⎘</button>
    </div>
    <button id="panel-close" onclick="clearSelection()">✕</button>
  </div>
  <div id="panel-body">
    <!-- View: spec detail -->
    <div id="panel-view-spec">
      <div id="panel-title"></div>
      <table class="meta-table" id="panel-meta"></table>
      <div id="panel-chips"></div>
      <div id="panel-reports-btn-wrap">
        <button class="btn" id="panel-reports-btn" onclick="openReportsView()">📋 REPORTS</button>
        <button class="btn" id="panel-run-prompt-btn" onclick="copyRunPrompt()" title="Copy a parent-agent prompt for kicking off and monitoring this Nightshift spec">▶ COPY RUN PROMPT</button>
        <button class="btn" id="panel-open-vscode-btn" onclick="openCurrentSpecInVSCode()" title="Open this spec in a new VS Code window">↗ OPEN/EDIT</button>
      </div>
      <hr class="panel-divider">
      <div class="panel-md" id="panel-md"></div>
    </div>
    <!-- View: reports list -->
    <div id="panel-view-reports" style="display:none">
      <div class="reports-filter-bar">
        <input type="text" id="reports-filter" placeholder="░ filter reports by name..." autocomplete="off">
        <button id="btn-reports-filter-clear" onclick="clearReportsFilter()" title="Clear filter">✕</button>
      </div>
      <div class="reports-actions-bar">
        <button class="btn" id="btn-mark-all-read" onclick="markAllReportsRead()" title="Mark every report in the list as read">✓✓ MARK ALL READ</button>
        <button class="btn" id="btn-copy-questions-prompt" onclick="copyQuestionsPrompt()" title="Copy a prompt to paste into Claude — gathers all open questions from unread reports">⧉ COPY PROMPT</button>
      </div>
      <div id="panel-reports-list"></div>
    </div>
    <!-- View: report content -->
    <div id="panel-view-report-content" style="display:none">
      <div id="panel-report-actions">
        <span id="panel-report-filename"></span>
        <button class="btn" id="btn-open-report-vscode" onclick="openCurrentReportInVSCode()" title="Open this report in a new VS Code window">↗ OPEN/EDIT</button>
        <button class="btn" id="btn-mark-read" onclick="markReportRead()">✓ MARK READ</button>
      </div>
      <hr class="panel-divider">
      <div class="panel-md" id="panel-report-md"></div>
    </div>
  </div>
</div>

<div id="spec-tooltip"></div>
<div id="toast" class="toast"></div>

<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<script>
const COLUMNS = __STATUS_COLUMNS_JSON__;
const STATUS_IDS = COLUMNS.map(c => c.id);
const NFR_STATUS_IDS = ['active', 'retired'];

function isNfrFamilySpec(spec) {
  const id = (spec && spec.id) || '';
  const type = (spec && spec.type) || '';
  return id.startsWith('NFR-') || type === 'nfr';
}

function allowedStatusIdsForSpec(spec) {
  return isNfrFamilySpec(spec) ? NFR_STATUS_IDS : STATUS_IDS;
}

// Status progression order — used to pick the "most progressive" status when
// main and a worktree disagree. The board treats the highest-rank state as
// the spec's effective status, so a spec marked in_progress in a worktree
// shows up in the IN_PROGRESS column even when main still says ready.
const PROGRESS_RANK = Object.fromEntries(STATUS_IDS.map((s, i) => [s, i]));

function effectiveStatusFor(spec, wtStatus) {
  const mainStatus = spec.status || 'draft';
  const wts = (wtStatus || {})[spec.id] || [];
  if (!wts.length) return mainStatus;
  let best = mainStatus;
  let bestRank = PROGRESS_RANK[mainStatus] ?? 0;
  for (const wt of wts) {
    const r = PROGRESS_RANK[wt.status] ?? -1;
    if (r > bestRank) { best = wt.status; bestRank = r; }
  }
  return best;
}

function effectiveStatus(spec) {
  return effectiveStatusFor(spec, worktreeStatus);
}

const STATUS_COLOR = {
  draft:       'var(--c-draft)',
  ready:       'var(--c-ready)',
  in_progress: 'var(--c-in-progress)',
  blocked:     'var(--c-blocked)',
  planned:     'var(--c-planned)',
  active:      'var(--c-active)',
  done:        'var(--c-done)',
  superseded:  'var(--c-superseded)',
  retired:     'var(--c-retired)',
};

// Node fill color — read live from CSS variables at graph render time
const STATUS_TO_CSSVAR = {
  draft: '--c-draft', ready: '--c-ready', in_progress: '--c-in-progress',
  planned: '--c-planned', blocked: '--c-blocked', active: '--c-active', done: '--c-done',
  superseded: '--c-superseded', retired: '--c-retired',
};
// Status → graph column index (matches board column order)
const STATUS_COL_INDEX = Object.fromEntries(STATUS_IDS.map((s, i) => [s, i]));

let specs = [];
let depsMode = false;
let activeTab = 'board'; // 'board' | 'graph'
let network = null;
let graphData = null;
let loopObservability = null;
let pendingSelectId = null;
let searchTimer = null;
let graphEdgesDataset = null;
let graphNodesDataset = null;
let openPanelId = null;       // spec id currently shown in detail panel
let openPanelMtime = null;    // _mtime snapshot of spec currently shown in panel
let hiddenColumns = new Set(); // set of column ids hidden by user
let columnWidths = {};         // { colId: widthPx }
let collapsedColumns = new Set();
let recentSpecs = [];          // [{id, title, status}], newest first, max 20
let columnOrder = COLUMNS.map(c => c.id); // ordered list of column ids
let cardOrder = {};            // { colId: [specId, ...] } — intra-column card order
let panelWidth = null;         // px — null means use CSS default (40%)
let graphPositions = {};       // { specId: {x, y} } — user-dragged graph node positions
let worktreeStatus = {};       // { specId: [{branch, status, path}, ...] } — sibling worktrees with differing status
let graphSnap = true;          // snap node positions to a grid on drag-end
const GRAPH_SNAP_PX = 35;      // grid size in graph-coordinate space
let graphHiddenStatuses = new Set(); // statuses hidden in graph view ONLY (independent of board's hiddenColumns)
let showGroupingEdges = true;        // dashed parent (grouping-membership) edges in graph view; toggle to de-clutter high-fan-out parents
let showArchived = false;            // when false, done specs older than ARCHIVED_AGE_DAYS are hidden from board + graph
let activeTypeFilters = new Set();   // empty = show all types; non-empty = show only listed types (board + graph)
let isDragging = false;             // true while a SortableJS drag is in progress
let renderBoardQueued = false;      // renderBoard() was called during a drag — flush on onCardDrop
const ARCHIVED_AGE_DAYS = 14;
const ARCHIVED_AGE_SECONDS = ARCHIVED_AGE_DAYS * 24 * 60 * 60;

// A spec is "archived" when it's effectively `done` AND its file mtime is
// older than ARCHIVED_AGE_DAYS. Pure display behavior — not a real status.
function isArchived(spec) {
  if (!spec) return false;
  if (effectiveStatus(spec) !== 'done') return false;
  const m = spec._mtime;
  if (!m) return false;
  return (Date.now() / 1000) - m > ARCHIVED_AGE_SECONDS;
}

// Reports panel state
let panelView = 'spec'; // 'spec' | 'reports' | 'report-content'
let currentReportFilename = null;
let reportsCache = [];
let reportsFilter = '';   // case-insensitive substring filter on report list
let reportsListScrollTop = 0; // scroll position saved when entering a report, restored on back
let specNavStack = [];        // [{specId, scrollTop}] — back-navigation history for spec:// link hops

const THEME_COLORS = [
  '#74c0fc', // sky (default)
  '#69db7c', // mint
  '#ffa94d', // peach
  '#da77f2', // violet
  '#f783ac', // pink
  '#ff6b6b', // coral
  '#4ecdc4', // teal
  '#ffe066', // lemon
];
let themeColorIdx = 0;
let isDarkMode = true;

// Keyed by project identity, not transient port, so preferences survive
// launches with different port overrides.
const STORE_KEY = `ns-board-__PROJECT_KEY__`;

// Column-state schema version. Bump this whenever the canonical default
// collapsed/hidden set changes. On a version mismatch the client re-seeds
// collapsedColumns/hiddenColumns from each column's default_state (one-time
// adoption), then persists the new version so subsequent loads restore the
// user's own customisations normally.
const COL_STATE_VERSION = 1;

function _seedColumnsFromDefaults() {
  collapsedColumns = new Set(COLUMNS.filter(c => c.default_state === 'collapsed').map(c => c.id));
  hiddenColumns = new Set(COLUMNS.filter(c => c.default_state === 'hidden').map(c => c.id));
  columnOrder = COLUMNS.map(c => c.id);
}

function saveSettings() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({
      colStateVersion: COL_STATE_VERSION,
      columnWidths,
      hiddenColumns: [...hiddenColumns],
      collapsedColumns: [...collapsedColumns],
      columnOrder,
      cardOrder,
      panelWidth,
      graphPositions,
      graphSnap,
      graphHiddenStatuses: [...graphHiddenStatuses],
      showGroupingEdges,
      activeTypeFilters: [...activeTypeFilters],
      showArchived,
      isDarkMode,
      themeColorIdx,
      // openPanelId intentionally NOT persisted — sessions start with no
      // panel open. Recent-bar chips give the user a one-click re-entry.
      recentSpecs,
    }));
  } catch {}
}

function loadSettings() {
  try {
    const s = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
    if (s.columnWidths) columnWidths = s.columnWidths;
    // Column-state adoption: if no saved version or version mismatch, re-seed
    // collapsed/hidden/columnOrder from the canonical defaults once. cardOrder
    // and all other preferences are always restored — never wiped.
    if (s.colStateVersion === COL_STATE_VERSION) {
      if (s.hiddenColumns) hiddenColumns = new Set(s.hiddenColumns);
      if (s.collapsedColumns) collapsedColumns = new Set(s.collapsedColumns);
      if (s.columnOrder && s.columnOrder.length === COLUMNS.length) columnOrder = s.columnOrder;
    } else {
      _seedColumnsFromDefaults();
    }
    if (s.cardOrder) cardOrder = s.cardOrder;
    if (s.panelWidth) panelWidth = s.panelWidth;
    if (s.graphPositions) graphPositions = s.graphPositions;
    if (s.graphSnap !== undefined) graphSnap = s.graphSnap;
    if (s.graphHiddenStatuses) graphHiddenStatuses = new Set(s.graphHiddenStatuses);
    if (s.showGroupingEdges !== undefined) showGroupingEdges = s.showGroupingEdges;
    if (s.activeTypeFilters) {
      activeTypeFilters = new Set(s.activeTypeFilters);
      const btn = document.getElementById('btn-type-filter');
      if (btn) btn.classList.toggle('active', activeTypeFilters.size > 0);
    }
    if (s.showArchived !== undefined) showArchived = s.showArchived;
    if (s.isDarkMode !== undefined) isDarkMode = s.isDarkMode;
    if (s.themeColorIdx !== undefined) themeColorIdx = s.themeColorIdx;
    // openPanelId is NOT restored from localStorage — fresh session, no panel.
    if (s.recentSpecs) recentSpecs = s.recentSpecs;
  } catch {}
}

function applyPanelWidth() {
  if (!panelWidth) return;
  document.getElementById('panel').style.setProperty('--pw', panelWidth + 'px');
}

function applyArchivedBtnState() {
  const btn = document.getElementById('btn-archived');
  if (!btn) return;
  const archivedCount = (specs || []).filter(s => isArchived(s)).length;
  btn.classList.toggle('active', !!showArchived);
  if (showArchived) {
    btn.textContent = '🗄 ARCHIVED';
    btn.title = `Showing archived (done > ${ARCHIVED_AGE_DAYS} days). Click to hide.`;
  } else {
    btn.textContent = archivedCount > 0 ? `🗄 +${archivedCount}` : '🗄 ARCHIVED';
    btn.title = archivedCount > 0
      ? `${archivedCount} archived spec(s) hidden (done > ${ARCHIVED_AGE_DAYS} days). Click to show.`
      : `No archived specs yet (done > ${ARCHIVED_AGE_DAYS} days). Click to toggle.`;
  }
}

function toggleArchived() {
  showArchived = !showArchived;
  saveSettings();
  applyArchivedBtnState();
  renderBoard();
  if (activeTab === 'graph') showGraph();
}

function resetColumnLayout() {
  _seedColumnsFromDefaults();
  renderBoard();
  saveSettings();
}

function startPanelResize(e) {
  e.preventDefault();
  const panel = document.getElementById('panel');
  const handle = document.getElementById('panel-resize');
  const startX = e.clientX;
  const startW = panel.offsetWidth;
  handle.classList.add('dragging');

  function onMove(ev) {
    // Dragging left = wider, dragging right = narrower
    const newW = Math.max(280, Math.min(Math.round(window.innerWidth * 0.85), startW + startX - ev.clientX));
    panelWidth = newW;
    panel.style.setProperty('--pw', newW + 'px');
  }
  function onUp() {
    handle.classList.remove('dragging');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    saveSettings();
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function applyDarkMode() {
  document.documentElement.classList.toggle('light', !isDarkMode);
  document.getElementById('btn-theme-mode').textContent = isDarkMode ? '☀' : '☾';
}

function toggleDarkMode() {
  isDarkMode = !isDarkMode;
  applyDarkMode();
  saveSettings();
  // Graph node colors are snapshot from CSS vars at render time — refresh them
  if (activeTab === 'graph') showGraph();
}

function applyThemeColor() {
  document.documentElement.style.setProperty('--c-theme', THEME_COLORS[themeColorIdx]);
  document.getElementById('btn-theme-color').style.color = THEME_COLORS[themeColorIdx];
}

function cycleThemeColor() {
  themeColorIdx = (themeColorIdx + 1) % THEME_COLORS.length;
  applyThemeColor();
  saveSettings();
  if (activeTab === 'graph') showGraph();
}

function toggleCollapse(colId) {
  if (collapsedColumns.has(colId)) collapsedColumns.delete(colId);
  else collapsedColumns.add(colId);
  renderBoard();
  saveSettings();
}

function expandColumnForStatus(status) {
  if (status !== 'blocked') return;
  if (!collapsedColumns.has(status)) return;
  collapsedColumns.delete(status);
  saveSettings();
}

function renderRecentBar() {
  const chips = document.getElementById('recent-chips');
  chips.innerHTML = '';
  for (const s of recentSpecs) {
    const chip = document.createElement('span');
    chip.className = 'recent-chip' + (s.id === openPanelId ? ' active' : '');
    chip.textContent = s.id;
    chip.addEventListener('click', () => openPanel(s.id));
    chip.addEventListener('mouseenter', () => {
      // Tooltip uses the freshest spec object (which has _problem/_title) when available
      const liveSpec = specs.find(x => x.id === s.id) || s;
      showSpecTooltip(chip, liveSpec);
      peekSpec(s.id);
    });
    chip.addEventListener('mouseleave', () => {
      hideSpecTooltip();
      unpeekSpec(s.id);
    });
    chips.appendChild(chip);
  }
}

// Transient highlight on the matching card and/or graph node.
// Camera/scroll/zoom is NOT touched — if the card is offscreen, that's fine.
function peekSpec(specId) {
  // Board side: dashed outline via CSS class
  document.querySelectorAll(`.card[data-id="${specId}"]`).forEach(c => c.classList.add('card--peek'));
  // Graph side: thicker theme-colored border + soft glow, applied via dataset.update
  if (graphNodesDataset && typeof graphNodesDataset.get === 'function' && graphNodesDataset.get(specId)) {
    const css = getComputedStyle(document.documentElement);
    const themeColor = css.getPropertyValue('--c-theme').trim() || '#74c0fc';
    graphNodesDataset.update({
      id: specId,
      borderWidth: 4,
      borderWidthSelected: 4,
      shadow: { enabled: true, color: themeColor, size: 18, x: 0, y: 0 },
    });
  }
}

function unpeekSpec(specId) {
  document.querySelectorAll(`.card[data-id="${specId}"]`).forEach(c => c.classList.remove('card--peek'));
  if (graphNodesDataset && typeof graphNodesDataset.get === 'function' && graphNodesDataset.get(specId)) {
    graphNodesDataset.update({
      id: specId,
      borderWidth: 1,
      borderWidthSelected: 2,
      shadow: { enabled: false },
    });
  }
}

function _escHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[c]);
}

function specById(specId) {
  return specs.find(s => s.id === specId) || { id: specId, status: 'draft' };
}

function statusShort(status) {
  const s = status || 'draft';
  if (s === 'in_progress') return 'IP';
  if (s === 'superseded') return 'SUP';
  return s.slice(0, 4).toUpperCase();
}

function renderSpecChip(specId) {
  // SPEC-064: branch on external (different project) vs internal.
  const ext = resolveExternalProject(specId);
  if (ext) {
    // External chip — clickable link to the other project's board. Status is
    // filled in async by fetchExternalStatus; render with placeholder for now.
    const safeId = _escHtml(specId);
    const safeName = _escHtml(ext.name);
    return `<a class="chip spec-ref" data-spec-id="${safeId}" data-external="1" data-ext-port="${ext.port}" data-ext-name="${safeName}" data-status="external" href="http://localhost:${ext.port}/?spec=${encodeURIComponent(specId)}" target="_blank" rel="noopener" title="External · ${safeName}"><span class="chip-ext-icon">↗</span><span>${safeId}</span><span class="chip-status">…</span></a>`;
  }
  const spec = specById(specId);
  const status = effectiveStatus(spec);
  return `<a class="chip spec-ref" data-spec-id="${_escHtml(specId)}" data-status="${_escHtml(status)}" onclick="jumpToCard('${_escHtml(specId)}')"><span>${_escHtml(specId)}</span><span class="chip-status">${_escHtml(statusShort(status))}</span></a>`;
}

// ──────────────────────────────────────────────────────────────────────
// SPEC-064: Cross-project dependency registry (client side)
// ──────────────────────────────────────────────────────────────────────

const CURRENT_PROJECT = "__PROJECT__";  // server-side replaced by board.py
let projectsRegistry = null;            // {generated_at, projects: [...]}

async function loadProjectsRegistry() {
  try {
    const r = await fetch('/api/projects-registry');
    if (r.ok) projectsRegistry = await r.json();
  } catch {}
}

// Longest-prefix-match across all OTHER projects in the registry. Returns the
// matching project entry (with port + name + path), or null when the spec
// belongs to this project (or no match).
function resolveExternalProject(specId) {
  if (!projectsRegistry || !Array.isArray(projectsRegistry.projects)) return null;
  let best = null, bestLen = 0;
  for (const p of projectsRegistry.projects) {
    if (p.name === CURRENT_PROJECT) continue;
    for (const prefix of (p.spec_prefixes || [])) {
      if (specId.startsWith(prefix + "-") && prefix.length > bestLen) {
        best = p;
        bestLen = prefix.length;
      }
    }
  }
  return best;
}

// Fill in the status pill on every external chip in `root` (defaults to whole
// document). Best-effort: timeouts and unreachable boards leave the pill as
// "external" without raising errors in the console.
async function fillExternalChipStatuses(root) {
  const scope = root || document;
  const chips = scope.querySelectorAll('.chip[data-external="1"]:not([data-status-loaded])');
  for (const chip of chips) {
    chip.dataset.statusLoaded = "1";  // prevent re-fetch
    const specId = chip.dataset.specId;
    const port = chip.dataset.extPort;
    if (!specId || !port) continue;
    try {
      const r = await fetch(`/api/external-spec/${port}/${encodeURIComponent(specId)}`);
      if (!r.ok) continue;
      const data = await r.json();
      const pill = chip.querySelector('.chip-status');
      if (data._unreachable) {
        if (pill) pill.textContent = 'EXT';
        chip.dataset.unreachable = "1";
      } else if (data.status) {
        chip.dataset.status = data.status;
        if (pill) pill.textContent = statusShort(data.status);
      } else {
        if (pill) pill.textContent = 'EXT';
      }
    } catch {
      if (chip.querySelector('.chip-status')) chip.querySelector('.chip-status').textContent = 'EXT';
      chip.dataset.unreachable = "1";
    }
  }
}

// Show a tooltip near the anchor element with spec metadata + problem snippet.
// `anchor` is any element with getBoundingClientRect (real DOM element OR a
// duck-typed object — used for graph nodes which have no DOM element of their own).
// `spec` is a frontmatter dict (must have id; may have status, _title/title, _problem).
function showSpecTooltip(anchor, spec) {
  if (!spec || !spec.id) return;
  const tt = document.getElementById('spec-tooltip');
  const statusColor = STATUS_COLOR[spec.status] || 'var(--text-muted)';
  const status = (spec.status || 'draft').toUpperCase();
  const readiness = spec.readiness || '';
  const runState = (spec.run_state || '').replaceAll('_', ' ');
  const title = spec._title || spec.title || spec.id;
  const problem = spec._problem || '';
  let html = `
    <div class="tt-id">${_escHtml(spec.id)}</div>
    <div class="tt-title">${_escHtml(title)}</div>
    <div class="tt-status" style="color:${statusColor}" title="${_escHtml(registryHelp(spec, 'status'))}">${_escHtml(status)}</div>
  `;
  if (readiness) {
    html += `<div title="${_escHtml(registryHelp(spec, 'readiness'))}">${_escHtml(readiness)} · ${_escHtml(runState)}</div>`;
  }
  if (spec.readiness_evidence && spec.readiness_evidence.length) {
    html += `<div class="tt-problem">${_escHtml(spec.readiness_evidence.join('; '))}</div>`;
  }
  if (spec.readiness_dimensions && spec.readiness_dimensions.length) {
    html += `<div class="tt-problem">${spec.readiness_dimensions.map(dimension =>
      `${_escHtml(dimension.name)}: ${_escHtml(dimension.result)}`
    ).join('<br>')}</div>`;
  }
  if (problem) html += `<div class="tt-problem">${_escHtml(problem)}</div>`;
  tt.innerHTML = html;
  tt.style.display = 'block';

  const r = anchor.getBoundingClientRect();
  const ttW = tt.offsetWidth;
  const ttH = tt.offsetHeight;
  // Prefer above-and-aligned; flip below if no room above; clamp horizontally.
  let top = r.top - ttH - 8;
  if (top < 8) top = r.bottom + 8;
  let left = r.left;
  if (left + ttW > window.innerWidth - 8) left = Math.max(8, window.innerWidth - ttW - 8);
  tt.style.top = top + 'px';
  tt.style.left = left + 'px';
}

function hideSpecTooltip() {
  document.getElementById('spec-tooltip').style.display = 'none';
}

function registryHelp(spec, field) {
  return (spec && spec._help && spec._help[field]) || '';
}

// Backwards-compat shims (older call sites used the recent-bar names)
const showRecentTooltip = showSpecTooltip;
const hideRecentTooltip = hideSpecTooltip;

// Build lookup: spec_id → list of spec_ids that depend on it (reverse edges)
function buildBlocksMap() {
  const blocks = {};
  for (const s of specs) {
    const after = s.after || [];
    for (const dep of after) {
      if (!blocks[dep]) blocks[dep] = [];
      blocks[dep].push(s.id);
    }
  }
  return blocks;
}

function attachSpecRefPreview(root) {
  root.querySelectorAll('.spec-ref[data-spec-id]').forEach(el => {
    el.addEventListener('mouseenter', () => showSpecTooltip(el, specById(el.dataset.specId)));
    el.addEventListener('mouseleave', hideSpecTooltip);
  });
}

function decorateSpecLinks(root) {
  root.querySelectorAll('a[href^="spec://"]').forEach(a => {
    const linkedId = (a.getAttribute('href') || '').slice('spec://'.length);
    if (!linkedId) return;
    const spec = specById(linkedId);
    const status = effectiveStatus(spec);
    a.classList.add('spec-link', 'spec-ref');
    a.dataset.specId = linkedId;
    a.dataset.status = status;
    if (!a.querySelector('.spec-link-status')) {
      const statusEl = document.createElement('span');
      statusEl.className = 'spec-link-status';
      statusEl.textContent = statusShort(status);
      a.appendChild(statusEl);
    }
  });
  attachSpecRefPreview(root);
}

async function loadSpecs() {
  const r = await fetch('/api/specs');
  if (!r.ok) throw new Error('/api/specs: ' + r.status);
  const data = await r.json();
  if (!Array.isArray(data)) throw new Error('/api/specs: unexpected response type');
  specs = data;
  renderPendingWork();
  // Fetch worktree state in parallel; missing or empty result is fine
  fetch('/api/worktree-status').then(r => r.ok ? r.json() : {}).then(ws => {
    worktreeStatus = ws || {};
    renderBoard();
  }).catch(() => { worktreeStatus = {}; });
  // Always start a fresh session with no panel open. Persisting "last opened"
  // across reloads surprised users — they'd see a panel they hadn't opened.
  // Recent-bar chips remain available for one-click re-entry.
  openPanelId = null;
  renderBoard();
  renderRecentBar();
  loadLoopObservability();
}

function renderPendingWork() {
  const el = document.getElementById('pending-work');
  if (!el) return;
  // Use the same canonical frontmatter payload that drives the board columns.
  // Worktree badges are intentionally excluded: these are main-board planning
  // counts, not a second lifecycle interpretation.
  const count = (status) => specs.filter(s => s.status === status).length;
  el.innerHTML = [
    ['DRAFT', 'draft'],
    ['READY', 'ready'],
  ].map(([label, status]) =>
    `<span class="loop-metric pending-work-tile" data-status="${status}">${label} <strong>${count(status)}</strong></span>`
  ).join('');
}

function formatMetricValue(value, suffix = '') {
  if (value === null || value === undefined) return 'n/a';
  return `${value}${suffix}`;
}

function renderLoopObservability() {
  const el = document.getElementById('loop-metrics');
  if (!el) return;
  const m = loopObservability;
  if (!m || !m.run_count) {
    el.innerHTML = '<span class="loop-metric" title="Recorded Nightshift runs included in these operational metrics.">RUNS <strong>0</strong></span>';
    return;
  }
  el.innerHTML = [
    ['RUNS', m.run_count, '', 'Recorded Nightshift runs included in these operational metrics.'],
    ['MTTD', m.mttd_seconds, 's', 'Mean time to detect a failed or bad run, in seconds. Lower is better.'],
    ['MTTR', m.mttr_seconds, 's', 'Mean time to recover or restart after a failed run, in seconds. Lower is better.'],
    ['CFR', m.change_failure_rate, '%', 'Change failure rate: percent of runs that failed or were rolled back. Lower is better.'],
    ['FORMAT', m.format_failure_rate, '%', 'Format failure rate: percent of outputs with invalid JSON or another required format error. Lower is better.'],
    ['EASY-FIX', m.format_failure_easy_fix_fraction, '%', 'Among format failures, the percent that were trivially recoverable. Higher means errors are easier to repair.'],
  ].map(([label, value, suffix, help]) =>
    `<span class="loop-metric" title="${help}">${label} <strong>${formatMetricValue(value, suffix)}</strong></span>`
  ).join('');
}

async function loadLoopObservability() {
  try {
    const r = await fetch('/api/loop-observability');
    loopObservability = r.ok ? await r.json() : null;
  } catch {
    loopObservability = null;
  }
  renderLoopObservability();
}

function renderBoard() {
  if (!Array.isArray(specs)) return;
  // Block re-renders mid-drag: renderBoard() clears boardView.innerHTML, which
  // removes the dragged element. When SortableJS then drops it, the element is
  // inserted into the freshly-rendered column alongside the already-rendered card
  // for the same spec — producing a visual duplicate. Queue instead and flush in onCardDrop.
  if (isDragging) { renderBoardQueued = true; return; }
  renderBoardQueued = false;
  const boardView = document.getElementById('board-view');
  const blocksMap = buildBlocksMap();

  boardView.innerHTML = '';
  const orderedCols = columnOrder.map(id => COLUMNS.find(c => c.id === id)).filter(Boolean);
  for (const col of orderedCols) {
    if (hiddenColumns.has(col.id)) continue;

    const colSpecs = specs.filter(s => {
      if (effectiveStatus(s) !== col.id) return false;
      // Hide archived (done > 14 days) unless the user explicitly opted in
      if (!showArchived && isArchived(s)) return false;
      // Type filter: when active, only show specs whose type is selected
      if (activeTypeFilters.size > 0 && !activeTypeFilters.has(s.type || 'feature')) return false;
      return true;
    });

    // Collapsed column — render as narrow strip
    if (collapsedColumns.has(col.id)) {
      const strip = document.createElement('div');
      strip.className = 'column column--collapsed';
      strip.dataset.colId = col.id;
      if (col.id === 'blocked' && colSpecs.length > 0) strip.classList.add('column--blocked-hot');
      strip.title = `${col.label} (${colSpecs.length}) — click to expand`;
      strip.innerHTML = `<div class="col-collapsed-inner">
        <span class="col-collapsed-name">${col.label}</span>
        <span class="col-collapsed-count">${colSpecs.length}</span>
      </div>`;
      strip.addEventListener('click', () => toggleCollapse(col.id));
      boardView.appendChild(strip);
      continue;
    }

    const div = document.createElement('div');
    div.className = 'column';
    if (col.id === 'blocked' && colSpecs.length > 0) div.classList.add('column--blocked-hot');
    div.dataset.colId = col.id;
    const meaning = (col.meaning || '').replace(/"/g, '&quot;');

    const w = columnWidths[col.id];
    if (w) { div.style.cssText = `width:${w}px; flex:none; min-width:${w}px`; }

    div.innerHTML = `
      <div class="col-header">
        <span class="col-name-wrap">
          <span class="col-name">${col.label}</span>
          <span class="col-meaning" title="${meaning}">?</span>
        </span>
        <span class="col-count" id="count-${col.id}">${colSpecs.length}</span>
      </div>
      <div class="card-list" data-status="${col.id}" id="list-${col.id}"></div>
      <div class="col-resize" title="drag to resize"></div>
    `;
    boardView.appendChild(div);

    const listEl = div.querySelector('.card-list');
    // Sort. Done column always sorts by completion time (mtime desc, most recent on top)
    // so manual reorder doesn't stick there. Other columns respect cardOrder.
    let orderedColSpecs;
    if (col.id === 'done') {
      orderedColSpecs = [...colSpecs].sort((a, b) => (b._mtime || 0) - (a._mtime || 0));
    } else {
      const savedOrder = cardOrder[col.id];
      if (savedOrder && savedOrder.length) {
        orderedColSpecs = [...colSpecs].sort((a, b) => {
          const ai = savedOrder.indexOf(a.id);
          const bi = savedOrder.indexOf(b.id);
          if (ai === -1 && bi === -1) return 0;
          if (ai === -1) return 1;
          if (bi === -1) return -1;
          return ai - bi;
        });
      } else {
        // Default sort: bugfix specs float to the top (highest urgency by convention),
        // then preserve natural API order within each type group.
        orderedColSpecs = [...colSpecs].sort((a, b) =>
          (a.type === 'bugfix' ? 0 : 1) - (b.type === 'bugfix' ? 0 : 1)
        );
      }
    }
    for (const spec of orderedColSpecs) {
      listEl.appendChild(renderCard(spec, blocksMap));
    }

    new Sortable(listEl, {
      group: 'specs',
      animation: 150,
      ghostClass: 'sortable-ghost',
      dragClass: 'sortable-drag',
      onStart: () => { isDragging = true; },
      onEnd: onCardDrop,
    });

    div.querySelector('.col-resize').addEventListener('mousedown', (e) => startResize(e, col.id, div));
  }

  // Re-apply active card highlight after board re-render
  if (openPanelId) applyActiveCard(openPanelId);
  // Keep the ARCHIVED button label/tooltip in sync (count may have changed)
  applyArchivedBtnState();
}

function renderCard(spec, blocksMap) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.id = spec.id;

  const status = effectiveStatus(spec);
  card.dataset.status = status;

  const title = spec._title || spec.title || spec.id || '';
  const displayTitle = title.length > 40 ? title.substring(0, 40) + '…' : title;

  const priority = parseInt(spec.priority) || 0;
  const dots = '●'.repeat(Math.min(priority, 3));

  const typeBadge = spec.type ? `<span class="badge">${spec.type}</span>` : '';
  const layerBadge = spec.layer !== undefined && spec.layer !== null
    ? `<span class="badge" title="${_escHtml(registryHelp(spec, 'layer'))}">L${spec.layer}</span>` : '';
  const readinessBadge = spec.readiness
    ? `<span class="badge readiness-${spec.readiness.toLowerCase()}" title="${_escHtml(registryHelp(spec, 'readiness'))}">${_escHtml(spec.readiness)}</span>`
    : '';
  const runStateBadge = spec.run_state
    ? `<span class="badge" title="${_escHtml(registryHelp(spec, 'run_state'))}">${_escHtml(spec.run_state.replaceAll('_', ' '))}</span>`
    : '';

  let depHtml = '';
  if (depsMode) {
    const afterCount = (spec.after || []).length;
    const blocksCount = (blocksMap[spec.id] || []).length;
    depHtml = `<span class="dep-badge">→${afterCount} ←${blocksCount}</span>`;
  }

  // Worktree-state badge — surfaces sibling worktrees where this spec
  // has a different status (e.g. codex subagent has it as in_progress).
  const wt = worktreeStatus[spec.id];
  let wtHtml = '';
  if (wt && wt.length) {
    const first = wt[0];
    // Strip everything up to and including the last '/' so we keep just the leaf
    // (e.g. 'refs/heads/codex-fart-008' → 'codex-fart-008'). Truncate to 28 chars.
    const _b = first.branch || '';
    const _slashIdx = _b.lastIndexOf('/');
    const branchShort = (_slashIdx >= 0 ? _b.slice(_slashIdx + 1) : _b).slice(0, 28);
    const more = wt.length > 1 ? ` +${wt.length - 1}` : '';
    wtHtml = `<div class="wt-badge" title="Worktree branch '${first.branch}' has status: ${first.status}">🔧 ${(first.status || '').toUpperCase()} · ${branchShort}${more}</div>`;
  }

  card.innerHTML = `
    <div class="card-header">
      <span class="card-id">${spec.id || ''}</span>
      <span class="card-dots">${dots}</span>
    </div>
    <div class="card-title">${displayTitle}</div>
    <div class="card-meta">${typeBadge}${layerBadge}${readinessBadge}${runStateBadge}${depHtml}</div>
    ${wtHtml}
  `;

  card.addEventListener('click', (e) => {
    if (card.classList.contains('sortable-drag')) return;
    if (depsMode) {
      showGraph(spec.id);
    } else {
      openPanel(spec.id);
    }
  });

  // Hover preview — title, status (in its color), and the problem snippet
  card.addEventListener('mouseenter', () => showSpecTooltip(card, spec));
  card.addEventListener('mouseleave', hideSpecTooltip);

  return card;
}

function captureColOrder(listEl) {
  const colId = listEl.dataset.status;
  if (!colId) return;
  cardOrder[colId] = [...listEl.querySelectorAll('.card')].map(c => c.dataset.id).filter(Boolean);
}

function onCardDrop(evt) {
  isDragging = false;
  const wasPending = renderBoardQueued;
  renderBoardQueued = false;

  const specId = evt.item.dataset.id;
  const newStatus = evt.to.dataset.status;
  const oldStatus = evt.from.dataset.status;

  // Always capture the new card order for affected columns
  captureColOrder(evt.from);
  if (evt.to !== evt.from) captureColOrder(evt.to);

  if (newStatus === oldStatus) {
    saveSettings();
    if (wasPending) renderBoard();
    return;
  }

  // Update local state optimistically
  const spec = specs.find(s => s.id === specId);
  if (spec && !allowedStatusIdsForSpec(spec).includes(newStatus)) {
    if (wasPending) {
      renderBoard();
    } else {
      evt.item.dataset.status = oldStatus;
      evt.from.appendChild(evt.item);
      updateColumnCounts();
    }
    showToast(`⚠ ${specId}: NFR specs only use active or retired`);
    return;
  }
  if (spec) spec.status = newStatus;
  expandColumnForStatus(newStatus);
  // Also update the dragged card's data-status so the left-border CSS
  // (.card[data-status="..."] { border-left-color: ... }) repaints immediately,
  // without waiting for the next renderBoard() / poll cycle.
  evt.item.dataset.status = newStatus;
  updateColumnCounts();

  // If a renderBoard() was queued while the drag was in progress, flush it now.
  // spec.status is already updated, so the fresh render places the card correctly.
  // evt.item is removed by boardView.innerHTML = '' — that's intentional;
  // the reverted error path uses renderBoard() too when wasPending, not appendChild.
  if (wasPending) { renderBoard(); }

  fetch(`/api/spec/${specId}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: newStatus }),
  }).then(r => {
    if (!r.ok) {
      // Revert
      if (spec) spec.status = oldStatus;
      if (wasPending) {
        // evt.item and evt.from are orphaned (renderBoard removed them); re-render.
        updateColumnCounts();
        renderBoard();
      } else {
        evt.item.dataset.status = oldStatus;
        evt.from.appendChild(evt.item);
        updateColumnCounts();
      }
      showToast(`⚠ ${specId}: status write failed`);
      return;
    }
    // On a successful move into done, bump local _mtime so the auto-sort
    // (most-recent on top) puts the just-completed spec at the column head.
    if (newStatus === 'done' && spec) {
      spec._mtime = Math.floor(Date.now() / 1000);
      renderBoard();
    }
    // If the moved spec's detail panel is open, update the status dropdown.
    if (openPanelId === specId) {
      const sel = document.getElementById('panel-status-select');
      if (sel) { sel.value = newStatus; sel.dataset.status = newStatus; }
    }
  }).catch(() => {
    if (spec) spec.status = oldStatus;
    if (wasPending) {
      updateColumnCounts();
      renderBoard();
    } else {
      evt.item.dataset.status = oldStatus;
      evt.from.appendChild(evt.item);
      updateColumnCounts();
    }
    showToast(`⚠ ${specId}: status write failed`);
  });
}

function updateColumnCounts() {
  for (const col of COLUMNS) {
    const count = specs.filter(s => {
      if (effectiveStatus(s) !== col.id) return false;
      if (!showArchived && isArchived(s)) return false;
      return true;
    }).length;
    const el = document.getElementById(`count-${col.id}`);
    if (el) el.textContent = count;
  }
}

async function openPanel(specId, { keepNavStack = false } = {}) {
  if (!keepNavStack) specNavStack = [];
  const r = await fetch(`/api/spec/${specId}`);
  if (!r.ok) return;
  const data = await r.json();

  // Reset to spec view
  setPanelView('spec');

  const fm = data.frontmatter || {};
  const title = data.title || specId;
  const body = data.body_md || '';

  document.getElementById('panel-id').textContent = specId;
  document.getElementById('panel-title').textContent = title;

  // Metadata table — status gets an interactive dropdown, rest is plain text
  const currentStatus = fm.status || 'draft';
  const allowedStatuses = allowedStatusIdsForSpec(fm);
  const invalidCurrentStatus = !allowedStatuses.includes(currentStatus);
  const displayedStatuses = invalidCurrentStatus
    ? [currentStatus, ...allowedStatuses]
    : allowedStatuses;
  const statusOptions = displayedStatuses.map(s =>
    `<option value="${s}"${s === currentStatus ? ' selected' : ''}${invalidCurrentStatus && s === currentStatus ? ' disabled' : ''}>${s}${invalidCurrentStatus && s === currentStatus ? ` (invalid for ${isNfrFamilySpec(fm) ? 'nfr' : 'spec'})` : ''}</option>`
  ).join('');

  const fields = [
    ['type', fm.type],
    ['layer', fm.layer !== undefined ? fm.layer : ''],
    ['priority', fm.priority],
    ['readiness', fm.readiness],
    ['run_state', fm.run_state],
    ['blocker_class', fm.blocker_class],
    ['blocker_scope', fm.blocker_scope],
    ['block_reason', fm.block_reason],
    ['unblock_condition', fm.unblock_condition],
    ['created', fm.created],
  ];
  if (fm.stack) fields.push(['stack', fm.stack]);

  const metaEl = document.getElementById('panel-meta');
  const statusRow = `<tr><td title="${_escHtml(registryHelp(fm, 'status'))}">status</td><td><select id="panel-status-select" data-status="${currentStatus}" onchange="changeSpecStatus('${specId}', this.value)">${statusOptions}</select></td></tr>`;
  const otherRows = fields
    .filter(([k, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `<tr><td title="${_escHtml(registryHelp(fm, k))}">${k}</td><td>${_escHtml(String(v))}</td></tr>`)
    .join('');
  metaEl.innerHTML = statusRow + otherRows;

  // Chips
  const blocksMap = buildBlocksMap();
  const after = fm.after || [];
  const blocks = blocksMap[specId] || [];

  let chipsHtml = '';
  if (after.length) {
    chipsHtml += `<div class="chips-row"><span class="chips-label">after:</span>`;
    for (const dep of after) {
      chipsHtml += renderSpecChip(dep);
    }
    chipsHtml += '</div>';
  }
  if (blocks.length) {
    chipsHtml += `<div class="chips-row"><span class="chips-label">blocks:</span>`;
    for (const dep of blocks) {
      chipsHtml += renderSpecChip(dep);
    }
    chipsHtml += '</div>';
  }
  document.getElementById('panel-chips').innerHTML = chipsHtml;
  attachSpecRefPreview(document.getElementById('panel-chips'));
  // SPEC-064: fill in external dep statuses from peer boards (async, best-effort)
  fillExternalChipStatuses(document.getElementById('panel-chips'));

  // Markdown body
  const mdEl = document.getElementById('panel-md');
  if (body && typeof marked !== 'undefined') {
    mdEl.innerHTML = marked.parse(body);
  } else {
    mdEl.innerHTML = `<pre>${body}</pre>`;
  }
  decorateSpecLinks(mdEl);

  openPanelId = specId;
  openPanelMtime = fm._mtime || null;
  applyActiveCard(specId);
  document.getElementById('panel').classList.add('open');

  // Fetch report count for the button label (async, non-blocking)
  fetch('/api/reports').then(r => r.json()).then(reports => {
    reportsCache = reports;
    updateReportsBtnLabel();
  }).catch(() => {});

  // Push to recent (dedup + cap at 20)
  recentSpecs = [{id: specId, title: data.title || specId, status: (data.frontmatter||{}).status||'draft'},
    ...recentSpecs.filter(s => s.id !== specId)].slice(0, 20);
  renderRecentBar();
  saveSettings();
}

function applyActiveCard(specId) {
  document.querySelectorAll('.card--active').forEach(c => c.classList.remove('card--active'));
  document.querySelectorAll(`.card[data-id="${specId}"]`).forEach(c => c.classList.add('card--active'));
}

function closePanel() {
  document.getElementById('panel').classList.remove('open');
  // openPanelId intentionally kept — card stays highlighted as "last selected"
}

function clearSelection() {
  openPanelId = null;
  openPanelMtime = null;
  panelView = 'spec';
  document.querySelectorAll('.card--active').forEach(c => c.classList.remove('card--active'));
  closePanel();
  renderRecentBar();
  saveSettings();
}

function jumpToCard(specId) {
  // Open that spec's panel (replacing the current one)
  openPanel(specId);
  // Scroll its board card into view if board is visible
  if (activeTab === 'board') {
    setTimeout(() => {
      const card = document.querySelector(`#board-view .card[data-id="${specId}"]`);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 50);
  }
}

async function changeSpecStatus(specId, newStatus) {
  const sel = document.getElementById('panel-status-select');
  const oldStatus = sel ? sel.dataset.status : null;
  if (!oldStatus || newStatus === oldStatus) return;

  const spec = specs.find(s => s.id === specId);
  if (spec && !allowedStatusIdsForSpec(spec).includes(newStatus)) {
    if (sel) { sel.value = oldStatus; sel.dataset.status = oldStatus; }
    showToast(`⚠ ${specId}: NFR specs only use active or retired`);
    return;
  }

  try {
    const r = await fetch(`/api/spec/${specId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!r.ok) throw new Error('write failed');
    await loadSpecs();
    if (sel) sel.dataset.status = newStatus;
    expandColumnForStatus(newStatus);
    if (openPanelId === specId) await openPanel(specId, { keepNavStack: true });
    showToast(`✓ ${specId} → ${newStatus}`);
  } catch {
    if (sel) { sel.value = oldStatus; sel.dataset.status = oldStatus; }
    showToast(`⚠ ${specId}: status write failed`);
  }
}

async function doRefresh() {
  const btn = document.getElementById('btn-refresh');
  btn.textContent = '↻ REFRESH';
  try {
    await fetch('/api/refresh', { method: 'POST' });
    await loadSpecs();
  } finally {
    btn.textContent = '⟳ REFRESH';
  }
}

function toggleDeps() {
  depsMode = !depsMode;
  const btn = document.getElementById('btn-deps');
  if (depsMode) {
    btn.classList.add('active');
  } else {
    btn.classList.remove('active');
  }
  renderBoard();
}

async function showGraph(selectId) {
  activeTab = 'graph';
  document.getElementById('board-view').style.display = 'none';
  document.getElementById('search-results').classList.remove('visible');
  document.getElementById('graph-view').classList.add('active');
  renderGraphLegend();
  applyGraphSnapBtnState();
  _physicsRunning = false;
  applyAutoBtnState();

  // SPEC-063: fetch /api/specs in parallel with /api/graph so node status
  // promotion (line ~2917 below) uses fresh data on tab-activate, not the
  // possibly-stale cached specs[] from the last poll.
  const [graphResp, specsResp] = await Promise.all([
    fetch('/api/graph'),
    fetch('/api/specs').catch(() => null),
  ]);
  graphData = await graphResp.json();
  if (specsResp && specsResp.ok) {
    try { specs = await specsResp.json(); } catch {}
  }

  const container = document.getElementById('graph-container');

  // Pull theme-aware colors from current CSS variables
  const css = getComputedStyle(document.documentElement);
  const cssVar = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);
  const themeColor   = cssVar('--c-theme', '#74c0fc');
  const textColor    = cssVar('--text', '#d4d4d4');
  const surfaceColor = cssVar('--surface', '#1a1d24');
  const edgeColor    = cssVar('--text-muted', '#606474');
  const colorForStatus = (s) => cssVar(STATUS_TO_CSSVAR[s] || '--text-muted', '#888');
  // Non-runnable / grouping spec types — mirrors the nightshift-dag executable
  // predicate (executable == type not in {main, nfr}). These render as diamonds.
  const GROUPING_NODE_TYPES = new Set(['main', 'nfr']);

  // Column-based positioning — X is fixed per status, Y is seeded from cardOrder
  const COL_X_STEP = 260;
  const ROW_Y_STEP = 70;

  // Each graph node carries its main-branch status from /api/graph. Promote
  // to the worktree-aware effective status so the graph reflects in-flight work
  // the same way the board does.
  for (const n of graphData.nodes) {
    const liveSpec = specs.find(s => s.id === n.id);
    if (liveSpec) n.status = effectiveStatus(liveSpec);
  }
  // Hide nodes whose status is hidden in the graph's own filter (independent of the board)
  // AND drop archived done specs unless the user has toggled them on.
  const visibleNodes = graphData.nodes.filter(n => {
    if (graphHiddenStatuses.has(n.status || 'draft')) return false;
    const liveSpec = specs.find(s => s.id === n.id);
    if (!showArchived && liveSpec && isArchived(liveSpec)) return false;
    if (activeTypeFilters.size > 0 && liveSpec && !activeTypeFilters.has(liveSpec.type || 'feature')) return false;
    return true;
  });
  const visibleIds = new Set(visibleNodes.map(n => n.id));

  // Compact column map: only allocate X slots to statuses that actually have nodes,
  // preserving the board's status order for those that do.
  const STATUS_BOARD_ORDER = STATUS_IDS;
  const usedStatuses = STATUS_BOARD_ORDER.filter(s => visibleNodes.some(n => (n.status || 'draft') === s));
  const compactColMap = Object.fromEntries(usedStatuses.map((s, i) => [s, i]));
  const numCols = Math.max(1, usedStatuses.length);
  const compactBaseX = -((numCols - 1) * COL_X_STEP) / 2;  // centered horizontally

  const nodesArr = visibleNodes.map(n => {
    const status = n.status || 'draft';
    const col = compactColMap[status] ?? 0;
    const order = (cardOrder && cardOrder[status]) || [];
    const orderIdx = order.indexOf(n.id);
    const row = orderIdx >= 0 ? orderIdx : (order.length + Math.floor(Math.random() * 5));
    const c = colorForStatus(status);
    const saved = graphPositions[n.id];
    const colMembers = visibleNodes.filter(m => (m.status || 'draft') === status).length;
    // Center the column vertically around 0
    const yCenter = -((colMembers - 1) * ROW_Y_STEP) / 2;
    const x = saved ? saved.x : compactBaseX + col * COL_X_STEP;
    const y = saved ? saved.y : yCenter + row * ROW_Y_STEP;
    return {
      id: n.id,
      label: n.label,
      color: {
        background: c,
        border: c,
        highlight: { background: c, border: themeColor },
      },
      font: {
        color: textColor,
        face: 'monospace',
        size: 11,
        strokeWidth: 3,
        strokeColor: surfaceColor,
      },
      // Grouping / non-runnable specs (type in {main, nfr} — the nightshift-dag
      // executable predicate) get a distinct diamond so they read as "not a work
      // item you can kick off". Runnable specs keep the dot.
      shape: GROUPING_NODE_TYPES.has(n.type) ? 'diamond' : 'dot',
      size: 14,
      x, y,
      // No `fixed` property → user can drag the node freely in any direction
    };
  });

  const edgesArr = graphData.edges
    .filter(e => visibleIds.has(e.from) && visibleIds.has(e.to))
    .map((e, i) => ({
      id: i,
      from: e.from,
      to: e.to,
      arrows: 'to',
      color: { color: edgeColor, opacity: 0.55, highlight: themeColor },
      width: 1,
      smooth: { type: 'continuous' },
    }));

  // Dashed parent (grouping-membership) edges — faint, no arrowhead, so they read
  // as "belongs to" not "depends on". Only when both endpoints are visible, and
  // only when the toggle is on (high-fan-out parents can add 20+ dashed lines).
  const parentEdgesArr = (showGroupingEdges ? (graphData.parent_edges || []) : [])
    .filter(e => visibleIds.has(e.from) && visibleIds.has(e.to))
    .map((e, i) => ({
      id: `p${i}`,
      from: e.from,
      to: e.to,
      arrows: '',
      dashes: true,
      color: { color: edgeColor, opacity: 0.28, highlight: themeColor },
      width: 1,
      smooth: { type: 'continuous' },
    }));

  graphNodesDataset = new vis.DataSet(nodesArr);
  graphEdgesDataset = new vis.DataSet([...edgesArr, ...parentEdgesArr]);
  // Keep globals visible for diagnostics/tests and backwards compatibility.
  window.graphNodesDataset = graphNodesDataset;
  window.graphEdgesDataset = graphEdgesDataset;

  const options = {
    layout: { improvedLayout: false },
    // Physics disabled: nodes use our explicit column positions and don't drift.
    // Dragging works freely in both axes; saved positions persist.
    physics: { enabled: false },
    nodes: { shape: 'dot', size: 14 },
    edges: {
      arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      width: 1,
      smooth: { type: 'continuous' },
    },
    interaction: {
      hover: true,
      zoomView: true,
      dragView: true,
      dragNodes: true,
      navigationButtons: true,
      keyboard: { enabled: true, bindToWindow: false },
    },
  };

  if (network) {
    network.destroy();
    network = null;
  }

  network = new vis.Network(container, {
    nodes: graphNodesDataset,
    edges: graphEdgesDataset,
  }, options);
  window.network = network;

  // Physics is disabled, so stabilizationIterationsDone may not fire — use afterDrawing
  // (fires once per frame; .once() ensures it only runs on the first paint).
  network.once('afterDrawing', () => {
    if (selectId || pendingSelectId) {
      const sid = selectId || pendingSelectId;
      pendingSelectId = null;
      highlightNode(sid);
    } else {
      network.fit();
    }
  });

  // vis.js fires `click` even after a drag finishes. Track whether a node-drag
  // happened during the current interaction and suppress the next click event
  // so dragging a node doesn't accidentally open its detail panel.
  let _suppressNextNodeClick = false;
  // While a node is being dragged, suppress hover tooltips entirely — vis.js
  // can fire `hoverNode` mid-drag and the popover steals focus from the drag.
  let _isNodeDragging = false;
  network.on('click', function(params) {
    if (_suppressNextNodeClick) {
      _suppressNextNodeClick = false;
      return;
    }
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      highlightNode(nodeId);
      openPanel(nodeId);  // open the same right slide-in detail panel as a card click
    } else {
      restoreAllEdges();
      clearInfoBar();
    }
  });

  // Hover preview on graph nodes — re-uses the shared spec tooltip.
  // Synthesize an anchor at the node's DOM coordinates.
  network.on('hoverNode', function(params) {
    if (_isNodeDragging) return;  // never show popover during a drag
    const spec = specs.find(s => s.id === params.node);
    if (!spec) return;
    const positions = network.getPositions([params.node]);
    const cp = positions[params.node];
    if (!cp) return;
    const dom = network.canvasToDOM({ x: cp.x, y: cp.y });
    const cRect = container.getBoundingClientRect();
    const cx = cRect.left + dom.x;
    const cy = cRect.top + dom.y;
    const anchor = {
      getBoundingClientRect: () => ({
        top: cy - 10, bottom: cy + 10,
        left: cx, right: cx,
        width: 0, height: 20,
      }),
    };
    showSpecTooltip(anchor, spec);
  });
  network.on('blurNode', hideSpecTooltip);
  network.on('dragStart', function(params) {
    hideSpecTooltip();
    if (params.nodes && params.nodes.length > 0) {
      _suppressNextNodeClick = true;
      _isNodeDragging = true;
      // If AUTO is currently running, drag means "I want manual control now."
      // Stop physics immediately so the simulation doesn't fight the user.
      if (_physicsRunning) stopAutoArrange();
    }
  });

  // Persist node positions when the user drags them.
  // When snap is enabled, round to GRAPH_SNAP_PX so released nodes auto-align.
  network.on('dragEnd', function(params) {
    _isNodeDragging = false;
    if (!params.nodes || params.nodes.length === 0) return;
    const positions = network.getPositions(params.nodes);
    let changed = false;
    const updates = [];
    for (const id of params.nodes) {
      const p = positions[id];
      if (!p) continue;
      let nx = Math.round(p.x);
      let ny = Math.round(p.y);
      if (graphSnap) {
        nx = Math.round(nx / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
        ny = Math.round(ny / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
      }
      graphPositions[id] = { x: nx, y: ny };
      updates.push({ id, x: nx, y: ny });
      changed = true;
    }
    if (updates.length) graphNodesDataset.update(updates);
    if (changed) saveSettings();
  });

  network.on('doubleClick', function() {
    network.fit();
  });
}

function highlightNode(nodeId) {
  const allEdges = graphEdgesDataset.get();

  // Build per-node adjacency from live edge set
  const outEdges = {};  // nodeId → [{id, to}]
  const inEdges  = {};  // nodeId → [{id, from}]
  for (const e of allEdges) {
    (outEdges[e.from] = outEdges[e.from] || []).push({ id: e.id, to: e.to });
    (inEdges[e.to]   = inEdges[e.to]   || []).push({ id: e.id, from: e.from });
  }

  // BFS upstream (ancestors) + downstream (descendants) from selected node
  const pathEdgeIds = new Set();
  const visited = new Set([nodeId]);

  const upQueue = [nodeId];
  while (upQueue.length) {
    const cur = upQueue.shift();
    for (const { id: eid, from } of (inEdges[cur] || [])) {
      pathEdgeIds.add(eid);
      if (!visited.has(from)) { visited.add(from); upQueue.push(from); }
    }
  }

  const downQueue = [nodeId];
  while (downQueue.length) {
    const cur = downQueue.shift();
    for (const { id: eid, to } of (outEdges[cur] || [])) {
      pathEdgeIds.add(eid);
      if (!visited.has(to)) { visited.add(to); downQueue.push(to); }
    }
  }

  // Highlight full-path edges, dim everything else
  const edgeUpdates = allEdges.map(e => ({
    id: e.id,
    color: {
      color:   pathEdgeIds.has(e.id) ? '#4fc3f7' : 'rgba(68,68,68,0.15)',
      opacity: pathEdgeIds.has(e.id) ? 1.0 : 0.15,
    },
    width: pathEdgeIds.has(e.id) ? 2 : 1,
  }));
  graphEdgesDataset.update(edgeUpdates);

  // Focus and select the node
  network.focus(nodeId, { scale: 1.2, animation: true });
  network.selectNodes([nodeId]);

  // Update info bar
  const spec = specs.find(s => s.id === nodeId);
  const infoEl = document.getElementById('graph-info');
  if (spec) {
    const title = spec._title || spec.title || nodeId;
    infoEl.textContent = `${nodeId} │ ${effectiveStatus(spec)} │ ${title}`;
    infoEl.style.display = 'block';
  }
}

function restoreAllEdges() {
  const allEdges = graphEdgesDataset.get();
  const updates = allEdges.map(e => ({
    id: e.id,
    color: { color: '#444', opacity: 1.0 },
    width: 1,
  }));
  graphEdgesDataset.update(updates);
  network.unselectAll();
}

function clearInfoBar() {
  document.getElementById('graph-info').style.display = 'none';
}

function resetGraphLayout() {
  graphPositions = {};
  saveSettings();
  showGraph();  // re-render with default column layout
}

// Topological left→right layout with Sugiyama-style barycenter sorting.
//
// Column assignment: Kahn's longest-path (sources at x=0, most-blocked at right).
// Within-column order: barycenter heuristic (minimise edge crossings), with
// subtree weight (total transitive descendants) as tiebreaker so heavier
// blockers float to the top when crossings are neutral.
// Disconnected clusters are stacked vertically, largest first.
function applyDepsOrderLayout() {
  if (!graphNodesDataset || !graphEdgesDataset || !network) return;

  const allNodes = graphNodesDataset.get();
  const allEdges = graphEdgesDataset.get();

  // Build adjacency restricted to visible nodes
  const nodeIds = new Set(allNodes.map(n => n.id));
  const outgoing = {};
  const incoming = {};
  for (const n of allNodes) { outgoing[n.id] = []; incoming[n.id] = []; }
  for (const e of allEdges) {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      outgoing[e.from].push(e.to);
      incoming[e.to].push(e.from);
    }
  }

  // Connected components — undirected BFS
  const seen = new Set();
  const components = [];
  for (const n of allNodes) {
    if (seen.has(n.id)) continue;
    const comp = [];
    const q = [n.id];
    while (q.length) {
      const cur = q.shift();
      if (seen.has(cur)) continue;
      seen.add(cur); comp.push(cur);
      for (const nb of [...outgoing[cur], ...incoming[cur]]) {
        if (!seen.has(nb)) q.push(nb);
      }
    }
    components.push(comp);
  }
  components.sort((a, b) => b.length - a.length);  // largest first → top

  const COL_X       = 260;  // px between depth columns
  const ROW_Y       = 70;   // px between nodes in a column
  const GAP_Y       = 120;  // extra vertical gap between clusters
  const BARY_PASSES = 3;    // Sugiyama alternating sweeps

  const updates = [];
  let clusterTop = 0;

  for (const comp of components) {
    const compSet = new Set(comp);

    // ── 1. Kahn's longest-path depth ──────────────────────────────────────
    const inDeg = {};
    for (const id of comp) inDeg[id] = 0;
    for (const e of allEdges) {
      if (compSet.has(e.from) && compSet.has(e.to)) inDeg[e.to]++;
    }
    const depth     = {};
    const topoOrder = [];   // saved for subtree-weight pass
    const queue     = [];
    for (const id of comp) {
      if (inDeg[id] === 0) { depth[id] = 0; queue.push(id); }
    }
    let qi = 0;
    while (qi < queue.length) {
      const cur = queue[qi++];
      topoOrder.push(cur);
      for (const nb of outgoing[cur]) {
        if (!compSet.has(nb)) continue;
        const d = (depth[cur] || 0) + 1;
        if (depth[nb] === undefined || depth[nb] < d) depth[nb] = d;
        if (--inDeg[nb] === 0) queue.push(nb);
      }
    }
    for (const id of comp) { if (depth[id] === undefined) depth[id] = 0; }

    // ── 2. Subtree weight (total transitive descendants) ──────────────────
    // Process in reverse topological order so children are done before parents.
    const weight = {};
    for (const id of comp) weight[id] = 1;
    for (let i = topoOrder.length - 1; i >= 0; i--) {
      const id = topoOrder[i];
      for (const nb of outgoing[id]) {
        if (compSet.has(nb)) weight[id] += weight[nb];
      }
    }

    // ── 3. Build per-depth levels, seeded by weight desc ──────────────────
    const maxDepth = Math.max(...comp.map(id => depth[id]));
    const levels   = {};
    for (let d = 0; d <= maxDepth; d++) levels[d] = [];
    for (const id of comp) levels[depth[id]].push(id);
    for (let d = 0; d <= maxDepth; d++) {
      levels[d].sort((a, b) => weight[b] - weight[a]);
    }

    // ── 4. Barycenter passes ──────────────────────────────────────────────
    const maxColHeight = Math.max(...Object.values(levels).map(l => l.length));
    const bandCenter   = clusterTop + ((maxColHeight - 1) * ROW_Y) / 2;

    // nodeY tracks current Y coordinate used when computing neighbour barycentres
    const nodeY = {};
    const assignY = (d) => {
      const ids = levels[d];
      for (let i = 0; i < ids.length; i++) {
        nodeY[ids[i]] = bandCenter + (i - (ids.length - 1) / 2) * ROW_Y;
      }
    };
    for (let d = 0; d <= maxDepth; d++) assignY(d);

    // avg Y of a node's in-component neighbours; null if none have Y yet
    const baryOf = (id, neighbours) => {
      const ys = neighbours
        .filter(nb => compSet.has(nb) && nodeY[nb] !== undefined)
        .map(nb => nodeY[nb]);
      return ys.length ? ys.reduce((s, v) => s + v, 0) / ys.length : null;
    };

    const sortLevel = (d, neighboursFn) => {
      levels[d].sort((a, b) => {
        const ba = baryOf(a, neighboursFn(a));
        const bb = baryOf(b, neighboursFn(b));
        // Both have no neighbours in the adjacent column → fall back to weight
        if (ba === null && bb === null) return weight[b] - weight[a];
        if (ba === null) return 1;   // push unconnected to bottom
        if (bb === null) return -1;
        return ba !== bb ? ba - bb : weight[b] - weight[a];
      });
      assignY(d);
    };

    for (let pass = 0; pass < BARY_PASSES; pass++) {
      // Forward sweep: sort by average Y of predecessors
      for (let d = 1; d <= maxDepth; d++) sortLevel(d, id => incoming[id]);
      // Backward sweep: sort by average Y of successors
      for (let d = maxDepth - 1; d >= 0; d--) sortLevel(d, id => outgoing[id]);
    }

    // ── 5. Emit final positions ───────────────────────────────────────────
    for (let d = 0; d <= maxDepth; d++) {
      for (const id of levels[d]) {
        const x = d * COL_X;
        const y = nodeY[id];
        updates.push({ id, x, y });
        graphPositions[id] = { x, y };
      }
    }

    clusterTop += maxColHeight * ROW_Y + GAP_Y;
  }

  graphNodesDataset.update(updates);
  saveSettings();
  network.fit();
}

// AUTO is a toggle. Click once → physics starts. Click again → physics stops.
// Either way, dragging a node also immediately stops physics so the user can
// freeform-drag at any moment.
let _physicsRunning = false;

function autoArrangeGraph() {
  if (!network || !graphNodesDataset) return;
  if (_physicsRunning) {
    stopAutoArrange();
  } else {
    startAutoArrange();
  }
}

function startAutoArrange() {
  _physicsRunning = true;
  applyAutoBtnState();
  network.setOptions({
    physics: {
      enabled: true,
      barnesHut: {
        gravitationalConstant: -1500,
        centralGravity: 0.05,
        springLength: 110,
        springConstant: 0.04,
        damping: 0.55,
        avoidOverlap: 0.85,
      },
      stabilization: { enabled: true, iterations: 250, fit: false },
    },
  });
  // Auto-stop when stabilization completes (the natural settle point)
  network.once('stabilizationIterationsDone', () => {
    if (_physicsRunning) stopAutoArrange();
  });
}

function stopAutoArrange() {
  if (!_physicsRunning) return;
  _physicsRunning = false;
  applyAutoBtnState();
  network.setOptions({ physics: { enabled: false } });
  // Snapshot current physics-resolved positions and persist them
  const positions = network.getPositions();
  const updates = [];
  for (const id of Object.keys(positions)) {
    const p = positions[id];
    let nx = Math.round(p.x);
    let ny = Math.round(p.y);
    if (graphSnap) {
      nx = Math.round(nx / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
      ny = Math.round(ny / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
    }
    graphPositions[id] = { x: nx, y: ny };
    updates.push({ id, x: nx, y: ny });
  }
  if (updates.length) graphNodesDataset.update(updates);
  saveSettings();
}

function applyAutoBtnState() {
  const btn = document.getElementById('btn-graph-auto');
  if (!btn) return;
  btn.textContent = _physicsRunning ? '⏸ STOP' : '⚙ AUTO';
  btn.classList.toggle('active', _physicsRunning);
  btn.title = _physicsRunning
    ? 'Physics is running — click to stop and lock current positions, or drag any node'
    : 'Toggle force-directed auto-arrange; click again or drag a node to stop';
}

function toggleGraphSnap() {
  graphSnap = !graphSnap;
  applyGraphSnapBtnState();
  saveSettings();
  // Re-snap currently positioned nodes if turning ON
  if (graphSnap && network && graphNodesDataset) {
    const updates = [];
    const positions = network.getPositions();
    for (const id of Object.keys(positions)) {
      const p = positions[id];
      const nx = Math.round(p.x / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
      const ny = Math.round(p.y / GRAPH_SNAP_PX) * GRAPH_SNAP_PX;
      updates.push({ id, x: nx, y: ny });
      if (graphPositions[id]) graphPositions[id] = { x: nx, y: ny };
    }
    if (updates.length) graphNodesDataset.update(updates);
    saveSettings();
  }
}

function applyGraphSnapBtnState() {
  const btn = document.getElementById('btn-graph-snap');
  if (!btn) return;
  btn.classList.toggle('active', !!graphSnap);
}

// Build the graph legend dynamically. Each item is clickable: toggling it
// adds/removes the status from `hiddenColumns` (shared with the board), then
// re-renders both the legend visual state and the graph.
function renderGraphLegend() {
  const el = document.getElementById('graph-legend');
  if (!el) return;
  el.innerHTML = '';
  const cssVarFor = {
    planned: '--c-planned', draft: '--c-draft', ready: '--c-ready', in_progress: '--c-in-progress',
    blocked: '--c-blocked', active: '--c-active', done: '--c-done',
    superseded: '--c-superseded', retired: '--c-retired',
  };
  const labelOf = (s) => s.toUpperCase();
  for (const status of STATUS_IDS) {
    const item = document.createElement('div');
    const isHidden = graphHiddenStatuses.has(status);
    item.className = 'legend-item' + (isHidden ? ' legend-hidden' : '');
    item.innerHTML = `<span class="legend-dot" style="background:var(${cssVarFor[status]})"></span>${labelOf(status)}`;
    item.title = isHidden ? `Show ${labelOf(status)} in graph (hidden)` : `Hide ${labelOf(status)} from graph`;
    item.addEventListener('click', () => {
      if (graphHiddenStatuses.has(status)) graphHiddenStatuses.delete(status);
      else graphHiddenStatuses.add(status);
      saveSettings();
      renderGraphLegend();
      showGraph();  // re-render with new filter
    });
    el.appendChild(item);
  }
  // Grouping-edge toggle — dashed parent (membership) edges on/off.
  const ge = document.createElement('div');
  ge.className = 'legend-item' + (showGroupingEdges ? '' : ' legend-hidden');
  ge.innerHTML = `<span class="legend-dot" style="background:transparent;border-top:2px dashed var(--text-muted);border-radius:0"></span>GROUPING`;
  ge.title = showGroupingEdges ? 'Hide dashed parent (grouping) edges' : 'Show dashed parent (grouping) edges';
  ge.addEventListener('click', () => {
    showGroupingEdges = !showGroupingEdges;
    saveSettings();
    renderGraphLegend();
    showGraph();  // re-render with/without grouping edges
  });
  el.appendChild(ge);
}

async function showBoard() {
  activeTab = 'board';
  document.getElementById('board-view').style.display = 'flex';
  document.getElementById('graph-view').classList.remove('active');
  // Tab-activate sync: always full renderBoard() on switch from graph.
  // showGraph() silently updates specs[] without re-rendering the board, so
  // renderBoardDiff(prevSpecs=fresh, fresh) would see zero diff and leave
  // stale card positions/statuses in the DOM. Board was hidden — no jank.
  try {
    const r = await fetch('/api/specs');
    if (r.ok) {
      specs = await r.json();
      renderBoard();
      renderRecentBar();
      if (openPanelId) applyActiveCard(openPanelId);
    }
  } catch {}
  if (document.getElementById('search').value) {
    document.getElementById('search-results').classList.add('visible');
    document.getElementById('board-view').style.display = 'none';
  }
}

// Search
const searchInput = document.getElementById('search');
searchInput.addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  const clearBtn = document.getElementById('btn-clear-search');
  clearBtn.classList.toggle('visible', q.length > 0);
  if (!q) {
    document.getElementById('search-results').classList.remove('visible');
    if (activeTab === 'board') document.getElementById('board-view').style.display = 'flex';
    return;
  }
  searchTimer = setTimeout(() => doSearch(q), 250);
});

function clearSearch() {
  searchInput.value = '';
  document.getElementById('btn-clear-search').classList.remove('visible');
  document.getElementById('search-results').classList.remove('visible');
  if (activeTab === 'board') document.getElementById('board-view').style.display = 'flex';
  // Panel intentionally left open
}

async function doSearch(q) {
  const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  const results = await r.json();

  const el = document.getElementById('search-results');
  document.getElementById('board-view').style.display = 'none';

  if (!results.length) {
    el.innerHTML = '<div class="search-empty">no results</div>';
    el.classList.add('visible');
    return;
  }

  const listEl = document.createElement('div');
  listEl.className = 'search-list';

  for (const res of results) {
    const spec = specs.find(s => s.id === res.id) || { status: res.status };
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.id = res.id;
    const status = effectiveStatus(spec);
    card.dataset.status = status;
    card.innerHTML = `
      <div class="card-header">
        <span class="card-id">${res.id}</span>
      </div>
      <div class="card-title">${res.title || res.id}</div>
      <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">${res.excerpt || ''}</div>
    `;
    card.addEventListener('click', () => openPanel(res.id));
    listEl.appendChild(card);
  }

  el.innerHTML = '';
  el.appendChild(listEl);
  el.classList.add('visible');
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if (e.key === '/') {
    const panel = document.getElementById('panel');
    if (!panel.classList.contains('open')) {
      e.preventDefault();
      searchInput.focus();
    }
  }
  if (e.key === 'Escape') {
    const dd = document.getElementById('col-vis-dropdown');
    if (dd.classList.contains('open')) { dd.classList.remove('open'); return; }
    if (searchInput.value) { clearSearch(); return; }
    const panel = document.getElementById('panel');
    if (panel.classList.contains('open')) clearSelection();
  }
});

// Click outside panel closes it (but not clicks on cards or search UI)
document.addEventListener('click', (e) => {
  const panel = document.getElementById('panel');
  if (panel.classList.contains('open') &&
      !panel.contains(e.target) &&
      !e.target.closest('.card') &&
      !e.target.closest('#search') &&
      !e.target.closest('#btn-clear-search') &&
      !e.target.closest('#search-results') &&
      !e.target.closest('.col-resize') &&
      !e.target.closest('#panel-resize') &&
      !e.target.closest('#graph-container')) {
    closePanel();
  }
  // Close col-vis dropdown when clicking outside it
  const dd = document.getElementById('col-vis-dropdown');
  if (dd.classList.contains('open') && !e.target.closest('#col-vis-wrap')) {
    dd.classList.remove('open');
  }
  // Close type-filter dropdown when clicking outside it
  const tdd = document.getElementById('type-filter-dropdown');
  if (tdd.classList.contains('open') && !e.target.closest('#type-filter-wrap')) {
    tdd.classList.remove('open');
  }
});

// ── Column resize ──
function startResize(e, colId, colEl) {
  e.preventDefault();
  const startX = e.clientX;
  const startW = colEl.offsetWidth;
  const handle = colEl.querySelector('.col-resize');
  handle.classList.add('dragging');

  function onMove(ev) {
    const newW = Math.max(140, Math.min(600, startW + ev.clientX - startX));
    colEl.style.cssText = `width:${newW}px; flex:none; min-width:${newW}px`;
    columnWidths[colId] = newW;
    if (openPanelId) applyActiveCard(openPanelId);
  }
  function onUp() {
    handle.classList.remove('dragging');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    saveSettings();
  }
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

// ── Auto-fit columns ──
// Distribute all visible, non-collapsed columns to fill the board viewport
// width proportionally. Preserves column order, visibility, and collapsed state.
function fitColumns() {
  const boardView = document.getElementById('board-view');
  const cs = getComputedStyle(boardView);
  const paddingH = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
  const gap = parseFloat(cs.gap) || 10;

  const visibleExpanded = columnOrder.filter(
    id => !hiddenColumns.has(id) && !collapsedColumns.has(id)
  );
  if (visibleExpanded.length === 0) return;

  // Collapsed columns each occupy 32px (matches .column--collapsed CSS)
  const collapsedCount = columnOrder.filter(
    id => !hiddenColumns.has(id) && collapsedColumns.has(id)
  ).length;
  const numVisible = visibleExpanded.length + collapsedCount;
  const collapsedW = collapsedCount * 32;
  const gapsW = Math.max(0, numVisible - 1) * gap;
  const contentW = boardView.clientWidth - paddingH - gapsW - collapsedW;
  const perCol = Math.max(140, Math.floor(contentW / visibleExpanded.length));

  for (const id of visibleExpanded) {
    columnWidths[id] = perCol;
  }
  renderBoard();
  saveSettings();
}

// ── Header height sync ──
// Keep --header-h in sync so the detail panel starts below the toolbar.
function syncHeaderHeight() {
  const h = document.getElementById('header').offsetHeight;
  document.documentElement.style.setProperty('--header-h', h + 'px');
}

// ── Column visibility ──
function buildColVisDropdown() {
  const dd = document.getElementById('col-vis-dropdown');
  dd.innerHTML = '';
  const orderedCols = columnOrder.map(id => COLUMNS.find(c => c.id === id)).filter(Boolean);
  for (const col of orderedCols) {
    const item = document.createElement('label');
    item.className = 'col-vis-item';
    item.dataset.colId = col.id;
    const checked = !hiddenColumns.has(col.id);
    const isCollapsed = collapsedColumns.has(col.id);
    const collapseSymbol = isCollapsed ? '◁' : '▷';
    item.innerHTML = `<span class="col-drag-handle" title="drag to reorder">⠿</span><span class="col-vis-left"><input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleColVis('${col.id}', this.checked)"> ${col.label}</span><button class="col-collapse-btn" onclick="event.preventDefault(); toggleCollapse('${col.id}')">${collapseSymbol}</button>`;
    dd.appendChild(item);
  }
  // Enable drag-to-reorder via SortableJS
  if (dd._sortable) dd._sortable.destroy();
  dd._sortable = new Sortable(dd, {
    handle: '.col-drag-handle',
    animation: 120,
    onEnd: () => {
      const items = dd.querySelectorAll('.col-vis-item[data-col-id]');
      columnOrder = [...items].map(el => el.dataset.colId);
      renderBoard();
      saveSettings();
    },
  });
}

function toggleColVisDropdown() {
  const dd = document.getElementById('col-vis-dropdown');
  buildColVisDropdown();
  dd.classList.toggle('open');
}

function toggleColVis(colId, visible) {
  if (visible) hiddenColumns.delete(colId);
  else hiddenColumns.add(colId);
  renderBoard();
  saveSettings();
}

function buildTypeFilterDropdown() {
  const dd = document.getElementById('type-filter-dropdown');
  dd.innerHTML = '';
  const types = [...new Set(specs.map(s => s.type || 'feature'))].sort();
  for (const t of types) {
    const item = document.createElement('label');
    item.className = 'type-filter-item';
    const checked = activeTypeFilters.has(t);
    item.innerHTML = `<input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleTypeFilter('${t}', this.checked)"> ${t}`;
    dd.appendChild(item);
  }
}

function toggleTypeFilterDropdown() {
  const dd = document.getElementById('type-filter-dropdown');
  buildTypeFilterDropdown();
  dd.classList.toggle('open');
}

function toggleTypeFilter(type, checked) {
  if (checked) activeTypeFilters.add(type);
  else activeTypeFilters.delete(type);
  // Update button to show active state
  document.getElementById('btn-type-filter').classList.toggle('active', activeTypeFilters.size > 0);
  renderBoard();
  if (activeTab === 'graph') showGraph();
  saveSettings();
}

// Toast
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3000);
}

// ── Reports panel ──
function setPanelView(view) {
  panelView = view;
  document.getElementById('panel-view-spec').style.display            = view === 'spec'           ? '' : 'none';
  document.getElementById('panel-view-reports').style.display         = view === 'reports'        ? '' : 'none';
  document.getElementById('panel-view-report-content').style.display  = view === 'report-content' ? '' : 'none';
  const backBtn = document.getElementById('panel-back-btn');
  const copyIdBtn = document.getElementById('btn-copy-id');
  if (view === 'spec') {
    if (specNavStack.length > 0) {
      backBtn.style.display = '';
      backBtn.textContent = '← ' + specNavStack[specNavStack.length - 1].specId;
    } else {
      backBtn.style.display = 'none';
    }
    copyIdBtn.style.display = '';
  } else if (view === 'reports') {
    copyIdBtn.style.display = 'none';
    // Back-to-spec only makes sense if we *came from* a spec; from the header
    // REPORTS button there's no spec to go back to, so hide.
    backBtn.style.display = openPanelId ? '' : 'none';
    backBtn.textContent = '← SPEC';
  } else { // 'report-content'
    copyIdBtn.style.display = 'none';
    backBtn.style.display = '';
    backBtn.textContent = '← REPORTS';
  }
  // Update the header label to reflect what's showing
  const headerLabel = document.getElementById('panel-id');
  if (headerLabel) {
    if (view === 'spec' && openPanelId) {
      headerLabel.textContent = openPanelId;
    } else if (view === 'reports') {
      headerLabel.textContent = openPanelId ? openPanelId + ' · REPORTS' : 'ALL REPORTS';
    } else if (view === 'report-content') {
      headerLabel.textContent = openPanelId ? openPanelId + ' · REPORT' : 'REPORT';
    }
  }
}

async function copyText(text) {
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    // Clipboard permissions and secure-context requirements vary by browser.
  }

  const textarea = document.createElement('textarea');
  const activeElement = document.activeElement;
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    return typeof document.execCommand === 'function' && document.execCommand('copy');
  } catch (_) {
    return false;
  } finally {
    textarea.remove();
    if (activeElement && typeof activeElement.focus === 'function') activeElement.focus();
  }
}

async function copySpecId() {
  if (!openPanelId) return;
  const copied = await copyText(openPanelId);
  if (copied) {
    const btn = document.getElementById('btn-copy-id');
    const prev = btn.textContent;
    btn.textContent = '✓';
    setTimeout(() => { btn.textContent = prev; }, 1500);
  } else {
    showToast('⚠ clipboard write failed');
  }
}

function specPromptTitle(specId) {
  const panelTitle = document.getElementById('panel-title');
  if (openPanelId === specId && panelTitle && panelTitle.textContent.trim()) {
    return panelTitle.textContent.trim();
  }
  const spec = specs.find(s => s.id === specId);
  return spec ? (spec._title || spec.title || '') : '';
}

function buildRunPrompt(specId, specTitle = '') {
  const title = (specTitle || '').trim();
  const regexChars = '.+*?^$()[]{}|\\\\';
  const escapedSpecId = [...specId].map(ch => regexChars.includes(ch) ? `\\\\${ch}` : ch).join('');
  const titleStartsWithSpecId = new RegExp(`^${escapedSpecId}(?:$|\\\\s|[—–-])`).test(title);
  const specLabel = title && !titleStartsWithSpecId ? `${specId} ${title}` : (title || specId);
  return [
    'Use the Nightshift kickoff command to run this spec:',
    '',
    `/nightshift kickoff ${specLabel}`,
    '',
    'This is the parent kickoff flow. Follow the /nightshift kickoff skill exactly.',
    'Do not implement, research, validate, or code the spec yourself. Launch and coordinate the orchestrator subagent through the skill flow, monitor progress, then autonomously resolve the run as the skill specifies: verify the evidence gate and merge if sufficient; if the orchestrator reports blocked/stuck, run one focused unblock pass before marking the spec blocked; after the run report is written, process any "## Suggested Follow-up Specs" section per the skill (check_followup_spec.py conflict check).',
  ].join('\\n');
}

async function copyRunPrompt() {
  if (!openPanelId) { showToast('no spec selected'); return; }
  const specId = openPanelId;
  const copied = await copyText(buildRunPrompt(specId, specPromptTitle(specId)));
  if (copied) {
    showToast(`▶ run prompt copied for ${specId}`);
  } else {
    showToast('⚠ clipboard write failed');
  }
}

async function openCurrentSpecInVSCode() {
  if (!openPanelId) { showToast('no spec selected'); return; }
  const specId = openPanelId;
  try {
    const r = await fetch(`/api/open/spec/${encodeURIComponent(specId)}`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    showToast(`↗ opened ${specId} in VS Code`);
  } catch (e) {
    showToast('⚠ VS Code open failed');
  }
}

async function openCurrentReportInVSCode() {
  if (!currentReportFilename) { showToast('no report selected'); return; }
  const encoded = currentReportFilename.split('/').map(encodeURIComponent).join('/');
  try {
    const r = await fetch(`/api/open/report/${encoded}`, { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    showToast('↗ opened report in VS Code');
  } catch (e) {
    showToast('⚠ VS Code open failed');
  }
}

async function panelGoBack() {
  if (panelView === 'spec' && specNavStack.length > 0) {
    const prev = specNavStack.pop();
    await openPanel(prev.specId, { keepNavStack: true });
    document.getElementById('panel-body').scrollTop = prev.scrollTop;
  } else if (panelView === 'reports') {
    setPanelView('spec');
  } else if (panelView === 'report-content') {
    setPanelView('reports');
    document.getElementById('panel-body').scrollTop = reportsListScrollTop;
  }
}

// Called from a spec card's REPORTS button. Pre-fills the filter with the
// currently-open spec ID so the user only sees reports for that spec by default.
async function openReportsView() {
  const r = await fetch('/api/reports');
  reportsCache = await r.json();
  reportsFilter = openPanelId || '';
  document.getElementById('reports-filter').value = reportsFilter;
  renderReportsList();
  setPanelView('reports');
}

// Called from the header REPORTS button. No spec context, no pre-filter —
// shows everything in the project.
async function openReportsViewFromHeader() {
  // Detach any open spec so the panel header reads "ALL REPORTS"
  // and the back button is hidden (no spec to go back to).
  openPanelId = null;
  openPanelMtime = null;
  document.querySelectorAll('.card--active').forEach(c => c.classList.remove('card--active'));
  renderRecentBar();
  const r = await fetch('/api/reports');
  reportsCache = await r.json();
  reportsFilter = '';
  document.getElementById('reports-filter').value = '';
  renderReportsList();
  setPanelView('reports');
  document.getElementById('panel').classList.add('open');
}

function clearReportsFilter() {
  reportsFilter = '';
  document.getElementById('reports-filter').value = '';
  renderReportsList();
  document.getElementById('reports-filter').focus();
}

// Live filtering as user types in the filter input
document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'reports-filter') {
    reportsFilter = e.target.value;
    renderReportsList();
  }
});

// Intercept spec:// links rendered inside markdown bodies — open in the same
// panel with a scroll-restoring ← back button instead of browser navigation.
document.getElementById('panel-body').addEventListener('click', function(e) {
  const a = e.target.closest('a');
  if (!a) return;
  const href = a.getAttribute('href') || '';
  if (!href.startsWith('spec://')) return;
  e.preventDefault();
  const linkedId = href.slice('spec://'.length);
  if (!linkedId || linkedId === openPanelId) return;
  const panelBody = document.getElementById('panel-body');
  specNavStack.push({ specId: openPanelId, scrollTop: panelBody.scrollTop });
  if (specNavStack.length > 10) specNavStack.shift();
  openPanel(linkedId, { keepNavStack: true });
  panelBody.scrollTop = 0;
});

function renderReportsList() {
  const el = document.getElementById('panel-reports-list');
  el.innerHTML = '';
  const filter = (reportsFilter || '').trim().toLowerCase();
  const visible = filter
    ? reportsCache.filter(r =>
        ((r.filename || '') + ' ' + (r.name || '')).toLowerCase().includes(filter))
    : reportsCache;
  const totalUnread = reportsCache.filter(r => !r.is_read).length;
  // Show/hide action buttons based on whether there's anything to act on
  const markAllBtn = document.getElementById('btn-mark-all-read');
  if (markAllBtn) markAllBtn.style.display = totalUnread > 0 ? '' : 'none';
  if (!visible.length) {
    const empty = document.createElement('div');
    empty.className = 'reports-empty';
    empty.textContent = filter ? `no reports match "${filter}"` : 'no reports found';
    el.appendChild(empty);
    return;
  }
  const visibleUnread = visible.filter(r => !r.is_read).length;
  const heading = document.createElement('div');
  heading.className = 'reports-heading';
  heading.textContent = filter
    ? `${visible.length} of ${reportsCache.length} · ${visibleUnread} unread`
    : `${reportsCache.length} reports · ${totalUnread} unread`;
  el.appendChild(heading);
  for (const report of visible) {
    const item = document.createElement('div');
    item.className = 'report-item' + (report.is_read ? ' read' : '');
    const dateStr = report.mtime ? new Date(report.mtime * 1000).toISOString().slice(0, 10) : '';
    // Display: short basename (without .md), with the directory path as a subtitle hint
    const displayName = (report.name || report.filename).replace(/[.]md$/, '');
    const dir = report.filename.includes('/') ? report.filename.slice(0, report.filename.lastIndexOf('/')) : '';
    const subtitle = dir ? `${dateStr} · ${dir}` : dateStr;
    item.innerHTML = `
      <span class="report-dot ${report.is_read ? 'read' : 'unread'}">${report.is_read ? '○' : '●'}</span>
      <div class="report-info">
        <div class="report-name">${displayName}</div>
        <div class="report-meta-line">${subtitle}</div>
      </div>`;
    item.addEventListener('click', () => openReportContent(report.filename));
    el.appendChild(item);
  }
}

async function openReportContent(filename) {
  currentReportFilename = filename;
  const r = await fetch(`/api/report/${encodeURIComponent(filename)}`);
  if (!r.ok) { showToast('⚠ could not load report'); return; }
  const data = await r.json();

  // Display: short name, with directory hint underneath if present
  const shortName = (filename.split('/').pop() || filename).replace(/[.]md$/, '');
  document.getElementById('panel-report-filename').textContent = shortName;
  document.getElementById('panel-report-filename').title = filename;
  const mdEl = document.getElementById('panel-report-md');
  const content = data.content || '';
  mdEl.innerHTML = (typeof marked !== 'undefined') ? marked.parse(content) : `<pre>${content}</pre>`;

  const report = reportsCache.find(rp => rp.filename === filename);
  document.getElementById('btn-mark-read').style.display = (report && report.is_read) ? 'none' : '';

  reportsListScrollTop = document.getElementById('panel-body').scrollTop;
  setPanelView('report-content');
}

async function markReportRead() {
  if (!currentReportFilename) return;
  await fetch('/api/reports/read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: currentReportFilename }),
  });
  const report = reportsCache.find(r => r.filename === currentReportFilename);
  if (report) report.is_read = true;
  document.getElementById('btn-mark-read').style.display = 'none';
  updateReportsBtnLabel();
  // Re-render the list immediately so when the user clicks BACK they see
  // the updated read state (faded, no accent rail) without needing a refresh.
  renderReportsList();
  showToast('✓ marked as read');
}

async function markAllReportsRead() {
  const unread = reportsCache.filter(r => !r.is_read);
  if (!unread.length) { showToast('nothing to mark'); return; }
  const r = await fetch('/api/reports/read-all', { method: 'POST' });
  if (!r.ok) { showToast('⚠ could not mark all read'); return; }
  const { count } = await r.json();
  reportsCache.forEach(r => { r.is_read = true; });
  renderReportsList();
  updateReportsBtnLabel();
  showToast(`✓ ${count} report${count !== 1 ? 's' : ''} marked as read`);
}

async function copyQuestionsPrompt() {
  const unread = reportsCache.filter(r => !r.is_read);
  const targets = unread.length ? unread : reportsCache;
  if (!targets.length) { showToast('no reports to include'); return; }
  const fileList = targets.map(r => `- ${r.filename}`).join('\\n');
  const today = new Date().toISOString().slice(0, 10);
  const prompt = [
    'Read the Nightshift run reports listed below.',
    'For each report, extract every item under ## Open Questions.',
    'Also read the ## Blocked Specs section and flag any specs blocked on a decision.',
    '',
    'Consolidate all questions into a new QUESTIONS spec file at',
    '.nightshift/specs/{PROJECT}-QUESTIONS-NNN.md using this exact format:',
    '',
    '---',
    'id: {PROJECT}-QUESTIONS-NNN',
    'type: questions',
    'status: draft',
    `created: ${today}`,
    'wave: {short wave description}',
    'sources: [{comma-separated spec IDs mentioned across all questions}]',
    '---',
    '',
    '# Open Questions — {wave}',
    '',
    'Found N open questions across M source specs. X blockers, Y advisory.',
    '',
    '**Blockers (decision needed before promoting any spec to `ready`):** Q1, Q2, ...',
    '',
    '---',
    '',
    '## Q1 — {short title}',
    '',
    '**Source:** {SPEC-ID} § Open Questions',
    '**Severity:** blocker | advisory',
    '**Status:** OPEN',
    '',
    '**Question:** {full question text from the source}',
    '',
    '**Options (from source spec):**',
    '- A: ...',
    '- B: ...',
    '',
    '**Recommendation (from spec, if any):** ...',
    '',
    '**Decision:** _(pending)_',
    '',
    '---',
    '',
    '(repeat for Q2, Q3, ... — blockers first, then advisory)',
    '',
    'Reports to scan:',
    fileList,
  ].join('\\n');
  const copied = await copyText(prompt);
  if (copied) {
    showToast(`⧉ prompt copied (${targets.length} report${targets.length !== 1 ? 's' : ''})`);
  } else {
    showToast('⚠ clipboard write failed');
  }
}

function updateReportsBtnLabel() {
  const btn = document.getElementById('panel-reports-btn');
  if (!btn) return;
  const allUnread = reportsCache.filter(r => !r.is_read).length;
  const specId = openPanelId || '';
  // Reports that match the current spec ID (same matching rule the pre-filter uses)
  const specReports = specId
    ? reportsCache.filter(r =>
        ((r.filename || '') + ' ' + (r.name || '')).toLowerCase().includes(specId.toLowerCase()))
    : reportsCache;
  const specUnread = specReports.filter(r => !r.is_read).length;

  if (allUnread === 0) {
    btn.textContent = '📋 REPORTS';
    btn.title = 'No unread reports';
  } else if (!specId || specUnread === allUnread) {
    // No spec context, or all unreads happen to be for this spec — one number is enough
    btn.textContent = `📋 REPORTS (${allUnread} unread)`;
    btn.title = `${allUnread} unread report(s)`;
  } else {
    // Both numbers shown so the user can tell what they'll see when they open the panel
    btn.textContent = `📋 REPORTS (${specUnread}/${allUnread} unread)`;
    btn.title = `${specUnread} unread for ${specId} · ${allUnread} unread total (clear filter inside the panel to see them all)`;
  }
}

// ─────────────────────────────────────────────────────────────────────────
// SPEC-063: diff render + tab-activate sync + dep-aware panel refresh
// ─────────────────────────────────────────────────────────────────────────

// Classify the change between two specs[] snapshots. Drives the choice between
// diff render (cheap, single-card swap) and full renderBoard (safe, handles
// column moves and SortableJS state).
function classifySpecsChange(prev, fresh, prevWtStatus, freshWtStatus) {
  const prevById = new Map(prev.map(s => [s.id, s]));
  const freshById = new Map(fresh.map(s => [s.id, s]));
  const added = [], removed = [], statusChanged = [], onlyMtimeChanged = [];
  for (const [id, f] of freshById) {
    const p = prevById.get(id);
    if (!p) { added.push(id); continue; }
    if (effectiveStatusFor(p, prevWtStatus) !== effectiveStatusFor(f, freshWtStatus)) statusChanged.push(id);
    else if (p._mtime !== f._mtime) onlyMtimeChanged.push(id);
  }
  for (const id of prevById.keys()) if (!freshById.has(id)) removed.push(id);
  return { added, removed, statusChanged, onlyMtimeChanged };
}

function hasSpecsChange(change) {
  return !!(change.added.length || change.removed.length || change.statusChanged.length || change.onlyMtimeChanged.length);
}

function graphNeedsFullRebuild(change) {
  return !!(change.added.length || change.removed.length || change.statusChanged.length);
}

// Board diff render. Single-card swap when only mtime changed; falls back to
// full renderBoard() for column moves and add/remove (preserves Sortable state).
function renderBoardDiff(prevSpecs, freshSpecs, prevWtStatus, freshWtStatus) {
  const change = classifySpecsChange(prevSpecs, freshSpecs, prevWtStatus, freshWtStatus);
  if (change.added.length || change.removed.length || change.statusChanged.length) {
    renderBoard();
    return;
  }
  if (!change.onlyMtimeChanged.length) return;
  const blocksMap = buildBlocksMap();
  const freshById = new Map(freshSpecs.map(s => [s.id, s]));
  for (const id of change.onlyMtimeChanged) {
    const existing = document.querySelector(`.card[data-id="${id}"]`);
    if (!existing) continue;
    const fresh = freshById.get(id);
    if (!fresh) continue;
    existing.replaceWith(renderCard(fresh, blocksMap));
  }
  if (openPanelId) applyActiveCard(openPanelId);
}

// Graph diff: incremental node color update via vis.DataSet. Topology changes
// (add/remove/edge change) still require full showGraph() — for now we just
// skip when the network isn't initialized.
function updateGraphFromSpecs(freshSpecs) {
  if (!network || !graphNodesDataset) return;
  const css = getComputedStyle(document.documentElement);
  const themeColor   = (css.getPropertyValue('--c-theme').trim() || '#74c0fc');
  const textColor    = (css.getPropertyValue('--text').trim() || '#d4d4d4');
  const surfaceColor = (css.getPropertyValue('--surface').trim() || '#1a1d24');
  const colorForStatus = (s) => (css.getPropertyValue(STATUS_TO_CSSVAR[s] || '--text-muted').trim() || '#888');

  // Only update nodes that the graph already knows about. Topology changes
  // (a new spec appearing) require a full rebuild — handled by showGraph()
  // on next tab-activate.
  const known = new Set(graphNodesDataset.getIds());
  const updates = [];
  for (const spec of freshSpecs) {
    if (!known.has(spec.id)) continue;
    const eff = effectiveStatus(spec);
    if (graphHiddenStatuses.has(eff)) continue;
    const c = colorForStatus(eff);
    updates.push({
      id: spec.id,
      color: { background: c, border: c, highlight: { background: c, border: themeColor } },
    });
  }
  if (updates.length) graphNodesDataset.update(updates);
}

// Does the open spec reference otherSpecId (any direction)?
function panelDependsOn(openSpec, otherSpecId) {
  if (!openSpec) return false;
  const refs = new Set();
  for (const arr of [openSpec.after, openSpec.requires, openSpec.children, openSpec.violates, openSpec.nfrs]) {
    if (Array.isArray(arr)) for (const r of arr) refs.add(r);
  }
  if (openSpec.parent) refs.add(openSpec.parent);
  // Reverse edge (X blocks Y means Y depends on X for dep-display purposes too)
  const blocks = buildBlocksMap()[openSpec.id] || [];
  for (const b of blocks) refs.add(b);
  return refs.has(otherSpecId);
}

// Re-render only the panel's `after:` / `blocks:` chips. Cheap — no body fetch,
// no scroll-jump. Run when a dep's status changed but the open spec itself didn't.
function refreshPanelDependencies() {
  if (!openPanelId) return;
  const openSpec = specById(openPanelId);
  if (!openSpec || !openSpec.id) return;
  const after = openSpec.after || [];
  const blocks = buildBlocksMap()[openPanelId] || [];
  let chipsHtml = '';
  if (after.length) {
    chipsHtml += `<div class="chips-row"><span class="chips-label">after:</span>`;
    for (const dep of after) chipsHtml += renderSpecChip(dep);
    chipsHtml += '</div>';
  }
  if (blocks.length) {
    chipsHtml += `<div class="chips-row"><span class="chips-label">blocks:</span>`;
    for (const dep of blocks) chipsHtml += renderSpecChip(dep);
    chipsHtml += '</div>';
  }
  const el = document.getElementById('panel-chips');
  if (el) {
    el.innerHTML = chipsHtml;
    attachSpecRefPreview(el);
    // SPEC-064: also refresh external dep statuses on dep change
    fillExternalChipStatuses(el);
  }
}

// Auto-poll: refresh spec data every 10s on board or graph tab.
async function pollSpecs() {
  if (activeTab !== 'board' && activeTab !== 'graph') return;
  if (activeTab === 'board' && document.getElementById('search').value.trim()) return;
  try {
    const prevSpecs = specs;
    const prevWorktreeStatus = worktreeStatus;
    const prevOpenMtime = openPanelMtime;
    const [specsR, wsR] = await Promise.all([
      fetch('/api/specs'),
      fetch('/api/worktree-status').catch(() => null),
    ]);
    const fresh = await specsR.json();
    const freshWs = wsR && wsR.ok ? await wsR.json() : {};
    const change = classifySpecsChange(prevSpecs, fresh, prevWorktreeStatus, freshWs);
    const specsChanged = hasSpecsChange(change);
    const wsChanged = JSON.stringify(freshWs) !== JSON.stringify(prevWorktreeStatus);
    if (specsChanged || wsChanged) {
      specs = fresh;
      worktreeStatus = freshWs;
      if (specsChanged) renderPendingWork();
      if (activeTab === 'board') {
        if (wsChanged && !specsChanged) {
          // Worktree branch/path metadata can change without changing the
          // effective status. The card badge still needs a fresh render.
          renderBoard();
        } else {
          renderBoardDiff(prevSpecs, fresh, prevWorktreeStatus, freshWs);
        }
        renderRecentBar();
      }
      if (activeTab === 'graph') {
        if (graphNeedsFullRebuild(change)) {
          await showGraph();
        } else {
          updateGraphFromSpecs(fresh);
        }
      }
      if (openPanelId) applyActiveCard(openPanelId);

      if (openPanelId) {
        const openSpec = fresh.find(s => s.id === openPanelId);
        if (!openSpec) {
          clearSelection();
        } else if (openSpec._mtime !== prevOpenMtime) {
          // Open spec itself changed → reload full panel
          const panelBody = document.getElementById('panel-body');
          const prevScroll = panelBody ? panelBody.scrollTop : 0;
          await openPanel(openPanelId, { keepNavStack: true });
          if (panelBody) panelBody.scrollTop = prevScroll;
        } else {
          // SPEC-063: open spec didn't change, but a referenced dep may have.
          // Cheap chip refresh, no body re-fetch.
          const depChanged = fresh.some(s => {
            if (!panelDependsOn(openSpec, s.id)) return false;
            const prev = prevSpecs.find(p => p.id === s.id);
            return !prev || prev._mtime !== s._mtime ||
              effectiveStatusFor(prev, prevWorktreeStatus) !== effectiveStatusFor(s, freshWs);
          });
          if (depChanged) refreshPanelDependencies();
        }
      }
    }
  } catch {}
}
setInterval(pollSpecs, 10000);

// Init
loadSettings();
applyDarkMode();
applyThemeColor();
applyPanelWidth();
applyArchivedBtnState();
renderRecentBar();
syncHeaderHeight();
window.addEventListener('resize', syncHeaderHeight);
// SPEC-064: load cross-project registry early so external chips render with
// the right state on the first paint. Don't block on it — failures degrade
// gracefully (chips render as internal "missing spec" placeholders).
loadProjectsRegistry();
loadSpecs().then(() => {
  // SPEC-064: ?spec=<id> auto-opens the panel — used by external links from
  // peer boards. Silent no-op when the spec isn't in this project.
  const initialSpec = new URLSearchParams(window.location.search).get('spec');
  if (initialSpec) {
    setTimeout(() => { openPanel(initialSpec).catch(() => {}); }, 100);
  }
});
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# SPEC-070: Static board snapshot exporter
# ---------------------------------------------------------------------------

class ExportLeakError(ValueError):
    """Raised when export_board_html detects a residual absolute path in the HTML.

    The export is blocked before the caller can write it — fail-closed (AC7).
    ``leaks`` carries the list of offending strings for diagnostic messages.
    """

    def __init__(self, leaks: list[str]) -> None:
        self.leaks = leaks
        super().__init__(
            f"export blocked: {len(leaks)} residual absolute path(s) detected: "
            + ", ".join(repr(l) for l in leaks[:3])
        )


# CDN URLs for libs that must be inlined for offline use (AC2/AC6).
_LIB_URLS = {
    "marked": "https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js",
    "vis_network": "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js",
}

# CDN <script src="..."> strings to remove from the template (replaced by inlined versions).
_REMOVE_SCRIPT_SRCS = [
    '<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>',
    '<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>',
    '<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>',
]

# Google Fonts <link> to remove (offline export must not load external fonts).
_REMOVE_GOOGLE_FONTS = (
    '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">'
)


def _default_lib_fetcher(url: str) -> bytes:
    """Download a JS library from a CDN URL. Raises on failure."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read()
    except Exception as exc:
        raise RuntimeError(
            f"[board export] failed to fetch {url}: {exc}\n"
            "  Run with a network connection, or provide a lib_fetcher stub."
        ) from exc


def _build_graph_data(specs: list[dict]) -> dict:
    """Build the /api/graph payload from a list of frontmatter dicts."""
    nodes = []
    for s in specs:
        sid = s.get("id")
        if not sid:
            continue
        title = s.get("_title", sid)
        graph_title = _graph_display_title(sid, title)
        short_title = graph_title[:20] if len(graph_title) > 20 else graph_title
        nodes.append({
            "id": sid,
            "label": f"{sid}\n{short_title}",
            "status": s.get("status", "draft"),
            "group": s.get("status", "draft"),
            "provides": s.get("provides") or [],
            "requires": s.get("requires") or [],
            "touches": s.get("touches") or [],
            "parent": s.get("parent"),
            "type": s.get("type"),
            "unlocks": [],
        })
    edges = []
    unlocks: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for s in specs:
        sid = s.get("id")
        if not sid:
            continue
        for dep in (s.get("after") or []):
            edges.append({"from": dep, "to": sid, "arrows": "to"})
            unlocks.setdefault(dep, []).append(sid)
    for node in nodes:
        node["unlocks"] = sorted(unlocks.get(node["id"], []))
    node_ids = {n["id"] for n in nodes}
    parent_edges = []
    for s in specs:
        sid = s.get("id")
        pid = s.get("parent")
        if sid and pid and pid in node_ids:
            parent_edges.append({"from": pid, "to": sid, "kind": "parent", "dashes": True})
    return {"nodes": nodes, "edges": edges, "parent_edges": parent_edges}


def export_board_html(
    specs_dir: Path,
    project: str,
    *,
    lib_fetcher=None,
    reports_dir: Optional[Path] = None,
    worktree_status: Optional[dict] = None,
) -> str:
    """Build and return a self-contained static HTML snapshot of the board.

    Parameters
    ----------
    specs_dir:
        Path to the ``.nightshift/specs`` directory (or any flat specs dir).
    project:
        Project name string (used as the board title).
    lib_fetcher:
        ``(url: str) -> bytes`` callable used to download external JS libs.
        Defaults to a urllib-based downloader. Tests pass a stub.
    reports_dir:
        Path to a reports directory.  When supplied, all ``*.md`` files are
        scanned and their contents embedded in STATIC.reportContents.
        When ``None``, the sibling ``../reports`` of *specs_dir* is used if
        it exists, otherwise reports are omitted.
    worktree_status:
        Pre-built worktree status dict ``{spec_id: [{branch, status, path}]}``.
        When ``None`` the export uses an empty dict (no worktree overlays).
        Absolute ``path`` values are tokenized via ``path_vars.tokenize``
        before embedding.

    Raises
    ------
    ExportLeakError
        If the final HTML contains a residual absolute path outside a code
        fence/span (AC7 fail-closed gate).
    RuntimeError
        If lib_fetcher raises (download failed and no stub provided).
    """
    import sys as _sys
    _board_dir = Path(__file__).parent
    _sys.path.insert(0, str(_board_dir))

    # Lazy imports — only needed at export time, not at server startup.
    try:
        import path_vars as _pv
    except ImportError:
        _pv = None  # type: ignore[assignment]

    try:
        from validate_specs import _detect_leak_paths
    except ImportError:
        def _detect_leak_paths(text: str) -> list[str]:  # type: ignore[misc]
            return []

    fetcher = lib_fetcher or _default_lib_fetcher

    # ── 1. Gather spec data ─────────────────────────────────────────────
    _cache = SpecCache(specs_dir)
    _cache.warm()
    all_fm = _cache.get_all_frontmatter()

    # Bodies: dict spec_id → raw body markdown (token-bearing, NOT resolved)
    bodies: dict[str, str] = {}
    for fm in all_fm:
        sid = fm.get("id")
        if sid:
            b = _cache.get_body(sid)
            bodies[sid] = b or ""

    # Graph data
    graph_data = _build_graph_data(all_fm)

    # ── 2. Gather reports ───────────────────────────────────────────────
    _rdir: Optional[Path] = reports_dir
    if _rdir is None:
        candidate = specs_dir.parent / "reports"
        if candidate.is_dir():
            _rdir = candidate

    report_list: list[dict] = []
    report_contents: dict[str, str] = {}

    if _rdir is not None and _rdir.is_dir():
        for rpath in sorted(_rdir.rglob("*.md")):
            try:
                rel = str(rpath.relative_to(_rdir.parent))
                content = rpath.read_text(encoding="utf-8")
                report_list.append({
                    "filename": rel,
                    "name": rpath.name,
                    "mtime": rpath.stat().st_mtime,
                    "is_read": False,
                })
                report_contents[rel] = content
            except (OSError, ValueError):
                continue
        report_list.sort(key=lambda r: r["mtime"], reverse=True)

    # ── 3. Projects registry ────────────────────────────────────────────
    registry_path = specs_dir.parent / "projects-registry.json"
    if registry_path.is_file():
        try:
            registry_data = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            registry_data = {"generated_at": None, "projects": []}
    else:
        registry_data = {"generated_at": None, "projects": []}

    # ── 4. Tokenize abs paths in worktree status and registry ───────────
    wt_status: dict = worktree_status if worktree_status is not None else {}

    # Build tokenization anchors once; used for both worktree paths and registry paths.
    if _pv is not None:
        home = str(Path.home())
        project_root = str(specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent)
        argo_home_val = _pv._argo_home(specs_dir) or ""
        _anchors: dict[str, str] = {
            "PROJECT_ROOT": project_root,
            "ARGO_HOME": argo_home_val,
            "HOME": home,
        }
        _anchors = {k: v for k, v in _anchors.items() if v}  # drop empty
    else:
        _anchors = {}

    # Tokenize worktree entry "path" fields
    if wt_status and _anchors:
        tokenized_wt: dict = {}
        for spec_id, entries in wt_status.items():
            new_entries = []
            for entry in entries:
                new_entry = dict(entry)
                if "path" in new_entry and new_entry["path"]:
                    new_entry["path"] = _pv.tokenize(new_entry["path"], _anchors)
                new_entries.append(new_entry)
            tokenized_wt[spec_id] = new_entries
        wt_status = tokenized_wt

    # Sanitize registry project "path" fields.
    # Registry entries may contain machine-specific absolute paths that can't be
    # fully tokenized (e.g. /sessions/<id>/mnt/... from Cortex VM mounts, or
    # /Users/... paths from the local machine).  The "path" field is only useful
    # for the live server (board-to-board navigation links).  In a static export
    # those links are always dead, so stripping the field removes the leak without
    # losing any useful information.
    if isinstance(registry_data.get("projects"), list):
        stripped_projects = []
        for proj in registry_data["projects"]:
            new_proj = dict(proj)
            new_proj["path"] = None  # strip abs path — useless in static mode
            stripped_projects.append(new_proj)
        registry_data = dict(registry_data)
        registry_data["projects"] = stripped_projects

    # ── 5. Build STATIC blob ────────────────────────────────────────────
    static_blob = {
        "specs": all_fm,
        "bodies": bodies,
        "graph": graph_data,
        "loopObservability": compute_loop_observability(None) if compute_loop_observability else {},
        "reports": report_list,
        "reportContents": report_contents,
        "registry": registry_data,
        "worktreeStatus": wt_status,
    }
    # ── AC7 pre-check: fail-closed leak detection ───────────────────────
    #
    # Two separate checks, because body/report text and structured data have
    # different code-fence semantics:
    #
    # A. Raw body + report content (before JSON encoding):
    #    _detect_leak_paths uses newline-based code-fence masking. Once text is
    #    JSON-dumped, real newlines become literal \n (two chars) and the masking
    #    breaks — abs paths inside fences produce spurious false positives. Run on
    #    the raw text so code-fence exemptions work correctly.
    #
    # B. Structured data (specs/frontmatter, graph, reports list, registry,
    #    worktreeStatus) as a JSON serialization. These components contain no
    #    markdown code fences, so JSON-encoding does not introduce false positives.
    #    Any abs path here is a genuine leak (e.g. registry paths from
    #    /sessions/... hosts, frontmatter fields, graph node metadata).
    _pre_leaks: list[str] = []

    # A. Raw bodies and report contents
    for _sid, _body_text in bodies.items():
        _pre_leaks.extend(_detect_leak_paths(_body_text))
    for _rkey, _rcontent in report_contents.items():
        _pre_leaks.extend(_detect_leak_paths(_rcontent))

    # B. Structured blob components (no code fences — every hit is a real leak)
    _struct_json = json.dumps(
        {
            "specs": all_fm,
            "graph": graph_data,
            "reports": report_list,
            "registry": registry_data,
            "worktreeStatus": wt_status,
        },
        ensure_ascii=False,
        default=str,
    )
    _pre_leaks.extend(_detect_leak_paths(_struct_json))

    if _pre_leaks:
        raise ExportLeakError(_pre_leaks)

    static_json = json.dumps(static_blob, ensure_ascii=False, default=str)

    # ── 6. Download and inline external JS libs ─────────────────────────
    marked_js = fetcher(_LIB_URLS["marked"]).decode("utf-8", errors="replace")
    vis_js = fetcher(_LIB_URLS["vis_network"]).decode("utf-8", errors="replace")

    # ── 7. Patch HTML_TEMPLATE ──────────────────────────────────────────
    html = HTML_TEMPLATE
    html = html.replace("__PROJECT__", project)
    html = html.replace("__STATUS_COLUMNS_JSON__", status_columns_json)
    html = html.replace("__PROJECT_KEY__", project)

    # Remove Google Fonts link (AC6 — no external resources)
    html = html.replace(_REMOVE_GOOGLE_FONTS, "")

    # Remove CDN <script src="..."> tags for libs we inline + SortableJS
    for tag in _REMOVE_SCRIPT_SRCS:
        html = html.replace(tag, "")

    # Build the injection block: STATIC blob + lib inlining + fetch shim + Sortable stub
    shim_js = _build_static_shim(static_json, marked_js, vis_js)

    # Inject the shim immediately before the first <script> that uses the data.
    # The first non-CDN <script> block begins after the CDN tags on line 2201.
    # We look for the "<script>" that opens the main JS block (after the CDN lines).
    _inject_marker = "<script>\nconst COLUMNS = __STATUS_COLUMNS_JSON__;"
    # After template substitution, COLUMNS is already filled in, so look for the result:
    _inject_marker_resolved = f"<script>\nconst COLUMNS = {status_columns_json};"
    if _inject_marker_resolved in html:
        html = html.replace(
            _inject_marker_resolved,
            shim_js + "\n" + _inject_marker_resolved,
        )
    else:
        # Fallback: inject right before </body>
        html = html.replace("</body>", shim_js + "\n</body>")

    # Note: AC7 leak detection was already run above on raw bodies/reports
    # (before JSON encoding). No further scan of the final HTML is needed —
    # the JSON-escaped blob is not human-readable text and would produce false
    # negatives (code-fence masking breaks on \n-escaped newlines).

    return html


def _build_static_shim(static_json: str, marked_js: str, vis_js: str) -> str:
    """Return the JS injection block for static export.

    Contains:
    1. Inlined marked.js and vis-network.js
    2. window.__STATIC__ = <data blob>
    3. window.Sortable no-op stub (SortableJS is not loaded in static mode)
    4. fetch() override that resolves from __STATIC__ and no-ops mutations
    """
    # HTML-safe JSON: prevent </script> injection and avoid U+2028/U+2029 breaking
    # JS string literals (both are valid JSON but break HTML-embedded scripts).
    static_json = (
        static_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    return f"""<script>
/* ── SPEC-070 static export: inlined libs ── */
{marked_js}
</script>
<script>
/* ── vis-network ── */
{vis_js}
</script>
<style>
/* ── SPEC-083: hide static-irrelevant live-only UI ── */
html.static-export #btn-refresh {{ display: none !important; }}
html.static-export .wt-badge {{ display: none !important; }}
html.static-export .chip[data-external="1"] {{ display: none !important; }}
</style>
<script>
/* ── SPEC-070 static snapshot data ── */
window.__STATIC__ = true;
window.STATIC = {static_json};

/* SPEC-083: mark document as static-export so CSS rules above apply */
document.documentElement.classList.add('static-export');

/* Sortable stub — drag is disabled in static mode */
window.Sortable = function() {{}};
window.Sortable.prototype = {{ destroy: function() {{}} }};

/* fetch() shim — resolves all board API routes from STATIC blob */
(function() {{
  const _nativeF = window.fetch ? window.fetch.bind(window) : null;
  const S = window.STATIC;

  function _json(obj) {{
    return Promise.resolve({{ ok: true, status: 200, json: function() {{ return Promise.resolve(obj); }}, text: function() {{ return Promise.resolve(JSON.stringify(obj)); }} }});
  }}
  function _noop() {{
    return _json({{ ok: true }});
  }}

  window.fetch = function(url, opts) {{
    if (!window.__STATIC__) return _nativeF ? _nativeF(url, opts) : Promise.reject(new Error('no native fetch'));
    var method = (opts && opts.method) ? opts.method.toUpperCase() : 'GET';
    var u = String(url);

    /* Mutations — no-op silently */
    if (method !== 'GET') return _noop();

    /* /api/specs */
    if (u === '/api/specs') return _json(S.specs || []);

    /* /api/worktree-status */
    if (u === '/api/worktree-status') return _json(S.worktreeStatus || {{}});

    /* /api/graph */
    if (u === '/api/graph') return _json(S.graph || {{nodes:[], edges:[], parent_edges:[]}});

    /* /api/loop-observability */
    if (u === '/api/loop-observability') return _json(S.loopObservability || {{run_count: 0}});

    /* /api/reports */
    if (u === '/api/reports') return _json(S.reports || []);

    /* /api/projects-registry */
    if (u === '/api/projects-registry') return _json(S.registry || {{generated_at: null, projects: []}});

    /* /api/refresh */
    if (u === '/api/refresh') return _noop();

    /* /api/statuses */
    if (u === '/api/statuses') return _json([]);

    /* /api/spec/<id> */
    var specMatch = u.match(/^\\/api\\/spec\\/([^\\/\\?]+)$/);
    if (specMatch) {{
      var sid = decodeURIComponent(specMatch[1]);
      var fm = (S.specs || []).find(function(s) {{ return s.id === sid; }});
      if (!fm) return Promise.resolve({{ ok: false, status: 404, json: function() {{ return Promise.resolve({{}}); }}, text: function() {{ return Promise.resolve('not found'); }} }});
      return _json({{ frontmatter: fm, body_md: (S.bodies || {{}})[sid] || '', title: fm._title || sid }});
    }}

    /* /api/report/<filename> */
    var reportMatch = u.match(/^\\/api\\/report\\/(.+)$/);
    if (reportMatch) {{
      var fname = decodeURIComponent(reportMatch[1]);
      var content = (S.reportContents || {{}})[fname];
      if (content === undefined) return Promise.resolve({{ ok: false, status: 404, json: function() {{ return Promise.resolve({{}}); }}, text: function() {{ return Promise.resolve('not found'); }} }});
      return _json({{ filename: fname, content: content }});
    }}

    /* /api/search?q=... — client-side substring filter */
    var searchMatch = u.match(/^\\/api\\/search\\?q=(.*)$/);
    if (searchMatch) {{
      var q = decodeURIComponent(searchMatch[1]).toLowerCase();
      if (!q) return _json([]);
      var results = (S.specs || []).filter(function(s) {{
        return (s.id + ' ' + (s._title || '') + ' ' + (s.status || '')).toLowerCase().includes(q);
      }}).slice(0, 20).map(function(s) {{
        return {{ id: s.id, title: s._title || s.id, status: s.status || 'draft', excerpt: '' }};
      }});
      return _json(results);
    }}

    /* /api/external-spec/<port>/<id> — always unreachable in static mode */
    if (u.startsWith('/api/external-spec/')) {{
      return _json({{ status: null, _unreachable: true }});
    }}

    /* catch-all: return empty benign response */
    return _json(null);
  }};
}})();
</script>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nightshift Board — local Kanban for specs")
    parser.add_argument("--port", type=int, default=None,
                        help="Port (default: hash-based per project, range 7800-7999)")
    parser.add_argument("--open", action="store_true", dest="open_browser",
                        help="Auto-open browser after startup")
    parser.add_argument("--specs", type=str, default=None,
                        help="Override specs directory path")
    parser.add_argument("--export", type=str, default=None, metavar="PATH.html",
                        help="Write a self-contained static HTML snapshot and exit")
    parser.add_argument("--summary", action="store_true",
                        help="Print reconciled spec frontmatter as JSON and exit")
    args = parser.parse_args()

    specs_dir = Path(args.specs).resolve() if args.specs else Path(__file__).parent / "specs"
    if not specs_dir.exists():
        print(f"✗ Specs dir not found: {specs_dir}")
        sys.exit(1)

    # When deployed as .nightshift/specs, go up two levels to reach project root
    project_root = _project_root_for_specs_dir(specs_dir)
    try:
        board_branch = _validate_board_branch(project_root, specs_dir.parent / "config.yaml")
    except BoardBranchError as exc:
        print(f"✗ Board branch validation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    _name_src = project_root
    project_name = _name_src.name.lstrip('.').upper() or "PROJECT"

    if args.export:
        # Static export mode — write HTML and exit, no server started.
        out_path = Path(args.export)
        try:
            html = export_board_html(specs_dir, project_name)
        except ExportLeakError as exc:
            print(f"✗ Export blocked: {exc}", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"✗ Export failed: {exc}", file=sys.stderr)
            sys.exit(1)
        out_path.write_text(html, encoding="utf-8")
        print(f"✓ Exported {out_path} ({out_path.stat().st_size // 1024} KB)")
        sys.exit(0)

    # Hash-based port: deterministic per project, range 7800-7999
    port = args.port if args.port is not None else (7800 + sum(ord(c) for c in project_name) % 200)

    status_store = StatusStore.for_specs_dir(specs_dir) if StatusStore is not None else None
    cache = SpecCache(specs_dir, status_store=status_store)
    cache.warm()

    if args.summary:
        print(json.dumps(cache.get_all_frontmatter(), default=str))
        sys.exit(0)

    reports_dir = specs_dir.parent / "reports"
    reads_file = specs_dir.parent / "board-reads.json"

    # SPEC-078/079: apply per-project column override; print startup note if active
    _override_note = _apply_column_override(specs_dir.parent / "config.yaml")

    count = len(cache.get_all_frontmatter())
    print(f"▸ NIGHTSHIFT BOARD — {project_name} — {count} specs")
    if _override_note:
        print(f"  {_override_note}")
    print(f"  branch: {board_branch}")
    if status_store is not None:
        print(f"  status store: {status_store.db_path}")
    print(f"  http://localhost:{port}")
    print("  stop: Ctrl+C")

    if args.open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
