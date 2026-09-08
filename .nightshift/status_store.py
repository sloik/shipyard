#!/usr/bin/env python3
"""
SQLite-backed durable spec status checkpoints for Nightshift.

Status files remain the static spec metadata source. This store is the shared
runtime layer: every status transition appends a checkpoint row keyed by spec id.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

# SPEC-303: bound-parameter chunk for the batch status read; one connection
# is reused across chunks.
_BATCH_READ_CHUNK = 500


_CURRENT_SCHEMA_VERSION = 5
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

    def __init__(self, db_path: Path, *, repository_root: Path | None = None) -> None:
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
            self.bind_repository(repository_root)

    @classmethod
    def for_specs_dir(cls, specs_dir: Path) -> "StatusStore":
        specs_dir = Path(specs_dir).resolve()
        project_root = specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent
        return cls(
            default_db_path_for_specs_dir(specs_dir),
            repository_root=(
                project_root if _run_git_common_dir(project_root) is not None else None
            ),
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

    def bind_repository(self, repo_root: Path) -> dict[str, str]:
        """Durably bind this store to one Git common directory.

        Linked worktrees deliberately share this identity. Independent clones do
        not, even when their revisions and blobs are byte-identical.
        """
        identity = self._repository_identity(repo_root)
        self._bind_repository_common_dir(Path(identity["repo_common_dir"]))
        return identity

    def _bind_repository_common_dir(self, common_dir: Path) -> None:
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

    def get_states(self, spec_ids: Iterable[str]) -> dict[str, dict[str, Any] | None]:
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
        return states

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
                            "declared_surfaces", "attempt_number",
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
                                "declared_surfaces", "attempt_number",
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
