#!/usr/bin/env python3
"""
SQLite-backed cross-project execution history for Nightshift.

Ingests completed run data (metrics YAML + events NDJSON) from per-project
.nightshift/ directories into a central SQLite database at ~/.nightshift/history.db.
Provides query functions for cross-project analytics.

Dependencies: stdlib + sqlite3 + json + PyYAML (already a Nightshift dep).

SPEC-039 — Execution History Database
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None  # Deferred error — only raised when YAML parsing is needed

try:
    from loop_events import load_events, STEP_NAMES
except ImportError:
    # Standalone usage fallback — inline minimal implementation
    STEP_NAMES: Dict[int, str] = {
        1: "preflight",
        2: "task_selection",
        3: "context_loading",
        4: "test_planning",
        5: "test_writing",
        6: "plan_review",
        7: "implementation",
        8: "validation",
        9: "completion_verification",
        10: "post_review",
        11: "circuit_breaker",
        12: "commit_changelog",
        13: "metrics_logging",
        14: "report_generation",
        15: "post_run",
        16: "loop_exit",
    }

    def load_events(events_file: Path) -> List[Dict]:
        """Minimal fallback: read NDJSON events file."""
        events: List[Dict] = []
        try:
            with open(events_file, "r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        events.append(event)
        except (FileNotFoundError, OSError):
            pass
        return events


# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".nightshift"

_CURRENT_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SchemaVersionError(Exception):
    """Raised when the database schema version is higher than understood."""
    pass


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    status: str  # "ingested" | "already_exists" | "error"
    specs_ingested: int = 0
    events_ingested: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "specs_ingested": self.specs_ingested,
            "events_ingested": self.events_ingested,
            "warnings": list(self.warnings),
        }


@dataclass
class RunSummary:
    run_id: str
    project: str
    start_time: str
    end_time: Optional[str]
    outcome: str
    specs_attempted: int
    specs_completed: int
    model: Optional[str]
    harness: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "outcome": self.outcome,
            "specs_attempted": self.specs_attempted,
            "specs_completed": self.specs_completed,
            "model": self.model,
            "harness": self.harness,
        }


@dataclass
class FailureSummary:
    spec_id: str
    run_id: str
    project: str
    status: str
    failure_class: Optional[str]
    error_type: Optional[str]
    duration_s: Optional[float]
    model: Optional[str]
    completed_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "run_id": self.run_id,
            "project": self.project,
            "status": self.status,
            "failure_class": self.failure_class,
            "error_type": self.error_type,
            "duration_s": self.duration_s,
            "model": self.model,
            "completed_at": self.completed_at,
        }


@dataclass
class TimelineEvent:
    timestamp: str
    event_type: str
    spec_id: Optional[str]
    step: Optional[int]
    step_name: Optional[str]
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "spec_id": self.spec_id,
            "step": self.step,
            "step_name": self.step_name,
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# Database connection & schema migration
# ---------------------------------------------------------------------------


def _get_connection(db_dir: Optional[Path] = None) -> sqlite3.Connection:
    """Open (or create) the history database and ensure schema is current."""
    db_dir = db_dir or _DEFAULT_DB_DIR
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def ensure_schema(db_dir: Optional[Path] = None) -> int:
    """
    Public schema preflight — open the DB, run forward migrations, close.

    Called from LOOP.md Step 1 (preflight) before any spec runs so that a
    future-version DB causes an early, loud failure (SchemaVersionError).

    Returns the current schema version on success.
    Raises SchemaVersionError if the DB schema is newer than this module
    understands; re-raises OSError (or similar) if the DB directory is
    unwritable so the caller can decide how to handle it.
    """
    conn = _get_connection(db_dir)
    try:
        return _get_schema_version(conn)
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Check schema version and apply forward migrations."""
    version = _get_schema_version(conn)

    if version > _CURRENT_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Database schema version {version} is newer than this module "
            f"understands (max {_CURRENT_SCHEMA_VERSION}). "
            "Upgrade execution_history.py or use a compatible database."
        )

    migrations = [
        _migrate_v0_to_v1,
    ]

    for target_version, migrate_fn in enumerate(migrations, start=1):
        if version < target_version:
            migrate_fn(conn)
            version = target_version


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """Read schema_version from meta table. Return 0 if meta doesn't exist."""
    try:
        cursor = conn.execute(
            "SELECT value FROM meta WHERE key = ?", ("schema_version",)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        # meta table doesn't exist
        return 0


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """Create all initial tables (version 0 -> 1)."""
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id          TEXT PRIMARY KEY,
                project         TEXT NOT NULL,
                nightshift_dir  TEXT NOT NULL,
                start_time      TEXT NOT NULL,
                end_time        TEXT,
                outcome         TEXT NOT NULL DEFAULT 'unknown',
                specs_attempted INTEGER NOT NULL DEFAULT 0,
                specs_completed INTEGER NOT NULL DEFAULT 0,
                model           TEXT,
                harness         TEXT,
                loop_version    TEXT,
                config_hash     TEXT,
                ingested_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project);
            CREATE INDEX IF NOT EXISTS idx_runs_start_time ON runs(start_time);
            CREATE INDEX IF NOT EXISTS idx_runs_outcome ON runs(outcome);

            CREATE TABLE IF NOT EXISTS spec_results (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          TEXT NOT NULL REFERENCES runs(run_id),
                spec_id         TEXT NOT NULL,
                spec_file       TEXT,
                status          TEXT NOT NULL,
                started_at      TEXT,
                completed_at    TEXT,
                duration_s      REAL,
                tests_written   INTEGER DEFAULT 0,
                tests_passing   INTEGER DEFAULT 0,
                tests_failing   INTEGER DEFAULT 0,
                review_cycles   INTEGER DEFAULT 0,
                failure_class   TEXT,
                error_type      TEXT,
                model           TEXT,
                tier            TEXT,
                UNIQUE(run_id, spec_id)
            );

            CREATE INDEX IF NOT EXISTS idx_spec_results_run_id ON spec_results(run_id);
            CREATE INDEX IF NOT EXISTS idx_spec_results_spec_id ON spec_results(spec_id);
            CREATE INDEX IF NOT EXISTS idx_spec_results_status ON spec_results(status);

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL REFERENCES runs(run_id),
                spec_id     TEXT,
                event_type  TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                step        INTEGER,
                step_name   TEXT,
                data_json   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        """)

        # Upsert schema_version
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("schema_version", str(_CURRENT_SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _compute_config_hash(nightshift_dir: Path) -> Optional[str]:
    """SHA-256 of config.yaml in the project root (parent of .nightshift/)."""
    # The project root is the parent of the .nightshift directory
    project_root = Path(nightshift_dir).parent
    config_path = project_root / "config.yaml"
    if not config_path.exists():
        # Try inside .nightshift/
        config_path = Path(nightshift_dir) / "config.yaml"
    if not config_path.exists():
        return None
    try:
        data = config_path.read_bytes()
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


def _load_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load a YAML file, returning None on any error."""
    if yaml is None:
        _warn("warning: PyYAML not available, cannot parse YAML files")
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_project_name(nightshift_dir: Path) -> str:
    """Try to extract the project name from config.yaml."""
    project_root = Path(nightshift_dir).parent
    config_path = project_root / "config.yaml"
    if not config_path.exists():
        config_path = Path(nightshift_dir) / "config.yaml"
    data = _load_yaml_file(config_path)
    if data and isinstance(data.get("project"), dict):
        name = data["project"].get("name", "")
        if name:
            return str(name)
    return ""


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def ingest_run(
    nightshift_dir: Path,
    run_id: str,
    project: str = "",
    db_dir: Optional[Path] = None,
) -> IngestResult:
    """
    Ingest a completed run's data into the history database.

    Reads events.jsonl via load_events() and metrics YAML files.
    Idempotent: skips if run_id already exists.
    Single transaction for all inserts.

    Args:
        nightshift_dir: Path to the .nightshift/ directory
        run_id: Unique run identifier (e.g. "run-2026-04-10-031500")
        project: Project name (falls back to config.yaml extraction)
        db_dir: Override database directory (for testing)

    Returns:
        IngestResult with status, counts, and warnings
    """
    nightshift_dir = Path(nightshift_dir)
    warnings: List[str] = []

    try:
        conn = _get_connection(db_dir)
    except Exception as exc:
        return IngestResult(status="error", warnings=[f"DB connection failed: {exc}"])

    try:
        # Check idempotency
        cursor = conn.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        )
        if cursor.fetchone():
            conn.close()
            return IngestResult(status="already_exists")

        # Resolve project name
        if not project:
            project = _read_project_name(nightshift_dir)
        if not project:
            project = nightshift_dir.parent.name  # fallback to directory name

        # Load events
        events_file = nightshift_dir / "runs" / run_id / "events.jsonl"
        raw_events = load_events(events_file)
        if not raw_events:
            warnings.append(f"No events found in {events_file}")

        # Extract run-level info from events
        start_time = None
        end_time = None
        outcome = "unknown"
        model = None
        harness = None
        loop_version = None

        for evt in raw_events:
            evt_type = evt.get("event", "")
            if evt_type in ("loop_started", "run_started"):
                start_time = evt.get("ts", start_time)
                model = evt.get("model", model)
                harness = evt.get("harness", harness)
                loop_version = evt.get("loop_version", loop_version)
            elif evt_type in ("loop_ended", "run_completed"):
                end_time = evt.get("ts", end_time)
                outcome = evt.get("outcome", outcome)

        if start_time is None and raw_events:
            start_time = raw_events[0].get("ts", _iso_utc_now())
        elif start_time is None:
            start_time = _iso_utc_now()

        # Extract per-spec info from events
        spec_data: Dict[str, Dict[str, Any]] = {}
        for evt in raw_events:
            spec_id = evt.get("spec_id")
            if not spec_id:
                continue
            if spec_id not in spec_data:
                spec_data[spec_id] = {
                    "spec_id": spec_id,
                    "spec_file": evt.get("spec_file"),
                    "status": "unknown",
                    "started_at": None,
                    "completed_at": None,
                    "model": evt.get("model"),
                    "tier": evt.get("tier"),
                }
            sd = spec_data[spec_id]
            evt_type = evt.get("event", "")
            if evt_type in ("spec_started",):
                sd["started_at"] = evt.get("ts")
                if evt.get("spec_file"):
                    sd["spec_file"] = evt["spec_file"]
            elif evt_type in ("spec_completed", "spec_failed", "spec_blocked"):
                sd["completed_at"] = evt.get("ts")
                sd["status"] = evt.get("status", evt_type.replace("spec_", ""))
                if evt.get("failure_class"):
                    sd["failure_class"] = evt["failure_class"]
                if evt.get("error_type"):
                    sd["error_type"] = evt["error_type"]

        # Try to load metrics YAML files to enrich spec data
        metrics_dir = nightshift_dir / "metrics"
        metrics_loaded = False
        if metrics_dir.is_dir():
            for yaml_file in sorted(metrics_dir.glob("*.yaml")) + sorted(metrics_dir.glob("*.yml")):
                mdata = _load_yaml_file(yaml_file)
                if not mdata:
                    continue
                task_id = mdata.get("task_id", "")
                if not task_id:
                    continue
                metrics_loaded = True
                if task_id not in spec_data:
                    spec_data[task_id] = {
                        "spec_id": task_id,
                        "spec_file": mdata.get("spec_file"),
                        "status": "unknown",
                        "started_at": None,
                        "completed_at": None,
                    }
                sd = spec_data[task_id]
                # Enrich from metrics YAML
                sd["status"] = mdata.get("status", sd.get("status", "unknown"))
                sd["spec_file"] = mdata.get("spec_file", sd.get("spec_file"))
                sd["started_at"] = mdata.get("started_at", sd.get("started_at"))
                sd["completed_at"] = mdata.get("completed_at", sd.get("completed_at"))
                sd["model"] = mdata.get("model", sd.get("model"))
                sd["harness"] = mdata.get("harness", sd.get("harness"))
                sd["loop_version"] = mdata.get("loop_version", sd.get("loop_version"))

                # Extract phase data
                phases = mdata.get("phases", {})
                if isinstance(phases, dict):
                    tw = phases.get("test_writing", {})
                    if isinstance(tw, dict):
                        sd["tests_written"] = tw.get("tests_written", 0)
                        sd["tests_failing"] = tw.get("tests_failing", 0)
                    validation = phases.get("validation", {})
                    if isinstance(validation, dict):
                        sd["tests_passing"] = validation.get("tests_passed", 0)
                    review = phases.get("review", {})
                    if isinstance(review, dict):
                        sd["review_cycles"] = review.get("cycles", 0)

                # Failure info
                failure = mdata.get("failure", {})
                if isinstance(failure, dict):
                    sd["failure_class"] = failure.get("phase", sd.get("failure_class"))
                    sd["error_type"] = failure.get("error_type", sd.get("error_type"))

                # Run-level enrichment
                if not model:
                    model = mdata.get("model")
                if not harness:
                    harness = mdata.get("harness")
                if not loop_version:
                    loop_version = mdata.get("loop_version")
        else:
            warnings.append(f"Metrics directory not found: {metrics_dir}")

        if not metrics_loaded and spec_data:
            warnings.append("No metrics YAML files found; spec data populated from events only")

        # Compute duration for specs
        for sd in spec_data.values():
            if sd.get("started_at") and sd.get("completed_at"):
                try:
                    t_start = datetime.fromisoformat(
                        sd["started_at"].replace("Z", "+00:00")
                    )
                    t_end = datetime.fromisoformat(
                        sd["completed_at"].replace("Z", "+00:00")
                    )
                    sd["duration_s"] = (t_end - t_start).total_seconds()
                except (ValueError, TypeError):
                    sd["duration_s"] = None
            else:
                sd.setdefault("duration_s", None)

        # Count specs
        specs_attempted = len(spec_data)
        specs_completed = sum(
            1 for sd in spec_data.values() if sd.get("status") == "completed"
        )

        config_hash = _compute_config_hash(nightshift_dir)

        # --- Single transaction for all inserts ---
        with conn:
            # Insert run
            conn.execute(
                "INSERT INTO runs "
                "(run_id, project, nightshift_dir, start_time, end_time, outcome, "
                "specs_attempted, specs_completed, model, harness, loop_version, "
                "config_hash, ingested_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    project,
                    str(nightshift_dir),
                    start_time,
                    end_time,
                    outcome,
                    specs_attempted,
                    specs_completed,
                    model,
                    harness,
                    loop_version,
                    config_hash,
                    _iso_utc_now(),
                ),
            )

            # Insert spec_results
            for sd in spec_data.values():
                conn.execute(
                    "INSERT INTO spec_results "
                    "(run_id, spec_id, spec_file, status, started_at, completed_at, "
                    "duration_s, tests_written, tests_passing, tests_failing, "
                    "review_cycles, failure_class, error_type, model, tier) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        sd["spec_id"],
                        sd.get("spec_file"),
                        sd.get("status", "unknown"),
                        sd.get("started_at"),
                        sd.get("completed_at"),
                        sd.get("duration_s"),
                        sd.get("tests_written", 0),
                        sd.get("tests_passing", 0),
                        sd.get("tests_failing", 0),
                        sd.get("review_cycles", 0),
                        sd.get("failure_class"),
                        sd.get("error_type"),
                        sd.get("model"),
                        sd.get("tier"),
                    ),
                )

            # Insert events (bulk)
            event_rows = []
            for evt in raw_events:
                step = evt.get("step")
                step_name = evt.get("step_name")
                if step and not step_name and isinstance(step, int):
                    step_name = STEP_NAMES.get(step)
                event_rows.append((
                    run_id,
                    evt.get("spec_id"),
                    evt.get("event", "unknown"),
                    evt.get("ts", ""),
                    step,
                    step_name,
                    json.dumps(evt, ensure_ascii=False),
                ))

            conn.executemany(
                "INSERT INTO events "
                "(run_id, spec_id, event_type, timestamp, step, step_name, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                event_rows,
            )

        conn.close()

        return IngestResult(
            status="ingested",
            specs_ingested=specs_attempted,
            events_ingested=len(raw_events),
            warnings=warnings,
        )

    except Exception as exc:
        conn.close()
        return IngestResult(status="error", warnings=[f"Ingest failed: {exc}"])


def ingest_run_and_log(
    nightshift_dir: Path,
    run_id: str,
    project: str = "",
    events_file: Optional[Path] = None,
    db_dir: Optional[Path] = None,
) -> IngestResult:
    """
    Failure-tolerant wrapper around ingest_run() for LOOP.md Step 16.

    Catches every exception, and on any failure (including an IngestResult
    with status == "error") appends a ``history_ingest_failed`` event to the
    run's events.jsonl. The loop must never crash because of history
    ingestion — this is the single entry point LOOP.md calls.

    Args:
        nightshift_dir: The project's .nightshift/ directory (see R2).
        run_id: The completed run identifier.
        project: Optional project name override (falls back to config.yaml).
        events_file: Optional override for the events.jsonl path. Defaults to
            ``nightshift_dir / "runs" / run_id / "events.jsonl"``.
        db_dir: Override the history DB directory (for testing).

    Returns:
        IngestResult. status is one of "ingested", "already_exists", "error".
        Callers should treat any status as non-fatal.
    """
    nightshift_dir = Path(nightshift_dir)
    if events_file is None:
        events_file = nightshift_dir / "runs" / run_id / "events.jsonl"
    else:
        events_file = Path(events_file)

    try:
        result = ingest_run(
            nightshift_dir=nightshift_dir,
            run_id=run_id,
            project=project,
            db_dir=db_dir,
        )
    except Exception as exc:
        # Defensive — ingest_run already traps exceptions, but bugs happen.
        result = IngestResult(
            status="error",
            warnings=[f"ingest_run raised unexpectedly: {exc}"],
        )

    if result.status in ("ingested", "already_exists"):
        _append_event(
            events_file,
            {
                "ts": _iso_utc_now(),
                "event": "history_ingest_succeeded",
                "run_id": run_id,
                "status": result.status,
                "specs_ingested": result.specs_ingested,
                "events_ingested": result.events_ingested,
            },
        )
        return result

    # status == "error" — log and continue.
    _append_event(
        events_file,
        {
            "ts": _iso_utc_now(),
            "event": "history_ingest_failed",
            "run_id": run_id,
            "warnings": list(result.warnings),
        },
    )
    return result


def _append_event(events_file: Path, event: Dict[str, Any]) -> None:
    """
    Append a single NDJSON line to events.jsonl. Best-effort only.

    If the events file's parent directory doesn't exist we try to create it;
    if that still fails we swallow the error — the loop must never crash
    because we couldn't log a history_ingest_* event.
    """
    try:
        events_file = Path(events_file)
        events_file.parent.mkdir(parents=True, exist_ok=True)
        with open(events_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover — defensive
        _warn(f"failed to append history ingest event: {exc}")


def query_runs(
    project: Optional[str] = None,
    since: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db_dir: Optional[Path] = None,
) -> List[RunSummary]:
    """
    Query the runs table with optional filters.

    Args:
        project: Exact match on project name
        since: ISO 8601 date/datetime string, filters start_time >= since
        status: Exact match on outcome
        limit: Max rows returned (default 50)
        db_dir: Override database directory (for testing)

    Returns:
        List of RunSummary, ordered by start_time descending
    """
    conn = _get_connection(db_dir)
    try:
        clauses: List[str] = []
        params: List[Any] = []

        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if since is not None:
            clauses.append("start_time >= ?")
            params.append(since)
        if status is not None:
            clauses.append("outcome = ?")
            params.append(status)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        query = (
            "SELECT run_id, project, start_time, end_time, outcome, "
            "specs_attempted, specs_completed, model, harness "
            f"FROM runs {where} ORDER BY start_time DESC LIMIT ?"
        )
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [
            RunSummary(
                run_id=r[0],
                project=r[1],
                start_time=r[2],
                end_time=r[3],
                outcome=r[4],
                specs_attempted=r[5],
                specs_completed=r[6],
                model=r[7],
                harness=r[8],
            )
            for r in rows
        ]
    finally:
        conn.close()


def query_failures(
    project: Optional[str] = None,
    limit: int = 20,
    db_dir: Optional[Path] = None,
) -> List[FailureSummary]:
    """
    Cross-project failure analysis.

    Joins spec_results (where status != 'completed') with runs.

    Args:
        project: Filter to a specific project
        limit: Max rows returned (default 20)
        db_dir: Override database directory (for testing)

    Returns:
        List of FailureSummary, ordered by completed_at descending
    """
    conn = _get_connection(db_dir)
    try:
        clauses = ["sr.status != ?"]
        params: List[Any] = ["completed"]

        if project is not None:
            clauses.append("r.project = ?")
            params.append(project)

        where = "WHERE " + " AND ".join(clauses)

        query = (
            "SELECT sr.spec_id, sr.run_id, r.project, sr.status, "
            "sr.failure_class, sr.error_type, sr.duration_s, sr.model, sr.completed_at "
            "FROM spec_results sr "
            "JOIN runs r ON sr.run_id = r.run_id "
            f"{where} "
            "ORDER BY sr.completed_at DESC LIMIT ?"
        )
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [
            FailureSummary(
                spec_id=r[0],
                run_id=r[1],
                project=r[2],
                status=r[3],
                failure_class=r[4],
                error_type=r[5],
                duration_s=r[6],
                model=r[7],
                completed_at=r[8],
            )
            for r in rows
        ]
    finally:
        conn.close()


def get_run_timeline(
    run_id: str,
    db_dir: Optional[Path] = None,
) -> List[TimelineEvent]:
    """
    Chronological view of a single run.

    Args:
        run_id: The run identifier
        db_dir: Override database directory (for testing)

    Returns:
        List of TimelineEvent, ordered by timestamp ascending.
        Empty list for non-existent run_id.
    """
    conn = _get_connection(db_dir)
    try:
        cursor = conn.execute(
            "SELECT timestamp, event_type, spec_id, step, step_name, data_json "
            "FROM events WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        )
        rows = cursor.fetchall()

        result = []
        for r in rows:
            data = {}
            if r[5]:
                try:
                    data = json.loads(r[5])
                except (json.JSONDecodeError, TypeError):
                    data = {}
            result.append(
                TimelineEvent(
                    timestamp=r[0],
                    event_type=r[1],
                    spec_id=r[2],
                    step=r[3],
                    step_name=r[4],
                    data=data,
                )
            )
        return result
    finally:
        conn.close()


def export_to_cortex(
    run_id: str,
    db_dir: Optional[Path] = None,
) -> Any:
    """
    Format run data as a Cortex entry.

    Returns a dict with keys: category, observation, context, severity.
    Returns False for a non-existent run_id.

    The caller is responsible for the actual Cortex MCP call.
    """
    conn = _get_connection(db_dir)
    try:
        # Fetch run
        cursor = conn.execute(
            "SELECT run_id, project, start_time, end_time, outcome, "
            "specs_attempted, specs_completed, model, harness "
            "FROM runs WHERE run_id = ?",
            (run_id,),
        )
        run_row = cursor.fetchone()
        if not run_row:
            return False

        r_id, project, start_time, end_time, outcome, specs_att, specs_comp, model, harness = run_row

        # Fetch spec results
        cursor = conn.execute(
            "SELECT spec_id, status, failure_class, error_type, duration_s "
            "FROM spec_results WHERE run_id = ?",
            (run_id,),
        )
        spec_rows = cursor.fetchall()

        # Format spec details
        spec_details = []
        for sr in spec_rows:
            detail = f"{sr[0]}: {sr[1]}"
            if sr[2]:
                detail += f" (failure_class={sr[2]})"
            if sr[3]:
                detail += f" (error_type={sr[3]})"
            if sr[4] is not None:
                detail += f" [{sr[4]:.0f}s]"
            spec_details.append(detail)

        # Determine severity
        if outcome == "completed" and specs_att == specs_comp:
            severity = "info"
        elif outcome == "completed":
            severity = "low"
        elif outcome in ("failed", "blocked"):
            severity = "medium"
        else:
            severity = "low"

        observation = (
            f"Nightshift run {r_id} on project '{project}': "
            f"{outcome} ({specs_comp}/{specs_att} specs completed)"
        )
        if model:
            observation += f", model: {model}"

        context = (
            f"Run: {r_id}\n"
            f"Project: {project}\n"
            f"Time: {start_time} -> {end_time or 'N/A'}\n"
            f"Outcome: {outcome}\n"
            f"Specs: {specs_comp}/{specs_att}\n"
            f"Model: {model or 'N/A'}\n"
            f"Harness: {harness or 'N/A'}\n"
        )
        if spec_details:
            context += "\nSpec results:\n" + "\n".join(f"  - {d}" for d in spec_details)

        return {
            "category": "nightshift",
            "observation": observation,
            "context": context,
            "severity": severity,
        }
    finally:
        conn.close()
