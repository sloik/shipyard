#!/usr/bin/env python3
"""
SQLite-backed durable spec status checkpoints for Nightshift.

Status files remain the static spec metadata source. This store is the shared
runtime layer: every status transition appends a checkpoint row keyed by spec id.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CURRENT_SCHEMA_VERSION = 1
_DEFAULT_DB_NAME = "nightshift-status.db"


class StatusStoreError(RuntimeError):
    """Raised when the durable status store cannot be used safely."""


class LifecyclePersistenceError(StatusStoreError):
    """A coordinator transition could not durably establish its checkpoint."""


class TransitionReasonRequired(StatusStoreError, ValueError):
    """A judgment transition (SPEC-291 R3) was attempted with no reason."""


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


def default_db_path_for_specs_dir(specs_dir: Path) -> Path:
    """Return a DB path shared by all git worktrees for ``specs_dir``.

    Worktrees have separate checked-out ``.nightshift`` directories, so storing
    the DB there would recreate the invisibility bug. The git common directory is
    shared by all worktrees of the same repository.
    """

    specs_dir = Path(specs_dir).resolve()
    project_root = specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent
    common_git_dir = _run_git_common_dir(project_root)
    if common_git_dir is not None:
        return common_git_dir / _DEFAULT_DB_NAME
    return project_root / ".nightshift" / _DEFAULT_DB_NAME


class StatusStore:
    """Append-only status checkpoint store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @classmethod
    def for_specs_dir(cls, specs_dir: Path) -> "StatusStore":
        return cls(default_db_path_for_specs_dir(specs_dir))

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
                                actor: str | None = None) -> dict[str, Any]:
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
            checkpoint = self.update_state(
                spec_id, status, run_id=run_id, source=source, note=note or reason_text,
                payload={"spec_path": str(path), "canonical_spec_path": str(path)},
            )
        except Exception as exc:
            raise LifecyclePersistenceError(
                f"durable lifecycle checkpoint failed; frontmatter unchanged; "
                f"recovery: rerun coordinator transition for {spec_id}"
            ) from exc
        try:
            spec_artifacts.write_status_transition_artifact(
                spec_artifacts.reports_root_for_spec_path(path), spec_id,
                from_status=current_status, to_status=status,
                actor=actor or source, reason=reason_text,
                evidence=evidence, run_id=run_id,
            )
        except Exception as exc:
            raise LifecyclePersistenceError(
                f"checkpoint {checkpoint['checkpoint_id']} persisted but status-transition "
                f"artifact write failed; refusal: {exc}; "
                f"recovery: reconcile {path.name} artifacts and retry"
            ) from exc
        try:
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
            ("schema_version", str(_CURRENT_SCHEMA_VERSION)),
        )
