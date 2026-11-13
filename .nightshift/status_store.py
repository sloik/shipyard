#!/usr/bin/env python3
"""
SQLite-backed durable spec status checkpoints for Nightshift.

Status files remain the static spec metadata source. This store is the shared
runtime layer: every status transition appends a checkpoint row keyed by spec id.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterable

# SPEC-303: bound-parameter chunk for the batch status read; one connection
# is reused across chunks.
_BATCH_READ_CHUNK = 500


_CURRENT_SCHEMA_VERSION = 6
_DEFAULT_DB_NAME = "nightshift-status.db"


class StatusStoreError(RuntimeError):
    """Raised when the durable status store cannot be used safely."""


class LifecyclePersistenceError(StatusStoreError):
    """A coordinator transition could not durably establish its checkpoint."""


class TransitionReasonRequired(StatusStoreError, ValueError):
    """A judgment transition (SPEC-291 R3) was attempted with no reason."""


class TerminalDecisionConflict(StatusStoreError):
    """A logical run attempted to replace its immutable terminal choice."""


@dataclass(frozen=True)
class StatusCheckpoint:
    checkpoint_id: int
    spec_id: str
    status: str
    created_at: str
    run_id: str | None = None
    step: int | None = None
    source: str | None = None
    note: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "spec_id": self.spec_id,
            "status": self.status,
            "created_at": self.created_at,
            "run_id": self.run_id,
            "step": self.step,
            "source": self.source,
            "note": self.note,
            "payload": dict(self.payload or {}),
        }


@dataclass(frozen=True)
class TerminalDecision:
    decision_id: int
    spec_id: str
    run_id: str
    decision: str
    created_at: str
    source: str | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "spec_id": self.spec_id,
            "run_id": self.run_id,
            "decision": self.decision,
            "created_at": self.created_at,
            "source": self.source,
            "reason": self.reason,
            "payload": dict(self.payload or {}),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dumps(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _git_path(path: Path, *args: str) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute", *args],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 and result.stdout.strip() else None


def _primary_worktree(path: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return next((Path(line.removeprefix("worktree ")).resolve() for line in result.stdout.splitlines() if line.startswith("worktree ")), None)


def _checkpoint_path_identity(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str) or not value:
        return None
    source = Path(value).expanduser().resolve()
    top, git_dir, common_dir = (_git_path(source.parent, flag) for flag in ("--show-toplevel", "--git-dir", "--git-common-dir"))
    if top is None or git_dir is None or common_dir is None:
        return None
    try:
        relative = source.relative_to(top).as_posix()
    except ValueError:
        return None
    if git_dir == common_dir:
        return {"spec_path": str(source), "project_relative_spec_path": relative}
    primary = _primary_worktree(source.parent)
    if primary is None:
        return None
    return {"spec_path": str((primary / relative).resolve()), "project_relative_spec_path": relative, "worktree_spec_path": str(source)}


def _normalize_checkpoint_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    normalized = dict(payload)
    identity = _checkpoint_path_identity(normalized.get("canonical_spec_path") or normalized.get("spec_path"))
    if identity is None:
        return normalized
    normalized.update({"spec_path": identity["spec_path"], "canonical_spec_path": identity["spec_path"], "project_relative_spec_path": identity["project_relative_spec_path"]})
    if "worktree_spec_path" in identity:
        normalized["worktree_spec_path"] = identity["worktree_spec_path"]
    return normalized


def _legacy_worktree_path_matches(checkpoint_path: Any, spec_path: Path) -> bool:
    if not isinstance(checkpoint_path, str) or not checkpoint_path or not Path(checkpoint_path).is_absolute():
        return False
    current = spec_path.resolve()
    top = _git_path(current.parent, "--show-toplevel")
    if top is None:
        return False
    try:
        expected = current.relative_to(top).parts
    except ValueError:
        return False
    parts = Path(checkpoint_path).expanduser().resolve().parts
    for i, part in enumerate(parts):
        if parts[i:i + 2] == (".claude", "worktrees") and len(parts) > i + 3:
            if (Path(*parts[:i]) == top and parts[i + 2].startswith("agent-")
                    and tuple(parts[i + 3:]) == expected):
                return True
        if part == "nightshift-worktrees" and len(parts) > i + 3:
            temporary_root = parts[:3] == ("/", "var", "folders") or parts[:4] == ("/", "private", "var", "folders")
            if temporary_root and tuple(parts[i + 3:]) == expected:
                return True
    return False


def _checkpoint_path_matches(payload: dict[str, Any], spec_path: Path) -> bool:
    checkpoint_path = payload.get("spec_path")
    if not checkpoint_path or Path(str(checkpoint_path)).expanduser().resolve() == spec_path.resolve():
        return True
    # Relative metadata alone cannot authorize an unrelated absolute locator.
    identity = _checkpoint_path_identity(str(spec_path))
    if identity and Path(str(checkpoint_path)).expanduser().resolve() == Path(identity["spec_path"]):
        return True
    return _legacy_worktree_path_matches(checkpoint_path, spec_path)


def is_canonical_repository_relative_path(
    value: Any, *, allow_directory_marker: bool = False,
) -> bool:
    """Return whether *value* is an unambiguous repository-relative path."""
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or not value.isprintable()
    ):
        return False
    scheme, separator, _remainder = value.partition(":")
    if separator and scheme and scheme[0].isalpha() and all(
        character.isalnum() or character in "+-." for character in scheme
    ):
        return False
    checked = value
    if allow_directory_marker and checked.endswith("/"):
        checked = checked[:-1]
    if not checked or PurePosixPath(checked).is_absolute() \
            or PureWindowsPath(checked).drive:
        return False
    return all(
        component not in {"", ".", ".."} for component in checked.split("/")
    )


def _checkpoint_from_row(row: sqlite3.Row) -> StatusCheckpoint:
    return StatusCheckpoint(
        checkpoint_id=int(row["id"]),
        spec_id=str(row["spec_id"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
        run_id=row["run_id"],
        step=row["step"],
        source=row["source"],
        note=row["note"],
        payload=_json_loads(row["payload_json"]),
    )


def _terminal_decision_from_row(row: sqlite3.Row) -> TerminalDecision:
    return TerminalDecision(
        decision_id=int(row["id"]),
        spec_id=str(row["spec_id"]),
        run_id=str(row["run_id"]),
        decision=str(row["decision"]),
        created_at=str(row["created_at"]),
        source=row["source"],
        reason=row["reason"],
        payload=_json_loads(row["payload_json"]),
    )


def _run_git_common_dir(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = start / path
    return path.resolve()


def _run_git_show_toplevel(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    return Path(raw).resolve()


def _project_relpath(project_root: Path, checkout_root: Path | None) -> str | None:
    """Return ``project_root``'s POSIX-normalised path relative to its checkout.

    ``"."`` means ``project_root`` *is* the checkout toplevel (SPEC-340 R2).
    ``None`` means the relationship could not be established (e.g. ``git
    rev-parse --show-toplevel`` failed, or returned a path that does not
    contain ``project_root``) and the caller should fall back to the
    pre-SPEC-340 path so existing single-project installs are unaffected.
    """

    if checkout_root is None:
        return None
    try:
        relative = project_root.resolve().relative_to(checkout_root)
    except ValueError:
        return None
    return relative.as_posix() if str(relative) != "." else "."


def default_db_path_for_specs_dir(specs_dir: Path) -> Path:
    """Return a DB path shared by all git worktrees for ``specs_dir``.

    Worktrees have separate checked-out ``.nightshift`` directories, so storing
    the DB there would recreate the invisibility bug. The git common directory is
    shared by all worktrees of the same repository.

    SPEC-340: a single repository can hold several independently configured
    Nightshift projects, each a strict subdirectory of the checkout. The
    default path is namespaced by the project's path relative to *its own*
    checkout toplevel (computed per SPEC-340 R8 from that checkout's own
    ``--show-toplevel``, never from the common directory's parent) so sibling
    projects no longer collide. A project whose root *is* the checkout
    toplevel (relpath ``"."``) keeps its pre-SPEC-340 path unchanged
    (``<git-common-dir>/nightshift-status.db``, R2) -- every existing
    single-project install in the fleet is this case, and moving it would
    strand its history with no migration behind it.
    """

    specs_dir = Path(specs_dir).resolve()
    project_root = specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent
    common_git_dir = _run_git_common_dir(project_root)
    if common_git_dir is None:
        return project_root / ".nightshift" / _DEFAULT_DB_NAME
    checkout_root = _run_git_show_toplevel(project_root)
    relpath = _project_relpath(project_root, checkout_root)
    if relpath is None or relpath == ".":
        return common_git_dir / _DEFAULT_DB_NAME
    return common_git_dir / "nightshift" / relpath / _DEFAULT_DB_NAME


class StatusStore:
    """Append-only status checkpoint store."""

    def __init__(
        self,
        db_path: Path,
        *,
        repository_root: Path | None = None,
        project_relpath: str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()
        intrinsic_common_dir = self.db_path.resolve().parent
        if (
            (intrinsic_common_dir / "HEAD").is_file()
            and (intrinsic_common_dir / "objects").is_dir()
            and (intrinsic_common_dir / "refs").is_dir()
        ):
            self._bind_repository_common_dir(intrinsic_common_dir)
        if repository_root is not None:
            self.bind_repository(repository_root, project_relpath=project_relpath)

    @classmethod
    def for_specs_dir(cls, specs_dir: Path) -> "StatusStore":
        specs_dir = Path(specs_dir).resolve()
        project_root = specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent
        # SPEC-340 R4: pass a real checkout root (never project_root) to
        # repository_root -- _repository_identity's ``checkout_root !=
        # repository`` assertion requires it, and relaxing that assertion is
        # out of scope. The project's relpath inside that checkout (R8:
        # computed from *this* checkout's own --show-toplevel) widens the
        # bound identity so sibling subprojects no longer collide (R3); a
        # relpath of "." (project root is the checkout toplevel) is not
        # passed through, preserving every existing single-project install's
        # binding exactly as before this change (R2).
        checkout_root = _run_git_show_toplevel(project_root)
        relpath = _project_relpath(project_root, checkout_root)
        return cls(
            default_db_path_for_specs_dir(specs_dir),
            repository_root=checkout_root,
            project_relpath=relpath if relpath not in (None, ".") else None,
        )

    @staticmethod
    def _repository_identity(repo_root: Path) -> dict[str, str]:
        """Resolve one checkout and its shared Git repository identity."""
        repository = Path(repo_root).resolve()
        top = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        common = subprocess.run(
            [
                "git", "-C", str(repository), "rev-parse", "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True, text=True,
        )
        if top.returncode != 0 or common.returncode != 0:
            raise StatusStoreError("terminal projection repository identity is unavailable")
        checkout_root = Path(top.stdout.strip()).resolve()
        common_dir = Path(common.stdout.strip()).resolve()
        if checkout_root != repository or not common_dir.is_dir():
            raise StatusStoreError("terminal projection checkout identity is invalid")
        return {
            "repo_common_dir": str(common_dir),
            "checkout_root": str(checkout_root),
        }

    def bind_repository(
        self, repo_root: Path, *, project_relpath: str | None = None,
    ) -> dict[str, str]:
        """Durably bind this store to one Git common directory.

        Linked worktrees deliberately share this identity. Independent clones do
        not, even when their revisions and blobs are byte-identical.

        SPEC-340 R3: when ``project_relpath`` is given, the bound identity
        widens to also record which project (by its path inside the
        checkout) owns this store, so two sibling projects that somehow
        addressed the same DB file could never be silently treated as one.
        ``project_relpath=None`` (the toplevel-rooted case, R2, and every
        pre-SPEC-340 caller) leaves the ``project_relpath`` meta key
        untouched -- an existing single-project DB has no such key and none
        is required of it.
        """
        identity = self._repository_identity(repo_root)
        self._bind_repository_common_dir(
            Path(identity["repo_common_dir"]), project_relpath=project_relpath,
        )
        return identity

    def _bind_repository_common_dir(
        self, common_dir: Path, *, project_relpath: str | None = None,
    ) -> None:
        normalized = str(Path(common_dir).resolve())
        with closing(self._connect()) as conn:
            with conn:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = ?",
                    ("repository_common_dir",),
                ).fetchone()
                if row is not None and str(row["value"]) != normalized:
                    raise StatusStoreError(
                        "durable status store belongs to a different Git repository"
                    )
                if row is None:
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES (?, ?)",
                        ("repository_common_dir", normalized),
                    )
                if project_relpath is not None:
                    relpath_row = conn.execute(
                        "SELECT value FROM meta WHERE key = ?",
                        ("project_relpath",),
                    ).fetchone()
                    if (
                        relpath_row is not None
                        and str(relpath_row["value"]) != project_relpath
                    ):
                        raise StatusStoreError(
                            "durable status store belongs to a different Nightshift project"
                        )
                    if relpath_row is None:
                        conn.execute(
                            "INSERT INTO meta (key, value) VALUES (?, ?)",
                            ("project_relpath", project_relpath),
                        )

    def require_repository(self, repo_root: Path) -> dict[str, str]:
        """Return identity only when this store already owns the repository.

        Projection callers must never acquire ownership implicitly. A store is
        bound either intrinsically by living in a Git common directory or
        explicitly at construction via ``repository_root``.
        """
        identity = self._repository_identity(repo_root)
        row = self._fetch_one(
            "SELECT value FROM meta WHERE key = ?", ("repository_common_dir",),
        )
        if row is None or str(row["value"]) != identity["repo_common_dir"]:
            raise StatusStoreError(
                "terminal projection repository does not own the durable status store"
            )
        return identity

    def get_state(self, spec_id: str) -> dict[str, Any] | None:
        row = self._fetch_one(
            """
            SELECT * FROM status_checkpoints
            WHERE spec_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (spec_id,),
        )
        return _checkpoint_from_row(row).to_dict() if row else None

    def get_states(self, spec_ids: Iterable[str], *, include_terminal_projection: bool = False) -> dict[str, dict[str, Any] | None]:
        """Return the latest state for many specs over one connection (SPEC-303).

        Equivalent to calling ``get_state`` per id — same value, including
        ``None`` for a spec with no checkpoint — but one connection instead of
        one per spec. The board's cache reads every spec's status on each corpus
        refresh; done one at a time that was 88% of the refresh cost, because
        every ``get_state`` opened a connection, ran two PRAGMAs and closed it.
        """
        wanted = [str(spec_id) for spec_id in spec_ids]
        states: dict[str, dict[str, Any] | None] = {spec_id: None for spec_id in wanted}
        if not states:
            return states
        unique = list(states)
        projections = {}
        activity_inputs = {identity: {"checkpoints": [], "events": []} for identity in unique}
        with closing(self._connect()) as conn:
            # Chunked to stay clear of SQLite's bound-parameter limit; the
            # connection is still opened exactly once.
            for start in range(0, len(unique), _BATCH_READ_CHUNK):
                chunk = unique[start:start + _BATCH_READ_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"""
                    SELECT * FROM status_checkpoints
                    WHERE id IN (
                        SELECT MAX(id) FROM status_checkpoints
                        WHERE spec_id IN ({placeholders})
                        GROUP BY spec_id
                    )
                    """,
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    states[str(row["spec_id"])] = _checkpoint_from_row(row).to_dict()
                if include_terminal_projection:
                    projections.update(_terminal_projection_diagnostics(conn, chunk))
                    for point in conn.execute(f'SELECT id,spec_id,status,created_at,run_id FROM status_checkpoints WHERE spec_id IN ({placeholders}) ORDER BY id', tuple(chunk)):
                        activity_inputs[point['spec_id']]['checkpoints'].append({
                            'checkpoint_id': point['id'], 'spec_id': point['spec_id'], 'status': point['status'],
                            'created_at': point['created_at'], 'run_id': point['run_id']})
                    for event in conn.execute(f'SELECT spec_id,payload_json FROM activity_events WHERE spec_id IN ({placeholders}) ORDER BY id', tuple(chunk)):
                        activity_inputs[event['spec_id']]['events'].append(json.loads(event['payload_json']))
        return _BoardStateBatch(states, projections, activity_inputs) if include_terminal_projection else states

    def record_activity_event(self, *, spec_id: str, run_id: str, event_id: str, episode_id: str,
                              category: str, kind: str, at: str, actor: str, source: str,
                              phase: str | None = None, required_action: str | None = None,
                              next_action: str | None = None) -> dict[str, Any]:
        """Append a closed metadata boundary; never change status or store discussion content."""
        from loop_observability import ACTIVITY_CATEGORIES, _activity_epoch
        data = dict(spec_id=spec_id, run_id=run_id, event_id=event_id, episode_id=episode_id,
                    category=category, kind=kind, at=at, actor=actor, source=source)
        for key, value in dict(phase=phase, required_action=required_action, next_action=next_action).items():
            if value is not None:
                data[key] = value
        if any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value)
               for key, value in data.items() if key != 'at') or _activity_epoch(at) is None:
            raise ValueError('activity requires bounded identity codes and an explicit timezone timestamp')
        allowed = {'question', 'answer', 'takeover'} if category == 'discussion' else {'start', 'end'}
        if category not in (*ACTIVITY_CATEGORIES, 'discussion') or kind not in allowed:
            raise ValueError('unknown activity boundary')
        if (category == 'waiting' and kind == 'start' or category == 'discussion' and kind == 'question') and not required_action:
            raise ValueError('human action code required for explicit waiting')
        with closing(self._connect()) as conn:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                rows = conn.execute('SELECT payload_json FROM activity_events WHERE spec_id=? AND run_id=? AND (event_id=? OR episode_id=?)',
                                    (spec_id, run_id, event_id, episode_id)).fetchall()
                for row in rows:
                    previous = json.loads(row['payload_json'])
                    if previous['event_id'] == event_id:
                        if previous != data:
                            raise ValueError('activity event identity conflict')
                        return previous
                    if {k: v for k, v in previous.items() if k != 'event_id'} == {k: v for k, v in data.items() if k != 'event_id'}:
                        return previous
                    if previous['category'] != category:
                        raise ValueError('episode category identity conflict')
                    if category != 'discussion' and previous['kind'] == kind:
                        raise ValueError('episode boundary identity conflict')
                conn.execute('INSERT INTO activity_events (spec_id,run_id,event_id,episode_id,created_at,payload_json) VALUES (?,?,?,?,?,?)',
                             (spec_id, run_id, event_id, episode_id, at, json.dumps(data, sort_keys=True)))
        return data

    def get_activity_events(self, spec_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            return [json.loads(row['payload_json']) for row in conn.execute(
                'SELECT payload_json FROM activity_events WHERE spec_id=? ORDER BY id', (spec_id,))]

    def get_board_states(self, spec_ids: Iterable[str]) -> dict:
        """Read status and projection diagnostics over the same bounded connection."""
        return self.get_states(spec_ids, include_terminal_projection=True)

    def assert_durable_ready(self) -> None:
        """Fail unless the configured SQLite store is current and writable."""
        if not self.db_path.is_file():
            raise StatusStoreError(f"durable status store is missing: {self.db_path}")
        try:
            with closing(self._connect()) as conn:
                if _schema_version(conn) != _CURRENT_SCHEMA_VERSION:
                    raise StatusStoreError("durable status store schema is not current")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("SELECT id FROM terminal_decisions LIMIT 1").fetchone()
                conn.execute("SELECT id FROM cleanup_events LIMIT 1").fetchone()
                conn.execute("SELECT id FROM terminal_projection_events LIMIT 1").fetchone()
                conn.execute("SELECT id FROM merge_attempt_events LIMIT 1").fetchone()
                conn.rollback()
        except (OSError, sqlite3.Error) as exc:
            raise StatusStoreError(
                f"durable status store is unavailable or not writable: {self.db_path}"
            ) from exc

    def get_terminal_decision(self, spec_id: str, run_id: str) -> dict[str, Any] | None:
        """Return the immutable choice for one logical run, if one exists."""
        row = self._fetch_one(
            """
            SELECT * FROM terminal_decisions
            WHERE spec_id = ? AND run_id = ?
            """,
            (spec_id, run_id),
        )
        return _terminal_decision_from_row(row).to_dict() if row else None

    def record_terminal_decision(
        self, spec_id: str, run_id: str, decision: str, *,
        source: str = "coordinator", reason: str | None = None,
        payload: dict[str, Any] | None = None, created_at: str | None = None,
    ) -> dict[str, Any]:
        """Append one terminal choice, replay it, or reject its opposite.

        The unique run/spec key is the durable singleton. Identical replay
        returns the original row byte-for-byte; it never appends history.
        """
        if not spec_id or not run_id:
            raise ValueError("spec_id and run_id are required for terminal decision")
        if decision not in {"done", "blocked"}:
            raise ValueError("terminal decision must be done or blocked")
        timestamp = created_at or _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                row = conn.execute(
                    "SELECT * FROM terminal_decisions WHERE spec_id = ? AND run_id = ?",
                    (spec_id, run_id),
                ).fetchone()
                if row is None:
                    try:
                        cursor = conn.execute(
                            """
                            INSERT INTO terminal_decisions
                                (spec_id, run_id, decision, created_at, source, reason, payload_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (spec_id, run_id, decision, timestamp, source, reason, _json_dumps(payload)),
                        )
                    except sqlite3.IntegrityError:
                        row = conn.execute(
                            "SELECT * FROM terminal_decisions WHERE spec_id = ? AND run_id = ?",
                            (spec_id, run_id),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            "SELECT * FROM terminal_decisions WHERE id = ?",
                            (int(cursor.lastrowid),),
                        ).fetchone()
                if row is None:
                    raise StatusStoreError("terminal decision was not durably readable")
                existing = _terminal_decision_from_row(row)
                if existing.decision != decision:
                    raise TerminalDecisionConflict(
                        f"terminal decision conflict for {spec_id}/{run_id}: "
                        f"recorded {existing.decision}, refused {decision}"
                    )
        return existing.to_dict()

    def list_terminal_decisions(self, spec_id: str, *, source: str) -> list[dict[str, Any]]:
        """Return every immutable terminal-decision row of one spec and source, oldest first."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM terminal_decisions
                WHERE spec_id = ? AND source = ? ORDER BY id ASC
                """,
                (spec_id, source),
            ).fetchall()
        return [_terminal_decision_from_row(row).to_dict() for row in rows]

    def get_terminal_decision_history(
        self, spec_id: str, run_id: str,
    ) -> list[dict[str, Any]]:
        """Return the append-only singleton history for one logical run/spec."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM terminal_decisions
                WHERE spec_id = ? AND run_id = ? ORDER BY id ASC
                """,
                (spec_id, run_id),
            ).fetchall()
        return [_terminal_decision_from_row(row).to_dict() for row in rows]

    def record_revert_attempt(
        self, spec_id: str, run_id: str, *, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Durably append one exact coordinator-owned merge-revert attempt."""
        required = {
            "outcome", "reason_code", "main_before", "merge_revision",
            "main_after", "returncode", "stdout", "stderr",
        }
        if not required.issubset(payload):
            raise ValueError("revert attempt evidence is incomplete")
        return self.update_state(
            spec_id, "in_progress", run_id=run_id,
            source="integration_queue_revert_attempt",
            note=str(payload["reason_code"]),
            payload={"event": "merge_revert_attempt", **payload},
        )

    def get_revert_attempt_history(
        self, spec_id: str, run_id: str,
    ) -> list[dict[str, Any]]:
        """Return exact append-only revert-attempt checkpoints for one run."""
        return [
            item for item in self.get_run_history(spec_id, run_id)
            if item.get("source") == "integration_queue_revert_attempt"
            and (item.get("payload") or {}).get("event") == "merge_revert_attempt"
        ]

    def record_merge_attempt(
        self, spec_id: str, run_id: str, *, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one coordinator-owned merge attempt without changing lifecycle."""
        required = {
            "outcome", "reason_code", "main_before", "main_after",
            "candidate_revision", "returncode", "stdout", "stderr",
            "conflict_files", "observed_files", "declared_surfaces",
            "attempt_number", "recovery_rule",
        }
        outcome = payload.get("outcome")
        expected_contract = {
            "started": (
                "NS-INTEGRATION-MERGE-STARTED", "inspect_main_then_retry_once",
            ),
            "succeeded": (
                "NS-INTEGRATION-MERGE-SUCCEEDED", "continue_validation",
            ),
            "conflict": (
                "NS-INTEGRATION-MERGE-CONFLICT", "retry_once_on_restart",
            ),
            "command_failed": (
                "NS-INTEGRATION-MERGE-COMMAND-FAILED", "terminal_blocked",
            ),
            "interrupted": (
                "NS-INTEGRATION-MERGE-INTERRUPTED", "retry_once_on_restart",
            ),
            "postcondition_mismatch": (
                "NS-INTEGRATION-MERGE-POSTCONDITION-MISMATCH",
                "retry_once_on_restart",
            ),
            "recovery_required": (
                "NS-INTEGRATION-MERGE-RECOVERY-REQUIRED",
                "restore_exact_main_then_retry_once",
            ),
        }
        revisions = (
            payload.get("main_before"), payload.get("main_after"),
            payload.get("candidate_revision"),
        )
        if (
            not spec_id or not run_id or not required.issubset(payload)
            or outcome not in expected_contract
            or (payload.get("reason_code"), payload.get("recovery_rule"))
                != expected_contract.get(outcome)
            or not isinstance(payload.get("attempt_number"), int)
            or isinstance(payload.get("attempt_number"), bool)
            or payload["attempt_number"] not in {1, 2}
            or any(
                not isinstance(revision, str) or len(revision) != 40
                or any(character not in "0123456789abcdef" for character in revision)
                for revision in revisions
            )
            or not isinstance(payload.get("stdout"), str)
            or not isinstance(payload.get("stderr"), str)
            or (
                payload.get("returncode") is not None
                and (
                    not isinstance(payload.get("returncode"), int)
                    or isinstance(payload.get("returncode"), bool)
                )
            )
            or not isinstance(payload.get("conflict_files"), list)
            or not all(
                is_canonical_repository_relative_path(item)
                for item in payload["conflict_files"]
            )
            or not isinstance(payload.get("observed_files"), list)
            or not all(
                is_canonical_repository_relative_path(item)
                for item in payload["observed_files"]
            )
            or not isinstance(payload.get("declared_surfaces"), list)
            or not all(
                is_canonical_repository_relative_path(
                    item, allow_directory_marker=True,
                )
                for item in payload["declared_surfaces"]
            )
            or any(
                payload[field] != sorted(set(payload[field]))
                for field in (
                    "conflict_files", "observed_files", "declared_surfaces",
                )
            )
        ):
            raise ValueError("merge attempt evidence is incomplete or invalid")
        proof = payload.get("selfspec_reconciliation")
        if proof is not None:
            fields = {"schema_version", "spec_id", "run_id", "base", "main_before", "candidate", "spec_path",
                      "binding", "receipt_sha256", "contract_sha256", "held_event_id", "base_blob", "main_blob",
                      "candidate_blob", "resolution_blob", "mode", "expected_tree", "conflict_files",
                      "approval_sha256", "verification_sha256", "checked_items"}
            def hex_value(value, length):
                return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)
            if (not isinstance(proof, dict) or set(proof) != fields or type(proof.get("schema_version")) is not int or proof.get("schema_version") != 1
                    or proof.get("spec_id") != spec_id or proof.get("run_id") != run_id
                    or proof.get("main_before") != payload["main_before"]
                    or proof.get("candidate") != payload["candidate_revision"] or payload["attempt_number"] != 2
                    or proof.get("resolution_blob") != proof.get("candidate_blob")
                    or proof.get("mode") not in {"100644", "100755"}
                    or not is_canonical_repository_relative_path(proof.get("spec_path"))
                    or proof.get("conflict_files") != [proof["spec_path"]]
                    or type(proof.get("held_event_id")) is not int or proof["held_event_id"] < 1
                    or any(not hex_value(proof.get(key), 40) for key in
                           ("base", "main_before", "candidate", "base_blob", "main_blob", "candidate_blob", "resolution_blob", "expected_tree"))
                    or any(not hex_value(proof.get(key), 64) for key in
                           ("receipt_sha256", "contract_sha256", "approval_sha256", "verification_sha256"))
                    or not isinstance(proof.get("binding"), dict) or set(proof["binding"]) !=
                       {"git_common_dir_sha256", "worktree_sha256", "install_relative_sha256"}
                    or any(not hex_value(value, 64) for value in proof["binding"].values())
                    or not isinstance(proof.get("checked_items"), list) or not proof["checked_items"]
                    or any(not isinstance(item, str) or not re.fullmatch(r"(?:R|AC)[1-9][0-9]*", item)
                           for item in proof["checked_items"])
                    or proof["checked_items"] != sorted(set(proof["checked_items"]))):
                raise ValueError("self-spec reconciliation proof is malformed")
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                prior = conn.execute(
                    """
                    SELECT * FROM merge_attempt_events
                    WHERE spec_id = ? AND run_id = ? ORDER BY id ASC
                    """,
                    (spec_id, run_id),
                ).fetchall()
                starts = [
                    row for row in prior
                    if _json_loads(row["payload_json"]).get("outcome") == "started"
                ]
                if outcome == "started" and proof is not None:
                    anchor = next((row for row in prior if int(row["id"]) == proof["held_event_id"]), None)
                    anchor_payload = _json_loads(anchor["payload_json"]) if anchor is not None else {}
                    if (anchor_payload.get("outcome") != "conflict" or anchor_payload.get("attempt_number") != 1
                            or anchor_payload.get("main_before") != payload["main_before"]
                            or anchor_payload.get("candidate_revision") != payload["candidate_revision"]
                            or anchor_payload.get("conflict_files") != proof["conflict_files"]):
                        raise ValueError("self-spec proof lacks its original held conflict")
                if outcome == "started":
                    if payload["attempt_number"] != len(starts) + 1 or (
                        prior and _json_loads(prior[-1]["payload_json"]).get("outcome")
                        in {"started", "succeeded"}
                    ):
                        raise ValueError("merge started event sequence is invalid")
                else:
                    if not prior:
                        raise ValueError("merge outcome lacks durable started event")
                    latest = prior[-1]
                    started_payload = _json_loads(latest["payload_json"])
                    correcting_false_success = (
                        outcome == "recovery_required"
                        and started_payload.get("outcome") == "succeeded"
                        and payload.get("reconciled_event_id") == int(latest["id"])
                    )
                    if correcting_false_success:
                        matching_fields = (
                            "main_before", "candidate_revision", "observed_files",
                            "declared_surfaces", "attempt_number", "selfspec_reconciliation",
                        )
                        if any(
                            payload.get(field) != started_payload.get(field)
                            for field in matching_fields
                        ):
                            raise ValueError(
                                "merge recovery correction does not match succeeded event"
                            )
                    elif (
                        started_payload.get("outcome") != "started"
                        or payload.get("started_event_id") != int(latest["id"])
                        or any(
                            payload.get(field) != started_payload.get(field)
                            for field in (
                                "main_before", "candidate_revision", "observed_files",
                                "declared_surfaces", "attempt_number", "selfspec_reconciliation",
                            )
                        )
                    ):
                        raise ValueError("merge outcome does not match its started event")
                cursor = conn.execute(
                    """
                    INSERT INTO merge_attempt_events
                        (spec_id, run_id, created_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (spec_id, run_id, created_at, _json_dumps(payload)),
                )
                event_id = int(cursor.lastrowid)
        return {
            "event_id": event_id, "spec_id": spec_id, "run_id": run_id,
            "created_at": created_at, "payload": payload,
        }

    def get_merge_attempt_history(
        self, spec_id: str, run_id: str,
    ) -> list[dict[str, Any]]:
        """Return append-only merge-attempt evidence oldest first."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM merge_attempt_events
                WHERE spec_id = ? AND run_id = ? ORDER BY id ASC
                """,
                (spec_id, run_id),
            ).fetchall()
        return [
            {
                "event_id": int(row["id"]), "spec_id": str(row["spec_id"]),
                "run_id": str(row["run_id"]), "created_at": str(row["created_at"]),
                "payload": _json_loads(row["payload_json"]),
            }
            for row in rows
        ]

    def list_latest_revert_attempts(self) -> list[dict[str, Any]]:
        """Return the latest typed revert checkpoint for each logical run."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT checkpoint.*
                FROM status_checkpoints AS checkpoint
                JOIN (
                    SELECT spec_id, run_id, MAX(id) AS latest_id
                    FROM status_checkpoints
                    WHERE source = 'integration_queue_revert_attempt'
                      AND run_id IS NOT NULL
                    GROUP BY spec_id, run_id
                ) AS latest ON latest.latest_id = checkpoint.id
                ORDER BY checkpoint.id ASC
                """
            ).fetchall()
        attempts = [_checkpoint_from_row(row).to_dict() for row in rows]
        return [
            item for item in attempts
            if (item.get("payload") or {}).get("event") == "merge_revert_attempt"
        ]

    def record_cleanup_checkpoint(
        self, spec_id: str, run_id: str, *, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Append one coordinator-owned resource-cleanup checkpoint.

        Cleanup is evidence about an already terminal run, never a new lifecycle
        choice.  The immutable decision and its projected status therefore gate
        every checkpoint, and the terminal decision identity is copied into the
        payload so later retries cannot drift to another run.
        """
        decision = self.get_terminal_decision(spec_id, run_id)
        state = self.get_state(spec_id)
        if decision is None or state is None:
            raise StatusStoreError("cleanup requires an immutable terminal decision and status")
        if (
            state.get("status") != decision.get("decision")
            or state.get("run_id") != run_id
            or (state.get("payload") or {}).get("terminal_decision_id")
                != decision.get("decision_id")
        ):
            raise StatusStoreError("cleanup requires matching terminal status projection")
        required = {"event", "phase", "owner", "resources"}
        if not required.issubset(payload) or payload.get("event") != "resource_cleanup":
            raise ValueError("cleanup checkpoint evidence is incomplete")
        stored = {**payload, "terminal_decision_id": decision["decision_id"]}
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO cleanup_events
                        (spec_id, run_id, created_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (spec_id, run_id, created_at, _json_dumps(stored)),
                )
                event_id = int(cursor.lastrowid)
        return {
            "checkpoint_id": event_id, "spec_id": spec_id, "run_id": run_id,
            "created_at": created_at, "payload": stored,
        }

    def get_cleanup_history(self, spec_id: str, run_id: str) -> list[dict[str, Any]]:
        """Return append-only cleanup checkpoints for one exact terminal run."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM cleanup_events
                WHERE spec_id = ? AND run_id = ? ORDER BY id ASC
                """,
                (spec_id, run_id),
            ).fetchall()
        return [
            {
                "checkpoint_id": int(row["id"]), "spec_id": str(row["spec_id"]),
                "run_id": str(row["run_id"]), "created_at": str(row["created_at"]),
                "payload": _json_loads(row["payload_json"]),
            }
            for row in rows
        ]

    def record_terminal_projection_event(
        self, spec_id: str, run_id: str, *, payload: dict[str, Any],
        repo_root: Path,
    ) -> dict[str, Any]:
        """Append one parent-owned durable-to-frontmatter projection event."""
        decision = self.get_terminal_decision(spec_id, run_id)
        state = self.get_state(spec_id)
        if decision is None or state is None:
            raise StatusStoreError("terminal projection requires immutable decision and status")
        if (
            state.get("status") != decision.get("decision")
            or state.get("run_id") != run_id
            or (state.get("payload") or {}).get("terminal_decision_id")
                != decision.get("decision_id")
        ):
            raise StatusStoreError("terminal projection decision/status identity mismatch")
        required = {
            "event", "phase", "decision_id", "spec_path",
            "repo_common_dir", "checkout_root",
        }
        if (
            not required.issubset(payload)
            or payload.get("event") != "terminal_frontmatter_projection"
            or payload.get("phase") not in {"started", "completed"}
            or payload.get("decision_id") != decision.get("decision_id")
        ):
            raise ValueError("terminal projection event is incomplete or mismatched")
        hashes = {
            "base_head": (payload.get("base_head"), 40),
            "before_sha256": (payload.get("before_sha256"), 64),
            "expected_sha256": (payload.get("expected_sha256"), 64),
        }
        if any(
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
            for value, length in hashes.values()
        ):
            raise ValueError("terminal projection event hashes are invalid")
        relative = PurePosixPath(str(payload["spec_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("terminal projection spec path is unsafe")
        repository = Path(repo_root).resolve()
        repository_identity = self.require_repository(repository)
        if (
            payload.get("repo_common_dir") != repository_identity["repo_common_dir"]
            or payload.get("checkout_root") != repository_identity["checkout_root"]
        ):
            raise ValueError("terminal projection receipt repository identity mismatch")
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=repository,
            capture_output=True, text=True,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"], cwd=repository,
            capture_output=True, text=True,
        )
        base_blob = subprocess.run(
            ["git", "show", f"{payload['base_head']}:{relative.as_posix()}"],
            cwd=repository, capture_output=True,
        )
        if (
            top.returncode != 0
            or Path(top.stdout.strip()).resolve() != repository
            or head.returncode != 0
            or base_blob.returncode != 0
        ):
            raise ValueError("terminal projection repository/base binding is invalid")
        from spec_frontmatter import _serialise_frontmatter, _split_frontmatter
        import yaml

        try:
            base_text = base_blob.stdout.decode("utf-8")
            fm_text, body, end_nl = _split_frontmatter(base_text)
            frontmatter = yaml.safe_load(fm_text) or {}
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            raise ValueError("terminal projection base blob is malformed") from exc
        if not isinstance(frontmatter, dict) or frontmatter.get("id") != spec_id:
            raise ValueError("terminal projection base blob spec identity mismatch")
        target = {**frontmatter, "status": decision["decision"]}
        target_fm = _serialise_frontmatter(target)
        target_text = (
            f"---\n{target_fm}---\n{body}"
            if end_nl else f"---\n{target_fm}---{body}"
        )
        recomputed_before = hashlib.sha256(base_blob.stdout).hexdigest()
        recomputed_expected = hashlib.sha256(target_text.encode("utf-8")).hexdigest()
        closure = None
        if 'completion_inputs' in payload:
            from spec_artifacts import derive_terminal_first_projection
            closure, trailers = derive_terminal_first_projection(
                repository, spec_id, run_id, decision, relative.as_posix(),
                payload['base_head'], payload['completion_inputs'])
            hashes = {name: hashlib.sha256(data).hexdigest() for name, data in closure.items()}
            if payload.get('closure_sha256') != hashes:
                raise ValueError('terminal first projection closure binding mismatch')
            recomputed_expected = hashes[relative.as_posix()]
            history = self.get_terminal_projection_history(spec_id, run_id)
            original = next((event['payload'] for event in history
                             if event['payload'].get('phase') == 'started'), None)
            if original is not None and original != {**payload, 'phase': 'started'}:
                raise ValueError('terminal first projection cannot replace a started receipt')
            if payload['phase'] == 'completed' and original is None:
                raise ValueError('terminal first projection completed receipt lacks started closure')
        if (
            payload["before_sha256"] != recomputed_before
            or payload["expected_sha256"] != recomputed_expected
            or payload.get("terminal") != decision.get("decision")
        ):
            raise ValueError("terminal projection receipt does not match canonical base target")
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", relative.as_posix()],
            cwd=repository, capture_output=True, text=True,
        )
        if status.returncode != 0 or status.stdout.strip():
            if payload["phase"] == "started":
                raise ValueError("terminal projection started receipt requires clean base path")
            raise ValueError("terminal projection completed receipt requires clean projected path")
        if payload["phase"] == "started" and head.stdout.strip() != payload["base_head"]:
            raise ValueError("terminal projection started receipt base is not current HEAD")
        if closure is not None:
            for name, data in closure.items():
                target = repository / name
                current_path = repository
                for member in PurePosixPath(name).parts:
                    current_path /= member
                    if current_path.is_symlink():
                        raise ValueError(f'terminal first projection symlinked closure path: {name}')
                if target.is_file() and target.stat().st_nlink != 1:
                    raise ValueError(f'terminal first projection hardlinked closure path: {name}')
                dirty = subprocess.run(['git', 'status', '--porcelain', '--', name],
                                       cwd=repository, capture_output=True, text=True, check=True).stdout
                if target.is_symlink() or dirty.strip():
                    raise ValueError(f'terminal first projection requires clean closure path: {name}')
                if payload['phase'] == 'completed':
                    observed = subprocess.run(['git', 'show', f'HEAD:{name}'], cwd=repository,
                                              capture_output=True)
                    if observed.returncode or observed.stdout != data or target.read_bytes() != data:
                        raise ValueError(f'terminal first projection committed closure differs: {name}')
            if payload['phase'] == 'completed':
                changed = subprocess.run(['git', 'diff', '--name-only', 'HEAD^1', 'HEAD'],
                                         cwd=repository, capture_output=True, text=True, check=True).stdout.splitlines()
                message = subprocess.run(['git', 'log', '-1', '--pretty=%B'], cwd=repository,
                                         capture_output=True, text=True, check=True).stdout.splitlines()
                if set(changed) != set(closure) or message[:1] != [f'chore: mark {spec_id} done'] \
                    or any(line not in message for line in trailers):
                    raise ValueError('terminal first projection commit paths/subject/trailers differ')
        if payload["phase"] == "completed":
            parent = subprocess.run(
                ["git", "rev-parse", "HEAD^1^{commit}"], cwd=repository,
                capture_output=True, text=True,
            )
            head_blob = subprocess.run(
                ["git", "show", f"HEAD:{relative.as_posix()}"], cwd=repository,
                capture_output=True,
            )
            if (
                parent.returncode != 0
                or parent.stdout.strip() != payload["base_head"]
                or head_blob.returncode != 0
                or hashlib.sha256(head_blob.stdout).hexdigest() != recomputed_expected
            ):
                raise ValueError("terminal projection completed receipt commit binding is invalid")
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                if closure is not None:
                    rows = conn.execute('SELECT id, created_at, payload_json FROM terminal_projection_events '
                                        'WHERE spec_id = ? AND run_id = ? ORDER BY id', (spec_id, run_id)).fetchall()
                    for row in rows:
                        previous = _json_loads(row['payload_json'])
                        if previous.get('phase') == 'started' and previous != {**payload, 'phase': 'started'}:
                            raise ValueError('terminal first projection cannot replace a started receipt')
                        if previous == payload:
                            return {'event_id': int(row['id']), 'spec_id': spec_id, 'run_id': run_id,
                                    'created_at': row['created_at'], 'payload': payload}
                cursor = conn.execute(
                    """
                    INSERT INTO terminal_projection_events
                        (spec_id, run_id, created_at, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (spec_id, run_id, created_at, _json_dumps(payload)),
                )
                event_id = int(cursor.lastrowid)
        return {
            "event_id": event_id, "spec_id": spec_id, "run_id": run_id,
            "created_at": created_at, "payload": payload,
        }

    def record_terminal_projection_failure(self, spec_id: str, run_id: str, *,
                                           original_event_id: int | None = None, reason: str) -> dict[str, Any]:
        """Retain actual projection failure separately from immutable done."""
        original = next((event for event in self.get_terminal_projection_history(spec_id, run_id)
                         if event['event_id'] == original_event_id), None)
        decision = self.get_terminal_decision(spec_id, run_id)
        state = self.get_state(spec_id)
        if (decision is None or state is None or state.get('run_id') != run_id
            or (state.get('payload') or {}).get('terminal_decision_id') != decision['decision_id']
            or state.get('status') != decision['decision']
            or (original_event_id is not None and
                (original is None or original['payload'].get('phase') != 'started'))):
            raise StatusStoreError('terminal projection failure lacks matching immutable decision/receipt')
        payload = {'event': 'terminal_frontmatter_projection_failure', 'phase': 'pending',
                   'original_event_id': original_event_id,
                   'decision_id': decision['decision_id'],
                   'reason': str(reason)[:16384],
                   'recovery_action': 'queue.recover_terminal_projection(handle)'}
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute('INSERT INTO terminal_projection_events '
                    '(spec_id, run_id, created_at, payload_json) VALUES (?, ?, ?, ?)',
                    (spec_id, run_id, created_at, _json_dumps(payload)))
        return {'event_id': int(cursor.lastrowid), 'spec_id': spec_id, 'run_id': run_id,
                'created_at': created_at, 'payload': payload}

    def terminal_projection_diagnostics(self, spec_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Read projection progress separately from the accepted terminal decision."""
        if not spec_ids:
            return {}
        with closing(self._connect()) as conn:
            return _terminal_projection_diagnostics(conn, spec_ids)

    def record_terminal_metadata_recovery_event(
        self, spec_id: str, run_id: str, *, repo_root: Path,
        request: dict[str, Any], phase: str,
    ) -> dict[str, Any]:
        """Append a canonical metadata link; never replace the original receipt."""
        from spec_artifacts import derive_terminal_metadata_recovery

        if phase not in {"metadata_started", "metadata_completed"}:
            raise ValueError("metadata recovery phase invalid")
        identity = self.require_repository(repo_root)
        history = self.get_terminal_projection_history(spec_id, run_id)
        originals = [item for item in history
                     if item["event_id"] == request.get("original_event_id")]
        if len(originals) != 1:
            raise StatusStoreError("metadata recovery original receipt unavailable")
        original = originals[0]
        receipt = original["payload"]
        decision = self.get_terminal_decision(spec_id, run_id)
        state = self.get_state(spec_id)
        completion = (decision or {}).get("payload", {}).get("completion_evidence", {})
        if (decision is None or state is None or state.get("run_id") != run_id
            or state.get("status") != "done"
            or state.get("payload", {}).get("terminal_decision_id") != decision["decision_id"]
            or completion.get("ok") is not True or completion.get("outcome") != "accepted"
            or not {"report", "tests", "ac_checklist", "verifier"}.issubset(completion.get("artifacts", {}))
            or any(receipt.get(key) != identity[key] for key in ("repo_common_dir", "checkout_root"))):
            raise StatusStoreError("metadata recovery decision/repository binding invalid")
        closure = derive_terminal_metadata_recovery(repo_root, spec_id, run_id,
                                                   decision, original, request)
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in closure.items()}
        recovery_base = request.get("recovery_base_head", receipt["base_head"])
        payload = {"event": "terminal_frontmatter_metadata_recovery", "phase": phase,
                   "original_event_id": original["event_id"], "request": request,
                   "closure_sha256": hashes, "recovery_base_head": recovery_base}
        links = [item for item in history if item["payload"].get("event") == payload["event"]]
        if links and any(item["payload"].get("request") != request
                         or item["payload"].get("closure_sha256") != hashes for item in links):
            raise StatusStoreError("competing metadata recovery target refused")
        root = Path(repo_root).resolve()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=True).stdout.strip()
        if phase == "metadata_started":
            if links or head != recovery_base:
                raise StatusStoreError("metadata recovery requires pending original base HEAD")
            if hashlib.sha256((root / receipt["spec_path"]).read_bytes()).hexdigest() != receipt["expected_sha256"]:
                raise StatusStoreError("metadata recovery requires exact parent-owned pending bytes")
        else:
            if not links or links[0]["payload"].get("phase") != "metadata_started":
                raise StatusStoreError("metadata completion lacks started link")
            parent = subprocess.run(["git", "rev-parse", "HEAD^1"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip()
            subject = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=root,
                                     capture_output=True, text=True, check=True).stdout.strip()
            changed = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                                     cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
            if parent != recovery_base or subject != f"chore: mark {spec_id} done" or set(changed) != set(closure):
                raise StatusStoreError("metadata completion commit binding invalid")
            for name, digest in hashes.items():
                committed = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=root, capture_output=True, check=True).stdout
                dirty = subprocess.run(["git", "status", "--porcelain", "--", name], cwd=root,
                                       capture_output=True, text=True, check=True).stdout
                if hashlib.sha256(committed).hexdigest() != digest or dirty.strip():
                    raise StatusStoreError("metadata completion closure differs from committed bytes")
        created_at = _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                # Serialize the choice and detect a concurrent competing parent.
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute("SELECT id, payload_json FROM terminal_projection_events WHERE spec_id = ? AND run_id = ? ORDER BY id",
                                    (spec_id, run_id)).fetchall()
                existing = [_json_loads(row["payload_json"]) for row in rows
                            if _json_loads(row["payload_json"]).get("event") == payload["event"]]
                if any(item.get("request") != request or item.get("closure_sha256") != hashes for item in existing):
                    raise StatusStoreError("competing metadata recovery target refused")
                for row in rows:
                    if _json_loads(row["payload_json"]) == payload:
                        return {"event_id": int(row["id"]), "spec_id": spec_id,
                                "run_id": run_id, "payload": payload}
                if phase == "metadata_started" and existing:
                    raise StatusStoreError("metadata recovery already chosen")
                cursor = conn.execute("INSERT INTO terminal_projection_events (spec_id, run_id, created_at, payload_json) VALUES (?, ?, ?, ?)",
                                      (spec_id, run_id, created_at, _json_dumps(payload)))
        return {"event_id": int(cursor.lastrowid), "spec_id": spec_id, "run_id": run_id,
                "created_at": created_at, "payload": payload}

    def get_terminal_projection_history(
        self, spec_id: str, run_id: str,
    ) -> list[dict[str, Any]]:
        """Return append-only projection events for one logical terminal run."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM terminal_projection_events
                WHERE spec_id = ? AND run_id = ? ORDER BY id ASC
                """,
                (spec_id, run_id),
            ).fetchall()
        return [
            {
                "event_id": int(row["id"]), "spec_id": str(row["spec_id"]),
                "run_id": str(row["run_id"]), "created_at": str(row["created_at"]),
                "payload": _json_loads(row["payload_json"]),
            }
            for row in rows
        ]

    def update_state(
        self,
        spec_id: str,
        status: str,
        *,
        run_id: str | None = None,
        step: int | None = None,
        source: str | None = None,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if not spec_id:
            raise ValueError("spec_id required")
        if not status:
            raise ValueError("status required")
        payload = _normalize_checkpoint_payload(payload)
        timestamp = created_at or _utc_now()
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO status_checkpoints
                        (spec_id, status, created_at, run_id, step, source, note, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spec_id,
                        status,
                        timestamp,
                        run_id,
                        step,
                        source,
                        note,
                        _json_dumps(payload),
                    ),
                )
                checkpoint_id = int(cursor.lastrowid)
                row = conn.execute(
                    "SELECT * FROM status_checkpoints WHERE id = ?",
                    (checkpoint_id,),
                ).fetchone()
        if row is None:
            raise StatusStoreError("status checkpoint insert was not readable")
        return _checkpoint_from_row(row).to_dict()

    def transition_commit_backed(self, spec_path: Path, status: str, *, run_id: str,
                                source: str = "coordinator", note: str | None = None,
                                reason: str | None = None, evidence: Any = (),
                                actor: str | None = None,
                                reconsider_when: str | None = None,
                                state_rationale_evidence: Any = (),
                                provenance: str = "authored",
                                before_administrative_write: Callable[[], None] | None = None,
                                extra_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Write the coordinator checkpoint before tracked frontmatter.

        This ordering prevents a store outage from producing a false terminal
        frontmatter result. A subsequent file-write failure retains a precise,
        append-only recovery checkpoint instead of silently claiming success.

        SPEC-291 R3: every durable transition also writes a ``status-transition``
        artifact under ``reports/<SPEC-ID>/artifacts/``. A judgment transition
        (``lifecycle.is_judgment_transition``) with no ``reason``/``note`` is
        refused before any checkpoint is written -- a store outage can never
        make an unreasoned judgment transition look durable. A mechanical
        transition synthesizes its reason from ``run_id`` when none is given.
        ``note`` remains accepted as a reason source for backward-compatible
        callers (e.g. ``unblock_spec.finalize``); ``reason`` takes precedence
        when both are supplied.

        SPEC-357 R3: the same call also upserts the spec's ``## State
        rationale`` section (through ``spec_artifacts.capture_state_rationale``),
        pinned to the pre-mutation ``current_status`` so a competing revision
        landing between read and write is refused rather than silently
        overwritten.
        """
        import lifecycle
        import spec_artifacts
        from spec_frontmatter import parse_spec_file, write_spec_frontmatter

        path = Path(spec_path).resolve()
        parsed = parse_spec_file(path)
        spec_id = str(parsed.frontmatter.get("id") or "")
        if not spec_id:
            raise LifecyclePersistenceError(f"spec id missing from {path.name}")
        current_status = str(parsed.frontmatter.get("status") or "")

        reason_text = (reason if reason is not None else note)
        reason_text = reason_text.strip() if isinstance(reason_text, str) else ""
        if lifecycle.is_judgment_transition(current_status, status) and not reason_text:
            raise TransitionReasonRequired(
                f"transition {current_status!r} -> {status!r} for {spec_id} is a judgment "
                "transition and requires a non-empty reason"
            )
        if not reason_text:
            reason_text = f"mechanical transition to {status!r} via run {run_id}"

        try:
            if before_administrative_write is not None:
                before_administrative_write()
            checkpoint = self.get_state(spec_id) if before_administrative_write is not None else None
            payload = _normalize_checkpoint_payload({"spec_path": str(path), "canonical_spec_path": str(path), **(extra_payload or {})})
            if not (checkpoint and checkpoint.get("status") == status and checkpoint.get("run_id") == run_id
                    and checkpoint.get("source") == source and checkpoint.get("note") == (note or reason_text)
                    and checkpoint.get("payload") == payload):
                checkpoint = self.update_state(
                    spec_id, status, run_id=run_id, source=source, note=note or reason_text, payload=payload,
                )
        except Exception as exc:
            raise LifecyclePersistenceError(
                f"durable lifecycle checkpoint failed; frontmatter unchanged; "
                f"recovery: rerun coordinator transition for {spec_id}"
            ) from exc
        try:
            if before_administrative_write is not None:
                before_administrative_write()
            spec_artifacts.write_status_transition_artifact(
                spec_artifacts.reports_root_for_spec_path(path), spec_id,
                from_status=current_status, to_status=status,
                actor=actor or source, reason=reason_text,
                evidence=evidence, run_id=run_id,
                spec_path=path, expected_status=current_status,
                reconsider_when=reconsider_when,
                state_rationale_evidence=state_rationale_evidence,
                provenance=provenance,
            )
        except Exception as exc:
            raise LifecyclePersistenceError(
                f"checkpoint {checkpoint['checkpoint_id']} persisted but status-transition "
                f"artifact write failed; refusal: {exc}; "
                f"recovery: reconcile {path.name} artifacts and retry"
            ) from exc
        try:
            if before_administrative_write is not None:
                before_administrative_write()
            write_spec_frontmatter(path, lambda fm: {**fm, "status": status})
        except Exception as exc:
            raise LifecyclePersistenceError(
                f"checkpoint {checkpoint['checkpoint_id']} persisted but frontmatter write failed; "
                f"refusal: {exc}; "
                f"recovery: reconcile {path.name} to {status}"
            ) from exc
        return checkpoint

    def get_state_history(self, spec_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT * FROM status_checkpoints
            WHERE spec_id = ?
            ORDER BY id DESC
        """
        params: tuple[Any, ...]
        if limit is not None:
            sql += " LIMIT ?"
            params = (spec_id, int(limit))
        else:
            params = (spec_id,)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_checkpoint_from_row(row).to_dict() for row in rows]

    def get_run_history(self, spec_id: str, run_id: str) -> list[dict[str, Any]]:
        """Return one run's checkpoints oldest-first for restart-safe attribution."""
        if not run_id:
            raise ValueError("run_id required")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """
                SELECT * FROM status_checkpoints
                WHERE spec_id = ? AND run_id = ?
                ORDER BY id ASC
                """,
                (spec_id, run_id),
            ).fetchall()
        return [_checkpoint_from_row(row).to_dict() for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(sql, params).fetchone()

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as conn:
            version = _schema_version(conn)
            if version > _CURRENT_SCHEMA_VERSION:
                raise StatusStoreError(
                    f"Status store schema version {version} is newer than supported "
                    f"({_CURRENT_SCHEMA_VERSION})"
                )
            if version < 1:
                _migrate_v0_to_v1(conn)
                version = 1
            if version < 2:
                _migrate_v1_to_v2(conn)
                version = 2
            if version < 3:
                _migrate_v2_to_v3(conn)
                version = 3
            if version < 4:
                _migrate_v3_to_v4(conn)
                version = 4
            if version < 5:
                _migrate_v4_to_v5(conn)
            if version < 6:
                _migrate_v5_to_v6(conn)


def _schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", ("schema_version",)).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS status_checkpoints (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id      TEXT NOT NULL,
                status       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                run_id       TEXT,
                step         INTEGER,
                source       TEXT,
                note         TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_status_checkpoints_spec_id_id
                ON status_checkpoints(spec_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_status_checkpoints_created_at
                ON status_checkpoints(created_at);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS terminal_decisions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id      TEXT NOT NULL,
                run_id       TEXT NOT NULL,
                decision     TEXT NOT NULL CHECK (decision IN ('done', 'blocked')),
                created_at   TEXT NOT NULL,
                source       TEXT,
                reason       TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (spec_id, run_id)
            );

            CREATE INDEX IF NOT EXISTS idx_terminal_decisions_spec_run
                ON terminal_decisions(spec_id, run_id);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "2"),
        )


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cleanup_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id      TEXT NOT NULL,
                run_id       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_cleanup_events_spec_run
                ON cleanup_events(spec_id, run_id, id);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "3"),
        )


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS terminal_projection_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id      TEXT NOT NULL,
                run_id       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_terminal_projection_events_spec_run
                ON terminal_projection_events(spec_id, run_id, id);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "4"),
        )


def _migrate_v4_to_v5(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS merge_attempt_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id      TEXT NOT NULL,
                run_id       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_merge_attempt_events_spec_run
                ON merge_attempt_events(spec_id, run_id, id);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", "5"),
        )


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id TEXT NOT NULL, run_id TEXT NOT NULL,
                event_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(spec_id, run_id, event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_activity_events_spec_run ON activity_events(spec_id,run_id,id);
        """)
        conn.execute("INSERT OR REPLACE INTO meta (key,value) VALUES ('schema_version','6')")


# ---------------------------------------------------------------------------
# SPEC-332: the board/file status-sync rule, shared by board.py (live probe)
# and validate_specs.py (offline --status-store check). Pure functions: no
# database access, no FastAPI, so the validator can import them cheaply.
# ---------------------------------------------------------------------------

FRONTMATTER_RECONCILE_STATUSES = frozenset({
    "planned", "draft", "ready", "in_progress", "blocked",
    "active", "done", "superseded", "retired",
})
TERMINAL_DURABLE_STATUSES = frozenset({"done", "blocked"})
SYNC_DURABLE_TERMINAL_AHEAD = "durable-terminal-ahead-of-file"
SYNC_DURABLE_STALE_BEHIND = "durable-stale-behind-file"


def checkpoint_epoch(state: dict[str, Any]) -> float | None:
    """Return a durable row's checkpoint timestamp in seconds, or None."""
    raw = state.get("created_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def should_reconcile_frontmatter_status(
    frontmatter_status: str,
    durable_state: dict[str, Any],
    file_mtime: float,
    spec_path: Path | None = None,
) -> bool:
    """Whether a newer file status may repair a durable row.

    A durable row already at a terminal status (`done`/`blocked`) is
    authoritative and immutable via frontmatter (SPEC-296-008; BUG-313 R2). A
    non-terminal row may be forward-reconciled by a newer file status whose
    mtime is at or after the row's checkpoint (BUG-313): the documented
    interactive workflow finalizes a spec by editing frontmatter and never
    calls the automated terminal-decision projector.
    """
    durable_status = str(durable_state.get("status", ""))
    if durable_status == frontmatter_status:
        return False
    if durable_status in TERMINAL_DURABLE_STATUSES:
        return False
    if frontmatter_status not in FRONTMATTER_RECONCILE_STATUSES:
        return False
    payload = durable_state.get("payload")
    if spec_path is not None and isinstance(payload, dict):
        if not _checkpoint_path_matches(payload, spec_path):
            return False
    checkpoint_mtime = checkpoint_epoch(durable_state)
    if checkpoint_mtime is None:
        return True
    return file_mtime >= checkpoint_mtime


def classify_status_sync(
    frontmatter_status: str,
    durable_state: dict[str, Any] | None,
    file_mtime: float,
    spec_path: Path | None = None,
) -> dict[str, str] | None:
    """SPEC-332 R1: None when the board would show the file's status; else a
    mismatch record naming the durable value, the effective value and why.

    No durable row, an equal row, or a row the BUG-313 repair would overwrite
    are all "in sync" -- the effective status IS the file's. A terminal row
    the file has not caught up with is `durable-terminal-ahead-of-file`; a
    differing non-terminal row that the repair refuses (stale checkpoint or a
    different spec path) is `durable-stale-behind-file`.
    """
    if not durable_state or not durable_state.get("status"):
        return None
    durable_status = str(durable_state["status"])
    if durable_status == frontmatter_status:
        return None
    if should_reconcile_frontmatter_status(frontmatter_status, durable_state, file_mtime, spec_path):
        return None
    reason = (
        SYNC_DURABLE_TERMINAL_AHEAD
        if durable_status in TERMINAL_DURABLE_STATUSES
        else SYNC_DURABLE_STALE_BEHIND
    )
    result = {"durable": durable_status, "effective": durable_status, "reason": reason}
    payload = durable_state.get("payload")
    if reason == SYNC_DURABLE_STALE_BEHIND and spec_path is not None and isinstance(payload, dict) and _legacy_worktree_path_matches(payload.get("spec_path"), spec_path):
        result["recovery_action"] = "recognized legacy linked-worktree checkpoint: make the primary spec newer than the checkpoint and refresh; the board will reconcile it automatically"
    return result


def effective_status_view(
    frontmatter_status: str,
    durable_state: dict[str, Any] | None,
    file_mtime: float,
    spec_path: Path | None = None,
) -> dict[str, Any]:
    """SPEC-359 R5: the read-only twin of the board's effective-status choice.

    Applies the same rule as ``should_reconcile_frontmatter_status`` and
    reuses ``classify_status_sync`` for the mismatch record, but never writes
    the repair the board's own path performs. ``source`` is
    ``durable_checkpoint`` only when the durable row's differing status is what
    is displayed; otherwise the frontmatter governs.
    """
    effective, source = frontmatter_status, "frontmatter"
    durable_status = str(durable_state["status"]) if durable_state and durable_state.get("status") else None
    if durable_status and durable_status != frontmatter_status and not should_reconcile_frontmatter_status(
        frontmatter_status, durable_state or {}, file_mtime, spec_path
    ):
        effective, source = durable_status, "durable_checkpoint"
    found = classify_status_sync(frontmatter_status, durable_state, file_mtime, spec_path)
    return {
        "declared": frontmatter_status,
        "effective": effective,
        "source": source,
        "sync": {
            "in_sync": found is None,
            "durable": durable_status,
            "effective": effective,
            "reason": (found or {}).get("reason"),
        },
    }


def read_durable_states_readonly(db_path: Path, spec_ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    """SPEC-359 R5/R6: batch-read latest durable rows without creating or migrating the store.

    ``StatusStore(...)`` creates the file and runs schema migrations, which a
    diagnostic read must never do. This opens the existing database read-only
    and returns ``{}`` when it is absent or unreadable -- "no durable evidence",
    not an error.
    """
    wanted = [str(spec_id) for spec_id in spec_ids]
    path = Path(db_path)
    if not wanted or not path.is_file():
        return {}
    states: dict[str, dict[str, Any] | None] = {spec_id: None for spec_id in wanted}
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        with closing(conn):
            for start in range(0, len(wanted), _BATCH_READ_CHUNK):
                chunk = wanted[start:start + _BATCH_READ_CHUNK]
                rows = conn.execute(
                    "SELECT * FROM status_checkpoints WHERE id IN (SELECT MAX(id) FROM status_checkpoints "
                    f"WHERE spec_id IN ({','.join('?' * len(chunk))}) GROUP BY spec_id)",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    states[str(row["spec_id"])] = _checkpoint_from_row(row).to_dict()
    except (sqlite3.Error, OSError):
        return {}
    return states


# ---------------------------------------------------------------------------
# SPEC-340 R6: one-shot cross-DB migration splitting a shared status DB
# (one repository, several Nightshift projects) into one DB per project.
#
# Deliberately NOT a member of the intra-DB ``_migrate_vN_to_vN+1`` chain
# above: every function in that chain takes a single ``sqlite3.Connection``
# and cannot open, create, or write sibling DB files -- which is the entirety
# of what this migration does.
# ---------------------------------------------------------------------------

_MIGRATION_SPEC_ID_TABLES = (
    "status_checkpoints",
    "terminal_decisions",
    "cleanup_events",
    "terminal_projection_events",
    "merge_attempt_events",
    "activity_events",
)


def _collect_project_spec_ids(specs_dir: Path) -> set[str]:
    """Return every spec id declared by a Markdown frontmatter under ``specs_dir``.

    Used only for migration attribution (R7); template files are excluded
    since they never carry a real, addressable spec id.
    """
    from spec_frontmatter import FrontmatterError, parse_spec_file

    ids: set[str] = set()
    specs_dir = Path(specs_dir)
    if not specs_dir.is_dir():
        return ids
    for md_file in specs_dir.rglob("*.md"):
        if md_file.name.startswith("_TEMPLATE"):
            continue
        try:
            parsed = parse_spec_file(md_file)
        except FrontmatterError:
            continue
        spec_id = parsed.frontmatter.get("id")
        if spec_id:
            ids.add(str(spec_id))
    return ids


def migrate_split_shared_db(
    source_db_path: Path,
    project_specs_dirs: dict[str, Path],
) -> dict[str, Any]:
    """SPEC-340 R6: split one shared status DB into one DB per project.

    ``project_specs_dirs`` maps each project's relpath inside its checkout
    (``"."`` for the toplevel-rooted project, else the POSIX relpath
    ``_project_relpath`` would compute for it) to that project's specs
    directory. Row attribution is by set membership: a spec id belongs to a
    project when some spec file under that project's ``specs_dir`` declares
    that id in its frontmatter.

    Fail-closed (R7, AC7): a spec id present in the source but attributable
    to zero or more than one project aborts the *entire* migration before
    any destination file is created and before the source is touched --
    ``StatusStoreError`` names every offending id and its row count across
    all spec-id-bearing tables. The source DB is opened **read-only** via a
    ``file:...?mode=ro`` URI (never through ``StatusStore._connect``, which
    sets ``PRAGMA journal_mode=WAL`` and would rewrite the file header even
    on a path that goes on to refuse), so a refused migration leaves the
    source byte-identical.

    Returns a summary: ``{"source": ..., "projects": {relpath: {"db_path":
    ..., "rows": {table: row_count, ...}}}}``.
    """
    source_db_path = Path(source_db_path).resolve()
    if not source_db_path.is_file():
        raise StatusStoreError(f"migration source database not found: {source_db_path}")

    project_ids: dict[str, set[str]] = {
        relpath: _collect_project_spec_ids(Path(specs_dir))
        for relpath, specs_dir in project_specs_dirs.items()
    }

    source_uri = f"file:{source_db_path.as_posix()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_conn:
        source_conn.row_factory = sqlite3.Row
        existing_tables = {
            row["name"]
            for row in source_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        rows_by_table: dict[str, list[sqlite3.Row]] = {}
        for table in _MIGRATION_SPEC_ID_TABLES:
            if table not in existing_tables:
                continue
            rows_by_table[table] = source_conn.execute(f"SELECT * FROM {table}").fetchall()

        meta_row = source_conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("repository_common_dir",),
        ).fetchone()
        repository_common_dir = str(meta_row["value"]) if meta_row is not None else None

        # --- attribution pass: nothing is written anywhere until every row
        # across every table has resolved to exactly one project. ---
        unattributable: dict[str, int] = {}
        attribution: dict[str, dict[str, list[sqlite3.Row]]] = {
            relpath: {table: [] for table in rows_by_table} for relpath in project_ids
        }
        for table, rows in rows_by_table.items():
            for row in rows:
                spec_id = str(row["spec_id"])
                owners = [relpath for relpath, ids in project_ids.items() if spec_id in ids]
                if len(owners) != 1:
                    unattributable[spec_id] = unattributable.get(spec_id, 0) + 1
                    continue
                attribution[owners[0]][table].append(row)

        if unattributable:
            detail = ", ".join(
                f"{spec_id} ({count} row(s))"
                for spec_id, count in sorted(unattributable.items())
            )
            raise StatusStoreError(
                "SPEC-340 migration refused: unattributable spec id(s) -- "
                f"{detail}. No destination database was written and the "
                f"source database ({source_db_path}) is unchanged. Resolve "
                "the ambiguity -- each id must belong to exactly one "
                "project's specs dir -- and re-run."
            )

        common_dir = (
            Path(repository_common_dir)
            if repository_common_dir is not None
            else source_db_path.parent
        )
        dest_paths: dict[str, Path] = {
            relpath: (
                common_dir / _DEFAULT_DB_NAME
                if relpath == "."
                else common_dir / "nightshift" / relpath / _DEFAULT_DB_NAME
            )
            for relpath in project_specs_dirs
        }
        # Computed and checked up front, before any destination file is
        # opened: a mixed-shape repository (a toplevel-rooted project's
        # relpath "." alongside subproject relpaths) would otherwise resolve
        # "." to common_dir / _DEFAULT_DB_NAME -- the source file itself --
        # and silently mutate it mid-migration, partial-output and all (R7).
        for relpath, dest_path in dest_paths.items():
            if dest_path.resolve() == source_db_path.resolve():
                raise StatusStoreError(
                    f"SPEC-340 migration refused: project {relpath!r}'s destination "
                    f"database ({dest_path}) is the source database itself. No "
                    "destination database was written and the source database "
                    f"({source_db_path}) is unchanged. Pass a source DB that is not "
                    "already one of the destination paths."
                )
        collisions: dict[Path, list[str]] = {}
        for relpath, dest_path in dest_paths.items():
            collisions.setdefault(dest_path.resolve(), []).append(relpath)
        for dest_path, relpaths in collisions.items():
            if len(relpaths) > 1:
                raise StatusStoreError(
                    "SPEC-340 migration refused: projects "
                    f"{', '.join(sorted(relpaths))!r} all resolve to the same "
                    f"destination database ({dest_path}). No destination database "
                    f"was written and the source database ({source_db_path}) is "
                    "unchanged."
                )

        summary: dict[str, Any] = {"source": str(source_db_path), "projects": {}}
        for relpath, specs_dir in project_specs_dirs.items():
            dest_path = dest_paths[relpath]
            dest_store = StatusStore(dest_path)
            dest_store._bind_repository_common_dir(
                common_dir,
                project_relpath=None if relpath == "." else relpath,
            )
            project_summary: dict[str, int] = {}
            with closing(dest_store._connect()) as dest_conn:
                with dest_conn:
                    for table, rows in attribution[relpath].items():
                        for row in rows:
                            columns = row.keys()
                            placeholders = ", ".join("?" for _ in columns)
                            column_list = ", ".join(columns)
                            dest_conn.execute(
                                f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})",
                                tuple(row[column] for column in columns),
                            )
                        project_summary[table] = len(rows)
            summary["projects"][relpath] = {"db_path": str(dest_path), "rows": project_summary}
        return summary


def _parse_migration_project_arg(value: str):
    import argparse

    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "expected RELPATH=SPECS_DIR (e.g. '.=./specs' or 'core=core/specs')"
        )
    relpath, _, specs_dir = value.partition("=")
    relpath = relpath.strip()
    if not relpath:
        raise argparse.ArgumentTypeError("RELPATH must not be empty")
    return relpath, Path(specs_dir.strip())


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the SPEC-340 R6 migration.

    Example::

        python status_store.py --source Cortex/.git/nightshift-status.db \\
            --project core=Cortex/core/.nightshift/specs \\
            --project api=Cortex/api/.nightshift/specs \\
            --project mcp=Cortex/mcp/.nightshift/specs \\
            --project tools=Cortex/tools/.nightshift/specs
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "SPEC-340 R6: split a shared Nightshift status DB (one repository, "
            "several projects) into one DB per project, attributed by which "
            "project's specs dir declares each row's spec id. Fails closed: "
            "any unattributable spec id aborts with no partial output."
        ),
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="Path to the shared source DB.",
    )
    parser.add_argument(
        "--project", dest="projects", action="append", required=True,
        type=_parse_migration_project_arg, metavar="RELPATH=SPECS_DIR",
        help=(
            "One per project sharing --source. RELPATH is '.' for the "
            "toplevel-rooted project, else the project's POSIX path inside "
            "the checkout (e.g. 'core'). Repeatable."
        ),
    )
    args = parser.parse_args(argv)
    project_specs_dirs = dict(args.projects)
    try:
        summary = migrate_split_shared_db(args.source, project_specs_dirs)
    except StatusStoreError as exc:
        print(str(exc))
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())


def _terminal_projection_diagnostics(conn, spec_ids):
    placeholders = ','.join('?' for _ in spec_ids)
    decisions = conn.execute(
            f'SELECT * FROM terminal_decisions WHERE id IN (SELECT MAX(id) FROM terminal_decisions '
            f'WHERE spec_id IN ({placeholders}) GROUP BY spec_id) ORDER BY id',
            spec_ids).fetchall()
    events = conn.execute(
            f'SELECT * FROM terminal_projection_events WHERE id IN (SELECT MAX(id) '
            f'FROM terminal_projection_events WHERE spec_id IN ({placeholders}) GROUP BY spec_id, run_id)',
            spec_ids).fetchall()
    cleanup_rows = conn.execute(
        f'SELECT * FROM cleanup_events WHERE id IN (SELECT MAX(id) FROM cleanup_events '
        f'WHERE spec_id IN ({placeholders}) GROUP BY spec_id, run_id)',
        spec_ids).fetchall()
    cleanups = {(row['spec_id'], row['run_id']): _json_loads(row['payload_json'])
                for row in cleanup_rows}
    histories = {}
    for row in events:
        histories.setdefault((row['spec_id'], row['run_id']), []).append(_json_loads(row['payload_json']))
    result = {}
    for row in decisions:
        history = histories.get((row['spec_id'], row['run_id']), [])
        last = history[-1] if history else {}
        completed = last.get('phase') in {'completed', 'metadata_completed'}
        result[row['spec_id']] = {
            'decision': row['decision'], 'run_id': row['run_id'],
            'projection': 'completed' if completed else 'pending',
            'cleanup_eligible': completed,
            'cleanup': cleanups.get((row['spec_id'], row['run_id']), {}).get('phase', 'pending'),
            'reason': None if completed else last.get('reason') or
                ('sealed tracked closure awaits ordinary commit' if history else
                 'accepted decision awaits bounded parent completion inputs and tracked closure'),
            'findings': [] if completed else [last.get('reason')] if last.get('reason') else [],
            'recovery_action': None if completed else 'queue.recover_terminal_projection(handle)',
        }
    return result



def read_terminal_projection_diagnostics_readonly(db_path: Path, spec_ids: list[str]) -> dict:
    """Offline diagnostics never initialize, migrate or write a status store."""
    if not spec_ids or not Path(db_path).is_file():
        return {}
    try:
        with closing(sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return _terminal_projection_diagnostics(conn, spec_ids)
    except (sqlite3.Error, OSError):
        return {}


class _BoardStateBatch(dict):
    def __init__(self, states, projections, activity_inputs=None):
        super().__init__(states)
        self.terminal_projections = projections
        self.activity_inputs = activity_inputs or {}
